import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Campaign, Product, Influencer
from app.models.settlement import Settlement
from app.models.user import User
from app.auth.dependencies import get_current_user

KST = ZoneInfo("Asia/Seoul")


def _kst_today() -> date:
    return datetime.now(KST).date()


def _auto_status(c: Campaign, today: date) -> str:
    """Compute KST-based status from dates. Cancelled is never overridden."""
    if c.status == "cancelled":
        return "cancelled"
    if c.start_date and c.end_date:
        if today < c.start_date:
            return "planning"
        elif today <= c.end_date:
            return "active"
        else:
            return "completed"
    if c.start_date and today >= c.start_date:
        return "active"
    return c.status


def _run_archiving(db: Session):
    """Auto-archive campaigns whose end_date month < current KST month,
    sync KST-based status to DB, and auto-create settlements for completed campaigns."""
    today = _kst_today()
    first_of_month = today.replace(day=1)

    all_active = db.query(Campaign).filter(Campaign.is_archived == False).all()
    changed = False
    newly_completed = []
    for c in all_active:
        new_status = _auto_status(c, today)
        if c.status != new_status:
            c.status = new_status
            changed = True
            if new_status == "completed":
                newly_completed.append(c)
        if c.end_date and c.end_date < first_of_month:
            c.is_archived = True
            changed = True
    if changed:
        db.commit()
    for c in newly_completed:
        _auto_settle(db, c)
    if newly_completed:
        db.commit()

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
                  current_user: User = Depends(get_current_user),
                  tab: str = "active"):
    _run_archiving(db)
    # Backfill: create settlements for existing completed campaigns that have none
    completed_no_settlement = db.query(Campaign).filter(
        Campaign.status == "completed",
        Campaign.influencer_id.isnot(None),
        ~Campaign.id.in_(db.query(Settlement.campaign_id).filter(Settlement.campaign_id.isnot(None)))
    ).all()
    if completed_no_settlement:
        for c in completed_no_settlement:
            _auto_settle(db, c)
        db.commit()
    today = _kst_today()

    if tab == "archive":
        campaigns = db.query(Campaign).filter(Campaign.is_archived == True).order_by(Campaign.end_date.desc()).all()
    else:
        campaigns = db.query(Campaign).filter(Campaign.is_archived == False).order_by(Campaign.start_date.asc().nullslast()).all()

    # Compute auto-status per campaign (KST-based, display only)
    status_map = {c.id: _auto_status(c, today) for c in campaigns}

    active_count   = sum(1 for s in status_map.values() if s == "active")
    planning_count = sum(1 for s in status_map.values() if s in ("planning", "negotiating", "contracted"))
    done_count     = sum(1 for s in status_map.values() if s in ("completed", "cancelled"))
    archive_count  = db.query(Campaign).filter(Campaign.is_archived == True).count()

    # Calendar JSON — only campaigns with dates
    cal_data = []
    for c in campaigns:
        if c.start_date:
            cal_data.append({
                "id": c.id,
                "name": c.name,
                "start": c.start_date.isoformat(),
                "end": (c.end_date or c.start_date).isoformat(),
                "status": status_map[c.id],
            })

    return templates.TemplateResponse("campaigns/list.html", {
        "request": request, "active_page": "campaigns", "current_user": current_user,
        "campaigns": campaigns, "status_map": status_map, "today": today, "tab": tab,
        "active_count": active_count, "planning_count": planning_count,
        "done_count": done_count, "archive_count": archive_count,
        "cal_json": json.dumps(cal_data, ensure_ascii=False),
    })


@router.get("/new")
def campaign_new(request: Request, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user),
                 product_id: str = "", influencer_id: str = ""):
    products = db.query(Product).filter(Product.status != "archived").order_by(Product.name).limit(300).all()
    influencers = db.query(Influencer).filter(Influencer.status == "active").order_by(Influencer.name).limit(300).all()
    return templates.TemplateResponse("campaigns/form.html", {
        "request": request, "active_page": "campaigns", "current_user": current_user,
        "campaign": None, "products": products, "influencers": influencers, "statuses": STATUSES,
        "prefill_product_id": product_id, "prefill_influencer_id": influencer_id,
    })


