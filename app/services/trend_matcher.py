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


def match_score(product, event: dict) -> tuple[float, list[str]]:
    """
    Compute keyword match score between a product and a seasonal event.
    Returns (score 0.0–1.0, list_of_matched_keywords).
    """
    # Build product text corpus
    text = " ".join([
        _to_str(getattr(product, "name", "")),
        _to_str(getattr(product, "description", "")),
        _to_str(getattr(product, "category", "")),
        _to_str(getattr(product, "tags", "")),
        _to_str(getattr(product, "unique_selling_point", "")),
        _to_str(getattr(product, "key_benefits", "")),
    ]).lower()

    matched = [kw for kw in event["keywords"] if kw.lower() in text]

    # Also check product category against event product_categories
    cat_match = any(
        c.lower() in (product.category or "").lower()
        for c in event["product_categories"]
    )
    if cat_match and not matched:
        # Weak category match only — score 0.15
        return 0.15, []

    if not matched:
        return 0.0, []

    # Score: matched / threshold (threshold = 30% of keywords, min 1)
    threshold = max(len(event["keywords"]) * 0.3, 1)
    score = min(len(matched) / threshold, 1.0)
    return round(score, 3), matched


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
