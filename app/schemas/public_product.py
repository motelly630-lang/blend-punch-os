"""
PublicProduct DTO — 외부 공개 전용 제품 데이터 구조

절대 포함 금지:
  supplier_price, vendor_commission_rate, lowest_price,
  internal_notes, notes, ai_analysis_raw, missing_fields,
  is_complete, review_status, priority_score
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PublicProduct:
    # ── 기본 식별 ──────────────────────────────────────────────────
    id: str
    name: str
    brand: str
    category: str

    # ── 이미지 ────────────────────────────────────────────────────
    product_image: Optional[str] = None

    # ── 설명 (공개 가능) ─────────────────────────────────────────
    description: Optional[str] = None
    unique_selling_point: Optional[str] = None
    key_benefits: Optional[list] = None
    categories: Optional[list] = None        # 소비자 카테고리 태그
    content_angle: Optional[str] = None
    group_buy_guideline: Optional[str] = None

    # ── 세트 구성 (이름/가격/수량만 — set_options의 notes 제외) ──
    set_options: Optional[list] = None

    # ── 링크 ──────────────────────────────────────────────────────
    source_url: Optional[str] = None
    product_link: Optional[str] = None

    # ── 공개 가격 (공구가 / 소비자가 / 할인율만) ─────────────────
    # ❌ supplier_price, lowest_price, vendor_commission_rate 절대 포함 금지
    groupbuy_price: float = 0.0
    consumer_price: float = 0.0
    discount_rate: float = 0.0              # DB 저장값: 0.30 = 30%

    # ── 인플루언서 판단 정보 ──────────────────────────────────────
    seller_commission_rate: float = 0.0     # 인플루언서 커미션율
    sample_type: Optional[str] = None       # 무상 / 유상 / 없음
    sample_price: Optional[float] = None    # 유상 샘플 가격 (공개 OK)
    shipping_type: Optional[str] = None     # 무료배송 / 유료배송
    dispatch_days: Optional[str] = None     # 당일 / 1~2일 / 3~5일 / 주문제작

    @classmethod
    def from_orm(cls, p) -> "PublicProduct":
        # set_options에서 내부 메모 필드 제거
        safe_sets = None
        if p.set_options:
            safe_sets = [
                {k: v for k, v in s.items() if k in ("name", "price", "qty", "components")}
                for s in p.set_options
                if isinstance(s, dict)
            ]

        return cls(
            id=p.id,
            name=p.name,
            brand=p.brand,
            category=p.category,
            product_image=p.product_image,
            description=p.description,
            unique_selling_point=p.unique_selling_point,
            key_benefits=p.key_benefits,
            categories=p.categories,
            content_angle=p.content_angle,
            group_buy_guideline=p.group_buy_guideline,
            set_options=safe_sets or None,
            source_url=p.source_url,
            product_link=p.product_link,
            groupbuy_price=p.groupbuy_price or 0.0,
            consumer_price=p.consumer_price or 0.0,
            discount_rate=p.discount_rate or 0.0,
            seller_commission_rate=p.seller_commission_rate or 0.0,
            sample_type=p.sample_type,
            sample_price=p.sample_price if p.sample_type == "유상" else None,
            shipping_type=p.shipping_type,
            dispatch_days=p.dispatch_days,
        )
