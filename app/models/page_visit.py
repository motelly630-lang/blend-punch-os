import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey
from app.models.base import Base


class PageVisitLog(Base):
    __tablename__ = "page_visit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    path = Column(String(500), nullable=False)
    visited_at = Column(DateTime, nullable=False, index=True)
