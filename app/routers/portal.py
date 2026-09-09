"""
협력사 포털 — 협력사 담당자(role=="partner") + 내부 직원 미리보기
/portal

내부 직원(admin/staff/manager)은 /portal/select 에서 협력사를 골라 같은 화면을
**보기 전용**으로 확인할 수 있다 (app/services/portal_access.py).

협력사에 배정된 제품을 기준으로 4개 일정을 자동 파생해서 보여준다:
  1. 공구 스케줄   — 내 제품이 걸린 캠페인 (시작~종료)
  2. 정산 일정     — 해당 캠페인의 정산 (공구 종료 + N일 = 지급 예정일)
  3. 제품 등록/검수 — 내 제품의 검수 상태
  4. 샘플/발송     — 내 제품의 샘플 발송 로그

모든 조회는 컨텍스트의 partner_id 로 스코프되므로 남의 데이터는 절대 안 보인다.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import nullslast
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.partner import Partner
from app.models.product import Product
from app.models.campaign import Campaign
from app.models.settlement import Settlement
from app.models.attendance import AttendanceLog
from app.models.crm import SampleLog, SAMPLE_LOG_STATUS_LABELS
from app.services.partner_stats import sales_summary
from app.auth.service import verify_password, create_access_token, decode_token
from app.auth.dependencies import require_staff
from app.services.portal_access import (
    PORTAL_AS_COOKIE, PortalCtx, portal_context, switchable_partners,
)
from app.config import settings

router = APIRouter(prefix="/portal")
templates = Jinja2Templates(directory="app/templates")

KST = timezone(timedelta(hours=9))
_COOKIE_KEY = "access_token"
_COOKIE_MAX_AGE = 60 * 60 * 8  # 8h


# ── 협력사 전용 로그인 (OS 로그인과 분리) ─────────────────────────────────────────

@router.get("/login")
def portal_login_page(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(_COOKIE_KEY)
    if token:
        payload = decode_token(token)
        if payload:
            user = db.query(User).filter(User.username == payload.get("sub"), User.is_active == True).first()
            if user and user.current_token == token:
                # 이미 로그인 상태 — 협력사는 포털, 그 외는 OS 홈
                return RedirectResponse("/portal" if user.role == "partner" else "/", status_code=302)
    return templates.TemplateResponse("auth/portal_login.html", {"request": request})


@router.post("/login")
def portal_login(
    request: Request,
    db: Session = Depends(get_db),
    username: str = Form(...),
    password: str = Form(...),
):
    user = (
        db.query(User).filter(User.username == username).first()
        or db.query(User).filter(User.email == username).first()
    )
    if not user or not user.is_active or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            "auth/portal_login.html",
            {"request": request, "error": "아이디 또는 비밀번호가 올바르지 않습니다."},
            status_code=401,
        )
    # 협력사 전용 — 내부 직원 계정은 OS 로그인으로
    if user.role != "partner":
        return templates.TemplateResponse(
            "auth/portal_login.html",
            {"request": request, "error": "내부 직원 계정입니다. OS 로그인을 이용해주세요.", "show_os_link": True},
            status_code=403,
        )

    token = create_access_token(username=user.username, role=user.role)
    user.current_token = token
    user.last_login_at = datetime.utcnow()

    # 출결 기록 (당일 첫 로그인)
    now_kst = datetime.now(KST).replace(tzinfo=None)
    today = now_kst.date()
    if not db.query(AttendanceLog).filter(AttendanceLog.user_id == user.id, AttendanceLog.date == today).first():
        db.add(AttendanceLog(user_id=user.id, date=today, first_login_at=now_kst))
    db.commit()

    response = RedirectResponse("/portal", status_code=302)
    response.set_cookie(
        key=_COOKIE_KEY, value=token, httponly=True, max_age=_COOKIE_MAX_AGE,
        samesite="lax", domain=settings.cookie_domain or None,
    )
    return response


REVIEW_STATUS_LABELS = {
    "draft": "초안",
    "structured": "정리 중",
    "reviewed": "검토 완료",
    "strategy_checked": "전략 검토",
    "approved": "승인",
    "rejected": "반려",
}
CAMPAIGN_STATUS_LABELS = {
    "planning": "기획중",
    "negotiating": "협의중",
    "contracted": "계약완료",
    "active": "진행중",
    "completed": "완료",
    "cancelled": "취소",
}
SETTLEMENT_STATUS_LABELS = {
    "pending": "정산 대기",
    "confirmed": "정산 확정",
    "paid": "지급 완료",
}


# ── 내부 직원 미리보기: 협력사 선택 / 전환 ───────────────────────────────────────

@router.get("/select")
def portal_select(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
):
    """내부 직원이 어떤 협력사 포털을 볼지 고르는 화면."""
    current = request.cookies.get(PORTAL_AS_COOKIE) or ""
    return templates.TemplateResponse("portal/select.html", {
        "request": request, "user": user,
        "partners": switchable_partners(db, user),
        "current_partner_id": current,
    })


@router.get("/switch")
def portal_switch(
    partner_id: str = "",
    next: str = "/portal",
    user: User = Depends(require_staff),
):
    """미리보기 대상 협력사를 쿠키에 저장하고 포털로 이동 (내부 직원 전용)."""
    # 오픈 리다이렉트 방지 — 포털 내부 경로만 허용
    target = next if next.startswith("/portal") else "/portal"
    if not partner_id:
        return RedirectResponse("/portal/select", status_code=302)
    response = RedirectResponse(target, status_code=302)
    response.set_cookie(
        key=PORTAL_AS_COOKIE, value=partner_id, httponly=True, max_age=_COOKIE_MAX_AGE,
        samesite="lax", domain=settings.cookie_domain or None,
    )
    return response


@router.get("/exit")
def portal_exit(user: User = Depends(require_staff)):
    """미리보기 종료 — 쿠키 삭제 후 내부 협력사 관리로 복귀."""
    response = RedirectResponse("/partners", status_code=302)
    response.delete_cookie(PORTAL_AS_COOKIE, domain=settings.cookie_domain or None)
    return response


@router.get("")
def portal_home(
    request: Request,
    db: Session = Depends(get_db),
    ctx: PortalCtx = Depends(portal_context),
):
    user, partner = ctx.user, ctx.partner
    if not partner:
        if ctx.is_admin_view:
            # 내부 직원인데 아직 협력사를 안 골랐다
            return RedirectResponse("/portal/select", status_code=302)
        # 계정은 partner 인데 협력사가 삭제된 경우
        return templates.TemplateResponse("portal/empty.html", {
            "request": request, "user": user, "partner": None,
        })

    # ── 내 제품 ────────────────────────────────────────────────────────────────
    # partner_id 만으로 필터하지 않고 협력사의 소속 회사까지 확인한다 — 어딘가에서
    # 크로스 테넌트 partner_id 가 저장되더라도 포털에는 새지 않도록 하는 2차 방어.
    products = (
        db.query(Product)
        .filter(
            Product.company_id == partner.company_id,
            Product.partner_id == partner.id,
            Product.is_archived == False,
        )
        .order_by(Product.created_at.desc())
        .all()
    )
    product_ids = [p.id for p in products]

    # ── 판매 현황 (결제완료 주문 기준) ──────────────────────────────────────────
    sales = sales_summary(db, product_ids)

    # ── 1. 공구 스케줄 ──────────────────────────────────────────────────────────
    # 캠페인에 협력사가 직접 지정됐거나(partner_id) 내 제품이 걸린(product_id) 공구 모두 노출
    from sqlalchemy import or_
    conds = [Campaign.partner_id == partner.id]
    if product_ids:
        conds.append(Campaign.product_id.in_(product_ids))
    campaigns = (
        db.query(Campaign)
        .filter(
            Campaign.company_id == partner.company_id,
            Campaign.is_archived == False,
            or_(*conds),
        )
        .order_by(nullslast(Campaign.start_date.desc()))
        .all()
    )
    campaign_ids = [c.id for c in campaigns]
    end_date_map = {c.id: c.end_date for c in campaigns}

    # ── 2. 정산 일정 (해당 캠페인의 정산) ───────────────────────────────────────
    settlements = []
    if campaign_ids:
        rows = (
            db.query(Settlement)
            .filter(Settlement.campaign_id.in_(campaign_ids))
            .order_by(Settlement.created_at.desc())
            .all()
        )
        for s in rows:
            end = end_date_map.get(s.campaign_id)
            payout_date = (end + timedelta(days=partner.settlement_days or 14)) if end else None
            settlements.append({"s": s, "payout_date": payout_date})

    # ── 4. 샘플/발송 로그 ──────────────────────────────────────────────────────
    samples = []
    if product_ids:
        samples = (
            db.query(SampleLog)
            .filter(SampleLog.product_id.in_(product_ids))
            .order_by(SampleLog.created_at.desc())
            .all()
        )

    # ── 상단 요약(KPI) ──────────────────────────────────────────────────────────
    from app.models.cs import CSTicket
    active_gongu = sum(1 for c in campaigns if c.status == "active")
    unanswered_cs = db.query(CSTicket).filter(
        CSTicket.partner_id == partner.id,
        CSTicket.is_forwarded_to_partner == True,
        CSTicket.is_archived == False,
        CSTicket.status.in_(["partner_waiting", "partner_pending"]),
    ).count()
    kpi = {
        "active_gongu": active_gongu,
        "product_count": len(products),
        "unanswered_cs": unanswered_cs,
        "revenue": sales.get("revenue", 0) if isinstance(sales, dict) else getattr(sales, "revenue", 0),
    }

    return templates.TemplateResponse("portal/home.html", ctx.tpl(
        active_portal="home",
        products=products,
        campaigns=campaigns,
        settlements=settlements,
        samples=samples,
        sales=sales,
        kpi=kpi,
        review_labels=REVIEW_STATUS_LABELS,
        campaign_labels=CAMPAIGN_STATUS_LABELS,
        settlement_labels=SETTLEMENT_STATUS_LABELS,
        sample_labels=SAMPLE_LOG_STATUS_LABELS,
    ))
