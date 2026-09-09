"""CS(고객서비스) 통합 관리 — 내부 직원/관리자용 라우터.

권한: require_feature("cs") (기능플래그 + role staff 이상), 테넌트 격리 get_company_id.
협업사(role=partner) 화면은 /portal/cs (별도, 5단계).

경로 순서 주의: 구체 경로(/new, /export, /settings/…)를 와일드카드 /{cs_id} 보다 먼저 선언.
"""
import io
from pathlib import Path
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import RedirectResponse, FileResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.dependencies import require_feature
from app.auth.tenant import get_company_id
from app.models.user import User
from app.models.cs import CSTicket, CSType, CSActivity, CSAttachment, CSGuide, CSTemplate
from app.models.product import Product
from app.models.partner import Partner
from app.models.influencer import Influencer
from app.cs import constants as C
from app.cs.numbering import gen_cs_number as _gen_cs_number
from app.cs.uploads import save_cs_image, save_cs_file
from app.cs.notify import notify, staff_ids, partner_user_ids
from app.models.cs import CSNotification, CSDownloadLog

router = APIRouter(prefix="/cs")
templates = Jinja2Templates(directory="app/templates")


# ── 공통 헬퍼 ─────────────────────────────────────────────────────────────────

def _active_types(db: Session, cid: int):
    return (
        db.query(CSType)
        .filter(CSType.company_id == cid, CSType.is_active == True)
        .order_by(CSType.sort_order, CSType.name)
        .all()
    )


def _display_maps(db: Session, cid: int, tickets):
    """목록 표시용 이름 매핑 (N+1 방지)."""
    pids = {t.product_id for t in tickets if t.product_id}
    tyids = {t.cs_type_id for t in tickets if t.cs_type_id}
    paids = {t.partner_id for t in tickets if t.partner_id}
    iids = {t.influencer_id for t in tickets if t.influencer_id}
    uids = {t.assigned_user_id for t in tickets if t.assigned_user_id}
    products = {p.id: p.name for p in db.query(Product.id, Product.name).filter(Product.id.in_(pids))} if pids else {}
    types = {t.id: t.name for t in db.query(CSType.id, CSType.name).filter(CSType.id.in_(tyids))} if tyids else {}
    partners = {p.id: p.name for p in db.query(Partner.id, Partner.name).filter(Partner.id.in_(paids))} if paids else {}
    infs = {i.id: i.name for i in db.query(Influencer.id, Influencer.name).filter(Influencer.id.in_(iids))} if iids else {}
    users = {u.id: u.username for u in db.query(User.id, User.username).filter(User.id.in_(uids))} if uids else {}
    return {"products": products, "types": types, "partners": partners, "influencers": infs, "users": users}


def _base_ctx(request: Request, user: User):
    """모든 CS 화면 공통 컨텍스트 (상태/처리방법/접수경로 라벨·배지)."""
    return {
        "request": request,
        "current_user": user,
        "active_page": "cs",
        "now": datetime.utcnow(),
        "STATUS_LABELS": C.CS_STATUS_LABELS,
        "STATUS_BADGES": C.CS_STATUS_BADGES,
        "STATUSES": C.CS_STATUSES,
        "RESOLUTION_LABELS": C.CS_RESOLUTION_LABELS,
        "RESOLUTIONS": C.CS_RESOLUTIONS,
        "CHANNEL_LABELS": C.CS_CHANNEL_LABELS,
        "CHANNELS": C.CS_CHANNELS,
        "ORDER_SOURCES": C.ORDER_SOURCES,
        "ORDER_SOURCE_LABELS": C.ORDER_SOURCE_LABELS,
        "SALES_CHANNELS": C.SALES_CHANNELS,
        "SALES_CHANNEL_LABELS": C.SALES_CHANNEL_LABELS,
        "RESOLUTION_FIELDS": C.CS_RESOLUTION_FIELDS,
    }


def _get_ticket(db: Session, cid: int, cs_id: str):
    return db.query(CSTicket).filter(CSTicket.id == cs_id, CSTicket.company_id == cid).first()


def _is_admin(user: User) -> bool:
    return user.role == "admin"


def _log(db, cid, ticket, user, activity_type, visibility=C.VIS_INTERNAL, body=None, from_value=None, to_value=None):
    db.add(CSActivity(
        company_id=cid, cs_ticket_id=ticket.id,
        activity_type=activity_type, visibility=visibility,
        body=body, from_value=from_value, to_value=to_value,
        actor_id=user.id, actor_name=user.username, actor_role=user.role,
    ))
    ticket.updated_by = user.id


# ── 목록 (요구사항 14) ────────────────────────────────────────────────────────

# 빠른 탭 → 필터 매핑
QUICK_TABS = [
    ("all",             "전체"),
    ("new",             "신규 인입"),
    ("partner_submitted", "협업사 접수"),
    ("internal_review", "내부 확인중"),
    ("partner_waiting", "협업사 답변대기"),
    ("processing",      "처리중"),
    ("due_today",       "오늘 처리예정"),
    ("overdue",         "지연건"),
    ("completed",       "처리완료"),
    ("hold",            "보류"),
]