def _parse_date(s):
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def _auto_settle(db: Session, campaign: Campaign):
    """Create a draft Settlement when campaign completes (if none exists yet)."""
    if not campaign.influencer_id:
        return
    existing = db.query(Settlement).filter_by(campaign_id=campaign.id).first()
    if existing:
        return
    inf = db.query(Influencer).filter_by(id=campaign.influencer_id).first()
    seller_rate = campaign.seller_commission_rate or campaign.commission_rate or 0.0
    commission_amt = round((campaign.actual_revenue or 0) * seller_rate)
    tax_rate = 0.033 if (inf and inf.business_type == "프리랜서") else 0.0
    tax_amt = round(commission_amt * tax_rate)
    s = Settlement(
        influencer_id=campaign.influencer_id,
        campaign_id=campaign.id,
        period_label=datetime.now().strftime("%Y년 %m월"),
        seller_type=(inf.business_type if inf and inf.business_type else "사업자"),
        sales_amount=campaign.actual_revenue or 0,
        commission_rate=seller_rate,
        commission_amount=commission_amt,
        tax_rate=tax_rate,
        tax_amount=tax_amt,
        final_payment=commission_amt - tax_amt,
        status="pending",
        notes="캠페인 완료 시 자동 생성",
    )
    db.add(s)


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
    unit_price: float = Form(0.0),
    seller_commission_rate_pct: float = Form(0.0),
    vendor_commission_rate_pct: float = Form(0.0),
    expected_sales: int = Form(0),
    actual_sales: int = Form(0),
    actual_revenue: float = Form(0.0),
    notes: str = Form(""),
):
    seller_rate = seller_commission_rate_pct / 100 if seller_commission_rate_pct else 0.0
    vendor_rate = vendor_commission_rate_pct / 100 if vendor_commission_rate_pct else 0.0
    seller_amt = round(actual_revenue * seller_rate)
    vendor_amt = round(actual_revenue * vendor_rate)

    campaign = Campaign(
        name=name,
        product_id=product_id or None,
        influencer_id=influencer_id or None,
        status=status,
        start_date=_parse_date(start_date),
        end_date=_parse_date(end_date),
        commission_rate=commission_rate,
        unit_price=unit_price,
        seller_commission_rate=seller_rate,
        vendor_commission_rate=vendor_rate,
        seller_commission_amount=seller_amt,
        vendor_commission_amount=vendor_amt,
        expected_sales=expected_sales,
        actual_sales=actual_sales,
        actual_revenue=actual_revenue,
        notes=notes or None,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    if status == "completed":
        _auto_settle(db, campaign)
        db.commit()
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
    products = db.query(Product).filter(Product.status != "archived").order_by(Product.name).limit(300).all()
    influencers = db.query(Influencer).filter(Influencer.status == "active").order_by(Influencer.name).limit(300).all()
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
    unit_price: float = Form(0.0),
    seller_commission_rate_pct: float = Form(0.0),
    vendor_commission_rate_pct: float = Form(0.0),
    expected_sales: int = Form(0),
    actual_sales: int = Form(0),
    actual_revenue: float = Form(0.0),
    notes: str = Form(""),
):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        return RedirectResponse("/campaigns", status_code=302)

    prev_status = campaign.status
    seller_rate = seller_commission_rate_pct / 100 if seller_commission_rate_pct else 0.0
    vendor_rate = vendor_commission_rate_pct / 100 if vendor_commission_rate_pct else 0.0
    seller_amt = round(actual_revenue * seller_rate)
    vendor_amt = round(actual_revenue * vendor_rate)

    campaign.name = name
    campaign.product_id = product_id or None
    campaign.influencer_id = influencer_id or None
    campaign.status = status
    campaign.start_date = _parse_date(start_date)
    campaign.end_date = _parse_date(end_date)
    campaign.commission_rate = commission_rate
    campaign.unit_price = unit_price
    campaign.seller_commission_rate = seller_rate
    campaign.vendor_commission_rate = vendor_rate
    campaign.seller_commission_amount = seller_amt
    campaign.vendor_commission_amount = vendor_amt
    campaign.expected_sales = expected_sales
    campaign.actual_sales = actual_sales
    campaign.actual_revenue = actual_revenue
    campaign.notes = notes or None
    db.commit()

    if status == "completed" and prev_status != "completed":
        _auto_settle(db, campaign)
        db.commit()

    return RedirectResponse(f"/campaigns/{campaign_id}?msg=수정되었습니다", status_code=302)


@router.post("/{campaign_id}/update-sales")
def update_sales(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    actual_sales: int = Form(0),
):
    """Inline sales volume update — recalculates revenue & commission amounts."""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        return JSONResponse({"error": "not found"}, status_code=404)
    campaign.actual_sales = actual_sales
    price = campaign.unit_price or 0
    if not price and campaign.product_id:
        p = db.query(Product).filter_by(id=campaign.product_id).first()
        if p:
            price = getattr(p, 'groupbuy_price', 0) or getattr(p, 'consumer_price', 0) or getattr(p, 'price', 0) or 0
    if price:
        campaign.actual_revenue = actual_sales * price
    seller_rate = campaign.seller_commission_rate or campaign.commission_rate or 0.0
    vendor_rate = campaign.vendor_commission_rate or 0.0
    rev = campaign.actual_revenue or 0.0
    campaign.seller_commission_amount = round(rev * seller_rate)
    campaign.vendor_commission_amount = round(rev * vendor_rate)
    db.commit()
    return JSONResponse({
        "actual_sales": campaign.actual_sales,
        "actual_revenue": campaign.actual_revenue or 0,
        "seller_commission_amount": campaign.seller_commission_amount or 0,
    })


@router.post("/{campaign_id}/delete")
def campaign_delete(campaign_id: str, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if campaign:
        db.delete(campaign)
        db.commit()
    return RedirectResponse("/campaigns?msg=삭제되었습니다", status_code=302)
