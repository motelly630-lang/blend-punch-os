import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models import Campaign, Product, Influencer
from app.models.settlement import Settlement
from app.models.transaction import Transaction
from app.models.sales_page import SalesPage
from app.models.user import User
from app.auth.dependencies import get_current_user, require_admin
from app.auth.tenant import get_company_id

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
    cid = get_company_id(current_user)
    _run_archiving(db)
    # Backfill: create settlements for existing completed campaigns that have none
    from sqlalchemy import and_
    completed_no_settlement = db.query(Campaign).filter(
        Campaign.company_id == cid,
        Campaign.status == "completed",
        Campaign.influencer_id.isnot(None),
        Campaign.actual_revenue > 0,
        ~Campaign.id.in_(db.query(Settlement.campaign_id).filter(Settlement.campaign_id.isnot(None)))
    ).all()
    if completed_no_settlement:
        for c in completed_no_settlement:
            _auto_settle(db, c)
        db.commit()
    today = _kst_today()

    if tab == "archive":
        campaigns = db.query(Campaign).filter(Campaign.company_id == cid, Campaign.is_archived == True).order_by(Campaign.end_date.desc()).all()
    else:
        campaigns = db.query(Campaign).filter(Campaign.company_id == cid, Campaign.is_archived == False).order_by(Campaign.start_date.asc().nullslast()).all()

    # Compute auto-status per campaign (KST-based, display only)
    status_map = {c.id: _auto_status(c, today) for c in campaigns}

    active_count   = sum(1 for s in status_map.values() if s == "active")
    planning_count = sum(1 for s in status_map.values() if s in ("planning", "negotiating", "contracted"))
    done_count     = sum(1 for s in status_map.values() if s in ("completed", "cancelled"))
    archive_count  = db.query(Campaign).filter(Campaign.company_id == cid, Campaign.is_archived == True).count()

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

    # Summary totals for right panel
    active_statuses = {"active", "completed"}
    total_revenue    = sum(c.actual_revenue or 0 for c in campaigns if status_map.get(c.id) == "active")
    total_seller_amt = sum(c.seller_commission_amount or 0 for c in campaigns if status_map.get(c.id) in active_statuses)
    total_vendor_amt = sum(c.vendor_commission_amount or 0 for c in campaigns if status_map.get(c.id) in active_statuses)

    # Product / influencer lists for inline edit & quick-create dropdowns
    products_list    = db.query(Product).filter(Product.company_id == cid, Product.status != "archived").order_by(Product.name).limit(400).all()
    influencers_list = db.query(Influencer).filter(Influencer.company_id == cid, Influencer.status == "active").order_by(Influencer.name).limit(400).all()
    products_json    = json.dumps([{"id": p.id, "name": p.name, "brand": p.brand or ""} for p in products_list], ensure_ascii=False)
    influencers_json = json.dumps([{"id": inf.id, "name": inf.name, "platform": inf.platform or ""} for inf in influencers_list], ensure_ascii=False)

    return templates.TemplateResponse("campaigns/list.html", {
        "request": request, "active_page": "campaigns", "current_user": current_user,
        "campaigns": campaigns, "status_map": status_map, "today": today, "tab": tab,
        "active_count": active_count, "planning_count": planning_count,
        "done_count": done_count, "archive_count": archive_count,
        "cal_json": json.dumps(cal_data, ensure_ascii=False),
        "total_revenue": total_revenue,
        "total_seller_amt": total_seller_amt,
        "total_vendor_amt": total_vendor_amt,
        "products_json": products_json,
        "influencers_json": influencers_json,
        "statuses": STATUSES,
    })




