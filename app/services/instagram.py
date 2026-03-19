"""
Instagram 프로필 데이터 수집 서비스 (instagrapi 기반)
- 로그인 세션을 파일로 유지 → 서버 재시작 시 재로그인 불필요
- 팔로워 수, 프로필 이미지, 최근 게시물 6개 반환
"""
import json
import logging
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SESSION_FILE = Path("instagram_session.json")
UPLOAD_DIR = Path("static/uploads/influencers")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_client = None  # 싱글톤


def _get_client():
    global _client
    if _client is not None:
        return _client

    from instagrapi import Client
    from app.config import settings

    if not settings.instagram_username or not settings.instagram_password:
        raise RuntimeError("INSTAGRAM_USERNAME / INSTAGRAM_PASSWORD 환경변수가 설정되지 않았습니다.")

    cl = Client()
    cl.delay_range = [1, 3]  # 요청 간격 랜덤 딜레이 (봇 탐지 방지)

    if SESSION_FILE.exists():
        try:
            cl.load_settings(SESSION_FILE)
            cl.login(settings.instagram_username, settings.instagram_password)
            logger.info("Instagram 세션 복원 성공")
        except Exception as e:
            logger.warning(f"세션 복원 실패, 재로그인: {e}")
            SESSION_FILE.unlink(missing_ok=True)
            cl = Client()
            cl.delay_range = [1, 3]
            cl.login(settings.instagram_username, settings.instagram_password)
            cl.dump_settings(SESSION_FILE)
            logger.info("Instagram 재로그인 성공")
    else:
        cl.login(settings.instagram_username, settings.instagram_password)
        cl.dump_settings(SESSION_FILE)
        logger.info("Instagram 최초 로그인 성공")

    _client = cl
    return cl


def _download_and_save(url: str) -> str:
    """이미지 URL → 로컬 저장 후 경로 반환."""
    if not url:
        return ""
    try:
        import httpx
        with httpx.Client(follow_redirects=True, timeout=15) as c:
            r = c.get(url)
            if r.status_code != 200 or not r.content:
                return ""
            ct = r.headers.get("content-type", "image/jpeg").lower()
            ext = "png" if "png" in ct else "webp" if "webp" in ct else "jpg"
            filename = f"{uuid.uuid4().hex}.{ext}"
            (UPLOAD_DIR / filename).write_bytes(r.content)
            return f"/static/uploads/influencers/{filename}"
    except Exception as e:
        logger.warning(f"이미지 다운로드 실패: {e}")
        return ""


def _num(n) -> int:
    try:
        return int(n) if n else 0
    except Exception:
        return 0


def fetch_instagram_profile(username: str) -> dict:
    """
    Instagram 유저명으로 프로필 정보 수집.
    반환: {name, handle, platform, followers, bio, profile_image_path, recent_posts, categories}
    """
    username = username.lstrip("@").strip()
    cl = _get_client()

    try:
        user = cl.user_info_by_username(username)
    except Exception as e:
        raise RuntimeError(f"Instagram 프로필 조회 실패: {e}")

    # 프로필 이미지 다운로드
    profile_image_path = ""
    pic_url = str(user.profile_pic_url_hd or user.profile_pic_url or "")
    if pic_url:
        profile_image_path = _download_and_save(pic_url)

    # 최근 게시물 6개
    recent_posts = []
    try:
        medias = cl.user_medias(user.pk, amount=6)
        for m in medias:
            thumb = str(m.thumbnail_url or m.resources[0].thumbnail_url if m.resources else "")
            recent_posts.append({
                "url": f"https://www.instagram.com/p/{m.code}/",
                "thumbnail": thumb,
                "likes": _num(m.like_count),
                "views": _num(getattr(m, "play_count", 0)),
                "caption": (m.caption_text or "")[:100],
                "media_type": str(m.media_type),
            })
    except Exception as e:
        logger.warning(f"최근 게시물 조회 실패: {e}")

    return {
        "name": user.full_name or username,
        "handle": username,
        "platform": "instagram",
        "followers": _num(user.follower_count),
        "bio": user.biography or "",
        "profile_image_path": profile_image_path,
        "profile_image_url": pic_url,
        "recent_posts": recent_posts,
        "post_count": _num(user.media_count),
        "following": _num(user.following_count),
    }


def reset_session():
    """세션 초기화 (로그인 문제 시 호출)."""
    global _client
    _client = None
    SESSION_FILE.unlink(missing_ok=True)
