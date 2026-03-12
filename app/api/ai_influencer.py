import re
import uuid
import json as _json
import httpx
from pathlib import Path
from fastapi import APIRouter, Form, UploadFile, File, Depends
from fastapi.responses import HTMLResponse
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.ai.client import ClaudeClient

router = APIRouter(prefix="/api/ai")

UPLOAD_DIR = Path("static/uploads/influencers")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_PROMPTS = Path(__file__).parent.parent / "prompts"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


def _detect_platform(url: str) -> str:
    u = url.lower()
    if "instagram.com" in u:
        return "instagram"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "tiktok.com" in u:
        return "tiktok"
    return "other"


def _extract_handle_from_url(url: str, platform: str) -> str:
    """Best-effort handle extraction from URL alone."""
    try:
        # Strip query/fragment
        clean = url.split("?")[0].split("#")[0].rstrip("/")
        parts = clean.split("/")
        if platform == "instagram":
            # instagram.com/handle
            return parts[-1].lstrip("@")
        if platform == "tiktok":
            # tiktok.com/@handle
            return parts[-1].lstrip("@")
        if platform == "youtube":
            # youtube.com/@handle  or  /channel/UC...  or  /c/name  or  /user/name
            last = parts[-1]
            if last.startswith("@"):
                return last[1:]
            if len(parts) >= 2 and parts[-2] in ("channel", "c", "user"):
                return last
            return last
    except Exception:
        pass
    return ""


def _meta_slice(html: str) -> str:
    """Extract meta tags + JSON-LD + title for Claude — keep small."""
    parts = []

    title = re.search(r"<title[^>]*>(.*?)</title>", html[:20000], re.I | re.S)
    if title:
        parts.append(f"<title>{title.group(1).strip()}</title>")

    metas = re.findall(r"<meta[^>]+>", html[:60000], re.I)
    parts.append("=== META ===")
    parts.extend(metas[:60])

    lds = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html[:60000], re.S | re.I,
    )
    if lds:
        parts.append("=== JSON-LD ===")
        for s in lds[:3]:
            parts.append(s.strip()[:3000])

    return "\n".join(parts)[:10000]


def _og_image(html: str) -> str:
    """Extract og:image content value."""
    for pat in (
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
    ):
        m = re.search(pat, html, re.I)
        if m:
            return m.group(1).strip()
    return ""


def _download_image(url: str) -> tuple[bytes, str] | None:
    """Download image bytes; return (bytes, extension) or None."""
    if not url or not url.startswith("http"):
        return None
    try:
        with httpx.Client(follow_redirects=True, timeout=15, headers=_HEADERS) as c:
            r = c.get(url)
            if r.status_code != 200 or not r.content:
                return None
            ct = r.headers.get("content-type", "image/jpeg").lower()
            ext = "png" if "png" in ct else "webp" if "webp" in ct else "jpg"
            return r.content, ext
    except Exception:
        return None


def _save_image_bytes(data: bytes, ext: str) -> str:
    filename = f"{uuid.uuid4().hex}.{ext}"
    (UPLOAD_DIR / filename).write_bytes(data)
    return f"/static/uploads/influencers/{filename}"


def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _result_html(data: dict, profile_image_path: str, original_url: str) -> str:
    """Build the htmx response HTML."""
    name = _esc(str(data.get("name") or ""))
    handle = _esc(str(data.get("handle") or ""))
    platform = _esc(str(data.get("platform") or ""))
    followers = data.get("followers") or 0
    followers_str = f"{int(followers):,}" if followers else "-"

    preview = " &nbsp;·&nbsp; ".join(filter(None, [
        f"<b>{name}</b>" if name else "",
        f"@{handle}" if handle else "",
        platform,
        f"팔로워 {followers_str}" if followers else "",
    ]))

    payload = {**data, "profile_image_path": profile_image_path, "profile_url": original_url}
    data_json = _esc(_json.dumps(payload, ensure_ascii=False))

    return f"""
<div id="ai-inf-result" class="space-y-3 p-4 bg-blue-50 border border-blue-200 rounded-lg">
  <div class="flex items-start gap-2">
    <svg class="w-4 h-4 text-blue-600 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
      <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
    </svg>
    <div>
      <div class="text-sm font-semibold text-blue-800 mb-0.5">분석 완료</div>
      <div class="text-xs text-blue-600">{preview}</div>
    </div>
  </div>
  <button type="button" onclick="applyAiInfluencerFill(JSON.parse(this.dataset.d))" data-d="{data_json}"
    class="w-full px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors">
    폼에 적용하기
  </button>
</div>
"""