@router.get("")
def cs_list(
    request: Request,
    tab: str = "all",
    q: str = "",
    status: str = "",
    cs_type_id: str = "",
    partner_id: str = "",
    urgent: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_feature("cs")),
):
    cid = get_company_id(user)
    query = db.query(CSTicket).filter(
        CSTicket.company_id == cid,
        CSTicket.is_archived == False,
    )

    # 빠른 탭
    now = datetime.utcnow()
    if tab == "new":
        query = query.filter(CSTicket.status == "received")
    elif tab == "partner_submitted":
        query = query.filter(CSTicket.submitted_by_partner == True,
                             CSTicket.status.notin_(["completed", "closed"]))
    elif tab in ("internal_review", "partner_waiting", "processing", "completed", "hold"):
        query = query.filter(CSTicket.status == tab)
    elif tab == "due_today":
        start = datetime(now.year, now.month, now.day)
        end = datetime(now.year, now.month, now.day, 23, 59, 59)
        query = query.filter(CSTicket.due_at >= start, CSTicket.due_at <= end,
                             CSTicket.status.notin_(["completed", "closed"]))
    elif tab == "overdue":
        query = query.filter(CSTicket.due_at < now,
                             CSTicket.status.notin_(["completed", "closed"]))

    # 개별 필터
    if status:
        query = query.filter(CSTicket.status == status)
    if cs_type_id:
        query = query.filter(CSTicket.cs_type_id == cs_type_id)
    if partner_id:
        query = query.filter(CSTicket.partner_id == partner_id)
    if urgent == "1":
        query = query.filter(CSTicket.is_urgent == True)

    # 검색 (요구사항 14: CS번호/주문번호/고객명/연락처/상품명/송장/인플루언서/협업사)
    if q:
        like = f"%{q.strip()}%"
        # 상품명 검색은 external_product_name + 연결된 product.name 둘 다 커버
        matched_pids = [
            r[0] for r in db.query(Product.id).filter(
                Product.company_id == cid, Product.name.ilike(like)
            ).all()
        ]
        conds = [
            CSTicket.cs_number.ilike(like),
            CSTicket.external_order_number.ilike(like),
            CSTicket.customer_name.ilike(like),
            CSTicket.customer_phone.ilike(like),
            CSTicket.external_product_name.ilike(like),
            CSTicket.tracking_number.ilike(like),
            CSTicket.campaign_name.ilike(like),
        ]
        if matched_pids:
            conds.append(CSTicket.product_id.in_(matched_pids))
        query = query.filter(or_(*conds))

    tickets = query.order_by(CSTicket.created_at.desc()).all()
    maps = _display_maps(db, cid, tickets)

    # 빠른 탭 카운트
    base = db.query(CSTicket).filter(CSTicket.company_id == cid, CSTicket.is_archived == False)
    start = datetime(now.year, now.month, now.day)
    end = datetime(now.year, now.month, now.day, 23, 59, 59)
    counts = {
        "all": base.count(),
        "new": base.filter(CSTicket.status == "received").count(),
        "partner_submitted": base.filter(CSTicket.submitted_by_partner == True,
                                         CSTicket.status.notin_(["completed", "closed"])).count(),
        "internal_review": base.filter(CSTicket.status == "internal_review").count(),
        "partner_waiting": base.filter(CSTicket.status == "partner_waiting").count(),
        "processing": base.filter(CSTicket.status == "processing").count(),
        "due_today": base.filter(CSTicket.due_at >= start, CSTicket.due_at <= end,
                                 CSTicket.status.notin_(["completed", "closed"])).count(),
        "overdue": base.filter(CSTicket.due_at < now,
                               CSTicket.status.notin_(["completed", "closed"])).count(),
        "completed": base.filter(CSTicket.status == "completed").count(),
        "hold": base.filter(CSTicket.status == "hold").count(),
    }

    ctx = _base_ctx(request, user)
    ctx.update({
        "tickets": tickets,
        "maps": maps,
        "counts": counts,
        "quick_tabs": QUICK_TABS,
        "current_tab": tab,
        "q": q,
        "f_status": status,
        "f_type": cs_type_id,
        "f_partner": partner_id,
        "f_urgent": urgent,
        "cs_types": _active_types(db, cid),
        "partners": db.query(Partner).filter(Partner.company_id == cid, Partner.is_active == True).order_by(Partner.name).all(),
        "now": now,
    })
    return templates.TemplateResponse("cs/list.html", ctx)


# ── 등록 (요구사항 5) ─────────────────────────────────────────────────────────

@router.get("/new")
def cs_new_form(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_feature("cs")),
):
    cid = get_company_id(user)
    products = db.query(Product).filter(Product.company_id == cid, Product.is_archived == False).order_by(Product.name).all()
    ctx = _base_ctx(request, user)
    ctx.update({
        "ticket": None,
        "cs_types": _active_types(db, cid),
        # 검색형 상품 선택용 (클라이언트 필터). partner_id 포함 → 표시용
        "products_json": [{"id": p.id, "name": p.name, "brand": p.brand or ""} for p in products],
        "partners": db.query(Partner).filter(Partner.company_id == cid, Partner.is_active == True).order_by(Partner.name).all(),
        "influencers": db.query(Influencer).filter(Influencer.company_id == cid, Influencer.is_archived == False).order_by(Influencer.name).all(),
        "staff_users": db.query(User).filter(User.company_id == cid, User.role.in_(["admin", "staff", "manager"]), User.is_active == True).order_by(User.username).all(),
    })
    return templates.TemplateResponse("cs/form.html", ctx)


def _parse_dt(v: str):
    if not v:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(v.strip(), fmt)
        except ValueError:
            continue
    return None


def _parse_float(v: str):
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def _parse_int(v: str):
    f = _parse_float(v)
    return int(f) if f is not None else None


