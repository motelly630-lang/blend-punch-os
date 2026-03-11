from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models import Product, Influencer, Campaign, Proposal
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
    product_count = db.query(func.count(Product.id)).scalar()
    influencer_count = db.query(func.count(Influencer.id)).scalar()
    campaign_count = db.query(func.count(Campaign.id)).scalar()
    proposal_count = db.query(func.count(Proposal.id)).scalar()

    active_campaigns = (
        db.query(Campaign)
        .filter(Campaign.status.in_(["active", "planning", "negotiating", "contracted"]))
        .order_by(Campaign.created_at.desc())
        .limit(5)
        .all()
    )
    recent_products = (
        db.query(Product).order_by(Product.created_at.desc()).limit(5).all()
    )
    recent_proposals = (
        db.query(Proposal).order_by(Proposal.created_at.desc()).limit(5).all()
    )

    return templates.TemplateResponse(
        "dashboard/index.html",
        {
            "request": request,
            "active_page": "dashboard",
            "current_user": current_user,
            "product_count": product_count,
            "influencer_count": influencer_count,
            "campaign_count": campaign_count,
            "proposal_count": proposal_count,
            "active_campaigns": active_campaigns,
            "recent_products": recent_products,
            "recent_proposals": recent_proposals,
        },
    )
