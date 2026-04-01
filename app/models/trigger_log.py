"""
자동 트리거 실행 로그.

승인(APPROVED) 시 자동으로 발생하는 액션(캠페인 생성, 제안서 생성 등)을 기록한다.
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Integer, JSON
from app.models.base import Base


class TriggerLog(Base):
    __tablename__ = "trigger_logs"

    id           = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id   = Column(Integer, default=1)

    # 트리거 발생 대상
    source_type  = Column(String(20), nullable=False)   # "product" | "brand"
    source_id    = Column(String(36), nullable=False)

    # 트리거 결과
    trigger_type = Column(String(50), nullable=False)   # "campaign_created" | "proposal_created"
    target_id    = Column(String(36), nullable=True)    # 생성된 캠페인/제안서 ID
    status       = Column(String(20), default="success") # success | error
    result       = Column(JSON, nullable=True)
    error_msg    = Column(Text, nullable=True)

    created_at   = Column(DateTime, default=datetime.utcnow)
