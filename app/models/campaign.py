import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Text, DateTime, Date, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(300), nullable=False)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=True)
    influencer_id = Column(String(36), ForeignKey("influencers.id"), nullable=True)
    status = Column(String(30), default="planning")
    # planning|negotiating|contracted|active|completed|cancelled
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    commission_rate = Column(Float, nullable=True)
    expected_sales = Column(Integer, default=0)
    actual_sales = Column(Integer, default=0)
    actual_revenue = Column(Float, default=0.0)
    notes = Column(Text, nullable=True)

    # Phase 5 additions — commission split
    unit_price = Column(Float, default=0.0)
    seller_commission_rate = Column(Float, default=0.0)      # 셀러 커미션율
    vendor_commission_rate = Column(Float, default=0.0)      # 벤더 마진율
    seller_commission_amount = Column(Float, default=0.0)    # 셀러 지급액 (calculated)
    vendor_commission_amount = Column(Float, default=0.0)    # 벤더 수익액 (calculated)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = relationship("Product", foreign_keys=[product_id])
    influencer = relationship("Influencer", foreign_keys=[influencer_id])
