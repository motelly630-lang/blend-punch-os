"""
image_service.py — 공통 이미지 처리 서비스
- 업로드 이미지: WebP 변환 + 최대 1080px 리사이징
- S3 업로드 우선, 미설정 시 로컬 저장 fallback
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
UPLOAD_DIR_BRANDS = Path("static/brands")
UPLOAD_DIR_SALES_PAGES = Path("static/uploads/sales_pages")
UPLOAD_DIR_BRANDING = Path("static/uploads/branding")
CACHE_DIR = Path("static/cache")

# 로컬 디렉토리 → S3 prefix 매핑
_S3_PREFIX_MAP = {
    str(UPLOAD_DIR_PRODUCTS): "uploads/products",
    str(UPLOAD_DIR_INFLUENCERS): "uploads/influencers",
    str(UPLOAD_DIR_BRANDS): "uploads/brands",
    str(UPLOAD_DIR_SALES_PAGES): "uploads/sales_pages",
    str(UPLOAD_DIR_BRANDING): "uploads/branding",
    str(CACHE_DIR): "uploads/cache",
}

REMOVE_BG_ENABLED = True
try:
    from app.config import settings as _settings
    REMOVE_BG_API_KEY = getattr(_settings, "remove_bg_api_key", "") or ""
except Exception:
    REMOVE_BG_API_KEY = ""

for _d in (UPLOAD_DIR_PRODUCTS, UPLOAD_DIR_INFLUENCERS, UPLOAD_DIR_BRANDS,
           UPLOAD_DIR_SALES_PAGES, CACHE_DIR):
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


# ── S3 유틸 ────────────────────────────────────────────

def _get_s3_assets_client():
    """S3 클라이언트 + 에셋 버킷명 반환. 미설정 시 (None, None)."""
    try:
        from app.config import settings
        if not settings.aws_access_key_id:
            return None, None
        bucket = settings.s3_assets_bucket or settings.s3_backup_bucket
        if not bucket:
            return None, None
        import boto3
        client = boto3.client(
            "s3",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        return client, bucket
    except Exception:
        return None, None


def _s3_public_url(bucket: str, region: str, s3_key: str) -> str:
    return f"https://{bucket}.s3.{region}.amazonaws.com/{s3_key}"


def _upload_bytes_to_s3(data: bytes, s3_key: str, content_type: str = "image/webp") -> str | None:
    """바이트를 S3에 업로드. 성공 시 퍼블릭 URL 반환, 실패 시 None."""
    try:
        from app.config import settings
        client, bucket = _get_s3_assets_client()
        if not client:
            return None
        client.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=data,
            ContentType=content_type,
        )
        return _s3_public_url(bucket, settings.aws_region, s3_key)
    except Exception:
        return None


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


def _pil_to_bytes(img: Image.Image, use_alpha: bool = False) -> tuple[bytes, str]:
    """PIL 이미지를 바이트로 변환. (data, ext) 반환."""
    buf = BytesIO()
    if use_alpha or img.mode == "RGBA":
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), "png"
    else:
        img = img.convert("RGB")
        img.save(buf, format="WEBP", quality=WEBP_QUALITY, method=4)
        return buf.getvalue(), "webp"


# ── 공개 API ────────────────────────────────────────────

def save_upload(file: UploadFile, dest_dir: Path, remove_bg: bool = False) -> str | None:
    """
    업로드 파일을 WebP로 변환.
    S3 설정 시 → S3 퍼블릭 URL 반환
    S3 미설정 시 → 로컬 /static/... 경로 반환
    실패 시 → None
    """
    if not file or not file.filename:
        return None
    try:
        data = file.file.read()
        img = Image.open(BytesIO(data))
        img = _process_image(img, remove_bg=remove_bg)
        use_alpha = remove_bg and REMOVE_BG_ENABLED and img.mode == "RGBA"
        img_bytes, ext = _pil_to_bytes(img, use_alpha=use_alpha)
        filename = f"{uuid.uuid4().hex}.{ext}"
        content_type = "image/png" if ext == "png" else "image/webp"

        # S3 업로드 시도
        s3_prefix = _S3_PREFIX_MAP.get(str(dest_dir), f"uploads/{dest_dir.name}")
        s3_key = f"{s3_prefix}/{filename}"
        s3_url = _upload_bytes_to_s3(img_bytes, s3_key, content_type)
        if s3_url:
            return s3_url

        # S3 실패 → 로컬 저장 fallback
        dest = dest_dir / filename
        dest.write_bytes(img_bytes)
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
            raw_data = file.file.read()
            content_type = f"image/{raw_ext.replace('jpg', 'jpeg')}"

            # S3 업로드 시도
            s3_prefix = _S3_PREFIX_MAP.get(str(dest_dir), f"uploads/{dest_dir.name}")
            s3_key = f"{s3_prefix}/{filename}"
            s3_url = _upload_bytes_to_s3(raw_data, s3_key, content_type)
            if s3_url:
                return s3_url

            # 로컬 fallback
            dest = dest_dir / filename
            dest.write_bytes(raw_data)
            return f"/{dest}"
        except Exception:
            return None


def save_product_image(file: UploadFile, remove_bg: bool = False) -> str | None:
    return save_upload(file, UPLOAD_DIR_PRODUCTS, remove_bg=remove_bg)


def save_influencer_image(file: UploadFile, remove_bg: bool = False) -> str | None:
    return save_upload(file, UPLOAD_DIR_INFLUENCERS, remove_bg=remove_bg)


def save_brand_logo(file: UploadFile, remove_bg: bool = False) -> str | None:
    return save_upload(file, UPLOAD_DIR_BRANDS, remove_bg=remove_bg)


def save_sales_page_image(file: UploadFile, remove_bg: bool = False) -> str | None:
    return save_upload(file, UPLOAD_DIR_SALES_PAGES, remove_bg=remove_bg)


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