@router.get("/new")
def campaign_new(request: Request, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user),
                 product_id: str = "", influencer_id: str = ""):
    cid = get_company_id(current_user)
    products = db.query(Product).filter(Product.company_id == cid, Product.status != "archived").order_by(Product.name).limit(300).all()
    influencers = db.query(Influencer).filter(Influencer.company_id == cid, Influencer.status == "active").order_by(Influencer.name).limit(300).all()
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
    """캠페인 완료 시 정산 자동 생성 또는 pending 상태 정산 재계산.

    - influencer_id 없으면 스킵
    - actual_revenue = 0 이면 스킵 (0원 정산 방지)
    - seller_type 우선순위: campaign.seller_type > influencer.business_type > '사업자'
    - 기존 pending 정산이 있으면 금액 재계산, confirmed/paid는 건드리지 않음
    """
    if not campaign.influencer_id:
        return
    if not (campaign.actual_revenue or 0):
        return

    from app.routers.settlements import calc_settlement
    inf = db.query(Influencer).filter_by(id=campaign.influencer_id).first()

    # seller_type: 캠페인 설정 우선, 없으면 인플루언서 사업자 유형, 최종 fallback 사업자
    seller_type = (
        campaign.seller_type
        or (inf.business_type if inf and inf.business_type else None)
        or "사업자"
    )
    seller_rate = campaign.seller_commission_rate or campaign.commission_rate or 0.0
    calc = calc_settlement(campaign.actual_revenue or 0, seller_rate, seller_type)
    period = (campaign.end_date.strftime("%Y년 %m월") if campaign.end_date else datetime.now().strftime("%Y년 %m월"))

    existing = db.query(Settlement).filter_by(campaign_id=campaign.id).first()
    if existing:
        # pending 상태만 재계산 (confirmed/paid는 건드리지 않음)
        if existing.status == "pending":
            existing.sales_amount      = campaign.actual_revenue or 0
            existing.commission_rate   = seller_rate
            existing.seller_type       = seller_type
            existing.period_label      = period
            existing.commission_amount = calc["commission_amount"]
            existing.vat_amount        = calc["vat_amount"]
            existing.tax_rate          = calc["tax_rate"]
            existing.tax_amount        = calc["tax_amount"]
            existing.final_payment     = calc["final_payment"]
            if inf and not existing.bank_name_snapshot:
                existing.bank_name_snapshot       = inf.bank_name
                existing.account_number_snapshot  = inf.account_number
                existing.account_holder_snapshot  = inf.account_holder
    else:
        s = Settlement(
            company_id=campaign.company_id,
            influencer_id=campaign.influencer_id,
            campaign_id=campaign.id,
            period_label=period,
            seller_type=seller_type,
            sales_amount=campaign.actual_revenue or 0,
            commission_rate=seller_rate,
            status="pending",
            notes="캠페인 완료 시 자동 생성",
            bank_name_snapshot=inf.bank_name if inf else None,
            account_number_snapshot=inf.account_number if inf else None,
            account_holder_snapshot=inf.account_holder if inf else None,
            **calc,
        )
        db.add(s)


def _parse_form_fields(
    product_id, influencer_id, commission_rate,
    unit_price, seller_commission_rate_pct, vendor_commission_rate_pct,
    actual_revenue,
):
    try:
        commission_rate_f = float(commission_rate) if commission_rate and commission_rate != "None" else 0.0
    except (ValueError, TypeError):
        commission_rate_f = 0.0
    seller_rate = seller_commission_rate_pct / 100 if seller_commission_rate_pct else 0.0
    vendor_rate = vendor_commission_rate_pct / 100 if vendor_commission_rate_pct else 0.0
    seller_amt = round(actual_revenue * seller_rate)
    vendor_amt = round(actual_revenue * vendor_rate)
    return commission_rate_f, seller_rate, vendor_rate, seller_amt, vendor_amt


