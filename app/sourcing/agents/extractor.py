"""ExtractorAgent — 1·2단계.

공급사 자유형 엑셀 행/PDF 블록 → 표준 상품 필드로 정규화.
강화된 중앙 ClaudeClient.complete_json(schema=) 의 Structured Outputs를 사용해
스키마-유효 JSON을 보장받는다 (펜스 벗기기/예외 파싱 불필요).
"""
from __future__ import annotations

import json
from pathlib import Path

from app.ai.client import ClaudeClient
from app.sourcing.schemas import EXTRACT_SCHEMA, SHEET_EXTRACT_SCHEMA

_PROMPTS = Path(__file__).resolve().parent.parent.parent / "prompts"
_PROMPT = _PROMPTS / "sourcing_extract.md"
_SHEET_PROMPT = _PROMPTS / "sourcing_sheet_extract.md"


def _split(text: str) -> tuple[str, str]:
    return text.split("## User")[0].replace("## System\n", "").strip(), text.split("## User Template\n", 1)[1]


def _load_prompt() -> tuple[str, str]:
    return _split(_PROMPT.read_text(encoding="utf-8"))


def _grid_to_text(grid: list[list[str]], max_rows: int = 80) -> str:
    """그리드 → 'r: a | b | c' 텍스트 (빈 행/빈 셀 정리)."""
    lines = []
    for i, row in enumerate(grid[:max_rows]):
        cells = [(c or "").strip().replace("\n", " ") for c in row]
        if not any(cells):
            continue
        lines.append(f"{i}: " + " | ".join(c for c in cells if c is not None))
    return "\n".join(lines)


def extract_sheet(grid: list[list[str]], filename: str = "") -> dict:
    """시트 전체(문서형 제안서) → {products:[...], 공통정보...} 추출.

    깔끔한 표가 아닌 공동구매 제안서/계획서 양식 대응. Structured outputs.
    """
    claude = ClaudeClient()
    if not claude.available:
        return {}
    system, tmpl = _split(_SHEET_PROMPT.read_text(encoding="utf-8"))
    user = tmpl.replace("{filename}", filename or "").replace("{sheet_text}", _grid_to_text(grid))
    return claude.complete_json(system, user, max_tokens=4000, schema=SHEET_EXTRACT_SCHEMA)


def extract_row(row: dict | str, hint: str = "") -> dict:
    """한 상품(엑셀 행 dict 또는 텍스트 블록)을 표준 필드 dict로 추출.

    반환: EXTRACT_SCHEMA 구조의 dict. AI 미사용 시 빈 dict.
    """
    claude = ClaudeClient()
    if not claude.available:
        return {}

    system, user_template = _load_prompt()
    row_data = json.dumps(row, ensure_ascii=False, indent=2) if isinstance(row, dict) else str(row)
    user = user_template.replace("{row_data}", row_data).replace("{hint}", hint or "없음")

    return claude.complete_json(system, user, max_tokens=1500, schema=EXTRACT_SCHEMA)


def to_product_fields(extracted: dict) -> dict:
    """추출 결과(EXTRACT_SCHEMA) → Product 모델 컬럼 dict로 매핑.

    margin_rate 등 계산값은 pricing 단계에서 채운다.
    """
    options = extracted.get("options") or []
    set_options = [
        {"name": o.get("name"), "qty": 1, "price": o.get("price"), "notes": ""}
        for o in options if o.get("name")
    ]
    return {
        "name": extracted.get("product_name"),
        "brand": extracted.get("brand"),
        "category": extracted.get("category"),
        "set_options": set_options or None,
        "consumer_price": extracted.get("consumer_price") or 0,
        "supplier_price": extracted.get("supplier_price") or 0,
        "groupbuy_price": extracted.get("groupbuy_price") or 0,
        "shipping_cost": extracted.get("shipping_cost"),
        "shipping_type": extracted.get("shipping_type"),
        "dispatch_days": extracted.get("dispatch_days"),
        "as_info": extracted.get("as_info"),
        "cert_info": extracted.get("cert_info") or None,
        "key_benefits": extracted.get("key_benefits") or None,
        "unique_selling_point": extracted.get("unique_selling_point"),
        "missing_fields": extracted.get("missing_fields") or None,
    }
