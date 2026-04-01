"""
사업자 정보 — 싱글턴 (id=1 고정)
전자상거래 법적 필수 표시 항목 + 안내문구 저장
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from app.models.base import Base


class BusinessInfo(Base):
    __tablename__ = "business_infos"

    id = Column(Integer, primary_key=True, default=1)

    # ── 전자상거래법 필수 사업자 정보 ─────────────────────────────
    company_name        = Column(String(200), nullable=True)   # 상호명
    ceo_name            = Column(String(100), nullable=True)   # 대표자명
    biz_reg_number      = Column(String(50),  nullable=True)   # 사업자등록번호 (000-00-00000)
    mail_order_number   = Column(String(100), nullable=True)   # 통신판매업신고번호
    address             = Column(Text,        nullable=True)   # 사업장 주소
    phone               = Column(String(50),  nullable=True)   # 대표 연락처
    email               = Column(String(200), nullable=True)   # 대표 이메일

    # ── 안내 문구 (관리자가 직접 편집) ──────────────────────────────
    shipping_guide      = Column(Text, nullable=True)          # 배송 안내
    return_policy       = Column(Text, nullable=True)          # 교환/환불 정책
    payment_guide       = Column(Text, nullable=True)          # 결제 안내

    # ── 브랜딩 이미지 ────────────────────────────────────────────────
    login_bg_image      = Column(String(500), nullable=True)   # 로그인 페이지 배경 이미지 URL
    orders_banner_image = Column(String(500), nullable=True)   # 주문 관리 페이지 배너 이미지 URL

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
