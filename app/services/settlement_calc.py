"""정산 계산 — **이 파일 하나만** 금액을 계산한다 (정산 화면·자동 정산·엑셀·시트·소싱 시뮬레이션 공용).

대표님 확정 규칙 (2026-09-24). 정산 대상 금액 = 총 판매금액 × 수수료율 (부가세 포함 금액으로 본다):

| 유형       | 실지급액                                   | 증빙          |
|------------|--------------------------------------------|---------------|
| 사업자     | 정산 대상 금액 전부                        | 세금계산서    |
| 간이사업자 | 부가세만 뺌 = 대상 ÷ 1.1                   | 현금영수증    |
| 프리랜서   | 대상 ÷ 1.1 에서 다시 3.3% 원천징수를 뺌     | 원천징수 3.3% |

예) 대상 100,000원 → 사업자 100,000 / 간이사업자 90,909 / 프리랜서 90,909 − 3,000 = 87,909
반올림: 원 단위 사사오입(ROUND_HALF_UP). 3.3% 는 한 번에 계산한다 (대표님 표 기준).
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

SELLER_TYPES = ("사업자", "간이사업자", "프리랜서")
VAT_DIVISOR = Decimal("1.1")
WITHHOLDING_RATE = Decimal("0.033")
EVIDENCE = {"사업자": "세금계산서", "간이사업자": "현금영수증", "프리랜서": "원천징수 3.3%"}
CALC_VERSION = "2026-09"


def _won(x: Decimal) -> int:
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calc(sales_amount, commission_rate, seller_type: str) -> dict:
    """총 판매금액·수수료율(0~1)·유형 → 금액 전부. 모르는 유형은 사업자로 계산한다."""
    if seller_type not in SELLER_TYPES:
        seller_type = "사업자"
    sales = Decimal(str(sales_amount or 0))
    rate = Decimal(str(commission_rate or 0))
    commission = _won(sales * rate)                       # 정산 대상 금액 (부가세 포함)
    supply = _won(Decimal(commission) / VAT_DIVISOR)       # 공급가액
    vat = commission - supply                             # 부가세
    withholding = 0
    if seller_type == "사업자":
        final = commission
    elif seller_type == "간이사업자":
        final = supply
    else:
        withholding = _won(Decimal(supply) * WITHHOLDING_RATE)
        final = supply - withholding
    return {
        "seller_type": seller_type,
        "commission_amount": commission,
        "supply_amount": supply,
        "vat_amount": vat,
        "tax_rate": float(WITHHOLDING_RATE) if seller_type == "프리랜서" else 0.0,
        "tax_amount": withholding,
        "final_payment": final,
        "evidence": EVIDENCE[seller_type],
    }


def model_fields(sales_amount, commission_rate, seller_type: str) -> dict:
    """Settlement 모델에 바로 넣을 칸만 (commission/supply/vat/tax/final + 계산 버전)."""
    c = calc(sales_amount, commission_rate, seller_type)
    return {k: c[k] for k in ("commission_amount", "supply_amount", "vat_amount", "tax_rate",
                              "tax_amount", "final_payment")} | {"calc_version": CALC_VERSION}


def resolve_rate(campaign=None, product=None, influencer=None) -> tuple[float | None, str]:
    """수수료율 자동 찾기: 캠페인 셀러 수수료율 → 제품 셀러 수수료율 → 인플루언서 선호 수수료율.
    (캠페인의 옛 commission_rate 칸은 폼이 0 으로 보내는 경우가 있어 쓰지 않는다.) → (율, 출처)"""
    for obj, attr, label in ((campaign, "seller_commission_rate", "캠페인"),
                             (product, "seller_commission_rate", "제품"),
                             (influencer, "commission_preference", "인플루언서 기본값")):
        v = getattr(obj, attr, None) if obj is not None else None
        if v and v > 0:
            return float(v), label
    return None, ""
