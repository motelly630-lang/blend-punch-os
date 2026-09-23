import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, text

from app.models.base import Base


class SlackNotificationLog(Base):
    """Slack 자동 알림 발송 기록.

    같은 이벤트(예: 캠페인 12 오픈)가 스케줄러 재실행·배포 중 프로세스 겹침으로 두 번 나가지 않게
    발송 전에 `sending` 행을 먼저 넣어 자리를 잡는다(선점). 아래 부분 유니크 인덱스가
    같은 dedupe_key 의 두 번째 선점을 DB 차원에서 막는다. 실패도 남겨서 '안 온 알림' 이 묻히지 않게 한다.
    """

    __tablename__ = "slack_notification_logs"
    __table_args__ = (
        Index(
            "uq_slack_notif_dedupe_active",
            "company_id", "dedupe_key",
            unique=True,
            postgresql_where=text("dedupe_key IS NOT NULL AND status IN ('sending', 'sent')"),
            sqlite_where=text("dedupe_key IS NOT NULL AND status IN ('sending', 'sent')"),
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    event = Column(String(50), nullable=False, index=True)       # campaign_open | settlement_pending ...
    dedupe_key = Column(String(200), nullable=True, index=True)  # 같은 키는 한 번만 성공 발송
    channel = Column(String(50), nullable=False)                 # 채널 키 (groupbuy ...) 또는 dm
    status = Column(String(20), nullable=False)                  # sending | sent | mock | failed
    reason = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
