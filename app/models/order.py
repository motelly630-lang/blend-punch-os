import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Text, DateTime, Integer, ForeignKey, JSON
from app.models.base import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    order_number = Column(String(50), unique=True, nullable=False)   # BP-YYYYMMDD-XXXXXX

    # 판매 페이지 / 상품
    sales_page_id = Column(String(36), ForeignKey("sales_pages.id"), nullable=False)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False)

    # 셀러 추적 (핵심)
    seller_id = Column(String(36), ForeignKey("sellers.id"), nullable=True)
    seller_code = Column(String(50), nullable=True)                  # 비정규화 — 항상 저장

    # 구매자 정보
    customer_name = Column(String(100), nullable=False)
    customer_phone = Column(String(20), nullable=False)
    customer_email = Column(String(200), nullable=True)

    # 배송 정보
    shipping_name = Column(String(100), nullable=False)
    shipping_phone = Column(String(20), nullable=False)
    shipping_address = Column(Text, nullable=False)
    shipping_address2 = Column(Text, nullable=True)
    shipping_zipcode = Column(String(10), nullable=False)
    shipping_memo = Column(Text, nullable=True)

    # 주문 상품 (비정규화 — 가격 변동 대응)
    option_name = Column(String(200), nullable=True)
    quantity = Column(Integer, default=1)
    unit_price = Column(Float, nullable=False)
    total_price = Column(Float, nullable=False)
    addon_items = Column(JSON, nullable=True)                        # [{name, price, qty}]

    # 결제 (토스페이먼츠)
    payment_key = Column(String(200), nullable=True)
    payment_method = Column(String(50), nullable=True)               # 카드|가상계좌|계좌이체
    payment_status = Column(String(20), default="pending")          # pending|paid|cancelled|refunded
    paid_at = Column(DateTime, nullable=True)

    # 주문/배송 상태
    order_status = Column(String(20), default="pending")            # pending|confirmed|shipping|delivered|cancelled
    carrier_name = Column(String(50), nullable=True)
    tracking_number = Column(String(100), nullable=True)
    shipped_at = Column(DateTime, nullable=True)

    # 관리자 메모
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
