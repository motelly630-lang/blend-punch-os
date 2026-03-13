from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models import Product, Influencer, Campaign, Proposal
from app.models.settlement import Settlement
from app.models.user import User
from app.auth.dependencies import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.now()

    # ── Basic counts ──────────────────────────────────────────────────────────
    product_count = db.query(func.count(Product.id)).scalar()
    influencer_count = db.query(func.count(Influencer.id)).scalar()
    campaign_count = db.query(func.count(Campaign.id)).scalar()
    proposal_count = db.query(func.count(Proposal.id)).scalar()

    # ── Revenue KPIs (SQL aggregates — no full table loads) ───────────────────
    total_revenue = db.query(func.sum(Campaign.actual_revenue)).filter(
        Campaign.status == "completed"
    ).scalar() or 0

    active_revenue = db.query(func.sum(Campaign.actual_revenue)).filter(
        Campaign.status == "active"
    ).scalar() or 0

    this_month = now.strftime("%Y-%m")
    monthly_revenue = db.query(func.sum(Campaign.actual_revenue)).filter(
        Campaign.status == "completed",
        func.strftime("%Y-%m", Campaign.updated_at) == this_month,
    ).scalar() or 0

    total_seller_commission = db.query(func.sum(Campaign.seller_commission_amount)).filter(
        Campaign.status == "completed"
    ).scalar() or 0

    # ── Settlement KPIs (SQL aggregates) ─────────────────────────────────────
    pending_amount = db.query(func.sum(Settlement.final_payment)).filter(
        Settlement.status == "pending"
    ).scalar() or 0
    confirmed_amount = db.query(func.sum(Settlement.final_payment)).filter(
        Settlement.status == "confirmed"
    ).scalar() or 0
    paid_amount = db.query(func.sum(Settlement.final_payment)).filter(
        Settlement.status == "paid"
    ).scalar() or 0
    pending_count = db.query(func.count(Settlement.id)).filter(
        Settlement.status == "pending"
    ).scalar() or 0
    confirmed_count = db.query(func.count(Settlement.id)).filter(
        Settlement.status == "confirmed"
    ).scalar() or 0

    # ── Monthly revenue trend (last 6 months, single GROUP BY query) ──────────
    monthly_raw = db.query(
        func.strftime("%Y-%m", Campaign.updated_at).label("ym"),
        func.sum(Campaign.actual_revenue).label("rev"),
    ).filter(
        Campaign.status == "completed",
        Campaign.actual_revenue.isnot(None),
    ).group_by("ym").all()

    monthly_by_ym = {row.ym: (row.rev or 0) for row in monthly_raw}

    monthly_trend = []
    for i in range(5, -1, -1):
        target = (now.replace(day=1) - timedelta(days=i * 28)).replace(day=1)
        label = target.strftime("%Y-%m")
        display = target.strftime("%-m월")
        monthly_trend.append({"month": display, "revenue": monthly_by_ym.get(label, 0)})

    max_trend_rev = max((m["revenue"] for m in monthly_trend), default=1) or 1

    # ── Top products by revenue (SQL GROUP BY) ────────────────────────────────
    top_raw = db.query(
        Campaign.product_id,
        func.sum(Campaign.actual_revenue).label("total_rev"),
    ).filter(
        Campaign.status == "completed",
        Campaign.product_id.isnot(None),
        Campaign.actual_revenue.isnot(None),
    ).group_by(Campaign.product_id).order_by(
        func.sum(Campaign.actual_revenue).desc()
    ).limit(5).all()

    top_products = []
    for row in top_raw:
        p = db.query(Product).filter(Product.id == row.product_id).first()
        if p:
            top_products.append({"product": p, "revenue": row.total_rev or 0})

    # ── Active campaigns ──────────────────────────────────────────────────────
    active_campaigns = (
        db.query(Campaign)
        .filter(Campaign.status.in_(["active", "planning", "negotiating", "contracted"]))
        .order_by(Campaign.created_at.desc())
        .limit(5)
        .all()
    )

    # ── Recent products ───────────────────────────────────────────────────────
    recent_products = db.query(Product).order_by(Product.created_at.desc()).limit(5).all()

    return templates.TemplateResponse(
        "dashboard/index.html",
        {
            "request": request,
            "active_page": "dashboard",
            "current_user": current_user,
            # Counts
            "product_count": product_count,
            "influencer_count": influencer_count,
            "campaign_count": campaign_count,
            "proposal_count": proposal_count,
            # Revenue KPIs
            "total_revenue": total_revenue,
            "monthly_revenue": monthly_revenue,
            "active_revenue": active_revenue,
            "total_seller_commission": total_seller_commission,
            # Settlement KPIs
            "pending_amount": pending_amount,
            "confirmed_amount": confirmed_amount,
            "paid_amount": paid_amount,
            "pending_count": pending_count,
            "confirmed_count": confirmed_count,
            # Trend
            "monthly_trend": monthly_trend,
            "max_trend_rev": max_trend_rev,
            # Top products
            "top_products": top_products,
            # Lists
            "active_campaigns": active_campaigns,
            "recent_products": recent_products,
        },
    )
