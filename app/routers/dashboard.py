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
    # ── Basic counts ──────────────────────────────────────────────────────────
    product_count = db.query(func.count(Product.id)).scalar()
    influencer_count = db.query(func.count(Influencer.id)).scalar()
    campaign_count = db.query(func.count(Campaign.id)).scalar()
    proposal_count = db.query(func.count(Proposal.id)).scalar()

    # ── Revenue KPIs ──────────────────────────────────────────────────────────
    all_campaigns = db.query(Campaign).all()
    completed = [c for c in all_campaigns if c.status == "completed"]
    active_now = [c for c in all_campaigns if c.status == "active"]

    total_revenue = sum(c.actual_revenue or 0 for c in completed)
    active_revenue = sum(c.actual_revenue or 0 for c in active_now)

    # This month
    now = datetime.now()
    this_month = now.strftime("%Y-%m")
    monthly_revenue = sum(
        c.actual_revenue or 0 for c in completed
        if c.updated_at and c.updated_at.strftime("%Y-%m") == this_month
    )

    # Total seller commission paid out
    total_seller_commission = sum(c.seller_commission_amount or 0 for c in completed)

    # ── Settlement KPIs ───────────────────────────────────────────────────────
    all_settlements = db.query(Settlement).all()
    pending_amount = sum(s.final_payment or 0 for s in all_settlements if s.status == "pending")
    confirmed_amount = sum(s.final_payment or 0 for s in all_settlements if s.status == "confirmed")
    paid_amount = sum(s.final_payment or 0 for s in all_settlements if s.status == "paid")
    pending_count = sum(1 for s in all_settlements if s.status == "pending")
    confirmed_count = sum(1 for s in all_settlements if s.status == "confirmed")

    # ── Monthly revenue trend (last 6 months) ─────────────────────────────────
    monthly_trend = []
    for i in range(5, -1, -1):
        # Go back i months from current month
        target = (now.replace(day=1) - timedelta(days=i * 28)).replace(day=1)
        label = target.strftime("%Y-%m")
        display = target.strftime("%-m월")
        rev = sum(
            c.actual_revenue or 0 for c in completed
            if c.updated_at and c.updated_at.strftime("%Y-%m") == label
        )
        monthly_trend.append({"month": display, "revenue": rev})

    max_trend_rev = max((m["revenue"] for m in monthly_trend), default=1) or 1

    # ── Top products by revenue ────────────────────────────────────────────────
    product_revenue: dict = {}
    for c in completed:
        if c.product_id and c.actual_revenue:
            product_revenue[c.product_id] = product_revenue.get(c.product_id, 0) + c.actual_revenue
    top_product_ids = sorted(product_revenue, key=lambda x: -product_revenue[x])[:5]
    top_products = []
    for pid in top_product_ids:
        p = db.query(Product).filter(Product.id == pid).first()
        if p:
            top_products.append({"product": p, "revenue": product_revenue[pid]})

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
