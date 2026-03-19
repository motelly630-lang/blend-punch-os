import asyncio
import html as _html
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


def _get_meta(html: str, prop: str) -> str:
    """og: 또는 name= 메타 태그 content 추출 후 HTML 디코딩."""
    p = re.escape(prop)
    patterns = [
        fr'property="{p}"\s+content="([^"]*)"',
        fr"property='{p}'\s+content='([^']*)'",
        fr'content="([^"]*)"\s+[^>]*property="{p}"',
        fr"content='([^']*)'\s+[^>]*property='{p}'",
        fr'name="{p}"\s+content="([^"]*)"',
        fr"name='{p}'\s+content='([^']*)'",
    ]
    for pat in patterns:
        m = re.search(pat, html, re.I)
        if m:
            return _html.unescape(m.group(1).strip())
    return ""


def _parse_followers(text: str) -> int:
    """'팔로워 672M명' 또는 '1.5M Followers' 등에서 정수 추출."""
    if not text:
        return 0
    # 한국어: 팔로워 672M명
    m = re.search(r'팔로워\s*([\d.,]+)\s*([KMBkmb만억]?)\s*명', text)
    if not m:
        # 영어: 1.5M Followers / Subscribers
        m = re.search(r'([\d.,]+)\s*([KMBkmb]?)\s*(?:Followers?|Subscribers?)', text, re.I)
    if not m:
        return 0
    num = float(m.group(1).replace(',', ''))
    unit = m.group(2).upper() if m.group(2) else ''
    mul = {'K': 1_000, 'M': 1_000_000, 'B': 1_000_000_000,
           '만': 10_000, '억': 100_000_000}.get(unit, 1)
    return int(num * mul)


def _extract_direct(html: str, platform: str, handle: str) -> dict:
    """HTML에서 직접 파싱할 수 있는 값 추출 (Claude 불필요한 부분)."""
    og_title = _get_meta(html, 'og:title')
    og_desc  = _get_meta(html, 'og:description')
    og_image = _get_meta(html, 'og:image')

    # 이름 추출: Instagram "Name(@handle) • ..." / YouTube "Name - YouTube"
    name = ""
    if og_title:
        # Instagram: "Name(@handle) • Instagram 사진..."
        m = re.match(r'^(.+?)\s*\(@?[\w.]+\)\s*[•·]', og_title)
        if m:
            name = m.group(1).strip()
        # YouTube: "Name - YouTube"
        elif ' - YouTube' in og_title:
            name = og_title.replace(' - YouTube', '').strip()
        # TikTok: "@handle (@handle)"
        elif og_title and not name:
            name = og_title.split('(')[0].strip().lstrip('@') or ""

    followers = _parse_followers(og_desc)

    return {
        "name": name,
        "followers": followers,
        "og_image_url": og_image,   # 빈 문자열이면 Instagram이 이미지 미제공
        "_og_title": og_title,
        "_og_desc": og_desc,
    }


def _meta_slice(html: str) -> str:
    """Extract meta tags (HTML-decoded) + JSON-LD for Claude — keep small."""
    parts = []

    title = re.search(r"<title[^>]*>(.*?)</title>", html[:20000], re.I | re.S)
    if title:
        parts.append(f"title: {_html.unescape(title.group(1).strip())}")

    # og: 핵심 값만 디코딩해서 전달
    for tag in ['og:title', 'og:description', 'og:image']:
        val = _get_meta(html, tag)
        if val:
            parts.append(f"{tag}: {val}")

    lds = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html[:60000], re.S | re.I,
    )
    if lds:
        parts.append("=== JSON-LD ===")
        for s in lds[:3]:
            parts.append(s.strip()[:3000])

    return "\n".join(parts)[:8000]


def _og_image(html: str) -> str:
    """Extract og:image content value (HTML-decoded)."""
    for pat in (
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
    ):
        m = re.search(pat, html, re.I)
        if m:
            return _html.unescape(m.group(1).strip())
    return ""


