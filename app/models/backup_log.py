from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from app.models.base import Base


class BackupLog(Base):
    """DB 백업 이력 로그"""
    __tablename__ = "backup_logs"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    filename    = Column(String(200), nullable=False)
    size_kb     = Column(Integer, default=0)
    status      = Column(String(20), default="success")   # success | failed
    s3_uploaded = Column(Boolean, default=False)
    trigger     = Column(String(20), default="auto")      # auto | manual
    triggered_by = Column(String(100), nullable=True)     # username (수동 시)
    error_msg   = Column(Text, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)
