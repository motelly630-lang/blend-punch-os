"""
CRM Pipeline Router
Routes:
  GET  /crm                         — kanban board (7-stage pipeline)
  GET  /crm/new                     — new pipeline form
  POST /crm/new                     — create pipeline
  GET  /crm/{pipeline_id}           — detail page
  POST /crm/{pipeline_id}/edit      — update pipeline
  POST /crm/{pipeline_id}/status    — quick status update (htmx)
  POST /crm/{pipeline_id}/delete    — delete pipeline
  POST /crm/{pipeline_id}/samples/new   — add sample log
  POST /crm/{pipeline_id}/samples/{sample_id}/status — update sample status
  POST /crm/{pipeline_id}/samples/{sample_id}/delete — delete sample log
"""
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.crm import CrmPipeline, SampleLog, CRM_STATUSES, CRM_STATUS_LABELS, SAMPLE_LOG_STATUSES, SAMPLE_LOG_STATUS_LABELS
from app.models.email_log import EmailLog, EMAIL_TEMPLATES
from app.models.influencer import Influencer
from app.models.product import Product
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.auth.tenant import get_company_id

router = APIRouter(prefix="/crm")
templates = Jinja2Templates(directory="app/templates")

STATUS_COLORS = {
    "new": "gray",
    "dm_sent": "blue",
    "replied": "indigo",
    "sample_requested": "amber",
    "sample_sent": "orange",
    "negotiating": "purple",
    "completed": "green",
    "rejected": "red",
}

SAMPLE_STATUS_COLORS = {
    "pending": "gray",
    "sent": "blue",
    "delivered": "green",
    "reviewing": "amber",
    "returned": "red",
}


# ── List / Kanban ──────────────────────────────────────────────────────────────

@router.get("")
def crm_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    view: str = "kanban",
    product_id: str = "",
    status: str = "",
):
    cid = get_company_id(current_user)
    q = db.query(CrmPipeline).filter(CrmPipeline.company_id == cid)
    if product_id:
        q = q.filter(CrmPipeline.product_id == product_id)
    if status:
        q = q.filter(CrmPipeline.status == status)
    pipelines = q.order_by(CrmPipeline.updated_at.desc()).limit(500).all()

    # Group by status for kanban
    kanban: dict[str, list] = {s: [] for s in CRM_STATUSES}
    for p in pipelines:
        if p.status in kanban:
            kanban[p.status].append(p)

    # Stats
    total = len(pipelines)
    active_count = sum(1 for p in pipelines if p.status not in ("completed", "rejected"))
    completed_count = sum(1 for p in pipelines if p.status == "completed")
    rejected_count = sum(1 for p in pipelines if p.status == "rejected")

    products = db.query(Product).filter(Product.company_id == cid, Product.status == "active").order_by(Product.name).all()
    influencers = db.query(Influencer).filter(Influencer.company_id == cid, Influencer.status == "active").order_by(Influencer.name).limit(300).all()

    return templates.TemplateResponse("crm/index.html", {
        "request": request,
        "active_page": "crm",
        "current_user": current_user,
        "pipelines": pipelines,
        "kanban": kanban,
        "crm_statuses": CRM_STATUSES,
        "status_labels": CRM_STATUS_LABELS,
        "status_colors": STATUS_COLORS,
        "view": view,
        "filter_product_id": product_id,
        "filter_status": status,
        "products": products,
        "influencers": influencers,
        "total": total,
        "active_count": active_count,
        "completed_count": completed_count,
        "rejected_count": rejected_count,
        "today": date.today().isoformat(),
    })


# ── New ────────────────────────────────────────────────────────────────────────

@router.get("/new")
def crm_new_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    influencer_id: str = "",
    product_id: str = "",
):
    cid = get_company_id(current_user)
    products = db.query(Product).filter(Product.company_id == cid, Product.status == "active").order_by(Product.name).all()
    influencers = db.query(Influencer).filter(Influencer.company_id == cid, Influencer.status == "active").order_by(Influencer.name).limit(300).all()
    return templates.TemplateResponse("crm/form.html", {
        "request": request,
        "active_page": "crm",
        "current_user": current_user,
        "pipeline": None,
        "products": products,
        "influencers": influencers,
        "crm_statuses": CRM_STATUSES,
        "status_labels": CRM_STATUS_LABELS,
        "prefill_influencer_id": influencer_id,
        "prefill_product_id": product_id,
    })