@router.post("/new")
def cs_create(
    request: Request,
    # 접수 기본
    channel: str = Form(""),
    is_urgent: str = Form(""),
    cs_type_id: str = Form(""),
    assigned_user_id: str = Form(""),
    due_at: str = Form(""),
    # 상품
    product_id: str = Form(""),
    external_product_name: str = Form(""),
    product_option: str = Form(""),
    quantity: str = Form(""),
    partner_id: str = Form(""),
    influencer_id: str = Form(""),
    campaign_name: str = Form(""),
    # 주문·고객
    external_order_number: str = Form(""),
    order_source: str = Form(""),
    sales_channel: str = Form(""),
    customer_name: str = Form(""),
    customer_phone: str = Form(""),
    customer_address: str = Form(""),
    customer_memo: str = Form(""),
    purchased_at: str = Form(""),
    shipped_at: str = Form(""),
    delivered_at: str = Form(""),
    courier: str = Form(""),
    tracking_number: str = Form(""),
    payment_amount: str = Form(""),
    # CS 내용
    inquiry_content: str = Form(""),
    customer_request: str = Form(""),
    internal_memo: str = Form(""),
    partner_note: str = Form(""),
    # 사진 첨부
    images: list[UploadFile] = File(None),
    images_public: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_feature("cs")),
):
    cid = get_company_id(user)

    # 상품 규칙: product_id 우선. 있으면 partner_id 를 product.partner_id 로 스냅샷.
    prod = None
    if product_id:
        prod = db.query(Product).filter(Product.id == product_id, Product.company_id == cid).first()
    if prod:
        product_id_val = prod.id
        external_name_val = None
        partner_val = prod.partner_id or (partner_id or None)
    else:
        product_id_val = None
        external_name_val = external_product_name.strip() or None
        partner_val = partner_id or None

    ticket = CSTicket(
        company_id=cid,
        cs_number=_gen_cs_number(db, cid),
        received_at=datetime.utcnow(),
        channel=channel or None,
        is_urgent=(is_urgent == "1"),
        status=C.CS_STATUS_DEFAULT,
        cs_type_id=cs_type_id or None,
        assigned_user_id=assigned_user_id or None,
        due_at=_parse_dt(due_at),
        product_id=product_id_val,
        external_product_name=external_name_val,
        product_option=product_option or None,
        quantity=_parse_int(quantity),
        partner_id=partner_val,
        influencer_id=influencer_id or None,
        campaign_name=campaign_name or None,
        external_order_number=external_order_number or None,
        order_source=order_source or None,
        sales_channel=sales_channel or None,
        customer_name=customer_name or None,
        customer_phone=customer_phone or None,
        customer_address=customer_address or None,
        customer_memo=customer_memo or None,
        purchased_at=_parse_dt(purchased_at),
        shipped_at=_parse_dt(shipped_at),
        delivered_at=_parse_dt(delivered_at),
        courier=courier or None,
        tracking_number=tracking_number or None,
        payment_amount=_parse_float(payment_amount),
        inquiry_content=inquiry_content or None,
        customer_request=customer_request or None,
        internal_memo=internal_memo or None,
        partner_note=partner_note or None,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(ticket)
    db.flush()  # ticket.id 확보

    # 타임라인: 등록 기록
    db.add(CSActivity(
        company_id=cid, cs_ticket_id=ticket.id,
        activity_type=C.ACT_CREATED, visibility=C.VIS_INTERNAL,
        to_value=C.CS_STATUS_LABELS.get(ticket.status),
        actor_id=user.id, actor_name=user.username, actor_role=user.role,
    ))

    # 사진 첨부 저장 (비공개 저장소)
    is_public = (images_public == "1")
    saved = 0
    for f in (images or []):
        if not f or not getattr(f, "filename", ""):
            continue
        if saved >= C.CS_MAX_IMAGES:
            break
        try:
            meta = save_cs_image(f, cid, ticket.id)
        except ValueError:
            continue  # 형식/용량 위반 파일은 건너뜀
        if not meta:
            continue
        db.add(CSAttachment(
            company_id=cid, cs_ticket_id=ticket.id,
            is_public=is_public, uploaded_by=user.id, uploaded_by_name=user.username,
            **meta,
        ))
        saved += 1
    if saved:
        db.add(CSActivity(
            company_id=cid, cs_ticket_id=ticket.id,
            activity_type=C.ACT_ATTACHMENT, visibility=C.VIS_INTERNAL,
            to_value=f"이미지 {saved}장",
            actor_id=user.id, actor_name=user.username, actor_role=user.role,
        ))

    # 알림: 담당자 배정 / 긴급이면 스태프 전체
    recips = []
    if ticket.assigned_user_id:
        recips.append(ticket.assigned_user_id)
    if ticket.is_urgent:
        recips += staff_ids(db, cid, exclude=user.id)
    recips = [r for r in recips if r and r != user.id]
    if recips:
        ntype = "urgent" if ticket.is_urgent else "assigned"
        title = ("긴급 CS 등록" if ticket.is_urgent else "새 CS 배정") + f": {ticket.cs_number}"
        notify(db, cid, recips, ntype, title, cs_id=ticket.id)

    db.commit()
    return RedirectResponse(f"/cs/{ticket.id}?msg=CS가+등록되었습니다", status_code=303)


# ── 첨부파일 스트리밍 (인증 필수, /static 미노출) — 요구사항 10·21 ──────────────
# 주의: 반드시 와일드카드 /{cs_id} 보다 먼저 선언.

@router.get("/attachments/{att_id}")
def cs_attachment_raw(
    att_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_feature("cs")),
):
    cid = get_company_id(user)
    att = (
        db.query(CSAttachment)
        .filter(CSAttachment.id == att_id, CSAttachment.company_id == cid, CSAttachment.is_deleted == False)
        .first()
    )
    if not att:
        return Response(status_code=404)
    path = Path(att.stored_path)
    if not path.exists():
        return Response(status_code=404)
    # 이미지는 인라인, 그 외(영상/문서)는 다운로드
    headers = None
    if att.file_type != "image" and att.file_name:
        from urllib.parse import quote
        headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(att.file_name)}"}
    return FileResponse(str(path), media_type=att.content_type or "application/octet-stream", headers=headers)


# ── 워크플로 액션 (요구사항 8·9·11) — 모두 타임라인 기록 ─────────────────────────

@router.post("/{cs_id}/status")
def cs_change_status(
    cs_id: str,
    status: str = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_feature("cs")),
):
    cid = get_company_id(user)
    ticket = _get_ticket(db, cid, cs_id)
    if not ticket:
        return RedirectResponse("/cs?err=CS를+찾을+수+없습니다", status_code=303)
    if status not in C.CS_STATUS_CODES:
        return RedirectResponse(f"/cs/{cs_id}?err=잘못된+상태값", status_code=303)

    prev = ticket.status
    if prev != status:
        was_closed = prev in ("completed", "closed")
        ticket.status = status
        if status == "completed":
            ticket.completed_at = datetime.utcnow()
        elif was_closed and status not in ("completed", "closed"):
            ticket.completed_at = None
            _log(db, cid, ticket, user, C.ACT_REOPENED, to_value=C.CS_STATUS_LABELS.get(status), body=note or None)
        _log(db, cid, ticket, user, C.ACT_STATUS_CHANGE,
             from_value=C.CS_STATUS_LABELS.get(prev), to_value=C.CS_STATUS_LABELS.get(status), body=note or None)
        if ticket.assigned_user_id and ticket.assigned_user_id != user.id:
            notify(db, cid, [ticket.assigned_user_id], "status",
                   f"상태 변경({C.CS_STATUS_LABELS.get(status)}): {ticket.cs_number}", cs_id=ticket.id)
        db.commit()
    return RedirectResponse(f"/cs/{cs_id}?msg=상태가+변경되었습니다", status_code=303)


@router.post("/{cs_id}/assign")
def cs_assign(
    cs_id: str,
    assigned_user_id: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_feature("cs")),
):
    cid = get_company_id(user)
    ticket = _get_ticket(db, cid, cs_id)
    if not ticket:
        return RedirectResponse("/cs?err=CS를+찾을+수+없습니다", status_code=303)

    new_id = assigned_user_id or None
    if new_id != ticket.assigned_user_id:
        ticket.assigned_user_id = new_id
        target = db.query(User).filter(User.id == new_id).first() if new_id else None
        _log(db, cid, ticket, user, C.ACT_ASSIGN, to_value=(target.username if target else "미지정"))
        if new_id and new_id != user.id:
            notify(db, cid, [new_id], "assigned", f"CS 담당자 배정: {ticket.cs_number}", cs_id=ticket.id)
        db.commit()
    return RedirectResponse(f"/cs/{cs_id}?msg=담당자가+지정되었습니다", status_code=303)


