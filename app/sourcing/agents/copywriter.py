"""CopywriterAgent — 9단계.

상품별 카드뉴스/릴스후킹/상세요약/셀러문구 생성. 규제 안전표현만 사용,
위험표현 금지. structured outputs.
"""
from __future__ import annotations

from pathlib import Path

from app.ai.client import ClaudeClient
from app.sourcing.schemas import COPY_SCHEMA

_PROMPT = Path(__file__).resolve().parent.parent.parent / "prompts" / "sourcing_copy.md"


def _load_prompt() -> tuple[str, str]:
    text = _PROMPT.read_text(encoding="utf-8")
    return text.split("## User")[0].replace("## System\n", "").strip(), text.split("## User Template\n", 1)[1]


def generate(name: str, brand: str = "", category: str = "", benefits: list[str] | None = None,
             usp: str = "", groupbuy_price: float = 0,
             safe: list[str] | None = None, risky: list[str] | None = None) -> dict:
    claude = ClaudeClient()
    if not claude.available:
        return {}
    system, tmpl = _load_prompt()
    user = (
        tmpl.replace("{product_name}", name or "")
        .replace("{brand}", brand or "")
        .replace("{category}", category or "")
        .replace("{benefits}", ", ".join(benefits or []) or "없음")
        .replace("{usp}", usp or "없음")
        .replace("{groupbuy_price}", f"{int(groupbuy_price or 0):,}")
        .replace("{safe}", ", ".join(safe or []) or "(제한 없음)")
        .replace("{risky}", ", ".join(risky or []) or "(없음)")
    )
    return claude.complete_json(system, user, max_tokens=2500, schema=COPY_SCHEMA)
