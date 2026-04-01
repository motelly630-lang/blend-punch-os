"""
에이전트 메모리 — 성공 캠페인 패턴 저장소.

이사(Director)가 새 제품 검토 시 이 테이블을 조회하여
과거 고매출 캠페인의 인플루언서 특성을 참조한다.
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Text, DateTime, JSON
from app.models.base import Base


class AgentMemory(Base):
    __tablename__ = "agent_memory"

    id                    = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id            = Column(Integer, default=1)

    # 성공 제품/캠페인 참조
    product_id            = Column(String(36), nullable=True)
    product_name          = Column(String(300), nullable=True)
    campaign_id           = Column(String(36), nullable=True)
    brand_name            = Column(String(200), nullable=True)
    category              = Column(String(100), nullable=True)

    # 성공 패턴 데이터
    influencer_categories = Column(JSON, nullable=True)   # ["요리유튜버", "주부블로거"]
    platform_mix          = Column(JSON, nullable=True)   # {"instagram": 0.6, "youtube": 0.4}
    follower_range        = Column(String(50), nullable=True)  # "10k-50k"
    priority_score        = Column(Float, nullable=True)

    # 수익 지표
    actual_revenue        = Column(Float, default=0.0)
    margin_rate           = Column(Float, nullable=True)
    commission_rate       = Column(Float, nullable=True)

    # 메모
    lesson_learned        = Column(Text, nullable=True)   # 이사가 남긴 메모

    created_at            = Column(DateTime, default=datetime.utcnow)