@router.post("/{cs_id}/forward-partner")
def cs_forward_partner(
    cs_id: str,
    partner_note: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_feature("cs")),
):
    cid = get_company_id(user)
    ticket = _get_ticket(db, cid, cs_id)
    if not ticket:
        return RedirectResponse("/cs?err=CS를+찾을+수+없습니다", status_code=303)
    if not ticket.partner_id:
        return RedirectResponse(f"/cs/{cs_id}?err=연결된+협업사가+없습니다", status_code=303)

    if partner_note.strip():
        ticket.partner_note = partner_note.strip()
    ticket.is_forwarded_to_partner = True
    ticket.forwarded_at = datetime.utcnow()
    # 전달 시 상태를 협업사 답변대기로 (received/internal_review 인 경우만 자동 전환)
    if ticket.status in ("received", "internal_review", "partner_pending"):
        prev = ticket.status
        ticket.status = "partner_waiting"
        _log(db, cid, ticket, user, C.ACT_STATUS_CHANGE,
             from_value=C.CS_STATUS_LABELS.get(prev), to_value=C.CS_STATUS_LABELS.get("partner_waiting"))
    _log(db, cid, ticket, user, C.ACT_FORWARD_PARTNER, visibility=C.VIS_PARTNER, body=ticket.partner_note or None)
    precips = partner_user_ids(db, ticket.partner_id, exclude=user.id)
    if precips:
        notify(db, cid, precips, "forwarded", f"CS 전달 도착: {ticket.cs_number}", body=ticket.partner_note or "", cs_id=ticket.id)
    db.commit()
    return RedirectResponse(f"/cs/{cs_id}?msg=협업사에+전달되었습니다", status_code=303)


@router.post("/{cs_id}/resolution")
def cs_resolution(
    cs_id: str,
    resolution_type: str = Form(""),
    refund_amount: str = Form(""),
    # 환불
    refund_due_date: str = Form(""),
    refund_done_date: str = Form(""),
    refund_by: str = Form(""),
    refund_memo: str = Form(""),
    # 재발송
    resend_product: str = Form(""),
    resend_option: str = Form(""),
    resend_qty: str = Form(""),
    resend_due_date: str = Form(""),
    resend_done_date: str = Form(""),
    resend_courier: str = Form(""),
    resend_tracking: str = Form(""),
    resend_by: str = Form(""),
    # 교환/반품
    collect_needed: str = Form(""),
    collect_due_date: str = Form(""),
    collect_tracking: str = Form(""),
    collect_done_date: str = Form(""),
    inspect_result: str = Form(""),
    extra_shipping_fee: str = Form(""),
    handler: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_feature("cs")),
):
    cid = get_company_id(user)
    ticket = _get_ticket(db, cid, cs_id)
    if not ticket:
        return RedirectResponse("/cs?err=CS를+찾을+수+없습니다", status_code=303)
    if resolution_type and resolution_type not in C.CS_RESOLUTION_CODES:
        return RedirectResponse(f"/cs/{cs_id}?err=잘못된+처리방법", status_code=303)

    all_vals = {
        "refund_due_date": refund_due_date, "refund_done_date": refund_done_date,
        "refund_by": refund_by, "refund_memo": refund_memo,
        "resend_product": resend_product, "resend_option": resend_option, "resend_qty": resend_qty,
        "resend_due_date": resend_due_date, "resend_done_date": resend_done_date,
        "resend_courier": resend_courier, "resend_tracking": resend_tracking, "resend_by": resend_by,
        "collect_needed": collect_needed, "collect_due_date": collect_due_date,
        "collect_tracking": collect_tracking, "collect_done_date": collect_done_date,
        "inspect_result": inspect_result, "extra_shipping_fee": extra_shipping_fee, "handler": handler,
    }
    # 처리방법별 해당 필드만 저장 (refund_amount 는 first-class 컬럼)
    wanted = [f for f in C.CS_RESOLUTION_FIELDS.get(resolution_type, []) if f != "refund_amount"]
    detail = {k: all_vals[k].strip() for k in wanted if all_vals.get(k, "").strip()}

    prev = ticket.resolution_type
    ticket.resolution_type = resolution_type or None
    ticket.refund_amount = _parse_float(refund_amount)
    ticket.resolution_detail = detail or None
    _log(db, cid, ticket, user, C.ACT_RESOLUTION,
         from_value=C.CS_RESOLUTION_LABELS.get(prev) if prev else None,
         to_value=C.CS_RESOLUTION_LABELS.get(resolution_type) if resolution_type else "해제")
    db.commit()
    return RedirectResponse(f"/cs/{cs_id}?msg=처리방법이+저장되었습니다", status_code=303)


# 내부 직원이 작성 가능한 댓글 유형 → visibility 매핑
_COMMENT_VIS = {
    C.ACT_INTERNAL_MEMO:   C.VIS_INTERNAL,
    C.ACT_PARTNER_PUBLIC:  C.VIS_PARTNER,
    C.ACT_CUSTOMER_NOTICE: C.VIS_ALL,
}


@router.post("/{cs_id}/comment")
def cs_comment(
    cs_id: str,
    comment_type: str = Form(...),
    body: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_feature("cs")),
):
    cid = get_company_id(user)
    ticket = _get_ticket(db, cid, cs_id)
    if not ticket:
        return RedirectResponse("/cs?err=CS를+찾을+수+없습니다", status_code=303)
    if comment_type not in _COMMENT_VIS or not body.strip():
        return RedirectResponse(f"/cs/{cs_id}?err=잘못된+댓글", status_code=303)

    _log(db, cid, ticket, user, comment_type, visibility=_COMMENT_VIS[comment_type], body=body.strip())
    db.commit()
    return RedirectResponse(f"/cs/{cs_id}?msg=기록이+추가되었습니다", status_code=303)


# ── 첨부파일 추가/공개전환/삭제 (요구사항 10) ─────────────────────────────────

@router.post("/{cs_id}/attachments")
def cs_add_attachments(
    cs_id: str,
    files: list[UploadFile] = File(None),
    is_public: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_feature("cs")),
):
    cid = get_company_id(user)
    ticket = _get_ticket(db, cid, cs_id)
    if not ticket:
        return RedirectResponse("/cs?err=CS를+찾을+수+없습니다", status_code=303)

    # 현재 개수(제한 체크용)
    existing = db.query(CSAttachment).filter(
        CSAttachment.cs_ticket_id == ticket.id, CSAttachment.is_deleted == False
    ).all()
    img_cnt = sum(1 for a in existing if a.file_type == "image")
    other_cnt = sum(1 for a in existing if a.file_type != "image")

    public = (is_public == "1")
    saved, skipped = 0, 0
    for f in (files or []):
        if not f or not getattr(f, "filename", ""):
            continue
        try:
            meta = save_cs_file(f, cid, ticket.id)
        except ValueError:
            skipped += 1
            continue
        if not meta:
            continue
        # 개수 제한
        if meta["file_type"] == "image":
            if img_cnt >= C.CS_MAX_IMAGES:
                skipped += 1
                continue
            img_cnt += 1
        else:
            if other_cnt >= C.CS_MAX_FILES:
                skipped += 1
                continue
            other_cnt += 1
        db.add(CSAttachment(
            company_id=cid, cs_ticket_id=ticket.id, is_public=public,
            uploaded_by=user.id, uploaded_by_name=user.username, **meta,
        ))
        saved += 1

    if saved:
        _log(db, cid, ticket, user, C.ACT_ATTACHMENT, to_value=f"파일 {saved}개")
        db.commit()
    msg = f"첨부+{saved}개+추가" + (f"+({skipped}개+제외)" if skipped else "")
    return RedirectResponse(f"/cs/{cs_id}?msg={msg}", status_code=303)


