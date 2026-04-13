import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Text, DateTime, JSON, Boolean, Integer, ForeignKey
from app.models.base import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    name = Column(String(200), nullable=False)
    brand = Column(String(200), nullable=False)
    category = Column(String(100), nullable=False)
    price = Column(Float, default=0.0)
    source_url = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    target_audience = Column(Text, nullable=True)
    key_benefits = Column(JSON, nullable=True)               # list[str]
    unique_selling_point = Column(Text, nullable=True)
    estimated_demand = Column(String(20), default="medium")  # high|medium|low
    recommended_commission_rate = Column(Float, default=0.15)
    content_angle = Column(Text, nullable=True)
    ai_analysis_raw = Column(Text, nullable=True)
    status = Column(String(20), default="draft")             # draft|active|archived
    visibility_status = Column(String(20), default="active") # active|hidden (catalog visibility)

    # Phase 2 additions
    product_image = Column(String(500), nullable=True)       # /uploads/products/xxx.jpg
    set_options = Column(JSON, nullable=True)                # [{name,qty,price,notes}]
    positioning = Column(Text, nullable=True)                # 포지셔닝 전략
    usage_scenes = Column(Text, nullable=True)               # 사용 장면
    recommended_inf_categories = Column(JSON, nullable=True) # list[str]
    categories = Column(JSON, nullable=True)                 # list[str] broad consumer tags
    group_buy_guideline = Column(Text, nullable=True)        # public-facing guide

    # Phase 3 additions
    internal_notes = Column(Text, nullable=True)             # 내부 메모
    shipping_type = Column(String(20), nullable=True)        # 무료배송|유료배송
    shipping_cost = Column(Float, nullable=True)             # 배송비 금액
    carrier = Column(String(50), nullable=True)              # 택배사
    ship_origin = Column(String(20), nullable=True)          # 국내|해외
    dispatch_days = Column(String(20), nullable=True)        # 당일|1~2일|3~5일|주문제작
    sample_type = Column(String(20), nullable=True)          # 무상|유상|없음
    sample_price = Column(Float, nullable=True)              # 샘플 가격 (유상일 때)

    # Phase 5 additions — full pricing structure
    consumer_price = Column(Float, default=0.0)              # 소비자가 (public)
    lowest_price = Column(Float, default=0.0)                # 최저가 (internal)
    supplier_price = Column(Float, default=0.0)              # 공급가 (INTERNAL ONLY)
    groupbuy_price = Column(Float, default=0.0)              # 공구가 (public)
    discount_rate = Column(Float, default=0.0)               # 할인율 decimal e.g. 0.30
    seller_commission_rate = Column(Float, default=0.0)      # 셀러 커미션 (public)
    vendor_commission_rate = Column(Float, default=0.0)      # 벤더 마진 (INTERNAL ONLY)
    product_link = Column(Text, nullable=True)               # 상품 링크

    # AI Assistant additions
    product_type = Column(String(1), default="A")            # A/B/C/D type classifier

    # 메모 (자유 입력, 내부 전용)
    notes = Column(Text, nullable=True)

    # SHOP 노출
    is_published = Column(Boolean, default=False)                    # SHOP 노출 여부

    # Data completeness
    is_complete = Column(Boolean, default=False)             # 필수 필드 모두 채워진 경우 True
    missing_fields = Column(JSON, nullable=True)             # list[str] 미입력 필드 레이블 목록
    is_archived = Column(Boolean, default=False)

    # AI 에이전트 파이프라인
    review_status  = Column(String(30), default="draft")   # draft|structured|reviewed|strategy_checked|approved|rejected
    priority_score = Column(Float, nullable=True)           # 이사 최종 점수 (0~100)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
