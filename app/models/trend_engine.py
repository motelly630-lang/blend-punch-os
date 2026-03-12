import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, JSON
from app.models.base import Base


class TrendBriefing(Base):
    __tablename__ = "trend_briefings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    report_date = Column(String(10), nullable=False)      # YYYY-MM-DD
    event_count = Column(Integer, default=0)
    product_match_count = Column(Integer, default=0)
    report_data = Column(JSON, nullable=True)             # full list of event+match dicts
    created_at = Column(DateTime, default=datetime.utcnow)