@router.post("/{cs_id}/attachments/{att_id}/toggle-public")
def cs_toggle_attachment_public(
    cs_id: str,
    att_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_feature("cs")),
):
    cid = get_company_id(user)
    att = db.query(CSAttachment).filter(
        CSAttachment.id == att_id, CSAttachment.cs_ticket_id == cs_id,
        CSAttachment.company_id == cid, CSAttachment.is_deleted == False,
    ).first()
    if att:
        att.is_public = not att.is_public
        db.commit()
    return RedirectResponse(f"/cs/{cs_id}?msg=첨부+공개설정+변경", status_code=303)


@router.post("/{cs_id}/attachments/{att_id}/delete")
def cs_delete_attachment(
    cs_id: str,
    att_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_feature("cs")),
):
    cid = get_company_id(user)
    att = db.query(CSAttachment).filter(
        CSAttachment.id == att_id, CSAttachment.cs_ticket_id == cs_id,
        CSAttachment.company_id == cid, CSAttachment.is_deleted == False,
    ).first()
    if not att:
        return RedirectResponse(f"/cs/{cs_id}?err=첨부를+찾을+수+없습니다", status_code=303)
    # 삭제 권한: 업로더 본인 또는 관리자 (요구사항 10 첨부 삭제 권한 제한)
    if att.uploaded_by != user.id and not _is_admin(user):
        return RedirectResponse(f"/cs/{cs_id}?err=삭제+권한이+없습니다", status_code=303)
    att.is_deleted = True   # 소프트 삭제
    db.commit()
    return RedirectResponse(f"/cs/{cs_id}?msg=첨부가+삭제되었습니다", status_code=303)


# ── 상품별 CS 가이드 관리 (요구사항 12) — 관리자 전용 ────────────────────────────

@router.get("/guides")
def cs_guides_list(
    request: Request,
    product_id: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_feature("cs")),
):
    cid = get_company_id(user)
    q = db.query(CSGuide).filter(CSGuide.company_id == cid)
    if product_id:
        q = q.filter(CSGuide.product_id == product_id)
    guides = q.order_by(CSGuide.product_id, CSGuide.sort_order, CSGuide.created_at).all()
    prod_map = {p.id: p.name for p in db.query(Product.id, Product.name).filter(Product.company_id == cid)}
    ctx = _base_ctx(request, user)
    ctx.update({
        "guides": guides, "prod_map": prod_map, "is_admin": _is_admin(user),
        "f_product": product_id,
        "products": db.query(Product).filter(Product.company_id == cid, Product.is_archived == False).order_by(Product.name).all(),
    })
    return templates.TemplateResponse("cs/guides_list.html", ctx)


@router.get("/guides/new")
def cs_guide_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require_feature("cs"))):
    if not _is_admin(user):
        return RedirectResponse("/cs/guides?err=관리자만+가능합니다", status_code=303)
    cid = get_company_id(user)
    ctx = _base_ctx(request, user)
    ctx.update({
        "guide": None,
        "products": db.query(Product).filter(Product.company_id == cid, Product.is_archived == False).order_by(Product.name).all(),
    })
    return templates.TemplateResponse("cs/guide_form.html", ctx)


@router.post("/guides/new")
def cs_guide_create(
    product_id: str = Form(""),
    title: str = Form(...),
    content_internal: str = Form(""),
    content_partner: str = Form(""),
    sort_order: str = Form("0"),
    db: Session = Depends(get_db),
    user: User = Depends(require_feature("cs")),
):
    if not _is_admin(user):
        return RedirectResponse("/cs/guides?err=관리자만+가능합니다", status_code=303)
    cid = get_company_id(user)
    db.add(CSGuide(
        company_id=cid, product_id=product_id or None, title=title.strip(),
        content_internal=content_internal or None, content_partner=content_partner or None,
        sort_order=_parse_int(sort_order) or 0, is_active=True,
    ))
    db.commit()
    return RedirectResponse("/cs/guides?msg=가이드가+등록되었습니다", status_code=303)


@router.get("/guides/{guide_id}/edit")
def cs_guide_edit(guide_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_feature("cs"))):
    if not _is_admin(user):
        return RedirectResponse("/cs/guides?err=관리자만+가능합니다", status_code=303)
    cid = get_company_id(user)
    guide = db.query(CSGuide).filter(CSGuide.id == guide_id, CSGuide.company_id == cid).first()
    if not guide:
        return RedirectResponse("/cs/guides?err=가이드를+찾을+수+없습니다", status_code=303)
    ctx = _base_ctx(request, user)
    ctx.update({
        "guide": guide,
        "products": db.query(Product).filter(Product.company_id == cid, Product.is_archived == False).order_by(Product.name).all(),
    })
    return templates.TemplateResponse("cs/guide_form.html", ctx)


@router.post("/guides/{guide_id}/edit")
def cs_guide_update(
    guide_id: str,
    product_id: str = Form(""),
    title: str = Form(...),
    content_internal: str = Form(""),
    content_partner: str = Form(""),
    sort_order: str = Form("0"),
    is_active: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_feature("cs")),
):
    if not _is_admin(user):
        return RedirectResponse("/cs/guides?err=관리자만+가능합니다", status_code=303)
    cid = get_company_id(user)
    guide = db.query(CSGuide).filter(CSGuide.id == guide_id, CSGuide.company_id == cid).first()
    if guide:
        guide.product_id = product_id or None
        guide.title = title.strip()
        guide.content_internal = content_internal or None
        guide.content_partner = content_partner or None
        guide.sort_order = _parse_int(sort_order) or 0
        guide.is_active = (is_active == "1")
        db.commit()
    return RedirectResponse("/cs/guides?msg=가이드가+수정되었습니다", status_code=303)


# ── 답변 템플릿 관리 (요구사항 13) — 관리자 전용 ─────────────────────────────────

@router.get("/templates")
def cs_templates_list(request: Request, db: Session = Depends(get_db), user: User = Depends(require_feature("cs"))):
    cid = get_company_id(user)
    tpls = db.query(CSTemplate).filter(CSTemplate.company_id == cid).order_by(CSTemplate.sort_order, CSTemplate.name).all()
    prod_map = {p.id: p.name for p in db.query(Product.id, Product.name).filter(Product.company_id == cid)}
    type_map = {t.id: t.name for t in db.query(CSType.id, CSType.name).filter(CSType.company_id == cid)}
    ctx = _base_ctx(request, user)
    ctx.update({"tpls": tpls, "prod_map": prod_map, "type_map": type_map, "is_admin": _is_admin(user)})
    return templates.TemplateResponse("cs/templates_list.html", ctx)


