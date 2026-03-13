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
from app.auth.dependencies import get_current_user

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
    q = db.query(OutreachLog)
    if operator:
        q = q.filter(OutreachLog.operator == operator)
    if status:
        q = q.filter(OutreachLog.sample_status == status)
    if product_id:
        q = q.filter(OutreachLog.product_id == product_id)
    logs = q.order_by(OutreachLog.outreach_date.desc(), OutreachLog.created_at.desc()).all()

    # Enrich with product/influencer names
    product_map = {p.id: p for p in db.query(Product).all()}
    influencer_map = {i.id: i for i in db.query(Influencer).all()}

    enriched = []
    for log in logs:
        enriched.append({
            "log": log,
            "product": product_map.get(log.product_id) if log.product_id else None,
            "influencer": influencer_map.get(log.influencer_id) if log.influencer_id else None,
        })

    # Stats per status
    status_counts = {s: 0 for s in SAMPLE_STATUSES}
    for log in logs:
        if log.sample_status in status_counts:
            status_counts[log.sample_status] += 1

    # All active products for form dropdowns
    products = db.query(Product).filter(Product.status == "active").order_by(Product.name).all()
    # Distinct operators for filter
    operators = sorted({r.operator for r in db.query(OutreachLog.operator).distinct()})

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
    products = db.query(Product).filter(Product.status == "active").order_by(Product.name).all()
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
    influencer_id = _get_or_create_influencer(db, influencer_handle)

    log = OutreachLog(
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
    log = db.query(OutreachLog).filter(OutreachLog.id == log_id).first()
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
    return HTMLResponse(
        f'<span class="text-xs font-semibold px-2.5 py-1 rounded-full {cls}">{sample_status}</span>'
    )
