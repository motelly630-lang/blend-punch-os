"""공구 콘텐츠 링크(인스타 릴스·게시물, 유튜브 쇼츠) → 화면에 띄울 수 있는 embed 주소.

API·토큰 없이 공개 게시물의 공식 embed 주소만 쓴다 (비공개·삭제된 게시물은 embed 가 비어 보인다).
"""
from __future__ import annotations

import re

_IG = re.compile(r"instagram\.com/(?:[A-Za-z0-9._]+/)?(reel|reels|p|tv)/([A-Za-z0-9_-]{5,})")
_YT = re.compile(r"(?:youtube\.com/(?:shorts/|watch\?v=|embed/)|youtu\.be/)([A-Za-z0-9_-]{6,})")


def parse(url: str) -> dict | None:
    """링크 → {url, kind, code, embed, label}. 모르는 링크면 None."""
    u = (url or "").strip()
    m = _IG.search(u)
    if m:
        kind = "reel" if m.group(1) in ("reel", "reels") else m.group(1)
        code = m.group(2)
        return {"url": f"https://www.instagram.com/{kind}/{code}/", "kind": "instagram", "code": code,
                "embed": f"https://www.instagram.com/{kind}/{code}/embed/", "label": "인스타 릴스" if kind == "reel" else "인스타 게시물"}
    m = _YT.search(u)
    if m:
        return {"url": u, "kind": "youtube", "code": m.group(1),
                "embed": f"https://www.youtube.com/embed/{m.group(1)}", "label": "유튜브"}
    return None


def parse_many(urls) -> list[dict]:
    out, seen = [], set()
    for u in urls or []:
        p = parse(u)
        if p and p["url"] not in seen:
            seen.add(p["url"])
            out.append(p)
    return out
