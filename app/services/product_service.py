"""
product_service.py — 제품 비즈니스 로직
- validate_product_completeness: 필수 필드 완성도 검증
"""

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
