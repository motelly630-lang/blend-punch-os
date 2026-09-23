"""
product_service.py — 제품 비즈니스 로직
- validate_product_completeness: 필수 필드 완성도 검증
- normalize_status / normalize_visibility: 코드값 정규화 (알 수 없는 값은 default)
- parse_status / parse_visibility: 엄격 파싱 (알 수 없는 값은 None → 호출측이 거부)
- PRODUCT_CATEGORIES / normalize_category: 대표 카테고리 공통 기준
"""
import re

# 코드값 허용 목록 — DB에는 반드시 이 영문 값만 들어가야 한다.
# 한글로 입력된 값("공개" 등)이 저장되면 조회 조건과 어긋나 조용히 누락된다.
# 실제 사고: 운영 제품 4건이 visibility_status="공개" 로 저장돼 공개 카탈로그에서 빠졌다
# (/public 은 "active" 또는 NULL 만 노출). 화면상 "공개"로 보이니 아무도 눈치채지 못했다.
STATUS_VALUES = ("draft", "active", "archived")
VISIBILITY_VALUES = ("active", "hidden")

# 한글/변형 입력 → 정식 코드값. migrate.py 의 일회성 정규화가 이 맵을 그대로 import 한다.
# 시트 연동(app/integrations/sheets_bridge.py PRODUCT_STATUS_MAP)의 표현도 여기에 합쳐
# 두었다 — 매핑이 두 곳으로 갈리면 한쪽에만 있는 표현이 조용히 draft 로 떨어진다.
_VISIBILITY_ALIASES = {
    "공개": "active", "노출": "active", "on": "active", "y": "active",
    "비공개": "hidden", "숨김": "hidden", "숨기기": "hidden", "노출안함": "hidden",
    "노출제외": "hidden", "off": "hidden", "n": "hidden", "x": "hidden",
}
_STATUS_ALIASES = {
    "초안": "draft", "임시": "draft",
    "검토": "draft", "협의중": "draft", "판매준비": "draft", "보류": "draft",
    "활성": "active", "진행": "active", "판매중": "active",
    "보관": "archived", "종료": "archived", "판매종료": "archived",
}


def _normalize(value, allowed, aliases, default):
    """허용값 검사와 별칭 조회 모두 소문자로 수행한다.

    ⚠️ 대소문자를 구분하면 `"Hidden"` 이 허용값 검사에서 탈락하고 별칭에도 없어
    default("active")로 떨어진다 — 숨김 의도가 공개로 뒤집히는 fail-open 이 된다.
    같은 이유로 `"Active"` 는 draft 로 떨어져 판매중 제품이 카탈로그에서 사라진다.
    """
    if not isinstance(value, str):
        return default
    v = value.strip().lower()
    if v in allowed:
        return v
    return aliases.get(v, default)


def normalize_visibility(value, default: str = "active") -> str:
    """visibility_status 를 허용 코드값으로 정규화.

    알 수 없는 값은 default("active"=노출). 기존 임포트 동작과 `_public_filter` 의
    "NULL 은 노출" 규칙에 맞춘 fail-open 이다. 숨김 의도가 담긴 표현은 위 별칭에
    등록해 두어야 하며, 새 표현이 발견되면 별칭에 추가할 것.
    """
    return _normalize(value, VISIBILITY_VALUES, _VISIBILITY_ALIASES, default)


def normalize_status(value, default: str = "draft") -> str:
    """status 를 허용 코드값으로 정규화. 알 수 없는 값은 default("draft")."""
    return _normalize(value, STATUS_VALUES, _STATUS_ALIASES, default)


def parse_status(value) -> str | None:
    """status 엄격 파싱 — 허용값·별칭이 아니면 None.

    자동저장처럼 '사용자가 방금 고른 값'을 저장하는 경로에서 쓴다. default 로 떨어뜨리면
    잘못된 입력이 조용히 다른 상태로 저장되기 때문이다.
    """
    return _normalize(value, STATUS_VALUES, _STATUS_ALIASES, None)


def parse_visibility(value) -> str | None:
    """visibility_status 엄격 파싱 — 허용값·별칭이 아니면 None."""
    return _normalize(value, VISIBILITY_VALUES, _VISIBILITY_ALIASES, None)


# ── 대표 카테고리 (products.category) ─────────────────────────────────────────
# 단일 기준. 화면 <select>·AI 프롬프트·임포트·소싱이 모두 이 목록을 참조한다.
PRODUCT_CATEGORIES = [
    "건강기능식품", "스킨케어", "뷰티/메이크업", "헤어케어", "바디케어",
    "다이어트/슬리밍", "식품/음료", "생활용품", "주방용품", "가전제품",
    "패션/의류", "패션잡화", "홈/인테리어", "유아/육아", "반려동물",
    "스포츠/레저", "전자기기", "욕실용품", "기타",
]
_CATEGORY_SET = set(PRODUCT_CATEGORIES)

# 의미가 같은 표기 차이만 매핑한다. '뷰티'·'건강'처럼 여러 표준 카테고리로 갈릴 수 있는
# 넓은 표현은 추측하지 않는다(매핑하지 않고 원본을 보존).
_CATEGORY_ALIASES = {
    "유아/육아용품": "유아/육아",
    "육아용품": "유아/육아",
    "건기식": "건강기능식품",
}


def _category_key(value: str) -> str:
    """구분자·공백 표기 차이 제거: '뷰티·메이크업', '뷰티 / 메이크업' → '뷰티/메이크업'."""
    s = re.sub(r"\s*[·ㆍ・/]\s*", "/", value.strip())
    return re.sub(r"\s+", " ", s)


def normalize_category(value) -> str | None:
    """표준 카테고리로 매핑되면 그 값, 아니면 None (원본 판단은 호출측)."""
    if not isinstance(value, str) or not value.strip():
        return None
    key = _category_key(value)
    if key in _CATEGORY_SET:
        return key
    return _CATEGORY_ALIASES.get(key)


def category_or_original(value, fallback: str = "기타") -> str:
    """임포트용: 표준으로 매핑되면 표준값, 안 되면 **원본 보존**, 비었으면 fallback."""
    if not isinstance(value, str) or not value.strip():
        return fallback
    return normalize_category(value) or value.strip()


# 필수 필드 정의: (model_attribute, display_label)
# spec 매핑: supply_price→supplier_price, marketing_copy→unique_selling_point, thumbnail_url→product_image
_REQUIRED_FIELDS = [
    ("name",                 "제품명"),
    ("price",                "가격"),
    ("supplier_price",       "공급가"),
    ("unique_selling_point", "마케팅 문구"),
    ("product_image",        "썸네일"),
    ("description",          "상세 설명"),
]


def validate_product_completeness(product) -> dict:
    """
    Product 객체(또는 dict)의 필수 필드를 검사하여 완성도를 반환.
    반환: {"is_complete": bool, "missing_fields": list[str]}
    """
    missing = []
    for attr, label in _REQUIRED_FIELDS:
        value = getattr(product, attr, None) if not isinstance(product, dict) else product.get(attr)
        if value is None:
            missing.append(label)
        elif isinstance(value, str) and not value.strip():
            missing.append(label)
        elif isinstance(value, (int, float)) and value == 0:
            missing.append(label)
    return {
        "is_complete": len(missing) == 0,
        "missing_fields": missing,
    }
