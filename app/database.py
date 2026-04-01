from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
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
    Base.metadata.create_all(bind=engine)
