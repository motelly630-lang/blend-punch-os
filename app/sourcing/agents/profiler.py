"""ProfileAgent — 16필드 풀 자동화의 AI 생성 필드.

제품명+브랜드+가격으로 카테고리·구조타입·설명·USP·혜택·앵글·포지셔닝·타겟·태그 생성.
structured outputs.
"""
from __future__ import annotations

from pathlib import Path

from app.ai.client import ClaudeClient
from app.sourcing.schemas import PROFILE_SCHEMA

_PROMPT = Path(__file__).resolve().parent.parent.parent / "prompts" / "sourcing_profile.md"


def _load() -> tuple[str, str]:
    t = _PROMPT.read_text(encoding="utf-8")
    return t.split("## User")[0].replace("## System\n", "").strip(), t.split("## User Template\n", 1)[1]


def generate(name: str, brand: str = "", category: str = "",
             consumer_price: float = 0, groupbuy_price: float = 0,
             options: str = "", benefits: list[str] | None = None, ref: str = "") -> dict:
    claude = ClaudeClient()
    if not claude.available:
        return {}
    system, tmpl = _load()
    user = (
        tmpl.replace("{product_name}", name or "")
        .replace("{brand}", brand or "")
        .replace("{category}", category or "미분류")
        .replace("{consumer_price}", f"{int(consumer_price or 0):,}")
        .replace("{groupbuy_price}", f"{int(groupbuy_price or 0):,}")
        .replace("{options}", options or "없음")
        .replace("{benefits}", ", ".join(benefits or []) or "없음")
        .replace("{ref}", ref or "없음")
    )
    return claude.complete_json(system, user, max_tokens=1500, schema=PROFILE_SCHEMA)
