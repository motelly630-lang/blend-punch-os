"""Structured-output JSON Schemas for the sourcing agents.

Constraints for Anthropic Structured Outputs:
  - every object has "additionalProperties": false
  - every property is listed in "required"
  - fields that may be unknown use a nullable type, e.g. ["number", "null"]
"""

# ── ExtractorAgent (1·2단계) ──────────────────────────────────────────────────
# 자유형 엑셀/PDF 행 → 표준 상품 필드로 정규화. 모르는 값은 null.

EXTRACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "product_name": {"type": ["string", "null"], "description": "상품명"},
        "brand": {"type": ["string", "null"], "description": "브랜드명"},
        "category": {"type": ["string", "null"], "description": "카테고리 (예: 화장품, 식품, 생활가전)"},
        "options": {
            "type": "array",
            "description": "옵션 목록 (없으면 빈 배열)",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "price": {"type": ["number", "null"]},
                },
                "required": ["name", "price"],
            },
        },
        "consumer_price": {"type": ["number", "null"], "description": "소비자가(정가) 원"},
        "supplier_price": {"type": ["number", "null"], "description": "공급가(원, 내부)"},
        "groupbuy_price": {"type": ["number", "null"], "description": "공구가(원)"},
        "shipping_cost": {"type": ["number", "null"], "description": "배송비(원). 무료면 0"},
        "shipping_type": {"type": ["string", "null"], "description": "무료배송|유료배송"},
        "dispatch_days": {"type": ["string", "null"], "description": "출고마감/소요 (당일|1~2일|3~5일|주문제작)"},
        "as_info": {"type": ["string", "null"], "description": "A/S 정보 (보증기간·교환반품·연락처)"},
        "cert_info": {
            "type": "array",
            "description": "인증정보 (KC·식약처 등). 없으면 빈 배열",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "type": {"type": "string", "description": "인증종류 (예: KC, 식약처, 전기안전)"},
                    "number": {"type": ["string", "null"], "description": "인증번호"},
                    "authority": {"type": ["string", "null"], "description": "발급기관"},
                },
                "required": ["type", "number", "authority"],
            },
        },
        "key_benefits": {
            "type": "array",
            "description": "핵심 혜택/셀링포인트 (최대 5개)",
            "items": {"type": "string"},
        },
        "unique_selling_point": {"type": ["string", "null"], "description": "한 줄 USP"},
        "missing_fields": {
            "type": "array",
            "description": "원본에서 찾을 수 없어 비워둔 표준 필드 라벨 목록",
            "items": {"type": "string"},
        },
    },
    "required": [
        "product_name", "brand", "category", "options",
        "consumer_price", "supplier_price", "groupbuy_price",
        "shipping_cost", "shipping_type", "dispatch_days",
        "as_info", "cert_info", "key_benefits", "unique_selling_point",
        "missing_fields",
    ],
}


# ── 시트 전체 추출 (문서형 제안서 대응) ──────────────────────────────────────
# 깔끔한 표가 아닌 공동구매 제안서/계획서 양식: 시트 전체를 보고 상품목록 + 공통정보 추출.

SHEET_EXTRACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "brand": {"type": ["string", "null"], "description": "브랜드/제조사 (문서에서 추정)"},
        "category": {"type": ["string", "null"], "description": "카테고리"},
        "product_url": {"type": ["string", "null"], "description": "상세페이지/판매 URL"},
        "shipping_carrier": {"type": ["string", "null"], "description": "택배사"},
        "shipping_fee": {"type": ["number", "null"], "description": "배송비(원)"},
        "dispatch_days": {"type": ["string", "null"], "description": "발송/출고 기준"},
        "as_info": {"type": ["string", "null"], "description": "A/S·교환·반품 정보"},
        "settlement_terms": {"type": ["string", "null"], "description": "정산 방법/기준"},
        "selling_points": {"type": "array", "description": "셀링포인트", "items": {"type": "string"}},
        "cautions": {"type": "array", "description": "주의/허들/기타 안내", "items": {"type": "string"}},
        "products": {
            "type": "array",
            "description": "표에서 추출한 상품 목록 (옵션/구성 단위)",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string", "description": "상품/옵션명"},
                    "option_note": {"type": ["string", "null"], "description": "구성/옵션 설명"},
                    "consumer_price": {"type": ["number", "null"], "description": "소비자가(정가)"},
                    "supplier_price": {"type": ["number", "null"], "description": "공급가"},
                    "groupbuy_price": {"type": ["number", "null"], "description": "공구가/판매가 (없으면 소비자가와 동일 가능)"},
                    "available_qty": {"type": ["number", "null"], "description": "판매 가능 수량"},
                    "note": {"type": ["string", "null"], "description": "비고"},
                },
                "required": ["name", "option_note", "consumer_price", "supplier_price",
                             "groupbuy_price", "available_qty", "note"],
            },
        },
    },
    "required": ["brand", "category", "product_url", "shipping_carrier", "shipping_fee",
                 "dispatch_days", "as_info", "settlement_terms", "selling_points", "cautions", "products"],
}


