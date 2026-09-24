import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, JSON, ForeignKey

from app.models.base import Base


class InfluencerMergeLog(Base):
    """중복 인플루언서 합치기 1건 = 1줄. 되돌리기에 필요한 것을 전부 남긴다.

    merged 쪽 행은 지우지 않고 보관(is_archived) 처리한다 — 블랜드픽 등 밖에서 그 번호를 가리켜도 깨지지 않게.
    """

    __tablename__ = "influencer_merge_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    keeper_id = Column(String(36), nullable=False, index=True)       # 남긴 인플루언서
    merged_id = Column(String(36), nullable=False, index=True)       # 보관 처리한 인플루언서
    moved = Column(JSON, nullable=True)          # {표 이름: [옮긴 행 id, ...]}
    keeper_before = Column(JSON, nullable=True)  # 채워 넣기 전 keeper 의 바뀐 칸 원래 값
    merged_before = Column(JSON, nullable=True)  # 보관 전 merged 의 바뀐 칸 원래 값
    merged_by = Column(String(100), nullable=True)
    undone_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
