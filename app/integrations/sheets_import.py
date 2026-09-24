"""통합 운영 스프레드시트 → OS 임포트 (upsert).

sheets_bridge.py 가 '읽기·매핑'을 담당하고, 이 모듈이 'DB 반영'을 담당한다.

설계 원칙
  1) upsert 키는 시트 PK(`sheet_code`). 같은 시트를 두 번 올려도 중복이 생기지 않는다.
     sheet_code 가 빈 행은 이름(브랜드명·업체명·상품명+브랜드)으로 한 번 더 찾아본다.
  2) 시트에 빈 칸은 '지우라는 뜻이 아니다' → 값이 없는 필드는 건드리지 않는다.
     OS에서 채워둔 상세 내용이 시트 임포트로 날아가지 않게 하기 위함.
  3) dry_run=True 면 무엇이 바뀔지만 계산하고 커밋·이미지 다운로드를 하지 않는다.
  4) 임포트 순서는 브랜드 → 업체 → 상품 → 셀러. 상품이 브랜드·업체를 참조하기 때문.

상품의 브랜드 연결: `Product.brand` 는 FK가 아니라 문자열이라 브랜드가 OS에 없어도
제품은 저장된다(그래서 브랜드 없는 제품이 생겼다). 여기서는 상품마스터의 브랜드명으로
`brands` 행을 자동 생성/연결해서 그 반쪽 상태를 없앤다.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.integrations import sheets_bridge as sb
from app.models.brand import Brand
from app.models.influencer import Influencer
from app.models.partner import Partner
from app.models.product import Product
from app.services.product_service import validate_product_completeness

log = logging.getLogger(__name__)

# 임포트 순서 — 상품이 브랜드/업체를 참조하므로 이 순서를 지켜야 한다
IMPORT_ORDER = ["brands", "vendors", "products", "sellers"]

_BRAND_LOGO_DIR = Path("static/brands")
_PRODUCT_IMG_DIR = Path("static/uploads/products")

# 시트 상태값 → OS
_BRAND_ARCHIVED = {"거래중지"}
_VENDOR_INACTIVE = {"거래중지"}
_SELLER_INACTIVE = {"휴면", "종료"}


# ── 유틸 ──────────────────────────────────────────────────────────────────────

def _image_unchanged(url: str, current: str | None) -> bool:
    """이 URL이 지금 저장돼 있는 그 이미지인가.

    내려받기(sheets_export)가 시트에 **우리 저장소 주소**를 써 넣기 때문에,
    URL의 md5만 비교하면 왕복할 때마다 같은 이미지가 새 파일로 계속 쌓인다.
    그래서 (1) 주소가 같거나 (2) 원본 URL의 md5로 저장된 파일이거나
    (3) 파일명이 같으면 → 이미 가진 이미지로 본다.
    """
    if not current:
        return False
    if current == url:
        return True
    if hashlib.md5(url.encode()).hexdigest() in current:
        return True
    tail = url.rstrip("/").split("/")[-1].split("?")[0]
    return bool(tail) and current.endswith(tail)


def _fetch_image(url: str, dest_dir: Path, current: str | None) -> str | None:
    """이미지 URL → 저장 경로. 이미 가진 이미지면 None(변경 없음)."""
    if _image_unchanged(url, current):
        return None
    from app.services import image_service
    return image_service.save_url_image(
        url, dest_dir, stem=hashlib.md5(url.encode()).hexdigest())


def _apply(obj, data: dict, changes: list[str]) -> None:
    """빈 값은 건드리지 않고, 실제로 달라지는 필드만 반영 + 변경내역 기록."""
    for attr, new in data.items():
        if new is None:
            continue
        old = getattr(obj, attr, None)
        if old == new:
            continue
        if isinstance(old, float) and isinstance(new, (int, float)) and float(old) == float(new):
            continue
        changes.append(f"{attr}: {_short(old)} → {_short(new)}")
        setattr(obj, attr, new)


def _short(v, limit: int = 24) -> str:
    if v is None or v == "":
        return "(없음)"
    s = str(v)
    return s if len(s) <= limit else s[:limit] + "…"


def _blank_report(entity: str) -> dict:
    spec = sb.ENTITIES[entity]
    return {
        "ok": True, "entity": entity, "label": spec["label"], "tab": spec["tab"],
        "created": 0, "updated": 0, "unchanged": 0, "failed": 0, "skipped": 0,
        "rows": [], "notes": [], "unmapped": [],
    }


def _reject_nameless(rep: dict, data: dict, special: dict,
                     code: str | None, label: str) -> None:
    """이름이 빈 행 처리.

    ID만 발급해두고 아직 아무것도 안 적은 행(시트에 흔하다)은 실패가 아니라
    '건너뜀'이다. 이름 말고 다른 값이 적혀 있으면 진짜 입력 누락으로 본다.
    """
    if not any(k != "sheet_code" for k in data) and not special:
        rep["skipped"] += 1
        return
    rep["rows"].append({"code": code or "", "name": "", "action": "failed",
                        "changes": [], "error": f"{label}이 비어 있음"})
    rep["failed"] += 1


def _find(db: Session, model, company_id: int, code: str | None,
          name_field: str | None = None, name: str | None = None, skip_archived_by_name: bool = False):
    """sheet_code 우선, 없으면 이름으로 기존 행 찾기.

    skip_archived_by_name: 이름으로 찾을 때 보관된 줄은 빼기 (인플루언서 — 중복 합치기로 보관된 줄을
    시트 가져오기가 다시 고르지 않게. 브랜드 등은 보관된 줄도 이름으로 찾아야 해서 기본값은 그대로).
    """
    q = db.query(model).filter(model.company_id == company_id)
    if code:
        found = q.filter(model.sheet_code == code).first()
        if found:
            return found
    if name_field and name:
        nq = q.filter(getattr(model, name_field) == name)
        if skip_archived_by_name and hasattr(model, "is_archived"):
            nq = nq.filter(model.is_archived.isnot(True))
        return nq.first()
    return None


# ── 브랜드 ────────────────────────────────────────────────────────────────────

def import_brands(db: Session, company_id: int = 1, dry_run: bool = True,
                  sh=None) -> dict:
    rep = _blank_report("brands")
    _, rows = sb.read_tab(rep["tab"], sh)
    for row in rows:
        data, special = sb.map_row(row, sb.BRAND_MAP)
        name = data.get("name")
        code = data.get("sheet_code")
        if not name:
            _reject_nameless(rep, data, special, code, "브랜드명")
            continue

        obj = _find(db, Brand, company_id, code, "name", name)
        creating = obj is None
        changes: list[str] = []
        if creating:
            obj = Brand(company_id=company_id, name=name)
            db.add(obj)

        status_ko = special.get("_status_ko")
        if status_ko:
            data["sheet_status"] = status_ko
            data["is_archived"] = status_ko in _BRAND_ARCHIVED

        logo_url = special.get("_logo_url")
        if logo_url and logo_url.startswith("http"):
            if dry_run:
                if not _image_unchanged(logo_url, obj.logo):
                    changes.append("logo: 다운로드 예정")
            else:
                saved = _fetch_image(logo_url, _BRAND_LOGO_DIR, obj.logo)
                if saved:
                    data["logo"] = saved
                elif not obj.logo:
                    rep["notes"].append(f"{name}: 로고 다운로드 실패 — {_short(logo_url, 60)}")
        elif logo_url:
            rep["notes"].append(f"{name}: logo_url 이 주소 형식이 아님 — {_short(logo_url, 40)}")

        _apply(obj, data, changes)
        _record(rep, code, name, creating, changes)

    _finish(db, rep)
    return rep


# ── 업체(협력사) ──────────────────────────────────────────────────────────────

def import_vendors(db: Session, company_id: int = 1, dry_run: bool = True,
                   sh=None) -> dict:
    rep = _blank_report("vendors")
    _, rows = sb.read_tab(rep["tab"], sh)
    for row in rows:
        data, special = sb.map_row(row, sb.VENDOR_MAP)
        name = data.get("name")
        code = data.get("sheet_code")
        if not name:
            _reject_nameless(rep, data, special, code, "업체명")
            continue

        obj = _find(db, Partner, company_id, code, "name", name)
        creating = obj is None
        changes: list[str] = []
        if creating:
            obj = Partner(company_id=company_id, name=name)
            db.add(obj)

        status_ko = special.get("_status_ko")
        if status_ko:
            data["sheet_status"] = status_ko
            data["is_active"] = status_ko not in _VENDOR_INACTIVE

        _apply(obj, data, changes)
        _record(rep, code, name, creating, changes)

    _finish(db, rep)
    return rep


# ── 상품 ──────────────────────────────────────────────────────────────────────

def import_products(db: Session, company_id: int = 1, dry_run: bool = True,
                    sh=None) -> dict:
    rep = _blank_report("products")
    _, rows = sb.read_tab(rep["tab"], sh)

    brands = {b.name: b for b in db.query(Brand).filter(Brand.company_id == company_id).all()}
    partners_by_code = {
        p.sheet_code: p for p in
        db.query(Partner).filter(Partner.company_id == company_id,
                                 Partner.sheet_code.isnot(None)).all()
    }
    auto_brands: list[str] = []

    for row in rows:
        data, special = sb.map_row(row, sb.PRODUCT_MAP)
        name = data.get("name")
        code = data.get("sheet_code")
        brand_name = data.get("brand")

        if not name:
            _reject_nameless(rep, data, special, code, "상품명")
            continue
        if not brand_name:
            rep["rows"].append({"code": code or "", "name": name, "action": "failed",
                                "changes": [], "error": "브랜드가 비어 있음"})
            rep["failed"] += 1
            continue
        data.setdefault("category", "기타")   # OS 필수 컬럼

        # 브랜드 자동 생성 — 상품마스터의 브랜드명이 브랜드마스터에 없을 때
        if brand_name not in brands:
            nb = Brand(company_id=company_id, name=brand_name, review_status="draft")
            db.add(nb)
            brands[brand_name] = nb
            auto_brands.append(brand_name)

        # 업체 연결 (vendor_id → partners.sheet_code)
        vendor_code = special.get("_vendor_code")
        if vendor_code:
            partner = partners_by_code.get(vendor_code)
            if partner:
                data["partner_id"] = partner.id
            else:
                rep["notes"].append(f"{name}: 업체ID '{vendor_code}' 를 OS에서 못 찾음 "
                                    f"(업체마스터를 먼저 임포트하세요)")

        # 상품은 이름+브랜드로도 찾는다 — 기존 OS 제품에 sheet_code 를 붙여주는 경로.
        # 이게 없으면 첫 임포트에서 이미 있는 제품이 전부 새로 생긴다.
        obj = _find(db, Product, company_id, code)
        if obj is None:
            obj = (db.query(Product)
                     .filter(Product.company_id == company_id,
                             Product.name == name, Product.brand == brand_name)
                     .first())
        creating = obj is None
        changes: list[str] = []
        if creating:
            obj = Product(company_id=company_id, name=name,
                          brand=brand_name, category=data["category"])
            db.add(obj)

        status_ko = special.get("_status_ko")
        if status_ko:
            data["sheet_status"] = status_ko
            data["status"] = sb.PRODUCT_STATUS_MAP.get(status_ko, "draft")

        if opt := special.get("_option_set"):
            parsed = sb.parse_options(opt)
            # 시트 표현이 같으면 그대로 둔다 — 텍스트 한 칸에는 qty·notes 를 담을 수
            # 없어서, 무조건 덮으면 OS에 있던 수량 정보가 왕복마다 날아간다
            if parsed and sb.options_to_text(parsed) != sb.options_to_text(obj.set_options):
                data["set_options"] = parsed

        # price(레거시 대표가) — 완성도 검증이 이 값을 본다
        gb = data.get("groupbuy_price")
        cp = data.get("consumer_price")
        if gb or cp:
            data["price"] = gb or cp

        # 파생값 — 시트는 정산율만 계산하고 할인율·마진율은 OS 쪽 캐시 컬럼
        if cp and gb and cp > 0:
            data["discount_rate"] = round((cp - gb) / cp, 4)
        sp = data.get("supplier_price")
        if gb and sp and gb > 0:
            data["margin_rate"] = round((gb - sp) / gb, 4)

        thumb = special.get("_thumbnail_url")
        if thumb and thumb.startswith("http"):
            if dry_run:
                if not _image_unchanged(thumb, obj.product_image):
                    changes.append("product_image: 다운로드 예정")
            else:
                saved = _fetch_image(thumb, _PRODUCT_IMG_DIR, obj.product_image)
                if saved:
                    data["product_image"] = saved
                elif not obj.product_image:
                    rep["notes"].append(f"{name}: 썸네일 다운로드 실패 — {_short(thumb, 60)}")
        elif thumb:
            rep["notes"].append(f"{name}: thumbnail_url 이 주소 형식이 아님 — {_short(thumb, 40)}")

        _apply(obj, data, changes)

        completeness = validate_product_completeness(obj)
        obj.is_complete = completeness["is_complete"]
        obj.missing_fields = completeness["missing_fields"] or None
        row_out = _record(rep, code, name, creating, changes)
        row_out["missing"] = completeness["missing_fields"]

    if auto_brands:
        rep["notes"].insert(0, f"브랜드 {len(auto_brands)}건 자동 생성: "
                               + ", ".join(auto_brands[:8])
                               + ("…" if len(auto_brands) > 8 else ""))
    _finish(db, rep)
    return rep


# ── 셀러(인플루언서) ──────────────────────────────────────────────────────────

def import_sellers(db: Session, company_id: int = 1, dry_run: bool = True,
                   sh=None) -> dict:
    rep = _blank_report("sellers")
    _, rows = sb.read_tab(rep["tab"], sh)
    for row in rows:
        data, special = sb.map_row(row, sb.SELLER_MAP)
        name = data.get("name")
        code = data.get("sheet_code")
        if not name:
            _reject_nameless(rep, data, special, code, "셀러명")
            continue

        platform = sb.PLATFORM_MAP.get(special.get("_platform_ko", ""), None)
        obj = _find(db, Influencer, company_id, code, "name", name, skip_archived_by_name=True)
        creating = obj is None
        changes: list[str] = []
        if creating:
            # platform/handle 은 NOT NULL — 시트가 비어 있으면 기본값으로 채운다
            obj = Influencer(company_id=company_id, name=name,
                             platform=platform or "instagram",
                             handle=data.get("handle") or name)
            db.add(obj)
        elif platform:
            data["platform"] = platform

        status_ko = special.get("_status_ko")
        if status_ko:
            data["sheet_status"] = status_ko
            data["status"] = "inactive" if status_ko in _SELLER_INACTIVE else "active"

        _apply(obj, data, changes)
        _record(rep, code, name, creating, changes)

    _finish(db, rep)
    return rep


# ── 공통 마무리 ───────────────────────────────────────────────────────────────

def _record(rep: dict, code: str | None, name: str,
            creating: bool, changes: list[str]) -> dict:
    if not code:
        # ID 없이도 OS에는 들어간다. 다만 내려받기가 그 행을 못 찾아 시트에 행을
        # 하나 더 붙이므로(같은 제품이 두 줄), 미리보기에서 미리 알려준다.
        rep["notes"].append(f"{name}: 시트 ID(A열)가 비어 있습니다 — 채워주세요 "
                            f"(비워두면 내려받기 때 같은 행이 하나 더 생깁니다)")
    action = "created" if creating else ("updated" if changes else "unchanged")
    rep[action] += 1
    out = {"code": code or "", "name": name, "action": action,
           "changes": changes, "error": ""}
    rep["rows"].append(out)
    return out


def _finish(db: Session, rep: dict) -> None:
    """DB에 내보내되(flush) 확정은 하지 않는다.

    커밋/롤백은 run() 이 전체에 대해 한 번만 한다. 그래야 dry-run 에서도
    '브랜드가 먼저 생긴 뒤 상품이 그 브랜드를 찾는' 실제 순서가 그대로 재현된다.
    """
    try:
        db.flush()
    except Exception as e:
        db.rollback()
        rep["ok"] = False
        rep["error"] = f"{type(e).__name__}: {e}"
        log.exception("sheet import flush failed: %s", rep["entity"])


_IMPORTERS = {
    "brands": import_brands,
    "vendors": import_vendors,
    "products": import_products,
    "sellers": import_sellers,
}


def run(db: Session, entities: list[str] | None = None, company_id: int = 1,
        dry_run: bool = True) -> dict:
    """선택한 대상을 IMPORT_ORDER 순서로 임포트. dry_run=True 면 미리보기."""
    if not sb.is_configured():
        return {"ok": False, "error": "미설정 (.env: GOOGLE_SA_JSON, INTEGRATED_SHEET_ID)"}

    targets = [e for e in IMPORT_ORDER if not entities or e in entities]
    if not targets:
        return {"ok": False, "error": "임포트할 대상이 없습니다"}

    try:
        sh = sb._open()
    except Exception as e:
        log.exception("sheet open failed")
        return {"ok": False, "error": f"시트 열기 실패 — {type(e).__name__}: {e}"}

    reports = []
    for entity in targets:
        try:
            reports.append(_IMPORTERS[entity](db, company_id, dry_run, sh))
        except Exception as e:
            db.rollback()
            log.exception("sheet import failed: %s", entity)
            rep = _blank_report(entity)
            rep.update(ok=False, error=f"{type(e).__name__}: {e}")
            reports.append(rep)

    failed = [r for r in reports if not r.get("ok")]
    if dry_run or failed:
        # 미리보기이거나 하나라도 깨졌으면 전부 되돌린다 (반쪽 임포트 방지)
        db.rollback()
        if failed and not dry_run:
            for r in reports:
                r.setdefault("error", "다른 대상이 실패해서 전체를 되돌렸습니다")
    else:
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            log.exception("sheet import commit failed")
            return {"ok": False, "error": f"저장 실패 — {type(e).__name__}: {e}",
                    "reports": reports}

    # 데이터사전은 한 번만 읽어서 '시트엔 있는데 OS로 못 넘어가는 필드'를 채운다
    try:
        dictionary = sb.read_dictionary(sh)
        for rep in reports:
            spec = sb.ENTITIES[rep["entity"]]
            rep["unmapped"] = sb.unmapped_fields(spec["tab"], dictionary, spec["map"])
    except Exception:
        log.warning("데이터사전 읽기 실패 — unmapped 리포트 생략", exc_info=True)

    return {
        "ok": all(r.get("ok") for r in reports),
        "dry_run": dry_run,
        "sheet_url": getattr(sh, "url", ""),
        "reports": reports,
        "totals": {
            k: sum(r.get(k, 0) for r in reports)
            for k in ("created", "updated", "unchanged", "failed", "skipped")
        },
    }
