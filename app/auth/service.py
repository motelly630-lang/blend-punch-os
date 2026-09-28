from datetime import datetime, timedelta
import bcrypt
from jose import JWTError, jwt
from app.config import settings

ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 60 * 8  # 8 hours


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(username: str, role: str, scope: str | None = None) -> str:
    expire = datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    payload = {"sub": username, "role": role, "exp": expire}
    if scope:
        payload["scope"] = scope   # "api" = 외부 API 전용 열쇠 (OS 화면 로그인에 못 씀)
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str, *, allow_api: bool = False) -> dict | None:
    """기본은 OS 로그인(쿠키)용 — 외부 API 전용 열쇠(scope=api)는 거부. 외부 API 만 allow_api=True."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        return None
    if payload.get("scope") == "api" and not allow_api:
        return None
    return payload
