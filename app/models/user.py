import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Integer, ForeignKey
from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(200), unique=True, nullable=True, index=True)
    hashed_password = Column(String(200), nullable=False)
    role = Column(String(20), default="partner")   # admin | staff | partner (legacy: manager, viewer)
    is_active = Column(Boolean, default=True)
    # NULL = 슈퍼어드민 (모든 기능/회사 접근 가능)
    # 값 있음 = 해당 company 소속, 회사 기능 제한 적용
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    # role=="partner" 인 협력사 담당자 계정은 이 협력사에 묶인다 (포털 스코프)
    partner_id = Column(String(36), ForeignKey("partners.id"), nullable=True, index=True)

    # 이메일 인증
    email_verified   = Column(Boolean, default=False)
    verify_token     = Column(String(100), nullable=True)
    verify_token_exp = Column(DateTime, nullable=True)

    # 구독
    subscription = Column(Boolean, default=False)

    # 비밀번호 재설정
    reset_token      = Column(String(100), nullable=True)
    reset_token_exp  = Column(DateTime, nullable=True)

    current_token = Column(String(512), nullable=True)
    last_login_at = Column(DateTime, nullable=True)   # 최근 로그인 일시 (협업사 계정 관리 표시용)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
