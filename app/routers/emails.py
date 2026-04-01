"""
이메일 발송 & 이력 API

Routes:
  POST /emails/send            — 이메일 발송 (템플릿 or 직접 작성)
  GET  /emails/history         — 이메일 이력 목록 (JSON)
  POST /emails/{log_id}/status — 상태 변경 (replied / converted / etc.)
"""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.email_log import EmailLog, EMAIL_TEMPLATES, EMAIL_STATUSES
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.auth.tenant import get_company_id
from app.services.email_service import send_email, render_template

router = APIRouter(prefix="/emails")
templates = Jinja2Templates(directory="app/templates")


# ── 발송 ──────────────────────────────────────────────────────────────────────

@router.post("/send", response_class=HTMLResponse)
def email_send(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    to_email: str = Form(...),
    to_name: str = Form(""),
    subject: str = Form(""),
    body: str = Form(""),
    template_name: str = Form(""),
    template_vars: str = Form(""),       # JSON string of substitution vars
    related_type: str = Form(""),
    related_id: str = Form(""),
):
    cid = get_company_id(current_user)

    # 템플릿이 선택된 경우 렌더링
    if template_name and template_name in EMAIL_TEMPLATES:
        import json
        try:
            vars_dict = json.loads(template_vars) if template_vars.strip() else {}
        except Exception:
            vars_dict = {}
        try:
            subject, body = render_template(template_name, vars_dict)
        except ValueError:
            return HTMLResponse(
                '<div class="text-red-500 text-sm">잘못된 템플릿입니다</div>',
                status_code=400,
            )

    if not to_email or not subject or not body:
        return HTMLResponse(
            '<div class="text-red-500 text-sm">수신자 이메일, 제목, 내용은 필수입니다</div>',
            status_code=400,
        )

    log = send_email(
        db,
        to_email=to_email.strip(),
        to_name=to_name.strip(),
        subject=subject.strip(),
        body=body.strip(),
        template_name=template_name or "",
        related_type=related_type or "",
        related_id=related_id or "",
        created_by=current_user.username,
        company_id=cid,
    )

    # htmx 응답: 새 로그 행 반환
    status_cls = {
        "sent": "bg-green-100 text-green-700",
        "failed": "bg-red-100 text-red-600",
        "pending": "bg-gray-100 text-gray-500",
    }.get(log.status, "bg-gray-100 text-gray-500")

    label = EMAIL_STATUSES.get(log.status, log.status)
    error_html = (
        f'<span class="text-xs text-red-400">{log.error_msg or ""}</span>'
        if log.status == "failed" else ""
    )

    return HTMLResponse(
        f'<div id="email-send-result" class="flex items-center gap-2 mt-2">'
        f'<span class="text-xs font-semibold px-2 py-0.5 rounded-full {status_cls}">{label}</span>'
        f'<span class="text-xs text-gray-500">→ {log.to_email}</span>'
        f'{error_html}'
        f'</div>'
        f'<div hx-get="/emails/history?related_type={related_type}&related_id={related_id}"'
        f' hx-trigger="load" hx-target="#email-history-list" hx-swap="innerHTML"></div>'
    )


# ── 이력 목록 (htmx fragment) ─────────────────────────────────────────────────

@router.get("/history", response_class=HTMLResponse)
def email_history(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    related_type: str = "",
    related_id: str = "",
):
    cid = get_company_id(current_user)
    q = db.query(EmailLog).filter(EmailLog.company_id == cid)
    if related_type:
        q = q.filter(EmailLog.related_type == related_type)
    if related_id:
        q = q.filter(EmailLog.related_id == related_id)
    logs = q.order_by(EmailLog.created_at.desc()).limit(50).all()

    return templates.TemplateResponse("emails/_history.html", {
        "request": request,
        "logs": logs,
        "email_statuses": EMAIL_STATUSES,
        "related_type": related_type,
        "related_id": related_id,
    })


# ── 상태 변경 (htmx) ──────────────────────────────────────────────────────────

@router.post("/{log_id}/status", response_class=HTMLResponse)
def email_update_status(
    log_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status: str = Form(...),
    related_type: str = Form(""),
    related_id: str = Form(""),
):
    cid = get_company_id(current_user)
    log = db.query(EmailLog).filter(
        EmailLog.id == log_id,
        EmailLog.company_id == cid,
    ).first()
    if not log:
        return HTMLResponse('<span class="text-red-400 text-xs">not found</span>', status_code=404)

    if status in EMAIL_STATUSES:
        log.status = status
        db.commit()

    # 상태 변경 후 이력 목록 재반환
    q = db.query(EmailLog).filter(EmailLog.company_id == cid)
    if related_type:
        q = q.filter(EmailLog.related_type == related_type)
    if related_id:
        q = q.filter(EmailLog.related_id == related_id)
    logs = q.order_by(EmailLog.created_at.desc()).limit(50).all()

    return templates.TemplateResponse("emails/_history.html", {
        "request": request,
        "logs": logs,
        "email_statuses": EMAIL_STATUSES,
        "related_type": related_type,
        "related_id": related_id,
    })
