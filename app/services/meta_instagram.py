"""Meta 공식 Instagram Graph API — Business Discovery 로 다른 인스타 계정의 공개 프로필 조회 (DE-006).

우리 인스타 프로페셔널 계정(@blend_punch)의 페이지 토큰으로, 비즈니스·크리에이터 계정의
아이디·표시 이름·팔로워·게시물 수·프로필 사진을 가져온다. 개인 계정·연령 제한 계정은 조회되지 않는다.

- 토큰은 settings.meta_page_token (서버 .env). 오류 메시지에 토큰이 섞여도 밖으로 내보내기 전에 가린다.
- 프로필 사진 주소는 인스타 CDN 서명 URL 이라 시간이 지나면 만료된다 → 받아서 OS 에 저장한다.
"""
from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path("static/uploads/influencers")
MAX_IMAGE_BYTES = 5 * 1024 * 1024
_TOKEN_RE = re.compile(r"EAA[A-Za-z0-9]{10,}")
_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


class MetaError(Exception):
    """사람이 읽을 수 있는 한국어 메시지를 담는다 (화면에 그대로 보여줘도 되는 내용만)."""


def available() -> bool:
    from app.config import settings
    return bool(settings.meta_page_token and settings.meta_ig_user_id)


def _redact(text: str) -> str:
    return _TOKEN_RE.sub("EAA…(가림)", text or "")


def _friendly(err: dict) -> str:
    code, sub = err.get("code"), err.get("error_subcode")
    if code == 190:
        return "Meta 토큰이 만료됐거나 끊겼어요 — 관리자가 토큰을 다시 받아야 해요"
    if code in (4, 17, 32, 613) or sub == 2207051:
        return "Meta 조회 한도에 걸렸어요 — 잠시 후 다시 시도해 주세요"
    if code == 110 or sub in (2207013, 2207003):
        return "조회할 수 없는 계정이에요 — 개인 계정이거나 아이디가 틀렸을 수 있어요 (비즈니스·크리에이터 계정만 가능)"
    return "Meta 조회 실패: " + _redact(str(err.get("message", "")))[:150]


def fetch_profile(username: str) -> dict:
    """인스타 아이디 → {handle, display_name, followers, media_count, biography, profile_picture_url}.

    실패하면 MetaError (한국어 안내 메시지).
    """
    from app.config import settings
    handle = (username or "").strip().lstrip("@").rstrip("/")
    if not _HANDLE_RE.match(handle):
        raise MetaError("인스타 아이디 형식이 아니에요")
    if not available():
        raise MetaError("Meta 연결 설정이 없어요 (META_PAGE_TOKEN)")
    fields = (f"business_discovery.username({handle})"
              "{username,name,biography,profile_picture_url,followers_count,media_count}")
    try:
        # 토큰은 주소(쿼리)가 아니라 헤더로 — 주소는 로그·프록시에 남는다
        with httpx.Client(timeout=15) as c:
            r = c.get(f"https://graph.facebook.com/{settings.meta_graph_version}/{settings.meta_ig_user_id}",
                      params={"fields": fields},
                      headers={"Authorization": f"Bearer {settings.meta_page_token}"})
        body = r.json()
    except Exception as e:
        logger.warning("Meta 조회 통신 오류: %s", _redact(str(e)))
        raise MetaError("Meta 서버에 연결하지 못했어요 — 잠시 후 다시 시도해 주세요")
    if "error" in body:
        logger.info("Meta 조회 실패 @%s: %s", handle, _redact(str(body["error"].get("message"))))
        raise MetaError(_friendly(body["error"]))
    bd = body.get("business_discovery") or {}
    return {
        "handle": bd.get("username") or handle,
        "display_name": bd.get("name") or "",
        "followers": int(bd.get("followers_count") or 0),
        "media_count": int(bd.get("media_count") or 0),
        "biography": bd.get("biography") or "",
        "profile_picture_url": bd.get("profile_picture_url") or "",
    }


_CDN_SUFFIXES = (".cdninstagram.com", ".fbcdn.net")


def _is_meta_cdn(url: str) -> bool:
    from urllib.parse import urlparse
    try:
        u = urlparse(url)
    except Exception:
        return False
    host = (u.hostname or "").lower()
    return u.scheme == "https" and any(host.endswith(s) for s in _CDN_SUFFIXES)


def save_profile_image(url: str) -> str:
    """프로필 사진을 받아 OS 에 저장하고 /static/... 경로를 돌려준다. 실패하면 ''.

    인스타·페이스북 CDN 주소만 받고, 리다이렉트는 따라가지 않으며, 받는 도중 5MB 를 넘으면 멈춘다.
    """
    if not _is_meta_cdn(url):
        return ""
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as c:
            with c.stream("GET", url) as r:
                ct = (r.headers.get("content-type") or "").lower()
                if r.status_code != 200 or not ct.startswith("image/"):
                    return ""
                buf = bytearray()
                for chunk in r.iter_bytes():
                    buf += chunk
                    if len(buf) > MAX_IMAGE_BYTES:
                        return ""
        if not buf:
            return ""
        ext = "png" if "png" in ct else "webp" if "webp" in ct else "jpg"
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}.{ext}"
        (UPLOAD_DIR / name).write_bytes(bytes(buf))
        return f"/static/uploads/influencers/{name}"
    except Exception as e:
        logger.warning("프로필 사진 저장 실패: %s", _redact(str(e)))
        return ""
