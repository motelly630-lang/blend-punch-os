"""ResearchAgent — 5단계.

2-step: (1) web_search 서버툴로 원문 수집 → (2) structured outputs로 RESEARCH_SCHEMA 정규화.
"""
from __future__ import annotations

from pathlib import Path

from app.ai.client import ClaudeClient
from app.sourcing.schemas import RESEARCH_SCHEMA

_PROMPT = Path(__file__).resolve().parent.parent.parent / "prompts" / "sourcing_research.md"

_NORMALIZE_SYSTEM = (
    "아래 웹서치 결과 텍스트를 제공된 JSON 스키마로 정규화하라. "
    "원문에 없는 내용은 지어내지 말고, competitors/keywords/pros/cautions는 텍스트에서 추출. "
    "sources에는 본문에 등장한 URL만."
)


def _load_prompt() -> tuple[str, str]:
    text = _PROMPT.read_text(encoding="utf-8")
    return text.split("## User")[0].replace("## System\n", "").strip(), text.split("## User Template\n", 1)[1]


def research(name: str, brand: str = "", category: str = "") -> dict:
    claude = ClaudeClient()
    if not claude.available:
        return {}

    system, tmpl = _load_prompt()
    user = (
        tmpl.replace("{product_name}", name or "")
        .replace("{brand}", brand or "")
        .replace("{category}", category or "")
    )
    # 1) 웹서치 원문 수집
    raw = claude.web_search_text(system, user, max_tokens=3000)
    if not raw.strip():
        return {}

    # 2) 구조화 정규화
    return claude.complete_json(
        _NORMALIZE_SYSTEM,
        f"웹서치 결과:\n\n{raw}",
        max_tokens=2000,
        schema=RESEARCH_SCHEMA,
    )
