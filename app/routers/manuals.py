"""
메뉴얼 시스템
GET  /api/manual/{page_key}          — htmx 패널 콘텐츠 (인증 필요)
GET  /settings/manuals               — 슈퍼어드민 목록
GET  /settings/manuals/{key}/edit    — 수정 폼
POST /settings/manuals/{key}         — 저장
"""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.manual import PageManual, DEFAULT_MANUALS
from app.models.user import User
from app.auth.dependencies import get_current_user, require_super_admin

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

PAGE_LABELS = {
    "dashboard": "대시보드", "products": "제품 관리", "brands": "브랜드 관리",
    "influencers": "인플루언서", "campaigns": "캠페인", "proposals": "제안서",
    "applications": "공구 신청", "trends": "트렌드", "trend_engine": "시즌 엔진",
    "settlements": "정산", "automation": "자동화 센터", "outreach": "아웃리치",
    "crm": "CRM 파이프라인", "orders": "주문 관리",
    "sales_pages": "판매 페이지", "sellers": "셀러 관리",
}


def _get_manual(db: Session, page_key: str) -> dict:
    """DB 조회 → 없으면 DEFAULT_MANUALS → 없으면 빈 dict."""
    row = db.query(PageManual).filter(PageManual.page_key == page_key).first()
    if row:
        return {
            "page_key": row.page_key,
            "title": row.title,
            "description": row.description or "",
            "how_to": row.how_to or "",
            "examples": row.examples or "",
            "warnings": row.warnings or "",
            "source": row.source,
        }
    default = DEFAULT_MANUALS.get(page_key)
    if default:
        return {"page_key": page_key, "source": "default", **default}
    return {}


# ── API: htmx 패널 콘텐츠 ────────────────────────────────────────────────────

@router.get("/api/manual/{page_key}", response_class=HTMLResponse)
def manual_content(
    page_key: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    manual = _get_manual(db, page_key)
    return templates.TemplateResponse("manuals/_content.html", {
        "request": request,
        "manual": manual,
        "page_key": page_key,
    })


# ── 어드민: 목록 ─────────────────────────────────────────────────────────────

@router.get("/settings/manuals")
def manuals_list(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    db_rows = {r.page_key: r for r in db.query(PageManual).all()}
    pages = []
    for key, label in PAGE_LABELS.items():
        row = db_rows.get(key)
        pages.append({
            "key": key,
            "label": label,
            "has_custom": row is not None,
            "source": row.source if row else "default",
            "updated_at": row.updated_at if row else None,
        })
    return templates.TemplateResponse("manuals/list.html", {
        "request": request,
        "pages": pages,
        "user": user,
        "active_page": "manuals",
    })


# ── 어드민: 수정 폼 ───────────────────────────────────────────────────────────

@router.get("/settings/manuals/{page_key}/edit")
def manual_edit(
    page_key: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    if page_key not in PAGE_LABELS:
        return RedirectResponse("/settings/manuals?err=존재하지+않는+페이지입니다", status_code=302)
    manual = _get_manual(db, page_key)
    return templates.TemplateResponse("manuals/edit.html", {
        "request": request,
        "manual": manual,
        "page_key": page_key,
        "page_label": PAGE_LABELS.get(page_key, page_key),
        "user": user,
        "active_page": "manuals",
    })


@router.post("/settings/manuals/{page_key}")
def manual_save(
    page_key: str,
    title: str = Form(""),
    description: str = Form(""),
    how_to: str = Form(""),
    examples: str = Form(""),
    warnings: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    if page_key not in PAGE_LABELS:
        return RedirectResponse("/settings/manuals?err=존재하지+않는+페이지입니다", status_code=302)

    row = db.query(PageManual).filter(PageManual.page_key == page_key).first()
    if row:
        row.title = title.strip() or PAGE_LABELS.get(page_key, page_key)
        row.description = description.strip() or None
        row.how_to = how_to.strip() or None
        row.examples = examples.strip() or None
        row.warnings = warnings.strip() or None
        row.source = "manual"
    else:
        row = PageManual(
            page_key=page_key,
            title=title.strip() or PAGE_LABELS.get(page_key, page_key),
            description=description.strip() or None,
            how_to=how_to.strip() or None,
            examples=examples.strip() or None,
            warnings=warnings.strip() or None,
            source="manual",
        )
        db.add(row)
    db.commit()
    return RedirectResponse(
        f"/settings/manuals/{page_key}/edit?msg=저장되었습니다",
        status_code=302,
    )
