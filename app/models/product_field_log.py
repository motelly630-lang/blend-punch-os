import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey

from app.models.base import Base


class ProductFieldLog(Base):
    """제품 칸을 사람이 채우거나 고친 기록 1건 = 1줄.

    나중에 '빈칸 자동 채우기'가 사람의 입력을 보고 따라 하도록 학습 재료로 쓴다
    (무엇을·무엇에서 무엇으로·어디서 찾아·어느 화면에서). 값이 실제로 바뀐 경우만 남긴다.
    """

    __tablename__ = "product_field_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    product_id = Column(String(36), nullable=False, index=True)
    field = Column(String(50), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    source_url = Column(String(1000), nullable=True)   # 사람이 값을 찾은 곳 (선택)
    via = Column(String(20), nullable=True)            # fill(빠르게 채우기) | detail | form | upload
    user_id = Column(String(36), nullable=True)
    username = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
