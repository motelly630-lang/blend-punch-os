import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Boolean, ForeignKey, JSON, Integer
from sqlalchemy.orm import relationship
from app.models.base import Base


class Playbook(Base):
    __tablename__ = "playbooks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=True)
    product_name = Column(String(200), nullable=False)   # snapshot at generation time
    product_brand = Column(String(200), nullable=True)
    product_usp = Column(Text, nullable=True)
    content_angle = Column(Text, nullable=True)
    body_json = Column(JSON, nullable=True)               # structured sections dict
    body = Column(Text, nullable=False)                   # flat copy-ready text
    ai_generated = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", foreign_keys=[product_id])
