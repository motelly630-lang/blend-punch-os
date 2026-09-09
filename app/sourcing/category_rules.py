"""카테고리 기준 자동 규칙 — 추천 커미션율 + 소비자 카테고리 태그 기본값.

소비자 카테고리 태그는 아래 고정 8개 안에서만 사용한다.
(실제 정책은 운영하며 조정 — 여기 상수만 수정)
"""
from __future__ import annotations

DEFAULT_COMMISSION = 0.15

# 소비자 카테고리 태그 — 이 8개만 허용
ALLOWED_CONSUMER_TAGS = ["식품", "주방", "리빙", "뷰티", "건강", "다이어트", "육아", "반려동물"]
_ALLOWED_SET = set(ALLOWED_CONSUMER_TAGS)

# (키워드들, 추천커미션율, 소비자 태그[허용 8개 내])
_RULES = [
    (["화장품", "스킨", "뷰티", "코스메", "세럼", "크림", "로션", "선크림", "클렌징", "마스크팩"], 0.20, ["뷰티"]),
    (["다이어트", "체지방", "슬리밍", "다욧"], 0.18, ["다이어트", "건강"]),
    (["건강기능식품", "건기식", "영양제", "유산균", "비타민", "오메가", "프로바이오틱스", "콜라겐"], 0.18, ["건강"]),
    (["식품", "음료", "간식", "과자", "즙", "차", "요거트", "그릭"], 0.15, ["식품"]),
    (["주방", "용기", "유청", "조리", "쿡", "도마", "냄비", "분리기"], 0.15, ["주방", "리빙"]),
    (["생활가전", "가전", "전자", "가습기", "청소기"], 0.12, ["리빙"]),
    (["유아", "키즈", "베이비", "아기", "기저귀"], 0.18, ["육아"]),
    (["반려", "펫", "강아지", "고양이", "사료"], 0.18, ["반려동물"]),
    (["리빙", "인테리어", "홈", "수납", "가구", "침구"], 0.15, ["리빙"]),
]


def _hit(category: str, name: str = "") -> tuple | None:
    hay = f"{category or ''} {name or ''}"
    for keywords, rate, tags in _RULES:
        if any(k in hay for k in keywords):
            return rate, tags
    return None


def recommended_commission(category: str, name: str = "") -> float:
    hit = _hit(category, name)
    return hit[0] if hit else DEFAULT_COMMISSION


def consumer_tags(category: str, name: str = "") -> list[str]:
    hit = _hit(category, name)
    return list(hit[1]) if hit else []


def filter_tags(tags: list[str]) -> list[str]:
    """허용 8개만 남기고 중복 제거."""
    return [t for t in dict.fromkeys(tags or []) if t in _ALLOWED_SET]
