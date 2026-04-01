import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Integer, Float, JSON, ForeignKey
from app.models.base import Base

# 상태값 정의
REVIEW_STATUSES = {
    "draft":            "초안",
    "ai_draft":         "AI 초안",
    "structured":       "구조화 완료",
    "reviewed":         "검토 완료",
    "strategy_checked": "전략 검토 완료",
    "approved":         "승인",
    "rejected":         "반려",
    "pending_review":   "관리자 검토 대기",
}

# 직급 정의
AGENT_ROLES = {
    "staff":    "사원",
    "assistant": "대리",
    "manager":  "과장",
    "lead":     "팀장",
    "director": "이사",
}


class AgentLog(Base):
    """에이전트 파이프라인 실행 로그."""
    __tablename__ = "agent_logs"

    id          = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id  = Column(Integer, default=1)

    # 대상 (brand 또는 product)
    target_type = Column(String(20), nullable=False)   # "brand" | "product"
    target_id   = Column(String(36), nullable=False)   # brands.id | products.id
    target_name = Column(String(200), nullable=True)

    # 직급
    role        = Column(String(20), nullable=False)   # staff|assistant|manager|lead|director

    # 입출력
    input_summary  = Column(Text, nullable=True)       # 이전 단계 누적 컨텍스트 요약
    output         = Column(Text, nullable=True)       # 이 에이전트의 분석 결과 (JSON str)
    decision       = Column(String(20), nullable=True) # "pass" | "reject"
    reject_reason  = Column(Text, nullable=True)
    priority_score = Column(Float, nullable=True)      # 이사 단계에서 최종 점수
    score          = Column(Float, nullable=True)      # 에이전트 자체 평가 점수 (0.0~1.0)
    confidence     = Column(Float, nullable=True)      # 확신도 (0.0~1.0)
    risk_level     = Column(String(10), nullable=True) # "LOW" | "HIGH"

    # 메타
    model_used  = Column(String(50), nullable=True)
    tokens_used = Column(Integer, nullable=True)
    elapsed_ms  = Column(Integer, nullable=True)
    status      = Column(String(20), default="success")  # success | error
    error_msg   = Column(Text, nullable=True)

    created_at  = Column(DateTime, default=datetime.utcnow)
