import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from app.models.base import Base


class Inquiry(Base):
    __tablename__ = "inquiries"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("shop_users.id"), nullable=True)
    name = Column(String(100), nullable=False)
    contact = Column(String(100), nullable=False)
    category = Column(String(50), nullable=False)   # 제품문의 / 서비스문의 / 기타
    message = Column(Text, nullable=False)
    status = Column(String(20), default="pending")  # pending / read / replied
    reply = Column(Text, nullable=True)
    replied_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
