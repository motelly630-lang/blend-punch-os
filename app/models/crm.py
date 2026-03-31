import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Text, DateTime, Date, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base


CRM_STATUSES = [
    "new",              # 신규 발굴
    "dm_sent",          # DM 발송
    "replied",          # 답변 수신
    "sample_requested", # 샘플 요청
    "sample_sent",      # 샘플 발송
    "negotiating",      # 협의중
    "completed",        # 계약 완료
    "rejected",         # 거절
]

CRM_STATUS_LABELS = {
    "new": "신규",
    "dm_sent": "DM 발송",
    "replied": "답변 수신",
    "sample_requested": "샘플 요청",
    "sample_sent": "샘플 발송",
    "negotiating": "협의중",
    "completed": "계약 완료",
    "rejected": "거절",
}

SAMPLE_LOG_STATUSES = ["pending", "sent", "delivered", "reviewing", "returned"]
SAMPLE_LOG_STATUS_LABELS = {
    "pending": "발송 준비",
    "sent": "발송 완료",
    "delivered": "수령 완료",
    "reviewing": "리뷰 중",
    "returned": "반송",
}


class CrmPipeline(Base):
    __tablename__ = "crm_pipelines"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    influencer_id = Column(String(36), ForeignKey("influencers.id"), nullable=False)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=True)
    status = Column(String(30), default="new")
    last_contact_date = Column(Date, nullable=True)
    dm_count = Column(Integer, default=0)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    influencer = relationship("Influencer", foreign_keys=[influencer_id])
    product = relationship("Product", foreign_keys=[product_id])
    sample_logs = relationship("SampleLog", back_populates="pipeline", cascade="all, delete-orphan")


class SampleLog(Base):
    __tablename__ = "sample_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    pipeline_id = Column(String(36), ForeignKey("crm_pipelines.id"), nullable=False)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=True)
    influencer_id = Column(String(36), ForeignKey("influencers.id"), nullable=True)
    tracking_number = Column(String(100), nullable=True)
    status = Column(String(30), default="pending")
    notes = Column(Text, nullable=True)
    sent_at = Column(Date, nullable=True)
    delivered_at = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    pipeline = relationship("CrmPipeline", back_populates="sample_logs")
    product = relationship("Product", foreign_keys=[product_id])
    influencer = relationship("Influencer", foreign_keys=[influencer_id])