@router.post("/inline-create")
async def campaign_inline_create(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Quick-create a campaign from the list view (JSON in, JSON out)."""
    cid = get_company_id(current_user)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "잘못된 요청입니다"}, status_code=400)
    try:
        name = (data.get("name") or "").strip()
        if not name:
            return JSONResponse({"error": "name required"}, status_code=400)
        campaign = Campaign(
            company_id=cid,
            name=name,
            product_id=data.get("product_id") or None,
            influencer_id=data.get("influencer_id") or None,
            status=data.get("status", "planning"),
            start_date=_parse_date(data.get("start_date", "")),
            end_date=_parse_date(data.get("end_date", "")),
            unit_price=float(data.get("unit_price") or 0),
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)
        return JSONResponse({"ok": True, "id": campaign.id})
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": f"저장 실패: {type(e).__name__}"}, status_code=500)


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
    commission_rate: str = Form("0"),
    unit_price: float = Form(0.0),
    seller_commission_rate_pct: float = Form(0.0),
    vendor_commission_rate_pct: float = Form(0.0),
    expected_sales: int = Form(0),
    actual_sales: int = Form(0),
    actual_revenue: float = Form(0.0),
    notes: str = Form(""),
    product_name_manual: str = Form(""),
    brand_name_manual: str = Form(""),
    category_manual: str = Form(""),
    seller_type: str = Form(""),
    campaign_type: str = Form("internal"),
    external_url: str = Form(""),
):
    cid = get_company_id(current_user)
    commission_rate_f, seller_rate, vendor_rate, seller_amt, vendor_amt = _parse_form_fields(
        product_id, influencer_id, commission_rate,
        unit_price, seller_commission_rate_pct, vendor_commission_rate_pct, actual_revenue,
    )
    campaign = Campaign(
        company_id=cid,
        name=name,
        product_id=product_id or None,
        influencer_id=influencer_id or None,
        status=status,
        start_date=_parse_date(start_date),
        end_date=_parse_date(end_date),
        commission_rate=commission_rate_f,
        unit_price=unit_price,
        seller_commission_rate=seller_rate,
        vendor_commission_rate=vendor_rate,
        seller_commission_amount=seller_amt,
        vendor_commission_amount=vendor_amt,
        expected_sales=expected_sales,
        actual_sales=actual_sales,
        actual_revenue=actual_revenue,
        notes=notes or None,
        product_name_manual=product_name_manual or None,
        brand_name_manual=brand_name_manual or None,
        category_manual=category_manual or None,
        seller_type=seller_type or None,
        campaign_type=campaign_type or "internal",
        external_url=external_url.strip() or None,
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
    cid = get_company_id(current_user)
    campaign = db.query(Campaign).filter(Campaign.company_id == cid, Campaign.id == campaign_id).first()
    if not campaign:
        return RedirectResponse("/campaigns?err=캠페인을+찾을+수+없습니다", status_code=302)

    # ── 캠페인 단위 손익 집계 ──────────────────────────────────────────────────
    txn_rev = db.query(func.sum(Transaction.amount)).filter(
        Transaction.campaign_id == campaign_id, Transaction.type == "revenue"
    ).scalar() or 0
    txn_cost = db.query(func.sum(Transaction.amount)).filter(
        Transaction.campaign_id == campaign_id, Transaction.type == "cost"
    ).scalar() or 0
    settle_amt = db.query(func.sum(Settlement.final_payment)).filter(
        Settlement.campaign_id == campaign_id,
        Settlement.status.in_(["paid", "confirmed"]),
    ).scalar() or 0
    camp_net = txn_rev - txn_cost - settle_amt

    camp_transactions = db.query(Transaction).filter(
        Transaction.campaign_id == campaign_id
    ).order_by(Transaction.transaction_date.desc()).all()

    sales_pages = db.query(SalesPage).filter(
        SalesPage.campaign_id == campaign_id,
        SalesPage.company_id == cid,
    ).order_by(SalesPage.created_at.desc()).all()

    return templates.TemplateResponse("campaigns/detail.html", {
        "request": request, "active_page": "campaigns", "current_user": current_user,
        "campaign": campaign,
        "camp_rev": txn_rev,
        "camp_cost": txn_cost,
        "camp_settle": settle_amt,
        "camp_net": camp_net,
        "camp_transactions": camp_transactions,
        "sales_pages": sales_pages,
    })


@router.get("/{campaign_id}/edit")
def campaign_edit(campaign_id: str, request: Request, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    cid = get_company_id(current_user)
    campaign = db.query(Campaign).filter(Campaign.company_id == cid, Campaign.id == campaign_id).first()
    if not campaign:
        return RedirectResponse("/campaigns", status_code=302)
    products = db.query(Product).filter(Product.company_id == cid, Product.status != "archived").order_by(Product.name).limit(300).all()
    influencers = db.query(Influencer).filter(Influencer.company_id == cid, Influencer.status == "active").order_by(Influencer.name).limit(300).all()
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
    commission_rate: str = Form("0"),
    unit_price: float = Form(0.0),
    seller_commission_rate_pct: float = Form(0.0),
    vendor_commission_rate_pct: float = Form(0.0),
    expected_sales: int = Form(0),
    actual_sales: int = Form(0),
    actual_revenue: float = Form(0.0),
    notes: str = Form(""),
    product_name_manual: str = Form(""),
    brand_name_manual: str = Form(""),
    category_manual: str = Form(""),
    seller_type: str = Form(""),
    campaign_type: str = Form("internal"),
    external_url: str = Form(""),
):
    cid = get_company_id(current_user)
    campaign = db.query(Campaign).filter(Campaign.company_id == cid, Campaign.id == campaign_id).first()
    if not campaign:
        return RedirectResponse("/campaigns", status_code=302)

    commission_rate_f, seller_rate, vendor_rate, seller_amt, vendor_amt = _parse_form_fields(
        product_id, influencer_id, commission_rate,
        unit_price, seller_commission_rate_pct, vendor_commission_rate_pct, actual_revenue,
    )
    prev_status = campaign.status
    campaign.name = name
    campaign.product_id = product_id or None
    campaign.influencer_id = influencer_id or None
    campaign.status = status
    campaign.start_date = _parse_date(start_date)
    campaign.end_date = _parse_date(end_date)
    campaign.commission_rate = commission_rate_f
    campaign.unit_price = unit_price
    campaign.seller_commission_rate = seller_rate
    campaign.vendor_commission_rate = vendor_rate
    campaign.seller_commission_amount = seller_amt
    campaign.vendor_commission_amount = vendor_amt
    campaign.expected_sales = expected_sales
    campaign.actual_sales = actual_sales
    campaign.actual_revenue = actual_revenue
    campaign.notes = notes or None
    campaign.product_name_manual = product_name_manual or None
    campaign.brand_name_manual = brand_name_manual or None
    campaign.category_manual = category_manual or None
    campaign.seller_type = seller_type or None
    campaign.campaign_type = campaign_type or "internal"
    campaign.external_url = external_url.strip() or None
    db.commit()

    if status == "completed":
        _auto_settle(db, campaign)
        db.commit()

    return RedirectResponse(f"/campaigns/{campaign_id}?msg=수정되었습니다", status_code=302)


@router.post("/{campaign_id}/inline-update")
async def campaign_inline_update(
    campaign_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Inline edit API — accepts JSON, returns JSON with updated values."""
    cid = get_company_id(current_user)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "잘못된 요청입니다"}, status_code=400)
    campaign = db.query(Campaign).filter(Campaign.company_id == cid, Campaign.id == campaign_id).first()
    if not campaign:
        return JSONResponse({"error": "not found"}, status_code=404)

    prev_status = campaign.status
    if "product_id" in data:
        campaign.product_id = data["product_id"] or None
    if "start_date" in data:
        campaign.start_date = _parse_date(data["start_date"])
    if "end_date" in data:
        campaign.end_date = _parse_date(data["end_date"])
    if "unit_price" in data:
        campaign.unit_price = float(data["unit_price"] or 0)
    if "actual_sales" in data:
        campaign.actual_sales = int(float(data["actual_sales"] or 0))
    if "actual_revenue" in data:
        campaign.actual_revenue = float(data["actual_revenue"] or 0)
    if "seller_commission_rate_pct" in data:
        campaign.seller_commission_rate = float(data["seller_commission_rate_pct"] or 0) / 100
    if "vendor_commission_rate_pct" in data:
        campaign.vendor_commission_rate = float(data["vendor_commission_rate_pct"] or 0) / 100
    if "status" in data:
        campaign.status = str(data["status"])
    if "campaign_type" in data:
        campaign.campaign_type = data["campaign_type"] or "internal"
    if "external_url" in data:
        campaign.external_url = (data["external_url"] or "").strip() or None

    try:
        rev = campaign.actual_revenue or 0
        campaign.seller_commission_amount = round(rev * (campaign.seller_commission_rate or 0))
        campaign.vendor_commission_amount = round(rev * (campaign.vendor_commission_rate or 0))
        db.commit()

        if campaign.status == "completed":
            _auto_settle(db, campaign)
            db.commit()
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": f"저장 실패: {type(e).__name__}"}, status_code=500)

    return JSONResponse({
        "ok": True,
        "start_date": campaign.start_date.isoformat() if campaign.start_date else "",
        "end_date": campaign.end_date.isoformat() if campaign.end_date else "",
        "unit_price": campaign.unit_price or 0,
        "actual_sales": campaign.actual_sales or 0,
        "actual_revenue": campaign.actual_revenue or 0,
        "seller_commission_rate_pct": round((campaign.seller_commission_rate or 0) * 100, 1),
        "vendor_commission_rate_pct": round((campaign.vendor_commission_rate or 0) * 100, 1),
        "seller_commission_amount": campaign.seller_commission_amount or 0,
        "vendor_commission_amount": campaign.vendor_commission_amount or 0,
        "status": campaign.status,
    })


