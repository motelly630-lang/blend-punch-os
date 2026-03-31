import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Integer
from sqlalchemy.orm import relationship
from app.models.base import Base


class GroupBuyApplication(Base):
    __tablename__ = "group_buy_applications"

    id           = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id   = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    product_id   = Column(String(36), ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    product_name = Column(String(200), nullable=False)
    brand        = Column(String(200), nullable=True)

    applicant_name  = Column(String(100), nullable=False)
    contact_type    = Column(String(20),  nullable=False)   # 카카오|인스타|전화|이메일
    contact_value   = Column(String(200), nullable=False)
    channel_handle  = Column(String(200), nullable=True)
    followers       = Column(String(50),  nullable=True)    # 예: "5만", "12,000"
    message         = Column(Text,        nullable=True)

    status     = Column(String(20), default="new")          # new|reviewing|approved|rejected
    admin_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", foreign_keys=[product_id], lazy="joined")
