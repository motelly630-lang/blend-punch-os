"""Google Sheets 연동 — 소싱 검수 결과를 스프레드시트에 자동 입력.

설정 (.env):
  GOOGLE_SA_JSON   = 서비스계정 키 JSON 파일 경로
  SOURCING_SHEET_ID= 대상 스프레드시트 ID

서비스계정 발급 + 시트 공유 방법은 docs/sourcing_agent_design.md 참조.
탭: '상품마스터'(추출+계산), '정산시뮬'(셀러 유형×수수료율).
"""
from __future__ import annotations

import logging

from app.config import settings
from app.sourcing import pricing

log = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

MASTER_TAB = "제품목록"
SETTLE_TAB = "정산시뮬"

# 사장님 제품 등록 템플릿(blendpunch_product_template)과 동일한 22컬럼
MASTER_HEADERS = [
    "제품명", "브랜드", "카테고리", "상태", "카탈로그공개여부", "이미지URL", "제품URL", "제품설명",
    "소비자가", "공구가", "셀러커미션율", "할인율",
    "핵심셀링포인트", "핵심혜택", "콘텐츠앵글", "포지셔닝전략",
    "배송유형", "배송비", "택배사", "출고지", "샘플여부", "소비자카테고리",
]

SETTLE_HEADERS = ["상품명", "공구가", "셀러유형", "수수료율", "수수료금액", "부가세", "원천징수", "정산금액", "비고"]


def is_configured() -> bool:
    return bool(settings.google_sa_json and settings.sourcing_sheet_id)


def _client():
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(settings.google_sa_json, scopes=_SCOPES)
    return gspread.authorize(creds)


def _ws(sh, title: str, headers: list[str]):
    """탭 가져오거나 생성하고 헤더 보장."""
    try:
        ws = sh.worksheet(title)
    except Exception:
        ws = sh.add_worksheet(title=title, rows=1000, cols=max(26, len(headers)))
    return ws


def _join(v) -> str:
    if isinstance(v, list):
        return " / ".join(str(x) for x in v)
    return "" if v is None else str(v)


def _pct(v) -> str:
    return f"{float(v) * 100:.1f}%" if v is not None else ""


def _cert(v) -> str:
    if not v:
        return ""
    return " / ".join(f"{c.get('type','')}{(' ' + c['number']) if c.get('number') else ''}" for c in v)


def _pct_num(v) -> str:
    """0~1 소수 → 정수% (예: 0.15→'15', 0.2168→'22'). 템플릿은 숫자(%)."""
    return str(round((v or 0) * 100)) if v is not None else ""


def _master_row(batch_id: str, p) -> list:
    """사장님 22컬럼 템플릿 형식으로 매핑 (그대로 OS 임포트/등록 가능)."""
    comm = p.seller_commission_rate or p.recommended_commission_rate or 0
    sample_map = {"무상": "무상", "유상": "유상", None: "없음", "": "없음"}
    return [
        p.name or "",
        p.brand or "",
        p.category or "",
        "draft",                                  # 상태 (승인 전)
        p.visibility_status or "active",          # 카탈로그공개여부
        p.product_image or "",                    # 이미지URL (네이버 쇼핑 이미지)
        p.product_link or "",                     # 제품URL (네이버 상품별)
        p.description or "",
        p.consumer_price or 0,
        p.groupbuy_price or 0,
        _pct_num(comm),                           # 셀러커미션율 (숫자%)
        _pct_num(p.discount_rate),                # 할인율 (숫자%)
        p.unique_selling_point or "",             # 핵심셀링포인트
        _join(p.key_benefits),                    # 핵심혜택 (쉼표)
        p.content_angle or "",
        p.positioning or "",
        p.shipping_type or "",                    # 배송유형
        p.shipping_cost or 0,
        p.carrier or "",
        p.ship_origin or "",                      # 출고지
        sample_map.get(p.sample_type, p.sample_type or "없음"),
        _join(p.categories),                      # 소비자카테고리 (쉼표)
    ]


def _ensure_header(ws, headers: list[str]) -> list[list[str]]:
    """헤더 보장 후 현재 전체 값 반환."""
    vals = ws.get_all_values()
    if not vals or vals[0][:1] != headers[:1]:
        ws.insert_row(headers, index=1, value_input_option="USER_ENTERED")
        vals = ws.get_all_values()
    return vals


def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def sync_batch(batch_id: str, products: list) -> dict:
    """배치 상품을 시트에 upsert (상품ID 기준: 있으면 갱신, 없으면 추가). 중복 방지."""
    if not is_configured():
        return {"ok": False, "error": "Google Sheets 미설정 (.env: GOOGLE_SA_JSON, SOURCING_SHEET_ID)"}
    if not products:
        return {"ok": False, "error": "상품이 없습니다."}

    try:
        sh = _client().open_by_key(settings.sourcing_sheet_id)

        # ── 제품목록: (제품명+브랜드) 기준 upsert (중복 방지) ──
        master = _ws(sh, MASTER_TAB, MASTER_HEADERS)
        vals = _ensure_header(master, MASTER_HEADERS)
        key_to_row = {(row[0], row[1] if len(row) > 1 else ""): i + 1
                      for i, row in enumerate(vals) if i > 0 and row and row[0]}
        last_col = _col_letter(len(MASTER_HEADERS))

        updated = added = 0
        appends = []
        for p in products:
            row = _master_row(batch_id, p)
            key = (p.name or "", p.brand or "")
            if key in key_to_row:
                rn = key_to_row[key]
                master.update(f"A{rn}:{last_col}{rn}", [row], value_input_option="USER_ENTERED")
                updated += 1
            else:
                appends.append(row)
                added += 1
        if appends:
            master.append_rows(appends, value_input_option="USER_ENTERED")

        # ── 정산시뮬: 상품명+유형 기준 (간단히 전체 재작성보다 append, 상품ID 키로 중복 방지) ──
        settle = _ws(sh, SETTLE_TAB, SETTLE_HEADERS)
        svals = _ensure_header(settle, SETTLE_HEADERS)
        existing_keys = {(r[0], r[2]) for r in svals[1:] if len(r) > 2}  # (상품명, 유형)
        srows = []
        for p in products:
            for t in pricing.SELLER_TYPES:
                if (p.name or "", t) in existing_keys:
                    continue
                s = pricing.settle(p.groupbuy_price or 0, p.seller_commission_rate or p.recommended_commission_rate or 0.15, t)
                srows.append([p.name or "", s.total_sales, t, _pct(s.commission_rate),
                              s.commission_amount, s.vat, s.withholding, s.settlement_amount, s.note])
        if srows:
            settle.append_rows(srows, value_input_option="USER_ENTERED")

        return {"ok": True, "url": sh.url, "rows": len(products), "updated": updated, "added": added}
    except Exception as e:
        log.exception("sheet sync failed")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
