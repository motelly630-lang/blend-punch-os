import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Text, DateTime, JSON, ForeignKey, Integer, Boolean
from app.models.base import Base


class SalesPage(Base):
    __tablename__ = "sales_pages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    slug = Column(String(100), unique=True, nullable=False)          # /shop/{slug}
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False)
    title = Column(String(300), nullable=True)                       # 판매 페이지 전용 타이틀
    description = Column(Text, nullable=True)                        # 짧은 텍스트 설명
    editor_content = Column(Text, nullable=True)                     # 리치 HTML (스마트스토어 붙여넣기)
    price = Column(Float, nullable=False, default=0.0)               # 실제 판매가
    original_price = Column(Float, nullable=True)                    # 정상가 (할인율 표시용)
    stock_quantity = Column(Integer, nullable=True)                  # None = 무제한
    main_image = Column(String(500), nullable=True)                  # 판매 페이지 전용 대표이미지
    extra_images = Column(JSON, nullable=True)                       # ["/static/uploads/..."]
    options = Column(JSON, nullable=True)                            # [{name, price, stock}]
    addon_products = Column(JSON, nullable=True)                     # [{name, price, max_qty, desc}]
    shipping_type = Column(String(20), default="free")               # free/paid
    shipping_cost = Column(Float, default=0.0)
    carrier = Column(String(50), nullable=True)
    status = Column(String(20), default="draft")                     # draft|scheduled|active|ended|closed
    starts_at = Column(DateTime, nullable=True)
    ends_at = Column(DateTime, nullable=True)

    # Commerce Upgrade — OS-SHOP 연결
    campaign_id  = Column(String(36), ForeignKey("campaigns.id"), nullable=True)
    is_published = Column(Boolean, default=False)                    # SHOP 노출 여부
    allowed_seller_codes = Column(JSON, nullable=True)               # null=모두허용, list=제한
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
