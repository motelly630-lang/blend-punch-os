"""
Outreach KPI Management
Routes:
  GET  /outreach           — KPI 대시보드 + 목록
  GET  /outreach/new       — 기록 입력 폼
  POST /outreach/new       — 기록 생성
  GET  /outreach/{id}/edit — 수정 폼
  POST /outreach/{id}/edit — 수정 저장
  POST /outreach/{id}/status — 상태 변경 (htmx)
  POST /outreach/{id}/to-crm — CRM 등록
"""
import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.outreach import OutreachLog, OUTREACH_STATUSES, STATUS_LABELS, STATUS_COLORS
from app.models.email_log import EmailLog, EMAIL_TEMPLATES
from app.models.influencer import Influencer
from app.models.product import Product
from app.models.campaign import Campaign
from app.models.user import User
from app.models.crm import CrmPipeline
from app.auth.dependencies import get_current_user
from app.auth.tenant import get_company_id

router = APIRouter(prefix="/outreach")
templates = Jinja2Templates(directory="app/templates")

BADGE_CLS = {
    "blue":   "bg-blue-100 text-blue-700",
    "amber":  "bg-amber-100 text-amber-700",
    "green":  "bg-green-100 text-green-700",
    "gray":   "bg-gray-100 text-gray-600",
    "red":    "bg-red-100 text-red-600",
}

# 답장/공구확정으로 간주할 상태 (레거시 포함)
_REPLIED_STATUSES = {"replied", "deal", "샘플요청", "샘플발송"}
_DEAL_STATUSES    = {"deal", "샘플발송"}


def _get_or_create_influencer(db: Session, handle: str) -> str | None:
    if not handle:
        return None
    clean = handle.lstrip("@").strip()
    inf = db.query(Influencer).filter(Influencer.handle == clean).first()
    if inf:
        return inf.id
    new_inf = Influencer(
        name=clean, handle=clean, platform="instagram",
        followers=0, status="active", has_campaign_history="false",
    )
    db.add(new_inf)
    db.flush()
    return new_inf.id


def _calc_kpi(logs: list) -> list[dict]:
    """담당자별 KPI 집계: DM수, 답장수, 답장률, 공구수, 공구율."""
    from collections import defaultdict
    data: dict[str, dict] = defaultdict(lambda: {"sent": 0, "replied": 0, "deal": 0})
    for log in logs:
        op = log.operator
        data[op]["sent"] += 1
        if log.sample_status in _REPLIED_STATUSES:
            data[op]["replied"] += 1
        if log.sample_status in _DEAL_STATUSES or log.campaign_id:
            data[op]["deal"] += 1
    result = []
    for op, d in sorted(data.items()):
        s = d["sent"]
        result.append({
            "operator": op,
            "sent":       s,
            "replied":    d["replied"],
            "reply_rate": round(d["replied"] / s * 100) if s else 0,
            "deal":       d["deal"],
            "deal_rate":  round(d["deal"] / s * 100) if s else 0,
        })
    return result


