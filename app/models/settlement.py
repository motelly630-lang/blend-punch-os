import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base


class Settlement(Base):
    __tablename__ = "settlements"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    influencer_id = Column(String(36), ForeignKey("influencers.id"), nullable=True)
    campaign_id = Column(String(36), ForeignKey("campaigns.id"), nullable=True)
    period_label = Column(String(50), nullable=True)       # 예: "2024년 3월"
    seller_type = Column(String(20), default="사업자")     # 사업자|간이사업자|프리랜서
    sales_amount = Column(Float, default=0.0)              # 총 매출
    commission_rate = Column(Float, default=0.15)          # 커미션율
    commission_amount = Column(Float, default=0.0)         # 커미션 금액 (매출 × 커미션율)
    vat_amount = Column(Float, default=0.0)                # 부가세 (커미션 × 10%)
    tax_rate = Column(Float, default=0.0)                  # 원천징수율 (프리랜서 0.033)
    tax_amount = Column(Float, default=0.0)                # 원천징수액
    final_payment = Column(Float, default=0.0)             # 최종 지급액
    status = Column(String(20), default="pending")         # pending|confirmed|paid
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    influencer = relationship("Influencer", foreign_keys=[influencer_id])
    campaign = relationship("Campaign", foreign_keys=[campaign_id])
