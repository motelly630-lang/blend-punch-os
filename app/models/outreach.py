import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Integer, ForeignKey
from app.models.base import Base


# 새 상태 체계 (sent → replied → deal)
OUTREACH_STATUSES = ["sent", "replied", "deal", "hold", "rejected"]

STATUS_LABELS = {
    "sent":     "DM 발송",
    "replied":  "답장",
    "deal":     "공구확정",
    "hold":     "보류",
    "rejected": "거절",
    # 레거시 호환
    "제안발송": "DM 발송",
    "샘플요청": "답장",
    "샘플발송": "공구확정",
    "보류":     "보류",
    "거절":     "거절",
}

STATUS_COLORS = {
    "sent":     "blue",
    "replied":  "amber",
    "deal":     "green",
    "hold":     "gray",
    "rejected": "red",
    # 레거시
    "제안발송": "blue",
    "샘플요청": "amber",
    "샘플발송": "green",
    "보류":     "gray",
    "거절":     "red",
}

# 레거시 상태도 사이드바 뱃지 카운트에 포함
SAMPLE_STATUSES = OUTREACH_STATUSES  # backward compat alias


class OutreachLog(Base):
    __tablename__ = "outreach_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    operator = Column(String(100), nullable=False)           # 담당자
    influencer_handle = Column(String(200), nullable=False)
    influencer_id = Column(String(36), nullable=True)
    product_id = Column(String(36), nullable=True)
    campaign_id = Column(String(36), ForeignKey("campaigns.id"), nullable=True)  # Outreach → Campaign 연결

    outreach_date = Column(String(10), nullable=False)       # YYYY-MM-DD (발송일)
    sample_status = Column(String(30), default="sent")       # sent|replied|deal|hold|rejected

    # KPI 타임스탬프
    sent_at = Column(DateTime, nullable=True)                # DM 발송 일시
    response_at = Column(DateTime, nullable=True)            # 답장 받은 일시

    # 상세 정보
    status_detail = Column(Text, nullable=True)              # 상태 상세 메모 (ex: "인스타 DM 답장, 샘플 요청함")
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
