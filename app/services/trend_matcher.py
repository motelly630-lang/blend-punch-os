"""
Trend Matcher — product auto-matching + daily briefing runner.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import TYPE_CHECKING

from app.services.season_matrix import SEASON_MATRIX

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# ── Date helpers ──────────────────────────────────────────────────────────────

def _this_year_peak(event: dict, ref: date) -> date:
    """Return the peak date for this year; if already past >60 days, return next year."""
    try:
        peak = date(ref.year, event["peak_month"], event["peak_day"])
    except ValueError:
        peak = date(ref.year, event["peak_month"], 28)  # safe fallback for Feb

    # If peak was more than 60 days ago, use next year's occurrence
    if (ref - peak).days > 60:
        try:
            peak = date(ref.year + 1, event["peak_month"], event["peak_day"])
        except ValueError:
            peak = date(ref.year + 1, event["peak_month"], 28)
    return peak


def days_until_peak(event: dict, ref: date | None = None) -> int:
    ref = ref or date.today()
    return ((_this_year_peak(event, ref)) - ref).days


def days_until_prep(event: dict, ref: date | None = None) -> int:
    """Days until preparation should start (peak - lead_time). Negative = already past prep date."""
    ref = ref or date.today()
    peak = _this_year_peak(event, ref)
    prep_start = peak - timedelta(days=event["lead_time_days"])
    return (prep_start - ref).days


def get_upcoming_events(window_days: int = 90, ref: date | None = None) -> list[dict]:
    """
    Return events whose prep-start window falls within the next `window_days` days.
    Also includes events already in prep window (prep_delta <= 0, peak_delta > 0).
    Sorted by peak date ascending.
    """
    ref = ref or date.today()
    result = []
    for event in SEASON_MATRIX:
        prep_delta = days_until_prep(event, ref)
        peak_delta = days_until_peak(event, ref)
        # Show if: prep starts within window OR already in prep period (past prep start but peak still ahead)
        if -event["lead_time_days"] <= prep_delta <= window_days and peak_delta > -14:
            result.append({
                **event,
                "prep_delta": prep_delta,   # days until prep start (negative = already in prep)
                "peak_delta": peak_delta,   # days until peak
                "peak_date": _this_year_peak(event, ref).isoformat(),
                "prep_date": (_this_year_peak(event, ref) - timedelta(days=event["lead_time_days"])).isoformat(),
            })
    result.sort(key=lambda e: e["peak_date"])
    return result


# ── Product matching ──────────────────────────────────────────────────────────

def _to_str(val) -> str:
    """Safely convert any field value to a string for text matching."""
    if val is None:
        return ""
    if isinstance(val, list):
        return " ".join(str(v) for v in val)
    return str(val)


# 시즌표의 큰 분류 → OS 제품 카테고리 (PRODUCT_CATEGORIES + 운영에 실제로 쓰는 값)
CATEGORY_GROUPS = {
    "뷰티": {"스킨케어", "뷰티/메이크업", "헤어케어", "바디케어"},
    "리빙": {"생활용품", "주방용품", "욕실용품", "홈/인테리어", "가전제품"},
    "가전": {"가전제품"},
    "주방": {"주방용품"},
    "식품": {"식품/음료", "건강기능식품"},
    "건강": {"건강기능식품", "바디케어"},
    "다이어트": {"다이어트/슬리밍", "건강기능식품", "식품/음료"},
    "육아": {"유아/육아용품", "유아/육아"},
    "패션": {"패션잡화"},
}
for _en, _ko in (("beauty", "뷰티"), ("living", "리빙"), ("home", "리빙"), ("lifestyle", "리빙"), ("food", "식품"),
                 ("health", "건강"), ("diet", "다이어트"), ("kids", "육아"), ("fashion", "패션")):
    CATEGORY_GROUPS[_en] = CATEGORY_GROUPS[_ko]


def category_fits(product_category: str, event: dict) -> bool:
    """제품 카테고리가 시즌의 분류에 들어가는가 (분류 이름이 그대로 들어 있어도 인정 — 예전 규칙)."""
    cat = (product_category or "").strip()
    if not cat:
        return False
    for c in event.get("product_categories") or []:
        if cat in CATEGORY_GROUPS.get(c, set()) or c.lower() in cat.lower():
            return True
    return False


def match_score(product, event: dict) -> tuple[float, list[str]]:
    """
    Compute keyword match score between a product and a seasonal event.
    Returns (score 0.0–1.0, list_of_matched_keywords).

    2026-09-26 개선 (운영 사례: '환절기 보습' 에 냉감 패드·욕실화·콜드브루가 설명의 '건조' 한 단어로 붙었다):
    - 제품 **이름**에 키워드가 있으면 강한 매칭 (분류가 다르면 0.6배)
    - **태그·설명**에만 있으면 분류가 맞을 때만, 절반 무게로
    - 키워드 없이 분류만 맞는 약한 매칭(0.15)은 예전 규칙 그대로 (분류 이름이 제품 분류에 그대로 들어 있을 때)
    """
    # 태그는 운영 데이터에 엉뚱한 단어가 많아(냉감 패드 태그에 '건조'·'수분') 설명과 같은 약한 무게로 본다
    title = _to_str(getattr(product, "name", "")).lower()
    body = " ".join([
        _to_str(getattr(product, "tags", "")),
        _to_str(getattr(product, "description", "")),
        _to_str(getattr(product, "unique_selling_point", "")),
        _to_str(getattr(product, "key_benefits", "")),
    ]).lower()
    kws = [kw for kw in event["keywords"]]
    name_hits = [kw for kw in kws if kw.lower() in title]
    desc_hits = [kw for kw in kws if kw not in name_hits and kw.lower() in body]
    fits = category_fits(getattr(product, "category", "") or "", event)
    threshold = max(len(kws) * 0.3, 1)

    if name_hits:
        score = min((len(name_hits) + 0.5 * len(desc_hits)) / threshold, 1.0)
        if not fits:
            score *= 0.6
        return round(score, 3), name_hits + desc_hits
    if desc_hits and fits:
        return round(min(0.5 * len(desc_hits) / threshold, 1.0), 3), desc_hits

    old_cat_match = any(c.lower() in (getattr(product, "category", "") or "").lower()
                        for c in event["product_categories"])
    if old_cat_match:
        return 0.15, []   # Weak category match only — score 0.15
    return 0.0, []


def match_products_to_event(db: "Session", event: dict, min_score: float = 0.15) -> list[dict]:
    """
    Query active products and return those that match the event.
    """
    from app.models.product import Product

    products = (
        db.query(Product)
        .filter(Product.status == "active")
        .all()
    )
    results = []
    for p in products:
        score, kws = match_score(p, event)
        if score >= min_score:
            results.append({
                "product_id": p.id,
                "product_name": p.name,
                "product_brand": p.brand or "",
                "category": p.category or "",
                "score": score,
                "matched_keywords": kws,
                # 이름에 시즌 키워드가 있는 '딱 맞는' 제품인가 — 보고에는 이것만 추천으로 보여준다
                "name_match": any(k.lower() in (p.name or "").lower() for k in event["keywords"]),
                "consumer_price": p.consumer_price or p.price or 0,
            })
    results.sort(key=lambda x: -x["score"])
    return results[:10]  # top 10 per event


# ── Briefing runner ───────────────────────────────────────────────────────────

def run_briefing(db: "Session") -> "TrendBriefing":  # noqa: F821
    """
    Run the daily briefing: match all upcoming events to products,
    save a TrendBriefing record, and return it.
    """
    from app.models.trend_engine import TrendBriefing

    today = date.today()
    upcoming = get_upcoming_events(window_days=90, ref=today)

    report_events = []
    total_matches = 0

    for event in upcoming:
        matches = match_products_to_event(db, event)
        total_matches += len(matches)
        report_events.append({
            "key": event["key"],
            "name": event["name"],
            "season": event["season"],
            "prep_delta": event["prep_delta"],
            "peak_delta": event["peak_delta"],
            "peak_date": event["peak_date"],
            "prep_date": event["prep_date"],
            "trend_score": event["trend_score"],
            "description": event.get("description", ""),
            "keywords": event["keywords"],
            "matched_products": matches,
        })

    briefing = TrendBriefing(
        report_date=today.isoformat(),
        event_count=len(upcoming),
        product_match_count=total_matches,
        report_data=report_events,
    )
    db.add(briefing)
    db.commit()
    db.refresh(briefing)
    return briefing
