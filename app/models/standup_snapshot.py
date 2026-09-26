import uuid
from datetime import datetime

from sqlalchemy import JSON, Column, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint

from app.models.base import Base


class StandupSnapshot(Base):
    """#출근보고 직원별 그날 숫자 — 다음 날 '어제보다 ±N' 을 보여주려고 남긴다 (app/services/slack_standup.py).

    하루·직원당 한 줄. 보고용 숫자만 담고 이름·개인정보는 담지 않는다.
    """

    __tablename__ = "standup_snapshots"
    __table_args__ = (UniqueConstraint("company_id", "report_date", "staff", name="uq_standup_snapshot_day"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    report_date = Column(Date, nullable=False)
    staff = Column(String(30), nullable=False)
    numbers = Column(JSON, nullable=False)          # {"매출 미입력": 92, ...}
    created_at = Column(DateTime, default=datetime.utcnow)
