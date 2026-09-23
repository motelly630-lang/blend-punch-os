"""격리 테스트 환경.

- DB: 임시 SQLite 파일 (개발·운영 RDS 에 접속하지 않는다)
- 외부 호출: AI 키 비움, 알림·메일 mock, 토스 호출은 각 테스트가 함수 교체(monkeypatch)
- 앱 lifespan(스케줄러·init_db)은 실행하지 않는다 (TestClient 를 with 없이 사용)

반드시 app 을 import 하기 전에 이 모듈을 import 해야 한다.
실행 (WSL):  .venv/bin/python -m unittest discover -s tests -t . -v
"""
import os
import tempfile
import uuid

_TMP = tempfile.mkdtemp(prefix="bp_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'test.db')}"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["TOSS_SECRET_KEY"] = "test_sk_unit_test_only"
os.environ["TOSS_CLIENT_KEY"] = "test_ck_unit_test_only"
os.environ["SECRET_KEY"] = "unit-test-secret"
os.environ["SHEET_AUTOSYNC"] = "false"
os.environ["INFLUENCER_ENRICH"] = "false"
os.environ["CAMPAIGN_ALERT"] = "false"
os.environ["ALERT_MOCK"] = "true"
os.environ["KAKAO_MOCK"] = "true"
os.environ["EMAIL_MOCK"] = "true"
os.environ["GOOGLE_SA_JSON"] = ""
os.environ["INTEGRATED_SHEET_ID"] = ""

from app.config import settings  # noqa: E402

assert settings.database_url.startswith("sqlite:///"), "테스트가 실제 DB 를 가리키고 있다 — 중단"

from fastapi.testclient import TestClient  # noqa: E402

import app.models as _all_models  # noqa: E402,F401  (모든 모델 등록 — 'import app.models' 는 이름 app 을 덮어쓴다)
from app.main import app  # noqa: E402
from app.database import SessionLocal, engine, init_db  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.feature_flag import Company  # noqa: E402
from app.models.user import User  # noqa: E402
from app.auth.service import create_access_token, hash_password  # noqa: E402

init_db()
Base.metadata.create_all(bind=engine)

_seeded = False


def seed_companies():
    global _seeded
    if _seeded:
        return
    db = SessionLocal()
    try:
        for cid, name in ((1, "테스트회사A"), (2, "테스트회사B")):
            if not db.query(Company).filter(Company.id == cid).first():
                db.add(Company(id=cid, name=name, plan="pro", is_active=True))
        db.commit()
    finally:
        db.close()
    _seeded = True


def uid() -> str:
    return uuid.uuid4().hex[:8]


def make_user(role: str = "admin", company_id: int = 1) -> User:
    seed_companies()
    db = SessionLocal()
    try:
        u = User(username=f"u_{role}_{uid()}", hashed_password=hash_password("pw"),
                 role=role, company_id=company_id, is_active=True)
        db.add(u)
        db.commit()
        db.refresh(u)
        db.expunge(u)
        return u
    finally:
        db.close()


def client_for(user: User | None = None) -> TestClient:
    c = TestClient(app, raise_server_exceptions=True, follow_redirects=False)
    if user is not None:
        c.cookies.set("access_token", create_access_token(user.username, user.role))
    return c