@router.get("/templates/new")
def cs_template_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require_feature("cs"))):
    if not _is_admin(user):
        return RedirectResponse("/cs/templates?err=관리자만+가능합니다", status_code=303)
    cid = get_company_id(user)
    products = db.query(Product).filter(Product.company_id == cid, Product.is_archived == False).order_by(Product.name).all()
    ctx = _base_ctx(request, user)
    ctx.update({
        "tpl": None,
        "products_json": [{"id": p.id, "name": p.name, "brand": p.brand or ""} for p in products],
        "sel_product_id": "",
        "sel_product_name": "",
        "cs_types": _active_types(db, cid),
    })
    return templates.TemplateResponse("cs/template_form.html", ctx)


@router.post("/templates/new")
def cs_template_create(
    name: str = Form(...),
    product_id: str = Form(""),
    cs_type_id: str = Form(""),
    customer_message: str = Form(""),
    internal_guide: str = Form(""),
    is_partner_visible: str = Form(""),
    sort_order: str = Form("0"),
    db: Session = Depends(get_db),
    user: User = Depends(require_feature("cs")),
):
    if not _is_admin(user):
        return RedirectResponse("/cs/templates?err=관리자만+가능합니다", status_code=303)
    cid = get_company_id(user)
    db.add(CSTemplate(
        company_id=cid, name=name.strip(), product_id=product_id or None, cs_type_id=cs_type_id or None,
        customer_message=customer_message or None, internal_guide=internal_guide or None,
        is_partner_visible=(is_partner_visible == "1"), sort_order=_parse_int(sort_order) or 0, is_active=True,
    ))
    db.commit()
    return RedirectResponse("/cs/templates?msg=템플릿이+등록되었습니다", status_code=303)


@router.get("/templates/{tpl_id}/edit")
def cs_template_edit(tpl_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_feature("cs"))):
    if not _is_admin(user):
        return RedirectResponse("/cs/templates?err=관리자만+가능합니다", status_code=303)
    cid = get_company_id(user)
    tpl = db.query(CSTemplate).filter(CSTemplate.id == tpl_id, CSTemplate.company_id == cid).first()
    if not tpl:
        return RedirectResponse("/cs/templates?err=템플릿을+찾을+수+없습니다", status_code=303)
    products = db.query(Product).filter(Product.company_id == cid, Product.is_archived == False).order_by(Product.name).all()
    sel = db.query(Product).filter(Product.id == tpl.product_id).first() if tpl.product_id else None
    ctx = _base_ctx(request, user)
    ctx.update({
        "tpl": tpl,
        "products_json": [{"id": p.id, "name": p.name, "brand": p.brand or ""} for p in products],
        "sel_product_id": tpl.product_id or "",
        "sel_product_name": sel.name if sel else "",
        "cs_types": _active_types(db, cid),
    })
    return templates.TemplateResponse("cs/template_form.html", ctx)


@router.post("/templates/{tpl_id}/edit")
def cs_template_update(
    tpl_id: str,
    name: str = Form(...),
    product_id: str = Form(""),
    cs_type_id: str = Form(""),
    customer_message: str = Form(""),
    internal_guide: str = Form(""),
    is_partner_visible: str = Form(""),
    sort_order: str = Form("0"),
    is_active: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_feature("cs")),
):
    if not _is_admin(user):
        return RedirectResponse("/cs/templates?err=관리자만+가능합니다", status_code=303)
    cid = get_company_id(user)
    tpl = db.query(CSTemplate).filter(CSTemplate.id == tpl_id, CSTemplate.company_id == cid).first()
    if tpl:
        tpl.name = name.strip()
        tpl.product_id = product_id or None
        tpl.cs_type_id = cs_type_id or None
        tpl.customer_message = customer_message or None
        tpl.internal_guide = internal_guide or None
        tpl.is_partner_visible = (is_partner_visible == "1")
        tpl.sort_order = _parse_int(sort_order) or 0
        tpl.is_active = (is_active == "1")
        db.commit()
    return RedirectResponse("/cs/templates?msg=템플릿이+수정되었습니다", status_code=303)


# ── 통계 대시보드 (요구사항 18) ──────────────────────────────────────────────────

def _period(date_from: str, date_to: str):
    """접수 기간 파싱. 기본: 이번 달 1일 ~ 지금."""
    now = datetime.utcnow()
    df = _parse_dt(date_from) or datetime(now.year, now.month, 1)
    dt = _parse_dt(date_to)
    if dt:
        dt = datetime(dt.year, dt.month, dt.day, 23, 59, 59)
    else:
        dt = now
    return df, dt


