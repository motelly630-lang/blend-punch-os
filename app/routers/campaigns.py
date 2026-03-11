from datetime import date
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Campaign, Product, Influencer
from app.models.user import User
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/campaigns")
templates = Jinja2Templates(directory="app/templates")

STATUSES = [
    ("planning", "기획중"),
    ("negotiating", "협의중"),
    ("contracted", "계약완료"),
    ("active", "진행중"),
    ("completed", "완료"),
    ("cancelled", "취소"),
]


@router.get("")
def campaign_list(request: Request, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    campaigns = db.query(Campaign).order_by(Campaign.created_at.desc()).all()
    # dashboard counts
    active_count = sum(1 for c in campaigns if c.status == "active")
    planning_count = sum(1 for c in campaigns if c.status in ("planning", "negotiating", "contracted"))
    done_count = sum(1 for c in campaigns if c.status == "completed")
    return templates.TemplateResponse("campaigns/list.html", {
        "request": request, "active_page": "campaigns", "current_user": current_user,
        "campaigns": campaigns,
        "active_count": active_count, "planning_count": planning_count, "done_count": done_count,
    })


@router.get("/new")
def campaign_new(request: Request, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user),
                 product_id: str = "", influencer_id: str = ""):
    products = db.query(Product).filter(Product.status != "archived").order_by(Product.name).all()
    influencers = db.query(Influencer).filter(Influencer.status == "active").order_by(Influencer.name).all()
    return templates.TemplateResponse("campaigns/form.html", {
        "request": request, "active_page": "campaigns", "current_user": current_user,
        "campaign": None, "products": products, "influencers": influencers, "statuses": STATUSES,
        "prefill_product_id": product_id, "prefill_influencer_id": influencer_id,
    })


@router.post("/new")
def campaign_create(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    name: str = Form(...),
    product_id: str = Form(""),
    influencer_id: str = Form(""),
    status: str = Form("planning"),
    start_date: str = Form(""),
    end_date: str = Form(""),
    commission_rate: float = Form(0.15),
    expected_sales: int = Form(0),
    actual_sales: int = Form(0),
    actual_revenue: float = Form(0.0),
    notes: str = Form(""),
):
    def parse_date(s):
        try:
            return date.fromisoformat(s) if s else None
        except ValueError:
            return None

    campaign = Campaign(
        name=name,
        product_id=product_id or None,
        influencer_id=influencer_id or None,
        status=status,
        start_date=parse_date(start_date),
        end_date=parse_date(end_date),
        commission_rate=commission_rate,
        expected_sales=expected_sales,
        actual_sales=actual_sales,
        actual_revenue=actual_revenue,
        notes=notes or None,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return RedirectResponse(f"/campaigns/{campaign.id}?msg=캠페인이+생성되었습니다", status_code=302)


@router.get("/{campaign_id}")
def campaign_detail(campaign_id: str, request: Request, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        return RedirectResponse("/campaigns?err=캠페인을+찾을+수+없습니다", status_code=302)
    return templates.TemplateResponse("campaigns/detail.html", {
        "request": request, "active_page": "campaigns", "current_user": current_user,
        "campaign": campaign,
    })


@router.get("/{campaign_id}/edit")
def campaign_edit(campaign_id: str, request: Request, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        return RedirectResponse("/campaigns", status_code=302)
    products = db.query(Product).filter(Product.status != "archived").order_by(Product.name).all()
    influencers = db.query(Influencer).filter(Influencer.status == "active").order_by(Influencer.name).all()
    return templates.TemplateResponse("campaigns/form.html", {
        "request": request, "active_page": "campaigns", "current_user": current_user,
        "campaign": campaign, "products": products, "influencers": influencers, "statuses": STATUSES,
    })


@router.post("/{campaign_id}/edit")
def campaign_update(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    name: str = Form(...),
    product_id: str = Form(""),
    influencer_id: str = Form(""),
    status: str = Form("planning"),
    start_date: str = Form(""),
    end_date: str = Form(""),
    commission_rate: float = Form(0.15),
    expected_sales: int = Form(0),
    actual_sales: int = Form(0),
    actual_revenue: float = Form(0.0),
    notes: str = Form(""),
):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        return RedirectResponse("/campaigns", status_code=302)

    def parse_date(s):
        try:
            return date.fromisoformat(s) if s else None
        except ValueError:
            return None

    campaign.name = name
    campaign.product_id = product_id or None
    campaign.influencer_id = influencer_id or None
    campaign.status = status
    campaign.start_date = parse_date(start_date)
    campaign.end_date = parse_date(end_date)
    campaign.commission_rate = commission_rate
    campaign.expected_sales = expected_sales
    campaign.actual_sales = actual_sales
    campaign.actual_revenue = actual_revenue
    campaign.notes = notes or None
    db.commit()
    return RedirectResponse(f"/campaigns/{campaign_id}?msg=수정되었습니다", status_code=302)


@router.post("/{campaign_id}/delete")
def campaign_delete(campaign_id: str, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if campaign:
        db.delete(campaign)
        db.commit()
    return RedirectResponse("/campaigns?msg=삭제되었습니다", status_code=302)