@router.post("/new")
def crm_create(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    influencer_id: str = Form(""),
    product_id: str = Form(""),
    status: str = Form("new"),
    last_contact_date: str = Form(""),
    dm_count: int = Form(0),
    notes: str = Form(""),
):
    cid = get_company_id(current_user)
    pipeline = CrmPipeline(
        company_id=cid,
        influencer_id=influencer_id or None,
        product_id=product_id or None,
        status=status,
        last_contact_date=date.fromisoformat(last_contact_date) if last_contact_date else None,
        dm_count=dm_count,
        notes=notes.strip() or None,
    )
    db.add(pipeline)
    db.commit()
    return RedirectResponse("/crm?msg=파이프라인이+등록되었습니다", status_code=302)


# ── Detail ─────────────────────────────────────────────────────────────────────

@router.get("/{pipeline_id}")
def crm_detail(
    pipeline_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = get_company_id(current_user)
    pipeline = db.query(CrmPipeline).filter(CrmPipeline.company_id == cid, CrmPipeline.id == pipeline_id).first()
    if not pipeline:
        return RedirectResponse("/crm?err=파이프라인을+찾을+수+없습니다", status_code=302)

    products = db.query(Product).filter(Product.company_id == cid, Product.status == "active").order_by(Product.name).all()
    influencers = db.query(Influencer).filter(Influencer.company_id == cid, Influencer.status == "active").order_by(Influencer.name).limit(300).all()

    email_logs = (
        db.query(EmailLog)
        .filter(EmailLog.company_id == cid, EmailLog.related_type == "crm", EmailLog.related_id == pipeline_id)
        .order_by(EmailLog.created_at.desc())
        .limit(30)
        .all()
    )

    # 템플릿 변수 자동 구성
    import json
    inf = pipeline.influencer
    prod = pipeline.product
    tpl_vars = {
        "influencer_name": inf.name if inf else "",
        "product_name": prod.name if prod else "",
        "sender_name": current_user.username,
    }

    return templates.TemplateResponse("crm/detail.html", {
        "request": request,
        "active_page": "crm",
        "current_user": current_user,
        "pipeline": pipeline,
        "crm_statuses": CRM_STATUSES,
        "status_labels": CRM_STATUS_LABELS,
        "status_colors": STATUS_COLORS,
        "sample_statuses": SAMPLE_LOG_STATUSES,
        "sample_status_labels": SAMPLE_LOG_STATUS_LABELS,
        "sample_status_colors": SAMPLE_STATUS_COLORS,
        "products": products,
        "influencers": influencers,
        "today": date.today().isoformat(),
        "email_logs": email_logs,
        "email_templates": EMAIL_TEMPLATES,
        "template_vars_json": json.dumps(tpl_vars, ensure_ascii=False),
        "prefill_email": inf.contact_email if inf and inf.contact_email else "",
        "prefill_name": inf.name if inf else "",
    })


# ── Edit ───────────────────────────────────────────────────────────────────────

@router.post("/{pipeline_id}/edit")
def crm_update(
    pipeline_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    influencer_id: str = Form(""),
    product_id: str = Form(""),
    status: str = Form("new"),
    last_contact_date: str = Form(""),
    dm_count: int = Form(0),
    notes: str = Form(""),
):
    cid = get_company_id(current_user)
    pipeline = db.query(CrmPipeline).filter(CrmPipeline.company_id == cid, CrmPipeline.id == pipeline_id).first()
    if not pipeline:
        return RedirectResponse("/crm", status_code=302)
    pipeline.influencer_id = influencer_id or None
    pipeline.product_id = product_id or None
    pipeline.status = status
    pipeline.last_contact_date = date.fromisoformat(last_contact_date) if last_contact_date else None
    pipeline.dm_count = dm_count
    pipeline.notes = notes.strip() or None
    db.commit()
    return RedirectResponse(f"/crm/{pipeline_id}?msg=수정되었습니다", status_code=302)


# ── Quick Status (htmx) ────────────────────────────────────────────────────────

@router.post("/{pipeline_id}/status", response_class=HTMLResponse)
def crm_update_status(
    pipeline_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status: str = Form(...),
):
    cid = get_company_id(current_user)
    pipeline = db.query(CrmPipeline).filter(CrmPipeline.company_id == cid, CrmPipeline.id == pipeline_id).first()
    if not pipeline:
        return HTMLResponse('<span class="text-red-500 text-xs">Not found</span>')
    pipeline.status = status
    db.commit()

    color = STATUS_COLORS.get(status, "gray")
    color_map = {
        "gray": "bg-gray-100 text-gray-600",
        "blue": "bg-blue-100 text-blue-700",
        "indigo": "bg-indigo-100 text-indigo-700",
        "amber": "bg-amber-100 text-amber-700",
        "orange": "bg-orange-100 text-orange-700",
        "purple": "bg-purple-100 text-purple-700",
        "green": "bg-green-100 text-green-700",
        "red": "bg-red-100 text-red-600",
    }
    cls = color_map.get(color, "bg-gray-100 text-gray-600")
    opts = "".join(
        f'<option value="{s}"{" selected" if s == status else ""}>{CRM_STATUS_LABELS[s]}</option>'
        for s in CRM_STATUSES
    )
    return HTMLResponse(
        f'<select name="status"'
        f' hx-post="/crm/{pipeline_id}/status"'
        f' hx-target="#status-cell-{pipeline_id}"'
        f' hx-swap="innerHTML"'
        f' hx-trigger="change"'
        f' class="text-xs font-semibold border-0 rounded-full px-2 py-1 cursor-pointer {cls}">'
        f'{opts}'
        f'</select>'
    )


# ── Delete Pipeline ────────────────────────────────────────────────────────────

@router.post("/{pipeline_id}/delete")
def crm_delete(
    pipeline_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = get_company_id(current_user)
    pipeline = db.query(CrmPipeline).filter(CrmPipeline.company_id == cid, CrmPipeline.id == pipeline_id).first()
    if pipeline:
        db.delete(pipeline)
        db.commit()
    return RedirectResponse("/crm?msg=삭제되었습니다", status_code=302)


# ── Sample Logs ────────────────────────────────────────────────────────────────

@router.post("/{pipeline_id}/samples/new")
def sample_create(
    pipeline_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    product_id: str = Form(""),
    tracking_number: str = Form(""),
    status: str = Form("pending"),
    sent_at: str = Form(""),
    notes: str = Form(""),
):
    cid = get_company_id(current_user)
    pipeline = db.query(CrmPipeline).filter(CrmPipeline.company_id == cid, CrmPipeline.id == pipeline_id).first()
    if not pipeline:
        return RedirectResponse("/crm", status_code=302)

    sample = SampleLog(
        company_id=cid,
        pipeline_id=pipeline_id,
        influencer_id=pipeline.influencer_id,
        product_id=product_id or pipeline.product_id or None,
        tracking_number=tracking_number.strip() or None,
        status=status,
        sent_at=date.fromisoformat(sent_at) if sent_at else None,
        notes=notes.strip() or None,
    )
    db.add(sample)
    # Auto-advance pipeline status if still at new/dm_sent
    if pipeline.status in ("new", "dm_sent", "replied"):
        pipeline.status = "sample_sent"
    db.commit()
    return RedirectResponse(f"/crm/{pipeline_id}?msg=샘플+기록+추가됨", status_code=302)


@router.post("/{pipeline_id}/samples/{sample_id}/status")
def sample_update_status(
    pipeline_id: str,
    sample_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status: str = Form(...),
    tracking_number: str = Form(""),
    delivered_at: str = Form(""),
):
    cid = get_company_id(current_user)
    sample = db.query(SampleLog).filter(SampleLog.company_id == cid, SampleLog.id == sample_id).first()
    if not sample:
        return RedirectResponse(f"/crm/{pipeline_id}", status_code=302)
    sample.status = status
    if tracking_number:
        sample.tracking_number = tracking_number.strip()
    if delivered_at:
        sample.delivered_at = date.fromisoformat(delivered_at)
    db.commit()
    return RedirectResponse(f"/crm/{pipeline_id}?msg=샘플+상태+업데이트됨", status_code=302)


@router.post("/{pipeline_id}/samples/{sample_id}/delete")
def sample_delete(
    pipeline_id: str,
    sample_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = get_company_id(current_user)
    sample = db.query(SampleLog).filter(SampleLog.company_id == cid, SampleLog.id == sample_id).first()
    if sample:
        db.delete(sample)
        db.commit()
    return RedirectResponse(f"/crm/{pipeline_id}?msg=샘플+기록+삭제됨", status_code=302)
