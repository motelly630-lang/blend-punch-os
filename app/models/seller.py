import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, Text, DateTime, ForeignKey
from app.models.base import Base


class Seller(Base):
    __tablename__ = "sellers"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    seller_code = Column(String(50), unique=True, nullable=False)   # URL 파라미터 ?seller=xxx
    name = Column(String(200), nullable=False)
    influencer_id = Column(String(36), ForeignKey("influencers.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
