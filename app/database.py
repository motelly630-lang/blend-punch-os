import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from app.config import settings

logger = logging.getLogger(__name__)

_is_sqlite = settings.database_url.startswith("sqlite")

if _is_sqlite:
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        echo=False,
    )
else:
    engine = create_engine(
        settings.database_url,
        pool_size=10,        # 항상 유지할 커넥션 수
        max_overflow=20,     # 트래픽 몰릴 때 추가 허용 커넥션
        pool_timeout=30,     # 커넥션 못 얻으면 30초 후 에러
        pool_recycle=1800,   # 30분마다 커넥션 갱신 (RDS 끊김 방지)
        pool_pre_ping=True,  # 사용 전 커넥션 상태 확인
        echo=False,
    )
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app.models.base import Base
    import app.models.product  # noqa
    import app.models.influencer  # noqa
    import app.models.campaign  # noqa
    import app.models.proposal  # noqa
    import app.models.playbook  # noqa
    import app.models.trend_engine  # noqa
    import app.models.outreach  # noqa
    import app.models.crm  # noqa
    import app.models.automation  # noqa
    import app.models.brand  # noqa
    import app.models.seller  # noqa
    import app.models.sales_page  # noqa
    import app.models.order  # noqa
    import app.models.business_info  # noqa
    import app.models.feature_flag  # noqa
    import app.models.manual  # noqa
    import app.models.email_log  # noqa
    import app.models.backup_log  # noqa
    import app.models.agent_log  # noqa
    import app.models.agent_memory  # noqa
    import app.models.trigger_log  # noqa
    import app.models.human_review_queue  # noqa
    import app.models.pipeline_job  # noqa
    import app.models.shop_user  # noqa
    import app.models.inquiry  # noqa
    Base.metadata.create_all(bind=engine)
