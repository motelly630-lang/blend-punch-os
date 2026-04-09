import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Text
from app.models.base import Base


class ShopUser(Base):
    __tablename__ = "shop_users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # 기본 정보
    email = Column(String(200), nullable=True, unique=True)
    password_hash = Column(String(500), nullable=True)      # 이메일 로그인용
    name = Column(String(100), nullable=True)
    nickname = Column(String(100), nullable=True)
    profile_image = Column(String(500), nullable=True)
    phone = Column(String(50), nullable=True)

    # 카카오 관련
    kakao_id = Column(String(100), nullable=True, unique=True)
    kakao_access_token = Column(Text, nullable=True)

    # 카카오 알림톡 동의
    kakao_notify_agreed = Column(Boolean, default=False)
    kakao_notify_agreed_at = Column(DateTime, nullable=True)

    # 역할
    role = Column(String(20), default="customer")           # customer|influencer|vendor
    role_status = Column(String(20), nullable=True)         # pending|approved|rejected

    # 상태
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)            # 이메일 인증 여부

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
