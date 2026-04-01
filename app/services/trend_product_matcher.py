"""
trend_product_matcher.py — 트렌드 ↔ 제품 매칭 서비스

매칭 알고리즘:
  1. 태그 교집합 기반 점수 (trend_tags ∩ product_tags)
  2. 키워드 확장 매핑 적용 (카테고리 → 관련 키워드)
  3. 카테고리 보정 점수
  최종: match_score = tag_score*0.5 + expanded_score*0.3 + category_bonus*0.2

분류 기준:
  match_score >= 0.30 → "matched"  → is_actionable=True
  match_score >= 0.10 → "similar"  → is_actionable=True
  else               → "none"     → needs_sourcing=True (trend_score>=6 시)

final_score = trend_score*0.5 + match_score*10*0.3 + season_score*0.2
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.models.trend import TrendItem

# ── 키워드 확장 매핑 ───────────────────────────────────────────────────────────
KEYWORD_EXPANSION: dict[str, list[str]] = {
    "다이어트": ["저당", "칼로리", "식단", "프로틴", "단백질", "저탄", "케토", "제로", "고단백", "다이어트"],
    "육아":    ["이유식", "아이간식", "유아", "영유아", "아기", "어린이", "키즈", "영아", "유아식"],
    "건강":    ["건강기능식품", "비타민", "영양제", "면역", "항산화", "미네랄", "오메가", "건강", "웰빙"],
    "뷰티":    ["스킨케어", "화장품", "성분", "보습", "미백", "세럼", "토너", "선크림", "클렌징", "뷰티"],
    "식품":    ["간편식", "밀키트", "반조리", "즉석", "먹거리", "식재료", "가공식품", "냉동식품"],
    "리빙":    ["인테리어", "홈데코", "생활용품", "홈", "리빙", "수납", "청소", "향초"],
    "주방":    ["조리도구", "주방용품", "소형가전", "쿡웨어", "냄비", "프라이팬", "주방", "조리기구"],
    "반려동물": ["펫푸드", "사료", "펫", "반려견", "반려묘", "강아지", "고양이", "펫간식", "동물"],
}

# 카테고리 유사 그룹 (교차 보정용)
CATEGORY_AFFINITY: dict[str, list[str]] = {
    "건강": ["다이어트", "식품"],
    "다이어트": ["건강", "식품"],
    "식품": ["건강", "다이어트", "주방"],
    "주방": ["식품", "리빙"],
    "리빙": ["주방"],
    "육아": ["식품"],
    "반려동물": [],
    "뷰티": [],
}

# 매칭 임계값
THRESHOLD_MATCHED = 0.30
THRESHOLD_SIMILAR = 0.10
SOURCING_MIN_SCORE = 6.0   # trend_score 이상일 때만 sourcing 분류


def _normalize(text: str) -> str:
    return text.strip().lower()


def _tokenize(vals: list[str] | None) -> set[str]:
    if not vals:
        return set()
    return {_normalize(v) for v in vals if v}


def _product_tokens(product) -> set[str]:
    """제품의 모든 텍스트 토큰 추출 (key_benefits + 이름 + 카테고리 + 브랜드 + description)."""
    tokens: set[str] = set()
    # key_benefits (JSON list[str])
    tokens |= _tokenize(getattr(product, "key_benefits", None) or [])
    # 제품명 단어 분리
    for word in (product.name or "").split():
        tokens.add(_normalize(word))
    # 카테고리, 브랜드
    tokens.add(_normalize(product.category or ""))
    tokens.add(_normalize(product.brand or ""))
    # description 첫 30단어
    for word in (product.description or "").split()[:30]:
        tokens.add(_normalize(word))
    return tokens


def _score_single_product(
    trend_tags: set[str],
    expanded_kw: set[str],
    trend_category: str,
    product,
) -> float:
    """제품 하나에 대한 매칭 점수 계산 (0.0~1.0)."""
    prod_tokens = _product_tokens(product)
    prod_category = _normalize(product.category or "")
    trend_cat = _normalize(trend_category)

    # 1) 태그 교집합 점수
    if trend_tags:
        tag_hit = len(trend_tags & prod_tokens)
        tag_score = min(tag_hit / len(trend_tags), 1.0)
    else:
        tag_score = 0.0

    # 2) 확장 키워드 점수
    if expanded_kw:
        exp_hit = len(expanded_kw & prod_tokens)
        exp_score = min(exp_hit / len(expanded_kw), 1.0)
    else:
        exp_score = 0.0

    # 3) 카테고리 보정
    affine = {trend_cat} | {_normalize(c) for c in CATEGORY_AFFINITY.get(trend_category, [])}
    category_bonus = 0.2 if prod_category in affine else 0.0

    score = tag_score * 0.5 + exp_score * 0.3 + category_bonus * 0.2
    return round(min(score, 1.0), 4)


def match_trend_to_products(
    db: "Session",
    trend: "TrendItem",
    company_id: int = 1,
    top_k: int = 5,
) -> dict:
    """
    TrendItem 하나에 대해 전체 제품 매칭 실행.
    반환값: {match_status, match_score, matched_products, is_actionable, needs_sourcing}
    """
    from app.models.product import Product

    products = (
        db.query(Product)
        .filter(
            Product.company_id == company_id,
            Product.is_archived == False,
        )
        .all()
    )

    trend_tags = _tokenize(trend.tags or [])
    expanded_kw = _tokenize(KEYWORD_EXPANSION.get(trend.category, []))

    scored = []
    for product in products:
        score = _score_single_product(trend_tags, expanded_kw, trend.category, product)
        if score >= THRESHOLD_SIMILAR:
            scored.append((score, product))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]

    best_score = top[0][0] if top else 0.0

    # 상태 분류
    if best_score >= THRESHOLD_MATCHED:
        match_status = "matched"
        is_actionable = True
        needs_sourcing = False
    elif best_score >= THRESHOLD_SIMILAR:
        match_status = "similar"
        is_actionable = True
        needs_sourcing = False
    else:
        match_status = "none"
        is_actionable = False
        needs_sourcing = (trend.trend_score or 0) >= SOURCING_MIN_SCORE

    matched_products = [
        {
            "product_id": p.id,
            "product_name": p.name,
            "brand": p.brand,
            "match_score": round(s, 4),
            "match_type": "exact" if s >= THRESHOLD_MATCHED else "similar",
            "product_image": p.product_image,
            "category": p.category,
        }
        for s, p in top
    ]

    return {
        "match_status": match_status,
        "match_score": best_score,
        "matched_products": matched_products,
        "is_actionable": is_actionable,
        "needs_sourcing": needs_sourcing,
    }


def compute_final_score(trend_score: float, match_score: float, season_score: float | None) -> float:
    """최종 점수 계산."""
    s = season_score or 0.0
    if s > 0:
        return round(trend_score * 0.5 + match_score * 10 * 0.3 + s * 0.2, 2)
    else:
        return round(trend_score * 0.5 + match_score * 10 * 0.5, 2)


def run_matching_for_trend(db: "Session", trend: "TrendItem") -> "TrendItem":
    """
    TrendItem 하나에 매칭 실행 후 DB 저장.
    ingest 시 자동 호출.
    """
    result = match_trend_to_products(db, trend, company_id=trend.company_id or 1)
    trend.match_status = result["match_status"]
    trend.match_score = result["match_score"]
    trend.matched_products = result["matched_products"]
    trend.is_actionable = result["is_actionable"]
    trend.needs_sourcing = result["needs_sourcing"]
    trend.final_score = compute_final_score(
        trend.trend_score or 5.0,
        result["match_score"],
        trend.season_score,
    )
    db.commit()
    return trend


def run_matching_all(db: "Session", company_id: int = 1) -> int:
    """전체 TrendItem 일괄 매칭 (수동 실행용)."""
    from app.models.trend import TrendItem
    items = db.query(TrendItem).filter(TrendItem.company_id == company_id).all()
    for item in items:
        run_matching_for_trend(db, item)
    return len(items)