# ── URL import ────────────────────────────────────────────────────────────────

@router.post("/influencer-url-fill", response_class=HTMLResponse)
async def influencer_url_fill(
    url: str = Form(...),
    current_user: User = Depends(get_current_user),
):
    platform = _detect_platform(url)
    url_handle = _extract_handle_from_url(url, platform)

    # ── Step 1: fetch page HTML ───────────────────────────────────────────────
    html = ""
    fetch_ok = False
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=15, headers=_HEADERS
        ) as client:
            r = await client.get(url)
            if r.status_code == 200:
                html = r.text
                fetch_ok = True
    except Exception:
        pass

    # ── Step 2: Claude extraction or URL fallback ─────────────────────────────
    claude = ClaudeClient()
    data: dict = {}

    if fetch_ok and html and claude.available:
        snippet = _meta_slice(html)
        prompt_file = _PROMPTS / "influencer_url_extract.md"
        raw_prompt = prompt_file.read_text(encoding="utf-8")
        system = raw_prompt.split("## User Template")[0].replace("## System\n", "").strip()
        user_tpl = raw_prompt.split("## User Template\n", 1)[1].strip()
        user_text = (
            user_tpl
            .replace("{{platform}}", platform)
            .replace("{{url}}", url)
            .replace("{{html_snippet}}", snippet)
        )
        try:
            data = claude.complete_json(system, user_text, max_tokens=1024)
        except Exception:
            pass

    # ── Fallback: fill what we can from the URL itself ────────────────────────
    if not data.get("handle") and url_handle:
        data.setdefault("handle", url_handle)
    if not data.get("platform"):
        data["platform"] = platform
    if not data.get("profile_url"):
        data["profile_url"] = url

    # ── Step 3: download profile image ───────────────────────────────────────
    profile_image_path = ""
    img_url = data.get("profile_image_url") or (html and _og_image(html)) or ""
    if img_url:
        result = _download_image(img_url)
        if result:
            img_bytes, ext = result
            profile_image_path = _save_image_bytes(img_bytes, ext)

    # ── Error: nothing useful extracted ──────────────────────────────────────
    if not any([data.get("name"), data.get("handle"), profile_image_path]):
        reason = "페이지 접근 불가 (로그인 필요 또는 비공개 계정일 수 있습니다)" if not fetch_ok else "데이터 추출 실패"
        if url_handle:
            # At least partially filled
            data = {"handle": url_handle, "platform": platform, "profile_url": url}
            return HTMLResponse(_result_html(data, "", url) + f"""
<div class="mt-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2">
  {_esc(reason)} — 핸들만 자동 입력되었습니다. 나머지는 직접 입력해주세요.
</div>""")
        return HTMLResponse(
            f'<div id="ai-inf-result" class="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">'
            f"분석 실패: {_esc(reason)}</div>"
        )

    return HTMLResponse(_result_html(data, profile_image_path, url))


# ── Screenshot OCR ────────────────────────────────────────────────────────────

@router.post("/influencer-image-fill", response_class=HTMLResponse)
async def influencer_image_fill(
    image: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    claude = ClaudeClient()
    if not claude.available:
        return HTMLResponse(
            '<div id="ai-inf-result" class="p-4 bg-yellow-50 border border-yellow-200 rounded-lg text-sm text-yellow-800">'
            "AI 미사용 모드 — API 키를 설정하면 이미지 분석을 사용할 수 있습니다.</div>"
        )

    try:
        image_bytes = await image.read()
        media_type = image.content_type or "image/jpeg"

        prompt_file = _PROMPTS / "influencer_image_fill.md"
        raw = prompt_file.read_text(encoding="utf-8")
        system = raw.split("## User Template")[0].replace("## System\n", "").strip()
        user_text = raw.split("## User Template\n", 1)[1].strip()

        data = claude.complete_vision_json(system, user_text, image_bytes, media_type)
    except Exception as e:
        return HTMLResponse(
            f'<div id="ai-inf-result" class="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">'
            f"이미지 분석 실패: {_esc(str(e))}</div>"
        )

    return HTMLResponse(_result_html(data, "", ""))
