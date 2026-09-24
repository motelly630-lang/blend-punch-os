import json
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from app.database import get_db
from app.models import Campaign, Product, Influencer
from app.models.partner import Partner
from app.models.settlement import Settlement
from app.models.transaction import Transaction
from app.models.sales_page import SalesPage
from app.models.user import User
from app.auth.dependencies import get_current_user, require_admin
from app.auth.tenant import get_company_id
from app.services import campaign_progress, content_embed
from app.services.campaign_service import (
    CAMPAIGN_STATUSES,
    PHASE_LABELS,
    CampaignValidationError,
    resolve_influencer_id,
    resolve_product_id,
    schedule_note,
    schedule_phase,
    validate_dates,
    validate_status,
)
from app.services.product_service import PRODUCT_CATEGORIES
from app.services.rates import RateError, parse_percent_input

KST = ZoneInfo("Asia/Seoul")


def _kst_today() -> date:
    return datetime.now(KST).date()


def _scoped_partner_id(db: Session, cid: int, product_id: str, form_partner_id: str):
    """캠페인에 붙일 협력사 id를 테넌트 스코프 안에서만 결정한다.

    제품에 배정된 협력사가 있으면 우선(제품은 이미 cid로 조회됨), 없으면 폼에서 고른 값을 쓴다.
    폼 값은 드롭다운이 cid로 스코프돼 있어도 POST 본문으로 임의 id를 넣을 수 있으므로
    반드시 소속을 확인해야 한다. 검증 없이 저장하면 협력사 포털(portal.py)이 그 캠페인을
    남의 회사 협력사에게 보여준다.
    """
    prod = (
        db.query(Product).filter(Product.id == product_id, Product.company_id == cid).first()
        if product_id else None
    )
    if prod and prod.partner_id:
        return prod.partner_id
    if not form_partner_id:
        return None
    owned = (
        db.query(Partner.id)
        .filter(Partner.id == form_partner_id, Partner.company_id == cid)
        .first()
    )
    return form_partner_id if owned else None


router = APIRouter(prefix="/campaigns")
templates = Jinja2Templates(directory="app/templates")

STATUSES = CAMPAIGN_STATUSES  # 단일 기준은 campaign_service


def _pct_or_error(raw, label: str) -> float:
    """캠페인 수수료 입력(%) → 비율. 빈 값 0."""
    try:
        v = parse_percent_input(raw)
    except RateError as e:
        raise CampaignValidationError(f"{label}: {e}") from e
    return v or 0.0


