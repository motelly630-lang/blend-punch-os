"""
기능 플래그 — Company 싱글턴(id=1) + 기능별 활성화 상태
멀티테넌트 확장 시 company_id 컬럼만 활용하면 됨
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from app.models.base import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    plan = Column(String(20), default="pro")       # beta | basic | pro
    is_active = Column(Boolean, default=True)      # False = 해당 회사 전체 접근 차단
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CompanyFeature(Base):
    """company_id + feature_key 복합 PK — 각 기능의 활성화 상태"""
    __tablename__ = "company_features"

    company_id = Column(Integer, ForeignKey("companies.id"), primary_key=True)
    feature_key = Column(String(100), primary_key=True)
    enabled = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
