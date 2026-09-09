"""가격·마진·정산 계산 (순수 Python, AI 미사용 — 결정적 계산).

소싱 에이전트 3·4단계. 모든 금액 단위는 원(KRW), 정수 반올림.

[3단계] 마진:
  - 마진율   = (공구가 - 공급가) / 공구가
  - 마진(원) = 공구가 - 공급가
  - 할인율   = 1 - 공구가 / 소비자가

[4단계] 인플루언서(셀러) 수수료 정산 — 셀러 유형별 세금 공제 (스크린샷 기준):
  - 수수료금액 = 총판매금액 × 수수료율
  - 사업자(general)      : 공제 없음            → 정산 = 수수료              (세금계산서 발행)
  - 간이사업자(simplified): 부가세(수수료×10%) 공제 → 정산 = 수수료 - 부가세        (현금영수증 발행)
  - 프리랜서(freelancer)  : 부가세 + 원천징수      → 정산 = 수수료 - 부가세 - 원천징수
        원천징수 = (수수료 - 부가세) × 3.3%
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 정산 시뮬에 노출할 기본 셀러 수수료율 시나리오
DEFAULT_COMMISSION_SCENARIOS = (0.10, 0.12, 0.15, 0.18, 0.20)

# 셀러 유형 (세금 처리 구분)
SELLER_TYPES = ("사업자", "간이사업자", "프리랜서")

VAT_RATE = 0.10          # 부가세
WITHHOLDING_RATE = 0.033  # 원천징수 (소득세 3% + 지방소득세 0.3%)


def _round(v: float) -> int:
    return int(round(v or 0))


# ── 3단계: 마진 ───────────────────────────────────────────────────────────────

def margin_rate(supplier_price: float, groupbuy_price: float) -> float | None:
    if not groupbuy_price or groupbuy_price <= 0:
        return None
    return round((groupbuy_price - supplier_price) / groupbuy_price, 4)


def margin_amount(supplier_price: float, groupbuy_price: float) -> int:
    return _round((groupbuy_price or 0) - (supplier_price or 0))


def discount_rate(consumer_price: float, groupbuy_price: float) -> float | None:
    if not consumer_price or consumer_price <= 0:
        return None
    return round(1 - (groupbuy_price or 0) / consumer_price, 4)


# ── 4단계: 셀러 수수료 정산 (유형별 세금 공제) ─────────────────────────────────

@dataclass
class Settlement:
    seller_type: str          # 사업자|간이사업자|프리랜서
    commission_rate: float    # 0.20
    total_sales: int          # 총판매금액
    commission_amount: int    # 수수료금액 = 총판매 × 율
    vat: int                  # 공제된 부가세
    withholding: int          # 공제된 원천징수
    settlement_amount: int    # 셀러가 실제 받는 정산금
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "seller_type": self.seller_type,
            "commission_rate": self.commission_rate,
            "total_sales": self.total_sales,
            "commission_amount": self.commission_amount,
            "vat": self.vat,
            "withholding": self.withholding,
            "settlement_amount": self.settlement_amount,
            "note": self.note,
        }


_NOTES = {
    "사업자": "세금계산서 발행",
    "간이사업자": "부가세 제외 · 현금영수증 발행",
    "프리랜서": "부가세 + 3.3% 제외",
}


def settle(total_sales: float, commission_rate: float, seller_type: str = "사업자") -> Settlement:
    """셀러 유형별 정산금 계산. 스크린샷 공식과 1:1 일치."""
    commission = (total_sales or 0) * (commission_rate or 0)
    if seller_type == "간이사업자":
        vat = commission * VAT_RATE
        wh = 0.0
    elif seller_type == "프리랜서":
        vat = commission * VAT_RATE
        wh = (commission - vat) * WITHHOLDING_RATE
    else:  # 사업자 (기본)
        vat = 0.0
        wh = 0.0
    settlement = commission - vat - wh
    return Settlement(
        seller_type=seller_type,
        commission_rate=commission_rate,
        total_sales=_round(total_sales),
        commission_amount=_round(commission),
        vat=_round(vat),
        withholding=_round(wh),
        settlement_amount=_round(settlement),
        note=_NOTES.get(seller_type, ""),
    )


def settlement_matrix(
    total_sales: float,
    rate: float,
    seller_types: tuple[str, ...] = SELLER_TYPES,
) -> list[Settlement]:
    """고정 총판매금액·수수료율에서 셀러 유형별 정산 (스크린샷 표 구조)."""
    return [settle(total_sales, rate, t) for t in seller_types]


# ── 통합 가격 분해 ─────────────────────────────────────────────────────────────

@dataclass
class PriceBreakdown:
    consumer_price: int
    supplier_price: int
    groupbuy_price: int
    discount_rate: float | None
    margin_rate: float | None
    margin_amount: int
    # 1건(공구가) 기준, 수수료율 시나리오별 × 셀러유형별 정산
    settlements: list[Settlement] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "consumer_price": self.consumer_price,
            "supplier_price": self.supplier_price,
            "groupbuy_price": self.groupbuy_price,
            "discount_rate": self.discount_rate,
            "margin_rate": self.margin_rate,
            "margin_amount": self.margin_amount,
            "settlements": [s.as_dict() for s in self.settlements],
        }


def compute(
    consumer_price: float = 0,
    supplier_price: float = 0,
    groupbuy_price: float = 0,
    scenarios: tuple[float, ...] = DEFAULT_COMMISSION_SCENARIOS,
    seller_types: tuple[str, ...] = SELLER_TYPES,
) -> PriceBreakdown:
    """마진 분해 + (1건=공구가 기준) 수수료율×셀러유형 정산 매트릭스.

    실제 총판매금액이 있으면 settlement_matrix(total_sales, rate, types)를 직접 호출.
    """
    settlements: list[Settlement] = []
    for rate in scenarios:
        settlements.extend(settlement_matrix(groupbuy_price or 0, rate, seller_types))
    return PriceBreakdown(
        consumer_price=_round(consumer_price),
        supplier_price=_round(supplier_price),
        groupbuy_price=_round(groupbuy_price),
        discount_rate=discount_rate(consumer_price, groupbuy_price),
        margin_rate=margin_rate(supplier_price, groupbuy_price),
        margin_amount=margin_amount(supplier_price, groupbuy_price),
        settlements=settlements,
    )
