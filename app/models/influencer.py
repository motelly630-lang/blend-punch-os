import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Text, DateTime, JSON
from app.models.base import Base


class Influencer(Base):
    __tablename__ = "influencers"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
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
    resident_registration_number = Column(String(30), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
