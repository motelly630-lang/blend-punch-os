import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Text, DateTime, JSON
from app.models.base import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(200), nullable=False)
    brand = Column(String(200), nullable=False)
    category = Column(String(100), nullable=False)
    price = Column(Float, default=0.0)
    source_url = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    target_audience = Column(Text, nullable=True)
    key_benefits = Column(JSON, nullable=True)               # list[str]
    unique_selling_point = Column(Text, nullable=True)
    estimated_demand = Column(String(20), default="medium")  # high|medium|low
    recommended_commission_rate = Column(Float, default=0.15)
    content_angle = Column(Text, nullable=True)
    ai_analysis_raw = Column(Text, nullable=True)
    status = Column(String(20), default="draft")             # draft|active|archived

    # Phase 2 additions
    product_image = Column(String(500), nullable=True)       # /uploads/products/xxx.jpg
    set_options = Column(JSON, nullable=True)                # [{name,qty,price,notes}]
    positioning = Column(Text, nullable=True)                # 포지셔닝 전략
    usage_scenes = Column(Text, nullable=True)               # 사용 장면
    recommended_inf_categories = Column(JSON, nullable=True) # list[str]
    categories = Column(JSON, nullable=True)                 # list[str] broad consumer tags
    group_buy_guideline = Column(Text, nullable=True)        # public-facing guide

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