# ── ProfileAgent (16필드 풀 자동화: AI 생성 필드) ─────────────────────────────

PROFILE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "category": {"type": "string", "description": "제품명/브랜드 기준 카테고리 (1depth)"},
        "structure_type": {"type": "string", "enum": ["수량형", "옵션형", "세트형"],
                            "description": "상품 구조 타입 (단일수량/옵션선택/세트구성)"},
        "description": {"type": "string", "description": "제품 설명 2~4문장"},
        "unique_selling_point": {"type": "string", "description": "핵심 셀링포인트 한 줄 (USP)"},
        "key_benefits": {"type": "array", "description": "핵심 혜택 3~5개", "items": {"type": "string"}},
        "content_angle": {"type": "string", "description": "콘텐츠 앵글 (어떤 각도로 소구할지)"},
        "positioning": {"type": "string", "description": "포지셔닝 전략 (시장 내 위치/차별점)"},
        "target_audience": {"type": "string", "description": "핵심 타겟 고객"},
        "consumer_tags": {
            "type": "array",
            "description": "소비자 카테고리 태그 — 반드시 아래 8개 중에서만 선택 (1~3개)",
            "items": {"type": "string", "enum": ["식품", "주방", "리빙", "뷰티", "건강", "다이어트", "육아", "반려동물"]},
        },
    },
    "required": ["category", "structure_type", "description", "unique_selling_point",
                 "key_benefits", "content_angle", "positioning", "target_audience", "consumer_tags"],
}


# ── ResearchAgent (5단계) ─────────────────────────────────────────────────────
# 웹서치 원문 텍스트 → 구조화 보강 정보로 정규화.

RESEARCH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "official_info": {"type": ["string", "null"], "description": "공식 제품 정보 요약 2~3문장"},
        "competitors": {
            "type": "array",
            "description": "경쟁/유사 상품 (최대 5개)",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "note": {"type": ["string", "null"], "description": "가격대/차별점 등 한 줄"},
                },
                "required": ["name", "note"],
            },
        },
        "review_keywords": {"type": "array", "description": "후기에서 자주 나오는 키워드", "items": {"type": "string"}},
        "pros": {"type": "array", "description": "장점/강점", "items": {"type": "string"}},
        "cautions": {"type": "array", "description": "주의사항/단점/리스크", "items": {"type": "string"}},
        "sources": {"type": "array", "description": "참고 출처 URL", "items": {"type": "string"}},
    },
    "required": ["official_info", "competitors", "review_keywords", "pros", "cautions", "sources"],
}


# ── ComplianceAgent (6단계) ───────────────────────────────────────────────────
# 규제 카테고리(의료기기/식품/건기식/화장품) 광고 표현 분리.

COMPLIANCE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "category": {"type": "string", "description": "판정한 규제 카테고리 또는 '일반'"},
        "is_regulated": {"type": "boolean", "description": "광고 규제 대상 여부"},
        "safe_expressions": {"type": "array", "description": "사용 가능한 표현", "items": {"type": "string"}},
        "risky_expressions": {
            "type": "array",
            "description": "사용 위험/금지 표현",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "phrase": {"type": "string", "description": "위험 표현"},
                    "reason": {"type": "string", "description": "위험 사유 (관련 규정)"},
                    "alternative": {"type": ["string", "null"], "description": "권장 대체 표현"},
                },
                "required": ["phrase", "reason", "alternative"],
            },
        },
        "disclaimer": {"type": ["string", "null"], "description": "필수 고지/주의 문구"},
    },
    "required": ["category", "is_regulated", "safe_expressions", "risky_expressions", "disclaimer"],
}


# ── CopywriterAgent (9단계) ───────────────────────────────────────────────────
# 상품별 마케팅 카피 생성. safe_expressions만 활용, risky_expressions 금지.

COPY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "card_news": {"type": "array", "description": "카드뉴스 슬라이드 문구 3~5개", "items": {"type": "string"}},
        "reels_hooks": {"type": "array", "description": "릴스 첫 3초 후킹 멘트 3개", "items": {"type": "string"}},
        "detail_summary": {"type": "string", "description": "상세페이지 요약 (2~3문단)"},
        "seller_message": {"type": "string", "description": "셀러 전달용 핵심 셀링 문구"},
    },
    "required": ["card_news", "reels_hooks", "detail_summary", "seller_message"],
}
