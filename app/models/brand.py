import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Integer, Float, ForeignKey, Boolean
from app.models.base import Base


class Brand(Base):
    __tablename__ = "brands"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    name = Column(String(200), nullable=False, unique=True)
    logo = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    is_archived = Column(Boolean, default=False)

    # AI 에이전트 파이프라인
    review_status  = Column(String(30), default="draft")
    priority_score = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