@router.get("/stats")
def cs_stats(
    request: Request,
    date_from: str = "",
    date_to: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_feature("cs")),
):
    cid = get_company_id(user)
    now = datetime.utcnow()
    df, dt = _period(date_from, date_to)

    base = db.query(CSTicket).filter(CSTicket.company_id == cid, CSTicket.is_archived == False)
    day0 = datetime(now.year, now.month, now.day)
    week0 = day0 - timedelta(days=now.weekday())
    month0 = datetime(now.year, now.month, 1)

    def cnt(q):
        return q.count()

    # 고정 기간 접수 건수
    today_cnt = cnt(base.filter(CSTicket.received_at >= day0))
    week_cnt = cnt(base.filter(CSTicket.received_at >= week0))
    month_cnt = cnt(base.filter(CSTicket.received_at >= month0))

    # 선택 기간 스코프
    scoped = base.filter(CSTicket.received_at >= df, CSTicket.received_at <= dt)
    total = cnt(scoped)
    open_cnt = cnt(scoped.filter(CSTicket.status.in_(C.CS_STATUS_OPEN)))
    processing_cnt = cnt(scoped.filter(CSTicket.status == "processing"))
    partner_wait_cnt = cnt(scoped.filter(CSTicket.status == "partner_waiting"))
    completed_cnt = cnt(scoped.filter(CSTicket.status == "completed"))
    delayed_cnt = cnt(base.filter(CSTicket.due_at < now, CSTicket.status.notin_(["completed", "closed"])))

    # 평균 처리시간 (완료건, 시간 단위)
    done = scoped.filter(CSTicket.status == "completed", CSTicket.completed_at.isnot(None)).all()
    avg_hours = None
    if done:
        secs = [(t.completed_at - t.created_at).total_seconds() for t in done if t.completed_at and t.created_at]
        if secs:
            avg_hours = round(sum(secs) / len(secs) / 3600, 1)

    # 처리방법별 (환불/재발송/교환·반품)
    def rescnt(rt):
        return cnt(scoped.filter(CSTicket.resolution_type == rt))
    def ressum(rt):
        s = db.query(func.coalesce(func.sum(CSTicket.refund_amount), 0)).filter(
            CSTicket.company_id == cid, CSTicket.is_archived == False,
            CSTicket.received_at >= df, CSTicket.received_at <= dt,
            CSTicket.resolution_type == rt,
        ).scalar()
        return int(s or 0)
    partial_cnt, partial_sum = rescnt("partial_refund"), ressum("partial_refund")
    full_cnt, full_sum = rescnt("full_refund"), ressum("full_refund")
    resend_cnt = rescnt("resend") + rescnt("missing_resend")
    exch_ret_cnt = rescnt("exchange") + rescnt("return")

    # 유형별
    type_rows = (
        db.query(CSTicket.cs_type_id, func.count(CSTicket.id))
        .filter(CSTicket.company_id == cid, CSTicket.is_archived == False,
                CSTicket.received_at >= df, CSTicket.received_at <= dt)
        .group_by(CSTicket.cs_type_id).all()
    )
    type_map = {t.id: t.name for t in db.query(CSType).filter(CSType.company_id == cid).all()}
    by_type = sorted([(type_map.get(tid, "미지정"), n) for tid, n in type_rows], key=lambda x: -x[1])

    # 협업사별
    partner_rows = (
        db.query(CSTicket.partner_id, func.count(CSTicket.id))
        .filter(CSTicket.company_id == cid, CSTicket.is_archived == False,
                CSTicket.received_at >= df, CSTicket.received_at <= dt, CSTicket.partner_id.isnot(None))
        .group_by(CSTicket.partner_id).all()
    )
    partner_map = {p.id: p.name for p in db.query(Partner).filter(Partner.company_id == cid).all()}
    by_partner = sorted([(partner_map.get(pid, "미지정"), n) for pid, n in partner_rows], key=lambda x: -x[1])

    # 상품별 (반복 CS 파악) — product_id + external_product_name 통합
    prod_counts = {}
    prod_map = {p.id: p.name for p in db.query(Product.id, Product.name).filter(Product.company_id == cid)}
    for t in scoped.all():
        name = prod_map.get(t.product_id) if t.product_id else (t.external_product_name or "미지정")
        prod_counts[name] = prod_counts.get(name, 0) + 1
    by_product = sorted(prod_counts.items(), key=lambda x: -x[1])[:15]
    repeat_products = [(n, c) for n, c in by_product if c >= 2]

    ctx = _base_ctx(request, user)
    ctx.update({
        "date_from": df.strftime("%Y-%m-%d"), "date_to": dt.strftime("%Y-%m-%d"),
        "today_cnt": today_cnt, "week_cnt": week_cnt, "month_cnt": month_cnt,
        "total": total, "open_cnt": open_cnt, "processing_cnt": processing_cnt,
        "partner_wait_cnt": partner_wait_cnt, "completed_cnt": completed_cnt, "delayed_cnt": delayed_cnt,
        "avg_hours": avg_hours,
        "partial_cnt": partial_cnt, "partial_sum": partial_sum,
        "full_cnt": full_cnt, "full_sum": full_sum,
        "resend_cnt": resend_cnt, "exch_ret_cnt": exch_ret_cnt,
        "by_type": by_type, "by_partner": by_partner, "by_product": by_product, "repeat_products": repeat_products,
    })
    return templates.TemplateResponse("cs/stats.html", ctx)


# ── 엑셀 다운로드 (요구사항 19) — 권한 제한 + 이력 기록 ────────────────────────────

def _export_query(db, cid, q, status, cs_type_id, partner_id, urgent, date_from, date_to):
    query = db.query(CSTicket).filter(CSTicket.company_id == cid, CSTicket.is_archived == False)
    if date_from or date_to:
        df, dt = _period(date_from, date_to)
        query = query.filter(CSTicket.received_at >= df, CSTicket.received_at <= dt)
    if status:
        query = query.filter(CSTicket.status == status)
    if cs_type_id:
        query = query.filter(CSTicket.cs_type_id == cs_type_id)
    if partner_id:
        query = query.filter(CSTicket.partner_id == partner_id)
    if urgent == "1":
        query = query.filter(CSTicket.is_urgent == True)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            CSTicket.cs_number.ilike(like), CSTicket.external_order_number.ilike(like),
            CSTicket.customer_name.ilike(like), CSTicket.customer_phone.ilike(like),
            CSTicket.external_product_name.ilike(like), CSTicket.tracking_number.ilike(like),
        ))
    return query.order_by(CSTicket.created_at.desc())


@router.get("/export")
def cs_export(
    q: str = "", status: str = "", cs_type_id: str = "", partner_id: str = "",
    urgent: str = "", date_from: str = "", date_to: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_feature("cs")),
):
    cid = get_company_id(user)
    tickets = _export_query(db, cid, q, status, cs_type_id, partner_id, urgent, date_from, date_to).all()

    type_map = {t.id: t.name for t in db.query(CSType).filter(CSType.company_id == cid).all()}
    partner_map = {p.id: p.name for p in db.query(Partner).filter(Partner.company_id == cid).all()}
    prod_map = {p.id: p.name for p in db.query(Product.id, Product.name).filter(Product.company_id == cid)}
    inf_map = {i.id: i.name for i in db.query(Influencer.id, Influencer.name).filter(Influencer.company_id == cid)}
    user_map = {u.id: u.username for u in db.query(User.id, User.username).filter(User.company_id == cid)}

    import openpyxl
    from openpyxl.styles import Font, PatternFill
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "CS내역"
    headers = ["CS번호", "접수일시", "외부주문번호", "주문출처", "판매채널", "고객명", "연락처",
               "상품명", "옵션", "수량", "CS유형", "문의내용", "상태", "처리방법", "환불금액",
               "협업사", "인플루언서", "내부담당자", "처리일", "처리내용", "송장번호", "재발송송장번호"]
    ws.append(headers)
    hf = PatternFill("solid", fgColor="2563EB"); hfont = Font(bold=True, color="FFFFFF", size=10)
    for c in ws[1]:
        c.fill = hf; c.font = hfont
    for t in tickets:
        rd = t.resolution_detail or {}
        ws.append([
            t.cs_number,
            t.received_at.strftime("%Y-%m-%d %H:%M") if t.received_at else "",
            t.external_order_number or "", C.ORDER_SOURCE_LABELS.get(t.order_source, t.order_source or ""),
            C.SALES_CHANNEL_LABELS.get(t.sales_channel, t.sales_channel or ""),
            t.customer_name or "", t.customer_phone or "",
            (prod_map.get(t.product_id) if t.product_id else t.external_product_name) or "",
            t.product_option or "", t.quantity if t.quantity is not None else "",
            type_map.get(t.cs_type_id, ""), t.inquiry_content or "",
            C.CS_STATUS_LABELS.get(t.status, t.status),
            C.CS_RESOLUTION_LABELS.get(t.resolution_type, "") if t.resolution_type else "",
            int(t.refund_amount) if t.refund_amount else "",
            partner_map.get(t.partner_id, ""), inf_map.get(t.influencer_id, ""),
            user_map.get(t.assigned_user_id, ""),
            t.completed_at.strftime("%Y-%m-%d") if t.completed_at else "",
            (rd.get("refund_memo") or rd.get("inspect_result") or ""),
            t.tracking_number or "", rd.get("resend_tracking", ""),
        ])
    for col in ws.columns:
        width = max((len(str(c.value)) for c in col if c.value), default=8)
        ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 40)

    buf = io.BytesIO(); wb.save(buf); buf.seek(0)

    # 다운로드 이력
    fsummary = f"q={q};status={status};type={cs_type_id};partner={partner_id};urgent={urgent};{date_from}~{date_to}"
    db.add(CSDownloadLog(company_id=cid, user_id=user.id, username=user.username,
                         filter_summary=fsummary, row_count=len(tickets)))
    db.commit()

    from urllib.parse import quote
    fname = quote(f"CS내역_{datetime.utcnow().strftime('%Y%m%d')}.xlsx")
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{fname}"},
    )


