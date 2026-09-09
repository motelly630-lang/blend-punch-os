import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text

from app.models.base import Base


class SheetSyncLog(Base):
    """통합시트 동기화 실행 기록.

    자동 동기화는 아무도 안 보는 사이에 돌기 때문에, 실패가 조용히 묻히면 안 된다.
    무엇이 언제 몇 건 바뀌었는지 남겨서 `/settings/sheets` 화면에서 볼 수 있게 한다.
    """

    __tablename__ = "sheet_sync_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)

    direction = Column(String(20), nullable=False)   # import(시트→OS) | export(OS→시트)
    trigger = Column(String(20), default="auto")     # auto | manual
    ok = Column(Boolean, default=True)

    created = Column(Integer, default=0)
    updated = Column(Integer, default=0)
    unchanged = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    skipped = Column(Integer, default=0)

    error = Column(Text, nullable=True)
    detail = Column(JSON, nullable=True)             # [{entity, label, created, updated, ...}]
    duration_ms = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
