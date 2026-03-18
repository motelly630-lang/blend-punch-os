import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime
from app.models.base import Base


class Brand(Base):
    __tablename__ = "brands"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(200), nullable=False, unique=True)
    logo = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
