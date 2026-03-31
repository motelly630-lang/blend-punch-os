from datetime import date
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.trend_engine import TrendBriefing
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.auth.tenant import get_company_id
from app.services.season_matrix import SEASON_MATRIX, SEASON_LABELS
from app.services.trend_matcher import (
    get_upcoming_events,
    match_products_to_event,
    run_briefing,
)

router = APIRouter(prefix="/trends")
templates = Jinja2Templates(directory="app/templates")


@router.get("/engine")
def engine_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = date.today()
    upcoming = get_upcoming_events(window_days=90, ref=today)

    # Live product matches for each upcoming event
    engine_events = []
    for event in upcoming:
        matches = match_products_to_event(db, event)
        engine_events.append({**event, "matched_products": matches})

    cid = get_company_id(current_user)
    # Latest briefings archive (last 10)
    briefings = (
        db.query(TrendBriefing)
        .filter(TrendBriefing.company_id == cid)
        .order_by(TrendBriefing.created_at.desc())
        .limit(10)
        .all()
    )

    # Full season matrix with D-day info for reference panel
    all_events = []
    for event in SEASON_MATRIX:
        from app.services.trend_matcher import days_until_prep, days_until_peak, _this_year_peak
        from datetime import timedelta
        prep_delta = days_until_prep(event, today)
        peak_delta = days_until_peak(event, today)
        peak_dt = _this_year_peak(event, today)
        all_events.append({
            **event,
            "prep_delta": prep_delta,
            "peak_delta": peak_delta,
            "peak_date": peak_dt.isoformat(),
            "prep_date": (peak_dt - timedelta(days=event["lead_time_days"])).isoformat(),
        })
    all_events.sort(key=lambda e: e["peak_date"])

    return templates.TemplateResponse("trends/engine.html", {
        "request": request,
        "active_page": "trend_engine",
        "current_user": current_user,
        "engine_events": engine_events,
        "all_events": all_events,
        "briefings": briefings,
        "season_labels": SEASON_LABELS,
        "today": today.isoformat(),
        "total_events": len(SEASON_MATRIX),
    })


@router.post("/engine/run")
def engine_run_briefing(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually trigger the daily briefing job."""
    briefing = run_briefing(db)
    return RedirectResponse(
        f"/trends/engine?msg=브리핑+완료+({briefing.event_count}개+이벤트+{briefing.product_match_count}개+매칭)",
        status_code=302,
    )


@router.get("/briefings")
def briefings_archive(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = get_company_id(current_user)
    briefings = (
        db.query(TrendBriefing)
        .filter(TrendBriefing.company_id == cid)
        .order_by(TrendBriefing.created_at.desc())
        .all()
    )
    return templates.TemplateResponse("trends/briefings.html", {
        "request": request,
        "active_page": "trend_engine",
        "current_user": current_user,
        "briefings": briefings,
    })
