import uuid
from datetime import datetime
from sqlalchemy import Column, ForeignKey, Integer, String, Float, Text, DateTime, JSON, Boolean
from app.models.base import Base


class TrendItem(Base):
    __tablename__ = "trend_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    category = Column(String(50), nullable=False)           # 식품|주방|리빙|뷰티|건강|다이어트|육아|반려동물
    title = Column(String(300), nullable=False)
    summary = Column(Text, nullable=True)
    source_url = Column(Text, nullable=True)
    trend_score = Column(Float, default=5.0)               # 1.0 ~ 10.0
    tags = Column(JSON, nullable=True)                     # list[str]
    recommended_inf_categories = Column(JSON, nullable=True)  # list[str]
    is_pinned = Column(Boolean, default=False)
    # Claw 연동 필드
    source = Column(String(50), nullable=True)             # instagram|naver|youtube|etc
    brands = Column(JSON, nullable=True)                   # list[str] — 연관 브랜드명
    season = Column(String(20), nullable=True)             # 2026-Q2 등
    source_name = Column(String(100), nullable=True)       # 출처명 (Claw 등)
    # 제품 매칭 필드
    match_status = Column(String(20), nullable=True)       # matched|similar|none
    match_score = Column(Float, nullable=True)             # 0.0~1.0
    season_score = Column(Float, nullable=True)            # 0.0~10.0
    final_score = Column(Float, nullable=True)             # 0.0~10.0
    is_actionable = Column(Boolean, default=False)
    needs_sourcing = Column(Boolean, default=False)
    matched_products = Column(JSON, nullable=True)         # [{product_id,name,brand,match_score,match_type}]
    created_at = Column(DateTime, default=datetime.utcnow)