@router.get("")
def campaign_list(request: Request, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user),
                  tab: str = "active"):
    """조회 전용 — 상태·보관·정산을 바꾸지 않는다.

    일정에 따른 진행 처리·보관은 관리자용 /campaigns/progress-review 에서 명시적으로 실행한다
    (app/services/campaign_progress.py).
    """
    cid = get_company_id(current_user)
    today = _kst_today()

    if tab == "archive":
        campaigns = db.query(Campaign).options(joinedload(Campaign.product), joinedload(Campaign.influencer)).filter(Campaign.company_id == cid, Campaign.is_archived == True).order_by(Campaign.end_date.desc()).all()
    else:
        campaigns = db.query(Campaign).options(joinedload(Campaign.product), joinedload(Campaign.influencer)).filter(Campaign.company_id == cid, Campaign.is_archived == False).order_by(Campaign.start_date.asc().nullslast()).all()

    # 저장된 상태 그대로 표시. 날짜 기준 단계·어긋남 안내는 별도 표시 (DB 미변경)
    status_map = {c.id: c.status for c in campaigns}
    phase_map = {c.id: PHASE_LABELS[schedule_phase(c.start_date, c.end_date, today)] for c in campaigns}
    note_map = {c.id: schedule_note(c.status, c.start_date, c.end_date, today) for c in campaigns}

    # ── 통계 카운트는 탭과 무관하게 전역(활성=비보관) 기준으로 계산 ──
    nonarch = db.query(Campaign).filter(Campaign.company_id == cid, Campaign.is_archived == False).all()
    nonarch_status = {c.id: c.status for c in nonarch}
    review_count = sum(1 for c in nonarch if schedule_note(c.status, c.start_date, c.end_date, today))
    active_count   = sum(1 for s in nonarch_status.values() if s == "active")
    planning_count = sum(1 for s in nonarch_status.values() if s in ("planning", "negotiating", "contracted"))
    done_count     = sum(1 for s in nonarch_status.values() if s in ("completed", "cancelled"))
    archive_count  = db.query(Campaign).filter(Campaign.company_id == cid, Campaign.is_archived == True).count()
    total_count    = len(nonarch)

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

    # ── 합계: 전체 캠페인(완료·보관 포함, 취소 제외) 기준 — 대시보드와 동일 관점 ──
    total_revenue = db.query(func.coalesce(func.sum(Campaign.actual_revenue), 0)).filter(
        Campaign.company_id == cid, Campaign.status != "cancelled").scalar() or 0
    total_seller_amt = db.query(func.coalesce(func.sum(Campaign.seller_commission_amount), 0)).filter(
        Campaign.company_id == cid, Campaign.status != "cancelled").scalar() or 0
    total_vendor_amt = db.query(func.coalesce(func.sum(Campaign.vendor_commission_amount), 0)).filter(
        Campaign.company_id == cid, Campaign.status != "cancelled").scalar() or 0

    # Product / influencer lists for inline edit & quick-create dropdowns
    products_list    = db.query(Product).filter(Product.company_id == cid, Product.status != "archived").order_by(Product.name).limit(400).all()
    influencers_list = db.query(Influencer).filter(Influencer.company_id == cid, Influencer.status == "active").order_by(Influencer.name).limit(400).all()
    products_json    = json.dumps([{"id": p.id, "name": p.name, "brand": p.brand or ""} for p in products_list], ensure_ascii=False)
    influencers_json = json.dumps([{"id": inf.id, "name": inf.name, "platform": inf.platform or ""} for inf in influencers_list], ensure_ascii=False)

    return templates.TemplateResponse("campaigns/list.html", {
        "request": request, "active_page": "campaigns", "current_user": current_user,
        "campaigns": campaigns, "status_map": status_map, "today": today, "tab": tab,
        "phase_map": phase_map, "note_map": note_map, "review_count": review_count,
        "active_count": active_count, "planning_count": planning_count,
        "done_count": done_count, "archive_count": archive_count, "total_count": total_count,
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
    partners = db.query(Partner).filter(Partner.company_id == cid, Partner.is_active == True).order_by(Partner.name).all()
    return templates.TemplateResponse("campaigns/form.html", {
        "request": request, "active_page": "campaigns", "current_user": current_user,
        "campaign": None, "products": products, "influencers": influencers, "statuses": STATUSES,
        "categories": PRODUCT_CATEGORIES,
        "partners_json": [{"id": p.id, "name": p.name} for p in partners],
        "sel_partner_id": "", "sel_partner_name": "",
        "prefill_product_id": product_id, "prefill_influencer_id": influencer_id,
    })


# ── 진행 상태 정리 (명시적 실행 경로) ─────────────────────────────────────────
# 주의: 와일드카드 /{campaign_id} 보다 먼저 선언해야 한다.

@router.get("/progress-review")
def progress_review(request: Request, db: Session = Depends(get_db),
                    current_user: User = Depends(require_admin)):
    """미리보기 — DB 를 바꾸지 않는다."""
    cid = get_company_id(current_user)
    today = _kst_today()
    proposal = campaign_progress.build_proposal(db, cid, today)
    return templates.TemplateResponse("campaigns/progress_review.html", {
        "request": request, "active_page": "campaigns", "current_user": current_user,
        "today": today, "proposal": proposal, "status_labels": dict(STATUSES),
    })


@router.post("/progress-review/apply")
async def progress_review_apply(request: Request, db: Session = Depends(get_db),
                                current_user: User = Depends(require_admin)):
    cid = get_company_id(current_user)
    form = await request.form()
    status_ids = set(form.getlist("status_ids"))
    archive_ids = set(form.getlist("archive_ids"))
    create_settlements = form.get("create_settlements") == "1"
    result = campaign_progress.apply_selected(
        db, cid, _kst_today(), status_ids, archive_ids, create_settlements, _auto_settle)
    from urllib.parse import quote
    msg = (f"상태 {len(result['changed'])}건 · 보관 {len(result['archived'])}건 반영"
           f" · 정산 생성 {len(result['settlements_created'])}건")
    if result["skipped"]:
        msg += f" · 더 이상 해당하지 않아 건너뜀 {len(result['skipped'])}건"
    return RedirectResponse(f"/campaigns/progress-review?msg={quote(msg)}", status_code=303)


def _parse_date(s):
    if s is None or s == "":
        return None
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError) as exc:
        raise CampaignValidationError("날짜는 유효한 YYYY-MM-DD 형식으로 입력하세요") from exc


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
    from app.services import settlement_calc
    # 반드시 캠페인과 같은 회사의 인플루언서만 — 계좌정보를 스냅샷하므로 스코프가 빠지면
    # 타사 인플루언서의 실계좌번호가 이 회사 정산 레코드에 저장된다.
    # (수동 생성 경로 settlements.py 는 이미 cid 스코프. 자동 경로가 누락돼 있었다)
    #
    # `or 1`: 레거시 캠페인의 company_id 가 NULL 이면 `company_id == NULL` 은 SQL 에서
    # 절대 참이 아니므로 inf=None → 계좌 스냅샷 없이 정산이 생기고, 아래에서 NULL 이
    # 그대로 전파돼 /settlements 목록에 안 보이는 고아 정산이 된다(d92cb06 증상 재현).
    # migrate.py 가 NULL 을 1로 백필하지만 실행 순서에 의존하지 않도록 여기서도 막는다.
    settle_cid = campaign.company_id or 1
    inf = (
        db.query(Influencer)
        .filter(
            Influencer.company_id == settle_cid,
            Influencer.id == campaign.influencer_id,
        )
        .first()
    )

    # seller_type: 캠페인 설정 우선, 없으면 인플루언서 사업자 유형, 최종 fallback 사업자
    seller_type = (
        campaign.seller_type
        or (inf.business_type if inf and inf.business_type else None)
        or "사업자"
    )
    # 수수료율: 캠페인 → 제품 → 인플루언서 기본값 (settlement_calc.resolve_rate), 없으면 옛 칸
    seller_rate, _ = settlement_calc.resolve_rate(campaign, getattr(campaign, "product", None), inf)
    seller_rate = seller_rate or campaign.commission_rate or 0.0
    calc = calc_settlement(campaign.actual_revenue or 0, seller_rate, seller_type)
    period = (campaign.end_date.strftime("%Y년 %m월") if campaign.end_date else datetime.now().strftime("%Y년 %m월"))

    existing = db.query(Settlement).filter_by(campaign_id=campaign.id).first()
    if existing:
        # 작성중(pending)만 재계산 (발행·지급된 건 건드리지 않음).
        # 사람이 지급액을 직접 고친(is_manual) 정산서는 덮지 않는다.
        if existing.status == "pending" and not existing.is_manual:
            existing.sales_amount      = campaign.actual_revenue or 0
            existing.commission_rate   = seller_rate
            existing.seller_type       = seller_type
            existing.period_label      = period
            for k, v in calc.items():
                setattr(existing, k, v)
            if inf and not existing.bank_name_snapshot:
                existing.bank_name_snapshot       = inf.bank_name
                existing.account_number_snapshot  = inf.account_number
                existing.account_holder_snapshot  = inf.account_holder
    else:
        s = Settlement(
            company_id=settle_cid,
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
    """수수료(%) 입력 → (레거시 commission_rate, 셀러 비율, 벤더 비율, 셀러 금액, 벤더 금액).

    잘못된 퍼센트 값은 CampaignValidationError. 소수점은 보존한다 (12.5% → 0.125).
    """
    try:
        commission_rate_f = float(commission_rate) if commission_rate and commission_rate != "None" else 0.0
    except (ValueError, TypeError):
        commission_rate_f = 0.0
    seller_rate = _pct_or_error(seller_commission_rate_pct, "셀러 수수료율")
    vendor_rate = _pct_or_error(vendor_commission_rate_pct, "벤더 마진율")
    seller_amt = round(actual_revenue * seller_rate)
    vendor_amt = round(actual_revenue * vendor_rate)
    return commission_rate_f, seller_rate, vendor_rate, seller_amt, vendor_amt


def _validated_core(db: Session, cid: int, *, status, product_id, influencer_id,
                    start_date, end_date) -> dict:
    """생성·수정·인라인 공통 검증. 실패 시 CampaignValidationError."""
    validate_dates(start_date, end_date)
    return {
        "status": validate_status(status),
        "product_id": resolve_product_id(db, cid, product_id),
        "influencer_id": resolve_influencer_id(db, cid, influencer_id),
        "start_date": start_date,
        "end_date": end_date,
    }


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
    name = (data.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name required"}, status_code=400)
    try:
        core = _validated_core(
            db, cid,
            status=data.get("status") or "planning",
            product_id=data.get("product_id"),
            influencer_id=data.get("influencer_id"),
            start_date=_parse_date(data.get("start_date", "")),
            end_date=_parse_date(data.get("end_date", "")),
        )
        unit_price = float(data.get("unit_price") or 0)
    except CampaignValidationError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except (TypeError, ValueError):
        return JSONResponse({"error": "숫자 형식이 잘못되었습니다"}, status_code=400)
    try:
        campaign = Campaign(
            company_id=cid,
            name=name,
            product_id=core["product_id"],
            influencer_id=core["influencer_id"],
            partner_id=_scoped_partner_id(db, cid, core["product_id"] or "", ""),
            status=core["status"],
            start_date=core["start_date"],
            end_date=core["end_date"],
            unit_price=unit_price,
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
    partner_id: str = Form(""),
    status: str = Form("planning"),
    start_date: str = Form(""),
    end_date: str = Form(""),
    commission_rate: str = Form("0"),
    unit_price: float = Form(0.0),
    seller_commission_rate_pct: str = Form(""),
    vendor_commission_rate_pct: str = Form(""),
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
    try:
        commission_rate_f, seller_rate, vendor_rate, seller_amt, vendor_amt = _parse_form_fields(
            product_id, influencer_id, commission_rate,
            unit_price, seller_commission_rate_pct, vendor_commission_rate_pct, actual_revenue,
        )
        core = _validated_core(
            db, cid, status=status, product_id=product_id, influencer_id=influencer_id,
            start_date=_parse_date(start_date), end_date=_parse_date(end_date),
        )
    except CampaignValidationError as e:
        from urllib.parse import quote
        return RedirectResponse(f"/campaigns/new?err={quote(str(e))}", status_code=302)
    status = core["status"]
    partner_val = _scoped_partner_id(db, cid, core["product_id"] or "", partner_id)
    campaign = Campaign(
        company_id=cid,
        name=name,
        product_id=core["product_id"],
        influencer_id=core["influencer_id"],
        partner_id=partner_val,
        status=status,
        start_date=core["start_date"],
        end_date=core["end_date"],
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


@router.get("/quick")
def campaign_quick_form(request: Request, db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    """공구 한 번에 등록 — 인스타 주소 · 제품 · 기간만."""
    cid = get_company_id(current_user)
    products = (db.query(Product.id, Product.name, Product.brand, Product.seller_commission_rate)
                .filter(Product.company_id == cid, Product.is_archived.isnot(True))
                .order_by(Product.created_at.desc()).limit(500).all())
    return templates.TemplateResponse("campaigns/quick.html", {
        "request": request, "active_page": "campaigns", "current_user": current_user, "products": products,
    })


@router.post("/quick")
def campaign_quick_create(request: Request, db: Session = Depends(get_db),
                          current_user: User = Depends(get_current_user),
                          insta: str = Form(""), influencer_name: str = Form(""), product_pick: str = Form(""),
                          brand_name: str = Form(""), groupbuy_price: str = Form(""), rate_pct: str = Form(""),
                          start_date: str = Form(""), end_date: str = Form(""), reel_url: str = Form("")):
    from urllib.parse import quote
    from app.services import quick_campaign as qc
    cid = get_company_id(current_user)

    def _d(v):
        try:
            return date.fromisoformat(v) if v else None
        except ValueError:
            return None

    def _f(v):
        try:
            return float(str(v).replace(",", "").strip() or 0)
        except ValueError:
            return 0.0

    # 제품 칸: 목록에서 고르면 "이름 · 브랜드  [#id]" 모양 → id 로, 아니면 새 제품 이름으로
    pick = (product_pick or "").strip()
    m = re.search(r"\[#([0-9a-f-]{36})\]$", pick)
    product_id, product_name = (m.group(1), "") if m else ("", pick)
    try:
        r = qc.create(db, cid, _kst_today(), insta=insta, influencer_name=influencer_name, product_id=product_id,
                      product_name=product_name, brand_name=brand_name, groupbuy_price=_f(groupbuy_price),
                      rate_pct=_f(rate_pct), start=_d(start_date), end=_d(end_date), reel_url=reel_url)
    except ValueError as e:
        db.rollback()
        return RedirectResponse("/campaigns/quick?err=" + quote(str(e)), status_code=302)
    made = []
    made.append(("새 인플루언서 " if r["influencer_new"] else "인플루언서 ") + r["influencer"].name
                + (f"({r['influencer_note']})" if r["influencer_note"] else ""))
    made.append("새 제품(작성 필요) " + r["product"].name if r["product_new"] else "제품 " + r["product"].name)
    if r["brand_new"]:
        made.append("새 브랜드(정보 입력 필요) " + r["brand"].name)
    return RedirectResponse(f"/campaigns/{r['campaign'].id}?msg=" + quote("공구를 만들었어요 — " + " · ".join(made)),
                            status_code=302)


@router.get("/gallery")
def campaign_gallery(request: Request, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user), show: str = "active", q: str = ""):
    """공구 아카이브 — 인플루언서가 올린 릴스가 카드로 보이는 곳 (진행 중 · 예정 · 지난 공구)."""
    cid = get_company_id(current_user)
    today = _kst_today()
    qry = (db.query(Campaign).options(joinedload(Campaign.influencer), joinedload(Campaign.product))
           .filter(Campaign.company_id == cid, (Campaign.status != "cancelled") | (Campaign.status.is_(None))))
    if show == "active":
        qry = qry.filter(Campaign.start_date <= today, (Campaign.end_date >= today) | (Campaign.end_date.is_(None)),
                         Campaign.is_archived.isnot(True))
    elif show == "upcoming":
        qry = qry.filter(Campaign.start_date > today)
    elif show == "past":
        qry = qry.filter(Campaign.end_date < today)
    elif show != "all":
        show = "active"
    if q:
        like = f"%{q.strip()}%"
        qry = qry.outerjoin(Influencer, Influencer.id == Campaign.influencer_id).filter(
            Campaign.name.ilike(like) | Influencer.name.ilike(like) | Campaign.product_name_manual.ilike(like))
    order = Campaign.start_date.asc() if show == "upcoming" else Campaign.start_date.desc()
    camps = qry.order_by(order.nullslast()).limit(120).all()
    cards = [{"c": c, "media": content_embed.parse_many(c.content_urls)} for c in camps]
    if show in ("past", "all"):
        cards.sort(key=lambda x: (not x["media"],))            # 지난·전체는 영상 있는 것부터 (순서는 유지)
    return templates.TemplateResponse("campaigns/gallery.html", {
        "request": request, "active_page": "campaigns", "current_user": current_user,
        "cards": cards, "show": show, "q": q, "today": today,
    })


@router.post("/{campaign_id}/links")
def campaign_add_link(campaign_id: str, url: str = Form(""), back: str = Form(""),
                      db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """릴스·게시물 링크 추가 (인스타 · 유튜브만)."""
    from urllib.parse import quote
    back = back if back.startswith("/campaigns") else f"/campaigns/{campaign_id}"
    sep = "&" if "?" in back else "?"
    c = db.query(Campaign).filter(Campaign.company_id == get_company_id(current_user), Campaign.id == campaign_id).first()
    if not c:
        return RedirectResponse("/campaigns", status_code=302)
    p = content_embed.parse(url)
    if not p:
        return RedirectResponse(back + sep + "err=" + quote("인스타 릴스·게시물 또는 유튜브 링크만 넣을 수 있어요"), status_code=302)
    urls = list(c.content_urls or [])
    if p["url"] not in [(content_embed.parse(u) or {}).get("url") for u in urls]:
        urls.append(p["url"])
        c.content_urls = urls                 # JSON 칸은 새 목록을 넣어야 저장된다
        db.commit()
    return RedirectResponse(back + sep + "msg=" + quote("링크를 추가했어요"), status_code=302)


@router.post("/{campaign_id}/links/remove")
def campaign_remove_link(campaign_id: str, url: str = Form(""), back: str = Form(""),
                         db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from urllib.parse import quote
    back = back if back.startswith("/campaigns") else f"/campaigns/{campaign_id}"
    sep = "&" if "?" in back else "?"
    c = db.query(Campaign).filter(Campaign.company_id == get_company_id(current_user), Campaign.id == campaign_id).first()
    if c and url in (c.content_urls or []):
        c.content_urls = [u for u in c.content_urls if u != url]
        db.commit()
    return RedirectResponse(back + sep + "msg=" + quote("링크를 뺐어요"), status_code=302)


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
        "content_media": content_embed.parse_many(campaign.content_urls),
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
    partners = db.query(Partner).filter(Partner.company_id == cid, Partner.is_active == True).order_by(Partner.name).all()
    sel = (
        db.query(Partner)
        .filter(Partner.company_id == cid, Partner.id == campaign.partner_id)
        .first()
        if campaign.partner_id else None
    )
    return templates.TemplateResponse("campaigns/form.html", {
        "request": request, "active_page": "campaigns", "current_user": current_user,
        "campaign": campaign, "products": products, "influencers": influencers, "statuses": STATUSES,
        "categories": PRODUCT_CATEGORIES,
        "partners_json": [{"id": p.id, "name": p.name} for p in partners],
        "sel_partner_id": campaign.partner_id or "", "sel_partner_name": sel.name if sel else "",
    })


def _validated_update(db: Session, cid: int, campaign: Campaign, *, status, product_id,
                      influencer_id, start_date, end_date) -> dict:
    """수정용 검증 — 바뀐 값만 검사한다.

    기존에 저장돼 있던 값(과거 데이터)을 그대로 다시 보낸 경우까지 거부하면
    다른 필드조차 수정할 수 없게 되므로, 변경된 항목만 허용값·회사 소속을 확인한다.
    """
    new_pid = (product_id or "").strip() or None
    new_iid = (influencer_id or "").strip() or None
    new_status = (status or "").strip()
    preserve_null_status = campaign.status is None and new_status == "__preserve_null_status__"
    out = {
        "status": (campaign.status if preserve_null_status or new_status == campaign.status
                   else validate_status(new_status)),
        "product_id": new_pid if new_pid == campaign.product_id else resolve_product_id(db, cid, new_pid),
        "influencer_id": (new_iid if new_iid == campaign.influencer_id
                          else resolve_influencer_id(db, cid, new_iid)),
        "start_date": start_date,
        "end_date": end_date,
    }
    validate_dates(start_date, end_date)
    return out


@router.post("/{campaign_id}/edit")
def campaign_update(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    name: str = Form(...),
    product_id: str = Form(""),
    influencer_id: str = Form(""),
    partner_id: str = Form(""),
    status: str = Form("planning"),
    start_date: str = Form(""),
    end_date: str = Form(""),
    commission_rate: str = Form("0"),
    unit_price: float = Form(0.0),
    seller_commission_rate_pct: str = Form(""),
    vendor_commission_rate_pct: str = Form(""),
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

    try:
        commission_rate_f, seller_rate, vendor_rate, seller_amt, vendor_amt = _parse_form_fields(
            product_id, influencer_id, commission_rate,
            unit_price, seller_commission_rate_pct, vendor_commission_rate_pct, actual_revenue,
        )
        core = _validated_update(
            db, cid, campaign, status=status, product_id=product_id, influencer_id=influencer_id,
            start_date=_parse_date(start_date), end_date=_parse_date(end_date),
        )
    except CampaignValidationError as e:
        from urllib.parse import quote
        return RedirectResponse(f"/campaigns/{campaign_id}/edit?err={quote(str(e))}", status_code=302)
    status = core["status"]
    campaign.name = name
    campaign.product_id = core["product_id"]
    campaign.influencer_id = core["influencer_id"]
    campaign.partner_id = _scoped_partner_id(db, cid, core["product_id"] or "", partner_id)
    campaign.status = status
    campaign.start_date = core["start_date"]
    campaign.end_date = core["end_date"]
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

    try:
        core = _validated_update(
            db, cid, campaign,
            status=str(data["status"]) if "status" in data else campaign.status,
            product_id=(data.get("product_id") or "") if "product_id" in data else (campaign.product_id or ""),
            influencer_id=(data.get("influencer_id") or "") if "influencer_id" in data else (campaign.influencer_id or ""),
            start_date=_parse_date(data["start_date"]) if "start_date" in data else campaign.start_date,
            end_date=_parse_date(data["end_date"]) if "end_date" in data else campaign.end_date,
        )
        seller_rate = (_pct_or_error(data["seller_commission_rate_pct"], "셀러 수수료율")
                       if "seller_commission_rate_pct" in data else None)
        vendor_rate = (_pct_or_error(data["vendor_commission_rate_pct"], "벤더 마진율")
                       if "vendor_commission_rate_pct" in data else None)
        unit_price = float(data["unit_price"] or 0) if "unit_price" in data else None
        actual_sales = int(float(data["actual_sales"] or 0)) if "actual_sales" in data else None
        actual_revenue = float(data["actual_revenue"] or 0) if "actual_revenue" in data else None
    except CampaignValidationError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except (TypeError, ValueError):
        return JSONResponse({"error": "숫자 형식이 잘못되었습니다"}, status_code=400)

    product_changed = core["product_id"] != campaign.product_id
    campaign.product_id = core["product_id"]
    campaign.influencer_id = core["influencer_id"]
    if product_changed:
        campaign.partner_id = _scoped_partner_id(db, cid, core["product_id"] or "", campaign.partner_id or "")
    campaign.start_date = core["start_date"]
    campaign.end_date = core["end_date"]
    campaign.status = core["status"]
    if unit_price is not None:
        campaign.unit_price = unit_price
    if actual_sales is not None:
        campaign.actual_sales = actual_sales
    if actual_revenue is not None:
        campaign.actual_revenue = actual_revenue
    if seller_rate is not None:
        campaign.seller_commission_rate = seller_rate
    if vendor_rate is not None:
        campaign.vendor_commission_rate = vendor_rate
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
        "seller_commission_rate_pct": round((campaign.seller_commission_rate or 0) * 100, 4),
        "vendor_commission_rate_pct": round((campaign.vendor_commission_rate or 0) * 100, 4),
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
        p = db.query(Product).filter(Product.company_id == cid, Product.id == campaign.product_id).first()
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
        # 정산서는 돈 기록 — 캠페인을 지워도 사라지면 안 된다 (DE-008). 정산서가 있으면 삭제 대신 보관.
        if db.query(Settlement.id).filter(Settlement.company_id == cid, Settlement.campaign_id == campaign_id).first():
            from urllib.parse import quote
            return RedirectResponse(f"/campaigns/{campaign_id}?err=" + quote(
                "정산서가 있는 공구는 지울 수 없어요 — 보관 처리해 주세요 (정산 기록을 지키기 위해)"), status_code=302)
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
        # 본인 회사 소유 캠페인만 추려서 그 캠페인의 정산만 삭제 (타사 정산 삭제 방지)
        owned_ids = [
            cid_ for (cid_,) in db.query(Campaign.id).filter(
                Campaign.company_id == cid, Campaign.id.in_(id_list)
            ).all()
        ]
        # 정산서가 있는 공구는 건너뛴다 (정산 기록 보존 — DE-008)
        with_settle = {c for (c,) in db.query(Settlement.campaign_id).filter(
            Settlement.company_id == cid, Settlement.campaign_id.in_(owned_ids or [""])).distinct()}
        deletable = [x for x in owned_ids if x not in with_settle]
        if deletable:
            db.query(Campaign).filter(Campaign.id.in_(deletable)).delete(synchronize_session=False)
        db.commit()
        from urllib.parse import quote
        msg = f"{len(deletable)}개 캠페인 삭제됨"
        if with_settle:
            msg += f" · 정산서가 있는 {len(with_settle)}개는 지우지 않았어요 (보관 처리해 주세요)"
        return RedirectResponse("/campaigns?msg=" + quote(msg), status_code=302)
    return RedirectResponse("/campaigns?msg=0개+캠페인+삭제됨", status_code=302)