# ── 목록 + KPI 대시보드 ───────────────────────────────────────────────────────

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

    # 전체 데이터 (KPI는 필터 없이)
    all_logs = db.query(OutreachLog).filter(OutreachLog.company_id == cid).all()
    kpi_table = _calc_kpi(all_logs)

    # 날짜별 그룹 (전체 기준)
    from collections import defaultdict
    _all_product_ids = {l.product_id for l in all_logs if l.product_id}
    _all_product_map = {p.id: p for p in db.query(Product).filter(Product.id.in_(_all_product_ids)).all()} if _all_product_ids else {}
    _date_buckets: dict[str, list] = defaultdict(list)
    for l in sorted(all_logs, key=lambda x: (x.outreach_date or "", x.created_at or ""), reverse=False):
        _date_buckets[l.outreach_date or "날짜없음"].append(l)
    date_groups = [
        {
            "date": d,
            "count": len(items),
            "operators": sorted({i.operator for i in items}),
            "items": [
                {
                    "log": i,
                    "product_name": _all_product_map[i.product_id].name if i.product_id and i.product_id in _all_product_map else None,
                    "status_label": STATUS_LABELS.get(i.sample_status, i.sample_status),
                    "status_color": STATUS_COLORS.get(i.sample_status, "gray"),
                }
                for i in items
            ],
        }
        for d, items in sorted(_date_buckets.items(), reverse=True)
    ]

    # 필터 적용
    q = db.query(OutreachLog).filter(OutreachLog.company_id == cid)
    if operator:
        q = q.filter(OutreachLog.operator == operator)
    if status:
        q = q.filter(OutreachLog.sample_status == status)
    if product_id:
        q = q.filter(OutreachLog.product_id == product_id)
    logs = q.order_by(OutreachLog.outreach_date.desc(), OutreachLog.created_at.desc()).all()

    # 관련 데이터 조회
    product_ids    = {log.product_id    for log in logs if log.product_id}
    influencer_ids = {log.influencer_id for log in logs if log.influencer_id}
    campaign_ids   = {log.campaign_id   for log in logs if log.campaign_id}

    product_map = {p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids)).all()} if product_ids else {}
    influencer_map = {i.id: i for i in db.query(Influencer).filter(Influencer.id.in_(influencer_ids)).all()} if influencer_ids else {}
    campaign_map = {c.id: c for c in db.query(Campaign).filter(Campaign.id.in_(campaign_ids)).all()} if campaign_ids else {}

    # CRM pipeline lookup
    crm_pipelines = db.query(CrmPipeline).filter(
        CrmPipeline.company_id == cid,
        CrmPipeline.influencer_id.in_(influencer_ids),
    ).all() if influencer_ids else []
    crm_map = {(p.influencer_id, p.product_id): p.id for p in crm_pipelines}

    enriched = []
    for log in logs:
        enriched.append({
            "log": log,
            "product":         product_map.get(log.product_id),
            "influencer":      influencer_map.get(log.influencer_id),
            "campaign":        campaign_map.get(log.campaign_id),
            "crm_pipeline_id": crm_map.get((log.influencer_id, log.product_id)),
            "status_label":    STATUS_LABELS.get(log.sample_status, log.sample_status),
            "status_color":    STATUS_COLORS.get(log.sample_status, "gray"),
        })

    # 상태별 카운트 (필터된 결과 기준)
    status_counts = {s: 0 for s in OUTREACH_STATUSES}
    for log in logs:
        key = log.sample_status
        if key in status_counts:
            status_counts[key] += 1

    # 이메일 발송 카운트
    outreach_ids = [log.id for log in logs]
    email_counts: dict[str, int] = {}
    if outreach_ids:
        rows = (
            db.query(EmailLog.related_id, func.count(EmailLog.id))
            .filter(
                EmailLog.company_id == cid,
                EmailLog.related_type == "outreach",
                EmailLog.related_id.in_(outreach_ids),
            )
            .group_by(EmailLog.related_id).all()
        )
        email_counts = {r[0]: r[1] for r in rows}

    products  = db.query(Product).filter(Product.company_id == cid, Product.status == "active").order_by(Product.name).all()
    campaigns = db.query(Campaign).filter(Campaign.company_id == cid, Campaign.is_archived == False).order_by(Campaign.name).all()
    operators = sorted({r.operator for r in db.query(OutreachLog.operator).filter(OutreachLog.company_id == cid).distinct()})
    today_count = sum(1 for log in logs if log.outreach_date == date.today().isoformat())

    import json
    return templates.TemplateResponse("outreach/index.html", {
        "request": request,
        "active_page": "outreach",
        "current_user": current_user,
        "kpi_table":       kpi_table,
        "enriched":        enriched,
        "status_counts":   status_counts,
        "outreach_statuses": OUTREACH_STATUSES,
        "status_labels":   STATUS_LABELS,
        "status_colors":   STATUS_COLORS,
        "badge_cls":       BADGE_CLS,
        "products":        products,
        "campaigns":       campaigns,
        "operators":       operators,
        "filter_operator": operator,
        "filter_status":   status,
        "filter_product_id": product_id,
        "today_count":     today_count,
        "total":           len(all_logs),
        "date_groups":     date_groups,
        "today":           date.today().isoformat(),
        "email_counts":    email_counts,
        "email_templates_json": json.dumps(
            {k: {"subject": v["subject"], "body": v["body"]} for k, v in EMAIL_TEMPLATES.items()},
            ensure_ascii=False,
        ),
    })


# ── 신규 등록 ─────────────────────────────────────────────────────────────────

