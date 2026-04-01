import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Text, DateTime, Date, Integer, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    campaign_id = Column(String(36), ForeignKey("campaigns.id"), nullable=True, index=True)

    type = Column(String(10), nullable=False)       # revenue / cost
    source = Column(String(30), nullable=False)     # smartstore / external_link / manual
    category = Column(String(30), nullable=True)    # supply_price / ad_cost / other (cost 전용)
    amount = Column(Float, default=0.0)
    transaction_date = Column(Date, nullable=True)
    description = Column(String(300), nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    campaign = relationship("Campaign", foreign_keys=[campaign_id])
