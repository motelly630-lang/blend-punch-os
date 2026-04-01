"""
파이프라인 작업 상태 — 서버 재시작에도 유지되는 영구 job 추적.
기존 _running_jobs 딕셔너리(메모리)를 대체한다.
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Integer, JSON
from app.models.base import Base


class PipelineJob(Base):
    __tablename__ = "pipeline_jobs"

    id          = Column(String(36), primary_key=True)   # = target_id
    company_id  = Column(Integer, default=1)
    target_type = Column(String(20), default="product")  # "product" | "brand"
    status      = Column(String(20), default="running")  # running|done|error
    result      = Column(JSON, nullable=True)
    error       = Column(Text, nullable=True)
    started_at  = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
