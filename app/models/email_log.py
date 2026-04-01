import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from app.models.base import Base


EMAIL_STATUSES = {
    "pending":   "발송 대기",
    "sent":      "발송 완료",
    "failed":    "발송 실패",
    "replied":   "답변 수신",
    "converted": "전환 완료",
}

# 내장 이메일 템플릿
EMAIL_TEMPLATES = {
    "initial_proposal": {
        "name": "초기 협업 제안",
        "subject": "[협업 제안] {product_name} 공동구매 협업 제안드립니다",
        "body": (
            "안녕하세요, {influencer_name}님!\n\n"
            "저는 블렌드펀치의 {sender_name}입니다.\n\n"
            "{product_name} 제품의 공동구매 협업을 제안드리고 싶어 연락드렸습니다.\n\n"
            "귀하의 채널과 저희 제품이 잘 맞을 것 같아 제안드립니다.\n"
            "관심이 있으시다면 편한 시간에 미팅을 잡고 싶습니다.\n\n"
            "감사합니다.\n{sender_name} 드림"
        ),
    },
    "follow_up": {
        "name": "후속 연락",
        "subject": "Re: 협업 제안 후속 연락드립니다",
        "body": (
            "안녕하세요, {influencer_name}님!\n\n"
            "지난번 협업 제안 관련하여 후속 연락드립니다.\n\n"
            "혹시 검토해보셨는지 여쭤봐도 될까요?\n"
            "궁금하신 점이 있으시면 편하게 연락 주세요.\n\n"
            "감사합니다.\n{sender_name} 드림"
        ),
    },
    "sample_notice": {
        "name": "샘플 발송 안내",
        "subject": "[샘플 발송] {product_name} 샘플을 발송해드렸습니다",
        "body": (
            "안녕하세요, {influencer_name}님!\n\n"
            "{product_name} 샘플을 발송해드렸습니다.\n\n"
            "택배사: {carrier}\n"
            "송장번호: {tracking_number}\n\n"
            "수령 후 사용해보시고 편하게 의견 주시면 감사하겠습니다.\n\n"
            "감사합니다.\n{sender_name} 드림"
        ),
    },
    "thank_you": {
        "name": "감사 인사",
        "subject": "협업 감사드립니다 — {product_name}",
        "body": (
            "안녕하세요, {influencer_name}님!\n\n"
            "이번 {product_name} 협업에 참여해주셔서 진심으로 감사드립니다.\n\n"
            "앞으로도 좋은 협업 기회가 있으면 연락드리겠습니다.\n\n"
            "감사합니다.\n{sender_name} 드림"
        ),
    },
}


class EmailLog(Base):
    """이메일 발송 이력 — 아웃리치/CRM과 연결"""
    __tablename__ = "email_logs"

    id           = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id   = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)

    # 수신자
    to_email     = Column(String(300), nullable=False)
    to_name      = Column(String(200), nullable=True)

    # 내용
    subject      = Column(String(500), nullable=False)
    body         = Column(Text, nullable=False)
    template_name = Column(String(100), nullable=True)   # 사용한 템플릿 키

    # 상태
    status       = Column(String(20), default="pending")  # pending|sent|failed|replied|converted
    error_msg    = Column(Text, nullable=True)

    # 연결 대상 (다형 참조)
    related_type = Column(String(30), nullable=True)   # outreach|crm|influencer|brand
    related_id   = Column(String(36), nullable=True, index=True)

    # 발송자
    created_by   = Column(String(100), nullable=True)

    # 시간
    scheduled_at = Column(DateTime, nullable=True)      # NULL = 즉시 발송
    sent_at      = Column(DateTime, nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
