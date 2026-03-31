import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Integer, ForeignKey
from app.models.base import Base


SAMPLE_STATUSES = ["제안발송", "샘플요청", "샘플발송", "보류", "거절"]


class OutreachLog(Base):
    __tablename__ = "outreach_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    operator = Column(String(100), nullable=False)        # employee who logged
    influencer_handle = Column(String(200), nullable=False)
    influencer_id = Column(String(36), nullable=True)     # linked influencer (auto or manual)
    product_id = Column(String(36), nullable=True)        # pitched product
    outreach_date = Column(String(10), nullable=False)    # YYYY-MM-DD
    sample_status = Column(String(30), default="제안발송")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
