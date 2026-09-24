"""OS → 통합 운영 스프레드시트 내려받기 (마스터 4종).

`sheets_import.py` 의 반대 방향. 같은 `*_MAP` 을 뒤집어 쓰므로 컬럼 이름 정의는
`sheets_bridge.py` 한 곳에만 있다.

핵심 설계
  1) **수식 열은 절대 쓰지 않는다.** 데이터사전 `source=formula` 인 필드는 건너뛴다.
     (시트를 읽으면 수식이 아니라 '계산된 값'이 오므로, 통째로 되쓰면 수식이 날아간다.)
  2) **시트에 이미 적힌 값을 빈 값으로 덮지 않는다.** OS 값이 비었으면 시트 것을 유지.
     import 쪽 규칙("빈 칸은 지우라는 뜻이 아니다")과 대칭.
  3) **`sheet_code` 를 발급해 OS에 저장한다.** 이게 없으면 내려받은 시트를 다시 올릴 때
     기존 행을 못 찾아 전부 새로 생긴다 (263개 → 526개). 내려받기의 진짜 목적은
     '데이터 복사'가 아니라 **양쪽을 같은 키로 묶는 것**이다.
  4) 예시 행(`(예시)` 등)은 건드리지 않고 그 아래에 이어 붙인다 (사장님 결정).
  5) 업체 → 브랜드 → 상품 → 셀러 순. 상품이 업체의 `sheet_code` 를 참조하기 때문.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.integrations import sheets_bridge as sb
from app.models.brand import Brand
from app.models.influencer import Influencer
from app.models.campaign import Campaign
from app.models.partner import Partner
from app.models.product import Product
from app.models.settlement import Settlement

log = logging.getLogger(__name__)

# 마스터 → 일정 → 정산 순. 뒤쪽이 앞쪽의 sheet_code 를 참조한다.
EXPORT_ORDER = ["vendors", "brands", "products", "sellers", "campaigns", "settlements"]

ENTITY_MODELS = {
    "brands":   {"model": Brand,      "prefix": "BRD"},
    "vendors":  {"model": Partner,    "prefix": "VND"},
    "products": {"model": Product,    "prefix": "PRD"},
    "sellers":  {"model": Influencer, "prefix": "SEL"},
    "campaigns":   {"model": Campaign,   "prefix": "CAM"},
    "settlements": {"model": Settlement, "prefix": "STL"},
}

# OS status → 시트 상태값. obj.sheet_status 가 있으면 그걸 우선한다 (원본 한글 보존).
_STATUS_TO_SHEET = {
    "products": {"draft": "검토", "active": "판매중", "archived": "판매종료"},
    # 대량 등록된 인플루언서의 OS status='active' 는 '등록됨'이란 뜻이라 '진행중'이 아니다
    "sellers":  {"active": "접촉전", "inactive": "휴면", "blacklist": "종료"},
    # OS 6단계 → 시트 8단계. cancelled 는 시트에 대응값이 없어 '종료' + 비고 표시.
    "campaigns": {"planning": "제안", "negotiating": "협의", "contracted": "예정",
                  "active": "진행중", "completed": "종료", "cancelled": "종료"},
    "settlements": {"pending": "정산대기", "confirmed": "정산요청", "paid": "정산완료"},
}

# 규격 밖으로 들어간 OS status 교정 (화면 필터에서 누락되는 값들)
_OS_STATUS_FIX = {"활성": "active", "초안": "draft", "보관": "archived", "판매중": "active"}

# OS platform → 코드값 탭 platform ENUM (PLATFORM_MAP 은 여러 한글이 같은 값으로 모여서 뒤집을 수 없다)
PLATFORM_TO_SHEET = {"instagram": "인스타그램", "youtube": "유튜브", "tiktok": "틱톡",
                     "blog": "네이버블로그", "naver": "카카오"}
_VALID_PRODUCT_STATUS = {"draft", "active", "archived"}


def _abs_url(path: str | None) -> str | None:
    """저장된 이미지 경로 → 밖에서 열리는 절대 URL (이미 http면 그대로)."""
    if not path:
        return None
    if path.startswith("http"):
        return path
    return f"{settings.app_base_url.rstrip('/')}/{path.lstrip('/')}"


def _status_ko(entity: str, obj) -> str | None:
    """OS 상태 → 시트 상태값. 새로 유도한 값은 OS `sheet_status` 에도 남긴다.

    안 남기면 시트에는 '거래중'이 적혀 있는데 OS는 비어 있어서, 바로 다시
    올릴 때 126건이 전부 '수정'으로 잡힌다 (실제로 바뀐 건 없는데도).
    """
    if getattr(obj, "sheet_status", None):
        return obj.sheet_status
    if entity == "brands":
        v = "거래중지" if getattr(obj, "is_archived", False) else "거래중"
    elif entity == "vendors":
        v = "거래중" if getattr(obj, "is_active", True) else "거래중지"
    else:
        v = _STATUS_TO_SHEET.get(entity, {}).get(getattr(obj, "status", None) or "")
    if v and hasattr(obj, "sheet_status"):
        obj.sheet_status = v
    return v


# 시트 필드가 '_' 로 시작하는 특수 항목 → OS 객체에서 값 뽑는 함수
_SPECIAL = {
    "_status_ko":     lambda entity, obj, ctx: _status_ko(entity, obj),
    "_paid_date_kst": lambda entity, obj, ctx: ((getattr(obj, "paid_at", None) + timedelta(hours=9)).strftime("%Y-%m-%d")
                                                if getattr(obj, "paid_at", None) else None),
    "_logo_url":      lambda entity, obj, ctx: _abs_url(getattr(obj, "logo", None)),
    "_thumbnail_url": lambda entity, obj, ctx: _abs_url(getattr(obj, "product_image", None)),
    "_option_set":    lambda entity, obj, ctx: sb.options_to_text(getattr(obj, "set_options", None)) or None,
    "_vendor_code":   lambda entity, obj, ctx: ctx["partner_codes"].get(getattr(obj, "partner_id", None)),
    "_platform_ko":   lambda entity, obj, ctx: ctx["platform_ko"].get(getattr(obj, "platform", None)),
    "_product_code":  lambda entity, obj, ctx: ctx["product_codes"].get(getattr(obj, "product_id", None)),
    "_seller_code":   lambda entity, obj, ctx: ctx["seller_codes"].get(getattr(obj, "influencer_id", None)),
    "_campaign_code": lambda entity, obj, ctx: ctx["campaign_codes"].get(getattr(obj, "campaign_id", None)),
    "_target_revenue": lambda entity, obj, ctx: _target_revenue(obj),
    "_note_ko":       lambda entity, obj, ctx: _note_ko(obj),
}


def _target_revenue(obj) -> float | None:
    """목표매출 = 예상수량 × 단가. OS 캠페인엔 목표매출 칸이 없어서 유도한다."""
    qty = getattr(obj, "expected_sales", 0) or 0
    unit = getattr(obj, "unit_price", 0) or 0
    return round(qty * unit) or None


def _note_ko(obj) -> str | None:
    """비고 — 시트에 담을 칸이 없는 상태(보관·취소)를 앞에 표시해준다."""
    marks = []
    if getattr(obj, "is_archived", False):
        marks.append("[보관]")
    if getattr(obj, "status", None) == "cancelled":
        marks.append("[취소]")
    note = (getattr(obj, "notes", None) or "").strip()
    return " ".join(marks + ([note] if note else [])) or None


def _cell(entity: str, attr: str, obj, ctx):
    """OS 객체 → 시트 셀 값. 비었으면 None (= 시트 값 유지).

    ⚠️ 금액·비율·건수의 0 은 '0원'이 아니라 **미입력**이다. 이걸 값으로 취급하면
    시트에 사장님이 적어둔 공급가(23000)를 OS의 0 으로 덮어써 지워버린다
    (2026-08-19 실제로 한 건 날렸다). 0 은 '빈 값'으로 보고 시트를 그대로 둔다.
    """
    if attr.startswith("_"):
        fn = _SPECIAL.get(attr)
        return fn(entity, obj, ctx) if fn else None
    v = getattr(obj, attr, None)
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) == 0.0:
        return None
    if attr in sb._LIST:
        return ", ".join(str(x) for x in v) if isinstance(v, list) else str(v)
    if isinstance(v, bool):
        return "Y" if v else "N"
    if isinstance(v, (date, datetime)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, str):
        # 줄바꿈은 LF로 통일 (시트는 LF, OS엔 CRLF가 섞여 있다)
        return v.replace("\r\n", "\n").replace("\r", "\n")
    if isinstance(v, float) and v.is_integer() and attr not in sb._RATE:
        return int(v)
    return v


_DATE_FORMATS = ("%Y-%m-%d", "%Y. %m. %d", "%Y.%m.%d", "%Y/%m/%d", "%Y. %m. %d.")


def _nl(v: str) -> str:
    """줄바꿈 표기 차이(CRLF/LF)로 '바뀌었다'가 되지 않게 정규화."""
    return v.replace("\r\n", "\n").replace("\r", "\n")


def _as_date(v: str):
    v = (v or "").strip()
    for f in _DATE_FORMATS:
        try:
            return datetime.strptime(v, f).date()
        except ValueError:
            continue
    return None


def _same_cell(attr: str, new, old: str) -> bool:
    """시트에 이미 같은 값이 들어 있는가.

    ⚠️ 시트를 읽으면 '26,900' · '15.00%' 처럼 **서식이 적용된 문자열**이 온다.
    문자열끼리 비교하면 26900 != '26,900' 이라 매번 '바뀌었다'가 되어, 아무것도
    안 바뀐 상태에서도 260행을 계속 다시 쓴다. 숫자는 숫자로 비교한다.
    """
    old = (old or "").strip()
    if new is None or new == "":
        return old == ""
    if isinstance(new, (int, float)) and not isinstance(new, bool):
        o = sb._rate(old) if attr in sb._RATE else sb._num(old)
        if o is None:
            return float(new) == 0.0     # 시트가 비었고 OS도 0 이면 같은 것으로 본다
        return abs(float(new) - o) < 1e-9
    new_s = str(new).strip()
    if _nl(new_s) == _nl(old):
        return True
    # 날짜는 시트 서식에 따라 표기가 달라지므로 날짜로 파싱해 비교한다
    d1, d2 = _as_date(new_s), _as_date(old)
    return bool(d1 and d2 and d1 == d2)


def _col_letter(idx: int) -> str:
    out = ""
    while idx:
        idx, rem = divmod(idx - 1, 26)
        out = chr(65 + rem) + out
    return out


def _blocks(indices: list[int]) -> list[tuple[int, int]]:
    """[0,1,2,4,5] → [(0,2),(4,5)] — 붙어 있는 열끼리 묶어 쓰기 범위를 줄인다."""
    out: list[tuple[int, int]] = []
    for i in sorted(indices):
        if out and i == out[-1][1] + 1:
            out[-1] = (out[-1][0], i)
        else:
            out.append((i, i))
    return out


def _next_code(prefix: str, year: int, used: set[int], cursor: list[int]) -> str:
    cursor[0] += 1
    while cursor[0] in used:
        cursor[0] += 1
    used.add(cursor[0])
    return f"{prefix}-{year}-{cursor[0]:04d}"


def _code_number(code: str) -> int | None:
    tail = code.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else None


def export_entity(db: Session, entity: str, company_id: int = 1,
                  dry_run: bool = True, sh=None,
                  dictionary: dict | None = None,
                  ctx: dict | None = None) -> dict:
    spec = sb.ENTITIES[entity]
    espec = ENTITY_MODELS[entity]
    model, prefix = espec["model"], espec["prefix"]
    fmap: dict = spec["map"]
    tab = spec["tab"]

    rep = {"ok": True, "entity": entity, "label": spec["label"], "tab": tab,
           "appended": 0, "updated": 0, "unchanged": 0, "coded": 0,
           "fixed": [], "notes": [], "skipped_fields": []}

    sh = sh or sb._open()
    dictionary = dictionary if dictionary is not None else sb.read_dictionary(sh)
    ctx = ctx or {}
    ws = sh.worksheet(tab)
    values = ws.get_all_values()
    if len(values) < sb.HEADER_ROW:
        rep.update(ok=False, error=f"{tab}: 헤더({sb.HEADER_ROW}행)가 없습니다")
        return rep

    headers = [h.strip() for h in values[sb.HEADER_ROW - 1]]
    formula_fields = {f.field_name for f in dictionary.get(tab, [])
                      if f.source.strip().lower() == "formula"}

    # 쓸 수 있는 열 = 헤더가 있고 · 수식이 아니고 · OS에 대응 필드가 있는 열
    writable = [i for i, h in enumerate(headers)
                if h and h not in formula_fields and fmap.get(h) is not None]
    rep["skipped_fields"] = [h for h in headers
                             if h and h not in formula_fields and fmap.get(h) is None]
    if not writable:
        rep.update(ok=False, error=f"{tab}: 쓸 수 있는 열이 없습니다")
        return rep

    # 시트 기존 행 색인 (A열 = PK 코드) + 이미 쓰인 번호 수집
    rows_by_code: dict[str, tuple[int, list[str]]] = {}
    used_numbers: set[int] = set()
    for offset, raw in enumerate(values[sb.FIRST_DATA_ROW - 1:]):
        row_no = sb.FIRST_DATA_ROW + offset
        code = (raw[0].strip() if raw else "")
        if not code:
            continue
        rows_by_code[code] = (row_no, raw)
        if (n := _code_number(code)) is not None:
            used_numbers.add(n)
    next_row = max(sb.FIRST_DATA_ROW, len(values) + 1)

    q = db.query(model).filter(model.company_id == company_id)
    # 공구는 보관된 것까지 전부 내린다 (과거 공구 이력이 목적). 비고에 [보관] 표시.
    if hasattr(model, "is_archived") and entity != "campaigns":
        q = q.filter(model.is_archived.isnot(True))
    objs = q.order_by(model.created_at.asc()).all()

    # OS에 이미 있는 코드 번호도 예약해야 새 번호가 겹치지 않는다
    for o in objs:
        if o.sheet_code and (n := _code_number(o.sheet_code)) is not None:
            used_numbers.add(n)

    year = datetime.now().year
    cursor = [0]
    planned: dict[int, list] = {}      # row_no → 헤더 길이의 값 리스트 (None = 안 씀)

    for obj in objs:
        # products: 규격 밖 status 교정 (예: '활성' → 'active')
        if entity == "products":
            cur = getattr(obj, "status", None)
            if cur and cur not in _VALID_PRODUCT_STATUS:
                fixed = _OS_STATUS_FIX.get(cur)
                if fixed:
                    rep["fixed"].append(f"{obj.name}: status '{cur}' → '{fixed}'")
                    obj.status = fixed

        code = obj.sheet_code
        if not code:
            code = _next_code(prefix, year, used_numbers, cursor)
            obj.sheet_code = code
            rep["coded"] += 1

        if code in rows_by_code:
            row_no, existing = rows_by_code[code]
            is_new = False
        else:
            row_no, existing, is_new = next_row, [], True
            next_row += 1

        row_vals: list = [None] * len(headers)
        changed = False
        for i in writable:
            field = headers[i]
            v = _cell(entity, fmap[field], obj, ctx)
            if i == 0:                          # PK 열은 항상 코드
                v = code
            old = existing[i].strip() if i < len(existing) else ""
            if v is None:
                # OS가 비었으면 시트 값을 유지 — 새 행이면 빈칸
                row_vals[i] = old if old else ""
                continue
            row_vals[i] = v
            if not _same_cell(fmap[field], v, old):
                changed = True

        if is_new:
            rep["appended"] += 1
        elif changed:
            rep["updated"] += 1
        else:
            rep["unchanged"] += 1
            continue                            # 바뀐 게 없으면 쓰지 않는다
        planned[row_no] = row_vals

    if not planned:
        rep["notes"].append("바뀐 행이 없습니다")
        return rep

    last_row = max(planned)
    requests, data = [], []

    # 행 수 · 수식 확장
    if last_row > ws.row_count:
        rep["notes"].append(f"시트 행 {ws.row_count} → {last_row} 확장")
        if not dry_run:
            ws.add_rows(last_row - ws.row_count)
    formula_cols = [i for i, h in enumerate(headers) if h in formula_fields]
    formula_last = _formula_extent(ws, formula_cols)
    if formula_cols and last_row > formula_last:
        rep["notes"].append(
            f"수식 열({', '.join(headers[i] for i in formula_cols)}) "
            f"{formula_last} → {last_row}행까지 확장")
        for i in formula_cols:
            requests.append({"copyPaste": {
                "source": {"sheetId": ws.id,
                           "startRowIndex": sb.FIRST_DATA_ROW - 1, "endRowIndex": sb.FIRST_DATA_ROW,
                           "startColumnIndex": i, "endColumnIndex": i + 1},
                "destination": {"sheetId": ws.id,
                                "startRowIndex": formula_last, "endRowIndex": last_row,
                                "startColumnIndex": i, "endColumnIndex": i + 1},
                "pasteType": "PASTE_FORMULA",
            }})

    # 연속된 행 × 연속된 열 → 한 범위로 묶어서 쓰기 횟수를 줄인다
    for r0, r1 in _blocks(list(planned)):
        for c0, c1 in _blocks(writable):
            data.append({
                "range": f"'{tab}'!{_col_letter(c0 + 1)}{r0}:{_col_letter(c1 + 1)}{r1}",
                "values": [[("" if v is None else v) for v in planned[r][c0:c1 + 1]]
                           for r in range(r0, r1 + 1)],
            })

    rep["write_ranges"] = [d["range"] for d in data]
    if dry_run:
        rep["notes"].append(f"[미리보기] 쓰기 범위 {len(data)}개 — 시트 변경 없음")
        return rep

    # ⚠️ 시트 쓰기는 되돌릴 수 없다(트랜잭션이 아니다). 그래서 발급한 sheet_code 를
    # **쓰기 전에** 확정한다. 순서가 반대면, 시트에는 코드가 적혔는데 DB는 롤백돼서
    # 다음 실행이 같은 행을 못 찾고 전부 다시 추가한다 (2026-08-19 실제로 겪음).
    db.commit()

    if requests:
        sh.batch_update({"requests": requests})
    # 큰 배치는 나눠 보낸다 (한 번에 너무 크면 API가 거부)
    for i in range(0, len(data), 40):
        sh.values_batch_update({"valueInputOption": "USER_ENTERED",
                                "data": data[i:i + 40]})
    return rep


def _formula_extent(ws, formula_cols: list[int]) -> int:
    """수식이 실제로 들어 있는 마지막 행.

    ⚠️ 일반 읽기는 수식이 아니라 '계산된 값'을 주고, 이 시트 수식들은 빈 행에서
    ""를 내놓는다. 그래서 값으로 판단하면 수식이 1000행까지 있는데도 5행까지만
    있는 줄 알고 멀쩡한 수식을 덮어쓴다. 반드시 FORMULA 레이어로 읽는다.

    읽기는 **탭당 1회**로 끝낸다. 열마다 따로 읽으면 정산관리(수식 9열)에서만
    9회가 나가고, Sheets 읽기 쿼터(분당 60회)에 바로 걸린다.
    """
    if not formula_cols:
        return 0
    grid = ws.get(
        f"A{sb.FIRST_DATA_ROW}:{_col_letter(ws.col_count)}{ws.row_count}",
        value_render_option="FORMULA")
    last = sb.FIRST_DATA_ROW - 1
    for offset, raw in enumerate(grid):
        if any(i < len(raw) and str(raw[i]).strip() for i in formula_cols):
            last = sb.FIRST_DATA_ROW + offset
    return last


def run(db: Session, entities: list[str] | None = None, company_id: int = 1,
        dry_run: bool = True) -> dict:
    """OS → 시트. dry_run=True 면 무엇을 쓸지만 계산한다."""
    if not sb.is_configured():
        return {"ok": False, "error": "미설정 (.env: GOOGLE_SA_JSON, INTEGRATED_SHEET_ID)"}

    targets = [e for e in EXPORT_ORDER if not entities or e in entities]
    if not targets:
        return {"ok": False, "error": "내려받을 대상이 없습니다"}

    try:
        sh = sb._open()
        dictionary = sb.read_dictionary(sh)
    except Exception as e:
        log.exception("sheet open failed")
        return {"ok": False, "error": f"시트 열기 실패 — {type(e).__name__}: {e}"}

    ctx = {
        "platform_ko": PLATFORM_TO_SHEET,
        "partner_codes": {}, "product_codes": {}, "seller_codes": {},
        "campaign_codes": {},
    }

    def _codes(m):
        """id → sheet_code. 직전 단계에서 발급된 코드까지 보이도록 그때그때 조회한다."""
        return {o.id: o.sheet_code for o in
                db.query(m).filter(m.company_id == company_id,
                                   m.sheet_code.isnot(None)).all()}

    reports = []
    for entity in targets:
        # 뒤 단계는 앞 단계의 sheet_code 를 참조 → 직전까지 발급된 코드를 모아둔다
        if entity == "products":
            ctx["partner_codes"] = _codes(Partner)
        elif entity == "campaigns":
            ctx["product_codes"] = _codes(Product)
            ctx["seller_codes"] = _codes(Influencer)
        elif entity == "settlements":
            ctx["campaign_codes"] = _codes(Campaign)
            ctx["seller_codes"] = _codes(Influencer)
        try:
            reports.append(export_entity(db, entity, company_id, dry_run, sh,
                                         dictionary, ctx))
        except Exception as e:
            db.rollback()
            log.exception("sheet export failed: %s", entity)
            reports.append({"ok": False, "entity": entity,
                            "label": sb.ENTITIES[entity]["label"],
                            "tab": sb.ENTITIES[entity]["tab"],
                            "appended": 0, "updated": 0, "unchanged": 0, "coded": 0,
                            "fixed": [], "notes": [], "skipped_fields": [],
                            "error": f"{type(e).__name__}: {e}"})

    failed = [r for r in reports if not r.get("ok")]
    if dry_run:
        db.rollback()
    elif failed:
        # 성공한 엔티티는 export_entity 안에서 이미 커밋됐다. 실패한 뒤에 남은
        # 미확정 변경만 되돌린다 (시트에 못 쓴 코드를 DB에 남기지 않기 위함).
        db.rollback()

    return {
        "ok": not failed,
        "dry_run": dry_run,
        "sheet_url": getattr(sh, "url", ""),
        "reports": reports,
        "totals": {k: sum(r.get(k, 0) for r in reports)
                   for k in ("appended", "updated", "unchanged", "coded")},
    }
