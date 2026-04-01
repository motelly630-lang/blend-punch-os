from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.trend import TrendItem
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.auth.tenant import get_company_id
from app.services.trend_product_matcher import run_matching_all, run_matching_for_trend

router = APIRouter(prefix="/trends")
templates = Jinja2Templates(directory="app/templates")

CATEGORIES = ["식품", "주방", "리빙", "뷰티", "건강", "다이어트", "육아", "반려동물"]


# ── 루트 → 피드로 리다이렉트 ─────────────────────────────────────────────────
@router.get("")
def trend_root(current_user: User = Depends(get_current_user)):
    return RedirectResponse("/trends/feed", status_code=302)


# ── 피드 (전체 트렌드 Raw 데이터) ────────────────────────────────────────────
@router.get("/feed")
def trend_feed(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    category: str = "",
    status: str = "",
):
    cid = get_company_id(current_user)
    query = db.query(TrendItem).filter(TrendItem.company_id == cid)
    if category:
        query = query.filter(TrendItem.category == category)
    if status:
        query = query.filter(TrendItem.match_status == status)
    items = query.order_by(TrendItem.is_pinned.desc(), TrendItem.trend_score.desc()).all()

    all_items = db.query(TrendItem).filter(TrendItem.company_id == cid).all()
    return templates.TemplateResponse("trends/feed.html", {
        "request": request,
        "active_page": "trends",
        "current_user": current_user,
        "items": items,
        "categories": CATEGORIES,
        "selected_category": category,
        "selected_status": status,
        "total": len(all_items),
        "matched_count": sum(1 for i in all_items if i.match_status == "matched"),
        "similar_count": sum(1 for i in all_items if i.match_status == "similar"),
        "none_count": sum(1 for i in all_items if i.match_status == "none"),
        "actionable_count": sum(1 for i in all_items if i.is_actionable),
        "sourcing_count": sum(1 for i in all_items if i.needs_sourcing),
    })


# ── 실행 트렌드 (핵심 페이지) ────────────────────────────────────────────────
@router.get("/actionable")
def trend_actionable(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    category: str = "",
):
    cid = get_company_id(current_user)
    query = db.query(TrendItem).filter(
        TrendItem.company_id == cid,
        TrendItem.is_actionable == True,
    )
    if category:
        query = query.filter(TrendItem.category == category)
    items = query.order_by(TrendItem.final_score.desc().nullslast(), TrendItem.trend_score.desc()).all()

    return templates.TemplateResponse("trends/actionable.html", {
        "request": request,
        "active_page": "trends",
        "current_user": current_user,
        "items": items,
        "categories": CATEGORIES,
        "selected_category": category,
    })


# ── 소싱 필요 트렌드 ──────────────────────────────────────────────────────────
@router.get("/sourcing")
def trend_sourcing(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    category: str = "",
):
    cid = get_company_id(current_user)
    query = db.query(TrendItem).filter(
        TrendItem.company_id == cid,
        TrendItem.needs_sourcing == True,
    )
    if category:
        query = query.filter(TrendItem.category == category)
    items = query.order_by(TrendItem.trend_score.desc()).all()

    return templates.TemplateResponse("trends/sourcing.html", {
        "request": request,
        "active_page": "trends",
        "current_user": current_user,
        "items": items,
        "categories": CATEGORIES,
        "selected_category": category,
    })


# ── 트렌드 저장 ───────────────────────────────────────────────────────────────
@router.post("/save")
def trend_save(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    category: str = Form(...),
    title: str = Form(...),
    summary: str = Form(""),
    source_url: str = Form(""),
    trend_score: float = Form(5.0),
    tags_raw: str = Form(""),
):
    cid = get_company_id(current_user)
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    item = TrendItem(
        company_id=cid,
        category=category, title=title, summary=summary or None,
        source_url=source_url or None, trend_score=trend_score,
        tags=tags or None,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    run_matching_for_trend(db, item)
    return RedirectResponse("/trends/feed", status_code=302)


# ── 매칭 수동 실행 ────────────────────────────────────────────────────────────
@router.post("/match/run")
def trend_match_run(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = get_company_id(current_user)
    count = run_matching_all(db, company_id=cid)
    return RedirectResponse(f"/trends/feed?msg={count}개+트렌드+매칭+완료", status_code=302)


# ── 트렌드 삭제 ───────────────────────────────────────────────────────────────
@router.post("/{item_id}/delete")
def trend_delete(
    item_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = get_company_id(current_user)
    item = db.query(TrendItem).filter(TrendItem.id == item_id, TrendItem.company_id == cid).first()
    if item:
        db.delete(item)
        db.commit()
    return RedirectResponse("/trends/feed", status_code=302)
