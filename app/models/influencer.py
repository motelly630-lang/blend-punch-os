import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Text, DateTime, JSON, ForeignKey, Boolean
from app.models.base import Base


class Influencer(Base):
    __tablename__ = "influencers"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    name = Column(String(200), nullable=False)
    platform = Column(String(30), nullable=False)       # instagram|youtube|tiktok|blog|naver
    handle = Column(String(200), nullable=False)
    profile_url = Column(Text, nullable=True)
    followers = Column(Integer, default=0)
    # engagement_rate kept in DB for backward compat but removed from form
    engagement_rate = Column(Float, default=0.0)
    categories = Column(JSON, nullable=True)            # list[str] - predefined tags
    audience_age_range = Column(String(50), nullable=True)
    audience_gender_ratio = Column(String(100), nullable=True)
    contact_email = Column(String(200), nullable=True)
    contact_phone = Column(String(50), nullable=True)
    contact_kakao = Column(String(100), nullable=True)
    agency_name = Column(String(200), nullable=True)
    past_gmv = Column(Float, default=0.0)
    avg_views_per_post = Column(Integer, default=0)
    commission_preference = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String(20), default="active")       # active|inactive|blacklist

    # Phase 2 additions
    profile_image = Column(String(500), nullable=True)  # /uploads/influencers/xxx.jpg

    # Phase 5 additions — payout identity
    has_campaign_history = Column(String(5), default="false")  # "true"|"false"
    business_type = Column(String(20), nullable=True)       # 사업자|간이사업자|프리랜서
    bank_name = Column(String(100), nullable=True)
    account_number = Column(String(100), nullable=True)
    account_holder = Column(String(100), nullable=True)
    # 사업자 / 간이사업자
    business_name = Column(String(200), nullable=True)
    business_registration_number = Column(String(50), nullable=True)
    representative_name = Column(String(100), nullable=True)
    business_address = Column(Text, nullable=True)
    tax_invoice_email = Column(String(200), nullable=True)
    # 프리랜서
    legal_name = Column(String(100), nullable=True)
    resident_registration_number = Column(String(30), nullable=True)  # 사용 안 함 — DE-005 (값은 항상 비어 있어야 한다)

    is_archived = Column(Boolean, default=False)

    # 통합 운영 스프레드시트 연동 — 시트 PK(SEL-...)와 상태값 한글 원본
    sheet_code   = Column(String(50), nullable=True, index=True)
    sheet_status = Column(String(30), nullable=True)

    # 인스타 프로필 자동수집 — 성공/실패 모두 기록해서 같은 계정을 무한 재시도하지 않는다
    enriched_at   = Column(DateTime, nullable=True, index=True)
    enrich_error  = Column(String(200), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