@router.post("/{campaign_id}/update-sales")
def update_sales(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    actual_sales: int = Form(0),
):
    """Inline sales volume update — recalculates revenue & commission amounts."""
    cid = get_company_id(current_user)
    campaign = db.query(Campaign).filter(Campaign.company_id == cid, Campaign.id == campaign_id).first()
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
                    current_user: User = Depends(require_admin)):
    cid = get_company_id(current_user)
    campaign = db.query(Campaign).filter(Campaign.company_id == cid, Campaign.id == campaign_id).first()
    if campaign:
        db.query(Settlement).filter_by(campaign_id=campaign_id).delete()
        db.delete(campaign)
        db.commit()
    return RedirectResponse("/campaigns?msg=삭제되었습니다", status_code=302)


@router.post("/bulk-delete")
def campaign_bulk_delete(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    ids: str = Form(""),
):
    cid = get_company_id(current_user)
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    if id_list:
        db.query(Settlement).filter(Settlement.campaign_id.in_(id_list)).delete(synchronize_session=False)
        db.query(Campaign).filter(Campaign.company_id == cid, Campaign.id.in_(id_list)).delete(synchronize_session=False)
        db.commit()
    return RedirectResponse(f"/campaigns?msg={len(id_list)}개+캠페인+삭제됨", status_code=302)
