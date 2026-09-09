"""통합 운영 스프레드시트 ↔ OS 브릿지.

시트: '블랜드펀치_공동구매_통합운영관리' (14탭)
설정 (.env):
  GOOGLE_SA_JSON      = 서비스계정 키 JSON 경로 (기존 소싱 에이전트와 공용)
  INTEGRATED_SHEET_ID = 통합시트 ID

핵심 설계 — 컬럼 매핑을 하드코딩하지 않는다.
  시트의 '데이터사전' 탭이 (sheet_name, table_name, field_name, korean_label,
  data_type, key, references, source, enum_values) 179개 필드를 정의한다.
  이 탭을 읽어 어떤 필드가 input(가져옴) / formula(계산값이라 무시)인지 판단하므로,
  시트에 컬럼이 추가·이동돼도 이 파일을 고칠 필요가 없다.
  시트 필드명 → OS 컬럼명 변환만 아래 *_MAP 에 명시한다 (이름이 서로 다르기 때문).

시트 구조 규약:
  1행 = 탭 제목 / 2행 = 설명문 / 3행 = 영문 필드명 / 4행 = 한글 라벨 / 5행부터 데이터
  → 헤더는 3행. 일반적인 '1행 헤더' 파서를 그대로 쓰면 전부 깨진다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field as dc_field

from app.config import settings

log = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

DICT_TAB = "데이터사전"
HEADER_ROW = 3          # 영문 필드명 행 (1-indexed)
LABEL_ROW = 4           # 한글 라벨 행
FIRST_DATA_ROW = 5      # 데이터 시작 행

# 예시 행 판별 — 이 문자열이 들어간 행은 가져오지 않는다
EXAMPLE_MARKERS = ("(예시)", "★예시", "예시 행")


# ── 시트 필드명 → OS 모델 속성 ────────────────────────────────────────────────
# 값이 None인 필드는 "시트에만 있고 OS에 대응 컬럼이 없음" — 리포트에 표시된다.

PRODUCT_MAP: dict[str, str | None] = {
    "product_id":      "sheet_code",
    "product_name":    "name",
    "brand":           "brand",
    "category":        "category",
    "vendor_id":       "_vendor_code",        # partners.sheet_code 로 조회 → partner_id
    "supply_price":    "supplier_price",
    "list_price":      "consumer_price",
    "sale_price":      "groupbuy_price",
    "shipping_fee":    "shipping_cost",
    "seller_fee_rate": "seller_commission_rate",
    "bp_fee_rate":     "vendor_commission_rate",
    "product_status":  "_status_ko",          # 한글 상태 → status + sheet_status
    "pg_fee_rate":     None,                  # OS에 PG수수료율 컬럼 없음
    "owner":           None,                  # OS에 담당자 컬럼 없음
    # 제품 상세 12열 (2026-08-19 추가) — 이게 없으면 OS에서 전부 '미완성' 제품이 된다
    "description":     "description",
    "thumbnail_url":   "_thumbnail_url",      # URL 다운로드 → product_image
    "marketing_copy":  "unique_selling_point",
    "option_set":      "_option_set",         # "1개입:29000, 2개입:52000" → set_options
    "shipping_type":   "shipping_type",
    "courier":         "carrier",
    "dispatch_days":   "dispatch_days",
    "ship_origin":     "ship_origin",
    "sample_type":     "sample_type",
    "sample_price":    "sample_price",
    "product_link":    "product_link",
    "internal_note":   "internal_notes",
}

BRAND_MAP: dict[str, str | None] = {
    "brand_id":     "sheet_code",
    "brand_name":   "name",
    "description":  "description",
    "logo_url":     "_logo_url",              # URL 다운로드 → logo
    "brand_status": "_status_ko",
    "vendor_id":    None,                     # OS brands 에 업체 FK 없음
    "owner":        None,
    "note":         None,
}

VENDOR_MAP: dict[str, str | None] = {
    "vendor_id":        "sheet_code",
    "vendor_name":      "name",
    "brand_name":       "business_name",
    "manager":          "contact_name",
    "phone":            "phone",
    "email":            "email",
    "biz_reg_no":       "biz_reg_number",
    "settle_terms":     "contract_terms",
    "tax_invoice_info": "tax_invoice_email",
    "vendor_status":    "_status_ko",
    "note":             "notes",
    "shipping_owner":   None,                 # OS partners 에 배송주체 없음
    "cs_owner":         None,                 # OS partners 에 CS주체 없음
}

SELLER_MAP: dict[str, str | None] = {
    "seller_id":         "sheet_code",
    "seller_name":       "name",
    "instagram_handle":  "handle",
    "platform":          "_platform_ko",
    "followers":         "followers",
    "main_category":     "categories",
    "avg_fee_rate":      "commission_preference",
    "seller_status":     "_status_ko",
    "note":              "notes",
    "owner":             None,
}

# ── 일정·정산 (OS → 시트 내려받기 전용) ──────────────────────────────────────
# 이 두 탭은 OS가 진실이고 시트는 읽기전용 미러다. 그래서 IMPORT_ORDER 에는 없다.

CAMPAIGN_MAP: dict[str, str | None] = {
    "campaign_id":      "sheet_code",
    "campaign_name":    "name",
    "product_id":       "_product_code",     # products.sheet_code
    "seller_id":        "_seller_code",      # influencers.sheet_code
    "start_date":       "start_date",
    "end_date":         "end_date",
    "campaign_status":  "_status_ko",
    "target_revenue":   "_target_revenue",   # 예상수량 × 단가 (OS에 목표매출 칸이 없다)
    "actual_revenue":   "actual_revenue",
    "order_count":      "actual_sales",      # OS는 '수량', 시트는 '주문건수' — 근사값
    "note":             "_note_ko",          # 보관 표시를 앞에 붙인다
    "owner":            None,                # OS 캠페인에 담당자 컬럼 없음
}

SETTLEMENT_MAP: dict[str, str | None] = {
    "settlement_id":      "sheet_code",
    "campaign_id":        "_campaign_code",
    "settle_due_date":    None,              # OS에 정산예정일 컬럼 없음
    "settle_done_date":   None,              # OS에 정산완료일 컬럼 없음
    "settlement_status":  "_status_ko",
    "note":               "notes",
    # OS 인플루언서 지급 정산 (2026-08-19 시트에 추가한 10열)
    "seller_id":          "_seller_code",
    "period_label":       "period_label",
    "payout_sales":       "sales_amount",
    "payout_fee_rate":    "commission_rate",
    "payout_commission":  "commission_amount",
    "payout_vat":         "vat_amount",
    "payout_tax_rate":    "tax_rate",
    "payout_tax":         "tax_amount",
    "payout_final":       "final_payment",
}

ENTITIES = {
    "products":  {"tab": "상품마스터",   "map": PRODUCT_MAP, "label": "상품"},
    "brands":    {"tab": "브랜드마스터", "map": BRAND_MAP,   "label": "브랜드"},
    "vendors":   {"tab": "업체마스터",   "map": VENDOR_MAP,  "label": "협력사(업체)"},
    # 탭명은 '인플루언서마스터' (2026-08-19 개칭). OS influencers 와 1:1.
    # ⚠️ OS `sellers` 테이블은 사람이 아니라 판매링크 코드(?seller=xxx)라서 완전히 다른 것.
    # 영문 필드명(seller_id/seller_name/seller_status)은 공구일정 FK·코드값 ENUM이
    # 참조하므로 그대로 둔다.
    "sellers":   {"tab": "인플루언서마스터", "map": SELLER_MAP, "label": "인플루언서"},
    # 아래 둘은 내려받기 전용 (sheets_import.IMPORT_ORDER 에 없음)
    "campaigns":   {"tab": "공구일정",  "map": CAMPAIGN_MAP,   "label": "공구"},
    "settlements": {"tab": "정산관리",  "map": SETTLEMENT_MAP, "label": "정산"},
}

# 상품상태(시트 6단계) → OS status(3단계). 원본 한글은 sheet_status 에 보존한다.
PRODUCT_STATUS_MAP = {
    "검토": "draft", "협의중": "draft", "판매준비": "draft",
    "판매중": "active", "판매종료": "archived", "보류": "draft",
}

PLATFORM_MAP = {
    "인스타그램": "instagram", "인스타": "instagram",
    "유튜브": "youtube", "틱톡": "tiktok",
    "네이버블로그": "blog", "블로그": "blog", "카카오": "naver", "기타": "instagram",
}

# 숫자/비율/리스트 변환 대상 (OS 속성명 기준)
_NUMERIC = {"supplier_price", "consumer_price", "groupbuy_price", "shipping_cost",
            "sample_price", "followers"}
_RATE = {"seller_commission_rate", "vendor_commission_rate", "commission_preference"}
_LIST = {"categories"}


# ── 데이터사전 ────────────────────────────────────────────────────────────────

@dataclass
class FieldDef:
    sheet_name: str
    table_name: str
    field_name: str
    korean_label: str
    data_type: str
    key: str
    references: str
    source: str            # input | formula | master
    enum_values: list[str] = dc_field(default_factory=list)

    @property
    def is_input(self) -> bool:
        return self.source.strip().lower() == "input"


def is_configured() -> bool:
    return bool(settings.google_sa_json and settings.integrated_sheet_id)


# 일시 오류(구글 쪽 5xx, 쿼터 429)는 잠깐 뒤 다시 하면 되는 경우가 많다.
# 무인 자동 동기화가 이런 걸로 실패 기록을 남기지 않게 몇 번 다시 시도한다.
_RETRY_STATUS = ("[429]", "[500]", "[502]", "[503]", "[504]")
_RETRY_WAITS = (3, 10, 30)


def _open():
    import time

    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(settings.google_sa_json, scopes=_SCOPES)
    last: Exception | None = None
    for wait in (*_RETRY_WAITS, None):
        try:
            return gspread.authorize(creds).open_by_key(settings.integrated_sheet_id)
        except Exception as e:
            last = e
            if wait is None or not any(c in str(e) for c in _RETRY_STATUS):
                raise
            log.warning("시트 열기 일시 실패 — %ss 뒤 재시도: %s", wait, e)
            time.sleep(wait)
    raise last  # 여기까지 오지 않지만 타입상 명시


def read_dictionary(sh=None) -> dict[str, list[FieldDef]]:
    """데이터사전 탭 → {시트탭명: [FieldDef, ...]}."""
    sh = sh or _open()
    rows = sh.worksheet(DICT_TAB).get_all_values()
    out: dict[str, list[FieldDef]] = {}
    for row in rows[FIRST_DATA_ROW - 1:]:          # 5행부터
        row = (row + [""] * 9)[:9]
        if not row[0].strip() or not row[2].strip():
            continue
        fd = FieldDef(
            sheet_name=row[0].strip(), table_name=row[1].strip(), field_name=row[2].strip(),
            korean_label=row[3].strip(), data_type=row[4].strip(), key=row[5].strip(),
            references=row[6].strip(), source=row[7].strip(),
            enum_values=[v.strip() for v in row[8].split(",") if v.strip()],
        )
        out.setdefault(fd.sheet_name, []).append(fd)
    return out


def _is_example(row: dict) -> bool:
    joined = " ".join(str(v) for v in row.values())
    return any(m in joined for m in EXAMPLE_MARKERS)


def read_tab(tab: str, sh=None) -> tuple[list[str], list[dict]]:
    """탭 → (영문 헤더, [{field_name: 값}]). 3행 헤더 규약을 따르고 예시행은 제외."""
    sh = sh or _open()
    values = sh.worksheet(tab).get_all_values()
    if len(values) < FIRST_DATA_ROW:
        return [], []
    headers = [h.strip() for h in values[HEADER_ROW - 1]]
    rows: list[dict] = []
    for raw in values[FIRST_DATA_ROW - 1:]:
        row = {h: (raw[i].strip() if i < len(raw) else "") for i, h in enumerate(headers) if h}
        if not any(row.values()):
            continue
        if _is_example(row):
            continue
        rows.append(row)
    return headers, rows


# ── 값 변환 ───────────────────────────────────────────────────────────────────

def _num(raw: str) -> float | None:
    raw = raw.replace(",", "").replace("₩", "").strip()
    if not raw or raw in ("-", "#REF!", "#N/A"):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _rate(raw: str) -> float | None:
    """'15%' / '15' / '0.15' 모두 0.15 로."""
    raw = raw.replace(",", "").strip()
    if not raw or raw in ("-", "#REF!", "#N/A"):
        return None
    pct = raw.endswith("%")
    try:
        v = float(raw.rstrip("%"))
    except ValueError:
        return None
    if pct or v > 1:
        v = v / 100.0
    return v


def convert(attr: str, raw: str):
    # 시트는 줄바꿈을 LF로 준다. OS에 CRLF가 섞여 있으면 같은 글인데도 매번
    # '바뀌었다'로 잡히므로 LF로 통일해서 저장한다.
    raw = (raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw or raw in ("-", "#REF!", "#N/A", "n/a"):
        return None
    if attr in _RATE:
        return _rate(raw)
    if attr in _NUMERIC:
        v = _num(raw)
        return int(v) if (v is not None and attr == "followers") else v
    if attr in _LIST:
        items = [s.strip() for s in raw.replace("/", ",").replace("，", ",").split(",") if s.strip()]
        return items or None
    return raw


def map_row(row: dict, fmap: dict[str, str | None]) -> tuple[dict, dict]:
    """시트 행 → (OS 속성 dict, 특수처리 dict). 매핑 없는 필드는 무시."""
    data: dict = {}
    special: dict = {}
    for sheet_field, attr in fmap.items():
        if attr is None:
            continue
        raw = row.get(sheet_field, "")
        if attr.startswith("_"):
            if raw:
                special[attr] = raw
            continue
        v = convert(attr, raw)
        if v is not None:
            data[attr] = v
    return data, special


# ── 세트옵션 텍스트 표현 ───────────────────────────────────────────────────────
# 시트에는 '1개입:15000; 2개입:28000' 한 칸으로 적고 OS는 JSON 으로 갖는다.
# 양방향(import/export)이 반드시 같은 함수를 써야 한다. 안 그러면 왕복할 때마다
# qty·notes 가 사라진 걸 '값이 바뀌었다'고 오인해 매번 '수정'으로 잡힌다.

def parse_options(raw: str) -> list[dict] | None:
    """'1개입:15000; 2개입:28000' → [{name, qty, price, notes}, ...].

    옵션 구분자는 **세미콜론(;) 또는 줄바꿈**뿐이다. 콤마는 구분자가 아니다 —
    옵션 이름에 콤마가 들어가는 경우가 흔해서('구성: 뚜껑, 패킹, 스프링, 받침')
    콤마를 구분자로 쓰면 이름이 쪼개지고, 반대로 이름의 콜론까지 겹치면
    어느 쪽이 구분자인지 원리적으로 구별할 수 없다.
    가격은 각 조각의 **마지막 콜론** 뒤로 본다. 가격이 없는 옵션도 허용.
    """
    import re
    raw = (raw or "").strip()
    if not raw:
        return None
    chunks = [c.strip() for c in re.split(r"[\n;]", raw) if c.strip()]
    items: list[dict] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        name, price = chunk, None
        if ":" in chunk:
            head, _, tail = chunk.rpartition(":")
            price = _num(tail)
            if price is not None:          # 콜론 뒤가 숫자가 아니면 이름의 일부다
                name = head
        items.append({"name": name.strip(), "qty": 1, "price": price, "notes": ""})
    return items or None


def options_to_text(options) -> str:
    """set_options JSON → 시트 한 칸 문자열 (세미콜론 구분). 비교 정규화에도 쓴다."""
    if not options or not isinstance(options, list):
        return ""
    parts = []
    for o in options:
        if not isinstance(o, dict):
            continue
        name = str(o.get("name") or "").strip()
        if not name:
            continue
        price = o.get("price")
        parts.append(f"{name}:{int(price)}" if price else name)
    return "; ".join(parts)


def unmapped_fields(tab: str, dictionary: dict[str, list[FieldDef]],
                    fmap: dict[str, str | None]) -> list[str]:
    """데이터사전상 input 필드인데 OS로 못 넘어가는 것들 (리포트용)."""
    out = []
    for fd in dictionary.get(tab, []):
        if not fd.is_input:
            continue
        if fmap.get(fd.field_name) is None:
            out.append(f"{fd.field_name}({fd.korean_label})")
    return out


def preview(entity: str) -> dict:
    """시트를 읽어 무엇이 들어오고 무엇이 빠지는지 요약 (저장하지 않음)."""
    if entity not in ENTITIES:
        return {"ok": False, "error": f"알 수 없는 대상: {entity}"}
    if not is_configured():
        return {"ok": False, "error": "미설정 (.env: GOOGLE_SA_JSON, INTEGRATED_SHEET_ID)"}
    spec = ENTITIES[entity]
    try:
        sh = _open()
        dictionary = read_dictionary(sh)
        headers, rows = read_tab(spec["tab"], sh)
        mapped = [map_row(r, spec["map"]) for r in rows]
        return {
            "ok": True,
            "entity": entity,
            "label": spec["label"],
            "tab": spec["tab"],
            "sheet_url": sh.url,
            "headers": headers,
            "row_count": len(rows),
            "rows": [{**d, **s} for d, s in mapped[:20]],
            "unmapped": unmapped_fields(spec["tab"], dictionary, spec["map"]),
        }
    except Exception as e:
        log.exception("sheets preview failed: %s", entity)
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
