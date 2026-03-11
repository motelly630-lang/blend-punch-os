import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base


class Proposal(Base):
    __tablename__ = "proposals"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id = Column(String(36), ForeignKey("products.id"), nullable=True)
    influencer_id = Column(String(36), ForeignKey("influencers.id"), nullable=True)
    campaign_id = Column(String(36), ForeignKey("campaigns.id"), nullable=True)
    proposal_type = Column(String(20), default="email")  # email|kakao
    title = Column(String(400), nullable=True)
    body = Column(Text, nullable=False)
    ai_generated = Column(Boolean, default=False)
    is_template = Column(Boolean, default=False)
    template_name = Column(String(200), nullable=True)
    sent_at = Column(DateTime, nullable=True)
    response_received = Column(Boolean, default=False)
    response_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = relationship("Product", foreign_keys=[product_id])
    influencer = relationship("Influencer", foreign_keys=[influencer_id])
    campaign = relationship("Campaign", foreign_keys=[campaign_id])
