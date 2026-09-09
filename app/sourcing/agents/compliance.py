"""ComplianceAgent — 6단계.

규제 카테고리(의료기기/식품/건기식/화장품) 광고 표현을 사용가능/위험으로 분리.
compliance_rules.py 규칙 + structured outputs.
"""
from __future__ import annotations

from pathlib import Path

from app.ai.client import ClaudeClient
from app.sourcing import compliance_rules
from app.sourcing.schemas import COMPLIANCE_SCHEMA

_PROMPT = Path(__file__).resolve().parent.parent.parent / "prompts" / "sourcing_compliance.md"


def _load_prompt() -> tuple[str, str]:
    text = _PROMPT.read_text(encoding="utf-8")
    return text.split("## User")[0].replace("## System\n", "").strip(), text.split("## User Template\n", 1)[1]


def analyze(name: str, brand: str = "", category: str = "",
            benefits: list[str] | None = None, extra: str = "") -> dict:
    claude = ClaudeClient()
    if not claude.available:
        return {}
    area = compliance_rules.detect_category(category, name)
    system, tmpl = _load_prompt()
    user = (
        tmpl.replace("{area}", area)
        .replace("{risk_guide}", compliance_rules.risk_guide(area))
        .replace("{product_name}", name or "")
        .replace("{brand}", brand or "")
        .replace("{benefits}", ", ".join(benefits or []) or "없음")
        .replace("{extra}", extra or "없음")
    )
    return claude.complete_json(system, user, max_tokens=2000, schema=COMPLIANCE_SCHEMA)
