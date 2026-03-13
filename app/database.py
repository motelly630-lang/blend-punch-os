from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
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
    Base.metadata.create_all(bind=engine)
