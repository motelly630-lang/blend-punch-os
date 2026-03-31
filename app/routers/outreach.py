"""
Outreach & Sample Tracking Center
Routes:
  GET  /outreach           — list with filters
  GET  /outreach/new       — fast-entry form
  POST /outreach/new       — create log (auto-sync influencer)
  POST /outreach/{id}/status — update sample status (htmx inline)
"""
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.outreach import OutreachLog, SAMPLE_STATUSES
from app.models.influencer import Influencer
from app.models.product import Product
from app.models.user import User
from app.models.crm import CrmPipeline
from app.auth.dependencies import get_current_user
from app.auth.tenant import get_company_id

router = APIRouter(prefix="/outreach")
templates = Jinja2Templates(directory="app/templates")

STATUS_COLORS = {
    "제안발송": "blue",
    "샘플요청": "amber",
    "샘플발송": "green",
    "보류": "gray",
    "거절": "red",
}


def _get_or_create_influencer(db: Session, handle: str) -> str | None:
    """Return influencer_id for handle; auto-create bare record if not found."""
    if not handle:
        return None
    # Normalize: strip @
    clean = handle.lstrip("@").strip()
    inf = db.query(Influencer).filter(
        Influencer.handle == clean
    ).first()
    if inf:
        return inf.id
    # Auto-create minimal record
    new_inf = Influencer(
        name=clean,
        handle=clean,
        platform="instagram",  # default; user can update later
        followers=0,
        status="active",
        has_campaign_history="false",
    )
    db.add(new_inf)
    db.flush()
    return new_inf.id


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
def outreach_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    operator: str = "",
    status: str = "",
    product_id: str = "",
):
    cid = get_company_id(current_user)
    q = db.query(OutreachLog).filter(OutreachLog.company_id == cid)
    if operator:
        q = q.filter(OutreachLog.operator == operator)
    if status:
        q = q.filter(OutreachLog.sample_status == status)
    if product_id:
        q = q.filter(OutreachLog.product_id == product_id)
    logs = q.order_by(OutreachLog.outreach_date.desc(), OutreachLog.created_at.desc()).limit(500).all()

    # Targeted queries — only fetch records referenced by the current page logs
    product_ids = {log.product_id for log in logs if log.product_id}
    influencer_ids = {log.influencer_id for log in logs if log.influencer_id}
    product_map = (
        {p.id: p for p in db.query(Product).filter(Product.company_id == cid, Product.id.in_(product_ids)).all()}
        if product_ids else {}
    )
    influencer_map = (
        {i.id: i for i in db.query(Influencer).filter(Influencer.company_id == cid, Influencer.id.in_(influencer_ids)).all()}
        if influencer_ids else {}
    )

    # CRM pipeline lookup: (influencer_id, product_id) → pipeline_id
    crm_pipelines = db.query(CrmPipeline).filter(
        CrmPipeline.company_id == cid,
        CrmPipeline.influencer_id.in_(influencer_ids)
    ).all() if influencer_ids else []
    crm_map: dict[tuple, str] = {
        (p.influencer_id, p.product_id): p.id for p in crm_pipelines
    }

    enriched = []
    for log in logs:
        key = (log.influencer_id, log.product_id)
        enriched.append({
            "log": log,
            "product": product_map.get(log.product_id) if log.product_id else None,
            "influencer": influencer_map.get(log.influencer_id) if log.influencer_id else None,
            "crm_pipeline_id": crm_map.get(key),
        })

    # Stats per status
    status_counts = {s: 0 for s in SAMPLE_STATUSES}
    for log in logs:
        if log.sample_status in status_counts:
            status_counts[log.sample_status] += 1

    # All active products for form dropdowns
    products = db.query(Product).filter(Product.company_id == cid, Product.status == "active").order_by(Product.name).all()
    # Distinct operators for filter
    operators = sorted({r.operator for r in db.query(OutreachLog.operator).filter(OutreachLog.company_id == cid).distinct()})

    today_count = sum(1 for log in logs if log.outreach_date == date.today().isoformat())

    return templates.TemplateResponse("outreach/index.html", {
        "request": request,
        "active_page": "outreach",
        "current_user": current_user,
        "enriched": enriched,
        "status_counts": status_counts,
        "sample_statuses": SAMPLE_STATUSES,
        "status_colors": STATUS_COLORS,
        "products": products,
        "operators": operators,
        "filter_operator": operator,
        "filter_status": status,
        "filter_product_id": product_id,
        "today_count": today_count,
        "total": len(logs),
        "today": date.today().isoformat(),
    })