# ── 인앱 알림 (요구사항 17) ──────────────────────────────────────────────────────

@router.get("/notifications")
def cs_notifications(request: Request, db: Session = Depends(get_db), user: User = Depends(require_feature("cs"))):
    cid = get_company_id(user)
    items = (
        db.query(CSNotification)
        .filter(CSNotification.company_id == cid, CSNotification.user_id == user.id)
        .order_by(CSNotification.created_at.desc())
        .limit(100).all()
    )
    ctx = _base_ctx(request, user)
    ctx.update({"items": items})
    return templates.TemplateResponse("cs/notifications.html", ctx)


@router.get("/notifications/unread")
def cs_notifications_unread(db: Session = Depends(get_db), user: User = Depends(require_feature("cs"))):
    cid = get_company_id(user)
    rows = (
        db.query(CSNotification)
        .filter(CSNotification.company_id == cid, CSNotification.user_id == user.id, CSNotification.is_read == False)
        .order_by(CSNotification.created_at.desc()).limit(10).all()
    )
    return {
        "count": db.query(CSNotification).filter(
            CSNotification.company_id == cid, CSNotification.user_id == user.id, CSNotification.is_read == False
        ).count(),
        "items": [{"id": n.id, "title": n.title, "cs_id": n.cs_ticket_id,
                   "created_at": n.created_at.strftime("%m/%d %H:%M") if n.created_at else ""} for n in rows],
    }


@router.post("/notifications/{nid}/read")
def cs_notification_read(nid: str, db: Session = Depends(get_db), user: User = Depends(require_feature("cs"))):
    cid = get_company_id(user)
    n = db.query(CSNotification).filter(
        CSNotification.id == nid, CSNotification.company_id == cid, CSNotification.user_id == user.id
    ).first()
    if n and not n.is_read:
        n.is_read = True
        n.read_at = datetime.utcnow()
        db.commit()
    # 관련 CS로 이동 (없으면 알림함으로)
    return RedirectResponse(f"/cs/{n.cs_ticket_id}" if n and n.cs_ticket_id else "/cs/notifications", status_code=303)


@router.post("/notifications/read-all")
def cs_notifications_read_all(db: Session = Depends(get_db), user: User = Depends(require_feature("cs"))):
    cid = get_company_id(user)
    db.query(CSNotification).filter(
        CSNotification.company_id == cid, CSNotification.user_id == user.id, CSNotification.is_read == False
    ).update({"is_read": True, "read_at": datetime.utcnow()})
    db.commit()
    return RedirectResponse("/cs/notifications?msg=모두+읽음+처리했습니다", status_code=303)


# ── 상세 (요구사항 15) ─────────────────────────────────────────────────────────
# 주의: 와일드카드 /{cs_id} 이므로 반드시 다른 모든 구체 경로(/guides, /templates 등) 뒤에 선언.

@router.get("/{cs_id}")
def cs_detail(
    cs_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_feature("cs")),
):
    cid = get_company_id(user)
    ticket = db.query(CSTicket).filter(CSTicket.id == cs_id, CSTicket.company_id == cid).first()
    if not ticket:
        return RedirectResponse("/cs?err=CS를+찾을+수+없습니다", status_code=303)

    # 연관 표시 정보
    product = db.query(Product).filter(Product.id == ticket.product_id).first() if ticket.product_id else None
    cs_type = db.query(CSType).filter(CSType.id == ticket.cs_type_id).first() if ticket.cs_type_id else None
    partner = db.query(Partner).filter(Partner.id == ticket.partner_id).first() if ticket.partner_id else None
    influencer = db.query(Influencer).filter(Influencer.id == ticket.influencer_id).first() if ticket.influencer_id else None
    assignee = db.query(User).filter(User.id == ticket.assigned_user_id).first() if ticket.assigned_user_id else None

    activities = (
        db.query(CSActivity)
        .filter(CSActivity.cs_ticket_id == ticket.id)
        .order_by(CSActivity.created_at.asc())
        .all()
    )
    attachments = (
        db.query(CSAttachment)
        .filter(CSAttachment.cs_ticket_id == ticket.id, CSAttachment.is_deleted == False)
        .order_by(CSAttachment.created_at.asc())
        .all()
    )

    # 상품별 CS 가이드 (요구사항 12) — 연결된 상품이 있을 때
    guides = []
    if ticket.product_id:
        guides = (
            db.query(CSGuide)
            .filter(CSGuide.company_id == cid, CSGuide.product_id == ticket.product_id, CSGuide.is_active == True)
            .order_by(CSGuide.sort_order, CSGuide.created_at)
            .all()
        )

    # 답변 템플릿 추천 (요구사항 13) — 상품/유형 일치 또는 공통(null)
    rec_templates = []
    for tpl in db.query(CSTemplate).filter(
        CSTemplate.company_id == cid, CSTemplate.is_active == True
    ).order_by(CSTemplate.sort_order, CSTemplate.name).all():
        prod_ok = (tpl.product_id is None) or (tpl.product_id == ticket.product_id)
        type_ok = (tpl.cs_type_id is None) or (tpl.cs_type_id == ticket.cs_type_id)
        if prod_ok and type_ok:
            rec_templates.append(tpl)

    ctx = _base_ctx(request, user)
    ctx.update({
        "ticket": ticket,
        "product": product,
        "cs_type": cs_type,
        "partner": partner,
        "influencer": influencer,
        "assignee": assignee,
        "activities": activities,
        "attachments": attachments,
        "guides": guides,
        "rec_templates": rec_templates,
        "templates_json": [
            {"id": t.id, "name": t.name, "customer_message": t.customer_message or "", "internal_guide": t.internal_guide or ""}
            for t in rec_templates
        ],
        "is_admin": _is_admin(user),
        "staff_users": db.query(User).filter(
            User.company_id == cid, User.role.in_(["admin", "staff", "manager"]), User.is_active == True
        ).order_by(User.username).all(),
    })
    return templates.TemplateResponse("cs/detail.html", ctx)
