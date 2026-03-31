import uuid
from datetime import datetime
from sqlalchemy import Column, ForeignKey, Integer, String, Float, Text, DateTime, JSON, Boolean
from app.models.base import Base


class TrendItem(Base):
    __tablename__ = "trend_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    category = Column(String(50), nullable=False)           # 식품|주방|리빙|뷰티|건강|다이어트|육아|반려동물
    title = Column(String(300), nullable=False)
    summary = Column(Text, nullable=True)
    source_url = Column(Text, nullable=True)
    trend_score = Column(Float, default=5.0)               # 1.0 ~ 10.0
    tags = Column(JSON, nullable=True)                     # list[str]
    recommended_inf_categories = Column(JSON, nullable=True)  # list[str]
    is_pinned = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
