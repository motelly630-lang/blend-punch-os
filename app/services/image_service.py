"""
image_service.py — 공통 이미지 처리 서비스
- 업로드 이미지: WebP 변환 + 최대 1080px 리사이징
- 외부 이미지(인스타그램 등) 서버 캐싱 → /static/cache/
- 누끼 제거: REMOVE_BG_ENABLED=True 시 활성화 (기본 비활성)
"""
import hashlib
import shutil
import uuid
from io import BytesIO
from pathlib import Path

import httpx
from fastapi import UploadFile
from PIL import Image

# ── 설정 ───────────────────────────────────────────────
MAX_DIMENSION = 1080
WEBP_QUALITY = 85
UPLOAD_DIR_PRODUCTS = Path("static/uploads/products")
UPLOAD_DIR_INFLUENCERS = Path("static/uploads/influencers")
CACHE_DIR = Path("static/cache")

REMOVE_BG_ENABLED = False  # True로 바꾸면 누끼 제거 활성화
REMOVE_BG_API_KEY = ""     # .env에서 REMOVE_BG_API_KEY로 설정

for _d in (UPLOAD_DIR_PRODUCTS, UPLOAD_DIR_INFLUENCERS, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# 인스타그램 이미지 다운로드용 헤더
_INSTAGRAM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.instagram.com/",
}


# ── 내부 유틸 ───────────────────────────────────────────

def _is_instagram_url(url: str) -> bool:
    return any(h in url for h in ("cdninstagram.com", "instagram.com", "fbcdn.net"))


def _process_image(img: Image.Image, remove_bg: bool = False) -> Image.Image:
    """리사이징 + (선택) 누끼 제거."""
    # EXIF orientation 보정
    try:
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    # 최대 1080px 리사이징 (비율 유지)
    if max(img.size) > MAX_DIMENSION:
        img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

    if remove_bg and REMOVE_BG_ENABLED:
        img = _remove_background(img)

    return img


def _remove_background(img: Image.Image) -> Image.Image:
    """remove.bg API를 사용한 배경 제거 (REMOVE_BG_ENABLED=True 시에만 호출됨)."""
    try:
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        resp = httpx.post(
            "https://api.remove.bg/v1.0/removebg",
            headers={"X-Api-Key": REMOVE_BG_API_KEY},
            files={"image_file": ("image.png", buf, "image/png")},
            data={"size": "auto"},
            timeout=30,
        )
        if resp.status_code == 200:
            return Image.open(BytesIO(resp.content)).convert("RGBA")
    except Exception:
        pass
    return img


def _save_pil(img: Image.Image, dest: Path, use_alpha: bool = False) -> None:
    """WebP로 저장. 투명도(alpha) 있으면 PNG fallback."""
    if use_alpha or img.mode == "RGBA":
        img.save(dest, format="PNG", optimize=True)
    else:
        img = img.convert("RGB")
        img.save(dest, format="WEBP", quality=WEBP_QUALITY, method=4)


# ── 공개 API ────────────────────────────────────────────

def save_upload(file: UploadFile, dest_dir: Path, remove_bg: bool = False) -> str | None:
    """
    업로드 파일을 WebP로 변환·저장.
    반환값: /static/... 경로 문자열 or None
    """
    if not file or not file.filename:
        return None
    try:
        data = file.file.read()
        img = Image.open(BytesIO(data))
        img = _process_image(img, remove_bg=remove_bg)
        use_alpha = remove_bg and REMOVE_BG_ENABLED and img.mode == "RGBA"
        ext = "png" if use_alpha else "webp"
        filename = f"{uuid.uuid4().hex}.{ext}"
        dest = dest_dir / filename
        _save_pil(img, dest, use_alpha=use_alpha)
        return f"/{dest}"
    except Exception:
        # 변환 실패 시 원본 그대로 저장
        try:
            file.file.seek(0)
            raw_ext = (file.filename.rsplit(".", 1)[-1].lower()
                       if "." in file.filename else "jpg")
            if raw_ext not in ("jpg", "jpeg", "png", "webp", "gif"):
                raw_ext = "jpg"
            filename = f"{uuid.uuid4().hex}.{raw_ext}"
            dest = dest_dir / filename
            with dest.open("wb") as out:
                file.file.seek(0)
                shutil.copyfileobj(file.file, out)
            return f"/{dest}"
        except Exception:
            return None


def save_product_image(file: UploadFile, remove_bg: bool = False) -> str | None:
    return save_upload(file, UPLOAD_DIR_PRODUCTS, remove_bg=remove_bg)


def save_influencer_image(file: UploadFile, remove_bg: bool = False) -> str | None:
    return save_upload(file, UPLOAD_DIR_INFLUENCERS, remove_bg=remove_bg)


def cache_external_image(url: str) -> str | None:
    """
    외부 이미지(인스타그램 등)를 서버에 다운로드하여 /static/cache/ 에 저장.
    반환값: /static/cache/xxx.webp 경로 or None (실패 시)
    캐시 키: URL MD5 → 중복 다운로드 방지
    """
    if not url or not url.startswith("http"):
        return None

    # 이미 캐시된 경우 바로 반환
    url_hash = hashlib.md5(url.encode()).hexdigest()
    for ext in ("webp", "png", "jpg"):
        cached = CACHE_DIR / f"{url_hash}.{ext}"
        if cached.exists():
            return f"/static/cache/{url_hash}.{ext}"

    try:
        headers = _INSTAGRAM_HEADERS if _is_instagram_url(url) else {}
        resp = httpx.get(url, headers=headers, timeout=10, follow_redirects=True)
        if resp.status_code != 200:
            return None

        img = Image.open(BytesIO(resp.content))
        img = _process_image(img)
        use_alpha = img.mode == "RGBA"
        ext = "png" if use_alpha else "webp"
        dest = CACHE_DIR / f"{url_hash}.{ext}"
        _save_pil(img, dest, use_alpha=use_alpha)
        return f"/static/cache/{url_hash}.{ext}"
    except Exception:
        return None
