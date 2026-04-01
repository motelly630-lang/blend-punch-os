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

    # 이메일 인증
    email_verified   = Column(Boolean, default=False)
    verify_token     = Column(String(100), nullable=True)
    verify_token_exp = Column(DateTime, nullable=True)

    # 비밀번호 재설정
    reset_token      = Column(String(100), nullable=True)
    reset_token_exp  = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