@router.get("/new")
def outreach_new_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = get_company_id(current_user)
    products = db.query(Product).filter(Product.company_id == cid, Product.status == "active").order_by(Product.name).all()
    return templates.TemplateResponse("outreach/form.html", {
        "request": request,
        "active_page": "outreach",
        "current_user": current_user,
        "products": products,
        "sample_statuses": SAMPLE_STATUSES,
        "today": date.today().isoformat(),
        "log": None,
    })


@router.post("/new")
def outreach_create(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    operator: str = Form(...),
    influencer_handle: str = Form(...),
    product_id: str = Form(""),
    outreach_date: str = Form(...),
    sample_status: str = Form("제안발송"),
    notes: str = Form(""),
):
    cid = get_company_id(current_user)
    influencer_id = _get_or_create_influencer(db, influencer_handle)

    log = OutreachLog(
        company_id=cid,
        operator=operator.strip(),
        influencer_handle=influencer_handle.lstrip("@").strip(),
        influencer_id=influencer_id,
        product_id=product_id or None,
        outreach_date=outreach_date,
        sample_status=sample_status,
        notes=notes.strip() or None,
    )
    db.add(log)
    db.commit()
    return RedirectResponse("/outreach?msg=아웃리치+기록+저장됨", status_code=302)


@router.post("/{log_id}/status", response_class=HTMLResponse)
def outreach_update_status(
    log_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    sample_status: str = Form(...),
):
    cid = get_company_id(current_user)
    log = db.query(OutreachLog).filter(OutreachLog.company_id == cid, OutreachLog.id == log_id).first()
    if not log:
        return HTMLResponse('<span class="text-red-500 text-xs">Not found</span>')
    log.sample_status = sample_status
    db.commit()

    color = STATUS_COLORS.get(sample_status, "gray")
    color_map = {
        "blue": "bg-blue-100 text-blue-700",
        "amber": "bg-amber-100 text-amber-700",
        "green": "bg-green-100 text-green-700",
        "gray": "bg-gray-100 text-gray-600",
        "red": "bg-red-100 text-red-600",
    }
    cls = color_map.get(color, "bg-gray-100 text-gray-600")
    opts = "".join(
        f'<option value="{s}"{" selected" if s == sample_status else ""}>{s}</option>'
        for s in SAMPLE_STATUSES
    )
    return HTMLResponse(
        f'<select name="sample_status"'
        f' hx-post="/outreach/{log_id}/status"'
        f' hx-target="#status-cell-{log_id}"'
        f' hx-swap="innerHTML"'
        f' hx-trigger="change"'
        f' class="text-xs font-semibold border-0 rounded-full px-2 py-1 cursor-pointer {cls}">'
        f'{opts}'
        f'</select>'
    )


# ── Promote to CRM Pipeline ────────────────────────────────────────────────────

OUTREACH_TO_CRM_STATUS = {
    "제안발송": "dm_sent",
    "샘플요청": "sample_requested",
    "샘플발송": "sample_sent",
    "보류": "negotiating",
    "거절": "rejected",
}


@router.post("/{log_id}/to-crm")
def outreach_to_crm(
    log_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = get_company_id(current_user)
    log = db.query(OutreachLog).filter(OutreachLog.company_id == cid, OutreachLog.id == log_id).first()
    if not log or not log.influencer_id:
        return RedirectResponse("/outreach?err=인플루언서+DB+등록이+필요합니다", status_code=302)

    # 이미 동일 (인플루언서 + 제품) 파이프라인 존재 여부 확인
    existing = db.query(CrmPipeline).filter(
        CrmPipeline.company_id == cid,
        CrmPipeline.influencer_id == log.influencer_id,
        CrmPipeline.product_id == log.product_id,
    ).first()
    if existing:
        return RedirectResponse(f"/crm/{existing.id}?msg=이미+CRM에+등록된+파이프라인입니다", status_code=302)

    crm_status = OUTREACH_TO_CRM_STATUS.get(log.sample_status, "dm_sent")
    pipeline = CrmPipeline(
        company_id=cid,
        influencer_id=log.influencer_id,
        product_id=log.product_id,
        status=crm_status,
        last_contact_date=date.fromisoformat(log.outreach_date) if log.outreach_date else None,
        dm_count=1,
        notes=f"[아웃리치 연동] {log.outreach_date} / {log.operator} / {log.notes or ''}".strip(" /"),
    )
    db.add(pipeline)
    db.commit()
    return RedirectResponse(f"/crm/{pipeline.id}?msg=CRM+파이프라인으로+등록되었습니다", status_code=302)