@router.get("/new")
def outreach_new_form(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = get_company_id(current_user)
    products  = db.query(Product).filter(Product.company_id == cid, Product.status == "active").order_by(Product.name).all()
    campaigns = db.query(Campaign).filter(Campaign.company_id == cid, Campaign.is_archived == False).order_by(Campaign.name).all()
    products_json = json.dumps(
        [{"id": p.id, "label": f"{p.name}{' — ' + p.brand if p.brand else ''}"} for p in products],
        ensure_ascii=False,
    )
    return templates.TemplateResponse("outreach/form.html", {
        "request": request,
        "active_page": "outreach",
        "current_user": current_user,
        "products":  products,
        "campaigns": campaigns,
        "outreach_statuses": OUTREACH_STATUSES,
        "status_labels": STATUS_LABELS,
        "today": date.today().isoformat(),
        "log": None,
        "products_json": products_json,
        "current_product_label": "",
    })


@router.post("/new")
def outreach_create(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    operator: str = Form(...),
    influencer_handle: str = Form(...),
    product_id: str = Form(""),
    campaign_id: str = Form(""),
    outreach_date: str = Form(...),
    sample_status: str = Form("sent"),
    sent_time: str = Form(""),
    response_at: str = Form(""),
    status_detail: str = Form(""),
    notes: str = Form(""),
):
    cid = get_company_id(current_user)
    influencer_id = _get_or_create_influencer(db, influencer_handle)

    def _parse_dt(val: str):
        if not val:
            return None
        try:
            return datetime.fromisoformat(val)
        except Exception:
            return None

    # 날짜 + 시간 합쳐서 sent_at 생성
    sent_at = None
    if sent_time and outreach_date:
        try:
            sent_at = datetime.fromisoformat(f"{outreach_date}T{sent_time}")
        except Exception:
            pass

    log = OutreachLog(
        company_id=cid,
        operator=operator.strip(),
        influencer_handle=influencer_handle.lstrip("@").strip(),
        influencer_id=influencer_id,
        product_id=product_id or None,
        campaign_id=campaign_id or None,
        outreach_date=outreach_date,
        sample_status=sample_status,
        sent_at=sent_at,
        response_at=_parse_dt(response_at),
        status_detail=status_detail.strip() or None,
        notes=notes.strip() or None,
    )
    db.add(log)
    db.commit()
    return RedirectResponse("/outreach?msg=아웃리치+기록+저장됨", status_code=302)


# ── 수정 ─────────────────────────────────────────────────────────────────────

@router.get("/{log_id}/edit")
def outreach_edit_form(
    log_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = get_company_id(current_user)
    log = db.query(OutreachLog).filter(OutreachLog.company_id == cid, OutreachLog.id == log_id).first()
    if not log:
        return RedirectResponse("/outreach?err=기록을+찾을+수+없습니다", status_code=302)
    products  = db.query(Product).filter(Product.company_id == cid, Product.status == "active").order_by(Product.name).all()
    campaigns = db.query(Campaign).filter(Campaign.company_id == cid, Campaign.is_archived == False).order_by(Campaign.name).all()
    products_json = json.dumps(
        [{"id": p.id, "label": f"{p.name}{' — ' + p.brand if p.brand else ''}"} for p in products],
        ensure_ascii=False,
    )
    current_product_label = ""
    if log and log.product_id:
        for p in products:
            if p.id == log.product_id:
                current_product_label = f"{p.name}{' — ' + p.brand if p.brand else ''}"
                break
    return templates.TemplateResponse("outreach/form.html", {
        "request": request,
        "active_page": "outreach",
        "current_user": current_user,
        "products":  products,
        "campaigns": campaigns,
        "outreach_statuses": OUTREACH_STATUSES,
        "status_labels": STATUS_LABELS,
        "today": date.today().isoformat(),
        "log": log,
        "products_json": products_json,
        "current_product_label": current_product_label,
    })


@router.post("/{log_id}/edit")
def outreach_update(
    log_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    operator: str = Form(...),
    influencer_handle: str = Form(...),
    product_id: str = Form(""),
    campaign_id: str = Form(""),
    outreach_date: str = Form(...),
    sample_status: str = Form("sent"),
    sent_time: str = Form(""),
    response_at: str = Form(""),
    status_detail: str = Form(""),
    notes: str = Form(""),
):
    cid = get_company_id(current_user)
    log = db.query(OutreachLog).filter(OutreachLog.company_id == cid, OutreachLog.id == log_id).first()
    if not log:
        return RedirectResponse("/outreach", status_code=302)

    def _parse_dt(val: str):
        if not val:
            return None
        try:
            return datetime.fromisoformat(val)
        except Exception:
            return None

    sent_at = None
    if sent_time and outreach_date:
        try:
            sent_at = datetime.fromisoformat(f"{outreach_date}T{sent_time}")
        except Exception:
            pass

    log.operator          = operator.strip()
    log.influencer_handle = influencer_handle.lstrip("@").strip()
    log.influencer_id     = _get_or_create_influencer(db, influencer_handle)
    log.product_id        = product_id or None
    log.campaign_id       = campaign_id or None
    log.outreach_date     = outreach_date
    log.sample_status     = sample_status
    log.sent_at           = sent_at
    log.response_at       = _parse_dt(response_at)
    log.status_detail     = status_detail.strip() or None
    log.notes             = notes.strip() or None
    db.commit()
    return RedirectResponse("/outreach?msg=수정됨", status_code=302)


# ── 상태 변경 (htmx) ──────────────────────────────────────────────────────────

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

    # 답장 시간 자동 기록
    if sample_status in ("replied", "deal") and not log.response_at:
        log.response_at = datetime.utcnow()

    log.sample_status = sample_status
    db.commit()

    color = STATUS_COLORS.get(sample_status, "gray")
    cls = BADGE_CLS.get(color, "bg-gray-100 text-gray-600")
    label = STATUS_LABELS.get(sample_status, sample_status)

    opts = "".join(
        f'<option value="{s}"{" selected" if s == sample_status else ""}>{STATUS_LABELS.get(s, s)}</option>'
        for s in OUTREACH_STATUSES
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


# ── CRM 등록 ──────────────────────────────────────────────────────────────────

OUTREACH_TO_CRM_STATUS = {
    "sent":     "dm_sent",
    "replied":  "sample_requested",
    "deal":     "sample_sent",
    "hold":     "negotiating",
    "rejected": "rejected",
    # 레거시
    "제안발송": "dm_sent",
    "샘플요청": "sample_requested",
    "샘플발송": "sample_sent",
    "보류":     "negotiating",
    "거절":     "rejected",
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