def _clean_img_url(url: str) -> str:
    """HTML-decode URL (Instagram CDN은 서명된 URL이므로 쿼리파라미터 수정 금지)."""
    if not url:
        return url
    return _html.unescape(url)


def _referer_for(url: str) -> str:
    if "instagram.com" in url or "cdninstagram.com" in url:
        return "https://www.instagram.com/"
    if "ytimg.com" in url or "youtube.com" in url:
        return "https://www.youtube.com/"
    if "tiktok.com" in url:
        return "https://www.tiktok.com/"
    return ""


def _download_image(url: str) -> tuple[bytes, str] | None:
    """Download image bytes; return (bytes, extension) or None."""
    url = _clean_img_url(url)
    if not url or not url.startswith("http"):
        return None
    try:
        headers = dict(_HEADERS)
        referer = _referer_for(url)
        if referer:
            headers["Referer"] = referer
        with httpx.Client(follow_redirects=True, timeout=15, headers=headers) as c:
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

    # ── Step 2a: 직접 파싱 (HTML decode 후 regex) ────────────────────────────
    direct: dict = {}
    if fetch_ok and html:
        direct = _extract_direct(html, platform, url_handle)

    # ── Step 2b: Claude로 카테고리 등 추가 분석 ──────────────────────────────
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
            data = await asyncio.to_thread(
                lambda: claude.complete_json(system, user_text, max_tokens=1024)
            )
        except Exception:
            pass

    # ── 직접 파싱값이 Claude보다 신뢰도 높음 → 덮어쓰기 ─────────────────────
    if direct.get("name"):
        data["name"] = direct["name"]
    if direct.get("followers"):
        data["followers"] = direct["followers"]

    # ── Fallback: URL에서 최소값 보정 ────────────────────────────────────────
    data.setdefault("handle", url_handle)
    data["platform"] = platform
    data["profile_url"] = url

    # ── Step 3: 이미지 다운로드 ──────────────────────────────────────────────
    profile_image_path = ""
    # og_image_url: 직접 파싱값 우선 (이미 HTML-decoded), Claude 값은 추가 디코딩
    raw_img_url = direct.get("og_image_url") or data.get("profile_image_url") or ""
    img_url = _clean_img_url(raw_img_url)
    if img_url:
        result = await asyncio.to_thread(_download_image, img_url)
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


# ── Shared helper: process a single URL → dict (used by bulk import) ──────────

async def process_influencer_url(url: str) -> dict:
    """
    Fetch + Claude-extract one influencer URL.
    Returns a dict with keys matching Influencer model fields.
    Always returns something (falls back to URL-only data on failure).
    """
    url = url.strip()
    platform = _detect_platform(url)
    url_handle = _extract_handle_from_url(url, platform)

    html = ""
    fetch_ok = False
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15, headers=_HEADERS) as client:
            r = await client.get(url)
            if r.status_code == 200:
                html = r.text
                fetch_ok = True
    except Exception:
        pass

    data: dict = {}
    claude = ClaudeClient()
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
            data = await asyncio.to_thread(
                lambda: claude.complete_json(system, user_text, max_tokens=1024)
            )
        except Exception:
            pass

    data.setdefault("handle", url_handle)
    data.setdefault("platform", platform)
    data["profile_url"] = url

    profile_image_path = ""
    raw_img_url = data.get("profile_image_url") or (html and _og_image(html)) or ""
    img_url = _clean_img_url(raw_img_url)
    if img_url:
        result = await asyncio.to_thread(_download_image, img_url)
        if result:
            img_bytes, ext = result
            profile_image_path = _save_image_bytes(img_bytes, ext)
    data["profile_image"] = profile_image_path

    return data


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

        data = await asyncio.to_thread(
            lambda: claude.complete_vision_json(system, user_text, image_bytes, media_type)
        )
    except Exception as e:
        return HTMLResponse(
            f'<div id="ai-inf-result" class="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">'
            f"이미지 분석 실패: {_esc(str(e))}</div>"
        )

    return HTMLResponse(_result_html(data, "", ""))
