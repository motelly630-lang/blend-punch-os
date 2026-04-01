from datetime import date
from typing import Optional, List
from fastapi import APIRouter, Request, Depends, Header, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.models.trend_engine import TrendBriefing
from app.models.trend import TrendItem
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.auth.tenant import get_company_id
from app.services.season_matrix import SEASON_MATRIX, SEASON_LABELS
from app.services.trend_matcher import (
    get_upcoming_events,
    match_products_to_event,
    run_briefing,
)
from app.services.trend_product_matcher import run_matching_for_trend

router = APIRouter(prefix="/trends")
templates = Jinja2Templates(directory="app/templates")


# ── Claw 연동 스키마 ──────────────────────────────────────────────────────────

class ClawTrendPayload(BaseModel):
    name: str
    category: str
    score: float                        # 0~10 트렌드 점수
    source: Optional[str] = None        # instagram|naver|youtube 등
    source_url: Optional[str] = None
    summary: Optional[str] = None
    brands: Optional[List[str]] = None  # 연관 브랜드명 목록
    season: Optional[str] = None        # 2026-Q2 등
    tags: Optional[List[str]] = None
    collected_at: Optional[str] = None  # ISO 8601


def _verify_claw_token(authorization: Optional[str] = Header(None)):
    """Bearer 토큰 검증. .env의 CLAW_API_TOKEN과 일치해야 함."""
    token = settings.claw_api_token
    if not token:
        raise HTTPException(status_code=503, detail="Claw API token not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    if authorization[7:] != token:
        raise HTTPException(status_code=403, detail="Invalid token")


# ── POST /api/trends  (Claw → Blend Punch OS) ────────────────────────────────

@router.post("/api/ingest")
def claw_ingest_trend(
    payload: ClawTrendPayload,
    db: Session = Depends(get_db),
    _: None = Depends(_verify_claw_token),
):
    """
    Claw가 수집한 트렌드 데이터를 수신하여 TrendItem 테이블에 저장한다.
    name + season 조합이 이미 존재하면 업데이트(upsert), 없으면 신규 생성.
    """
    # upsert: 동일 name+season 항목 찾기
    existing = (
        db.query(TrendItem)
        .filter(
            TrendItem.title == payload.name,
            TrendItem.season == payload.season,
        )
        .first()
    )

    if existing:
        existing.trend_score = payload.score
        existing.summary = payload.summary or existing.summary
        existing.source_url = payload.source_url or existing.source_url
        existing.source = payload.source or existing.source
        existing.brands = payload.brands or existing.brands
        existing.tags = payload.tags or existing.tags
        existing.source_name = "Claw"
        db.commit()
        run_matching_for_trend(db, existing)
        return JSONResponse({"status": "updated", "trend_id": existing.id})

    item = TrendItem(
        company_id=1,
        title=payload.name,
        category=payload.category,
        trend_score=payload.score,
        source=payload.source,
        source_url=payload.source_url,
        summary=payload.summary,
        brands=payload.brands,
        season=payload.season,
        tags=payload.tags,
        source_name="Claw",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    run_matching_for_trend(db, item)
    return JSONResponse({"status": "created", "trend_id": item.id}, status_code=201)


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
        "active_page": "trends",
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
        "active_page": "trends",
        "current_user": current_user,
        "briefings": briefings,
    })
