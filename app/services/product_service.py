"""
product_service.py — 제품 비즈니스 로직
- validate_product_completeness: 필수 필드 완성도 검증
- normalize_status / normalize_visibility: 코드값 정규화
"""

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
