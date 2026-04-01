"""
휴먼 리뷰 대기열.

score < 0.9 이면 파이프라인이 여기에 항목을 넣고 멈춘다.
관리자가 검토 후 'approve' 또는 'reject' 결정을 내리면 파이프라인이 재개된다.
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Float, Integer, JSON
from app.models.base import Base


class HumanReviewQueue(Base):
    __tablename__ = "human_review_queue"

    id               = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id       = Column(Integer, default=1)

    # 대상
    target_type      = Column(String(20), nullable=False)  # "product" | "brand"
    target_id        = Column(String(36), nullable=False)
    target_name      = Column(String(300), nullable=True)

    # 멈춘 지점
    stopped_at_role  = Column(String(20), nullable=False)  # "staff" | ... | "director"
    score            = Column(Float, nullable=True)         # 트리거된 점수
    confidence       = Column(Float, nullable=True)

    # 컨텍스트 스냅샷 (재개 시 사용)
    context_snapshot = Column(Text, nullable=True)          # JSON str

    # 상태
    status           = Column(String(20), default="pending")  # pending | approved | rejected
    reviewer_note    = Column(Text, nullable=True)
    reviewed_at      = Column(DateTime, nullable=True)

    created_at       = Column(DateTime, default=datetime.utcnow)
