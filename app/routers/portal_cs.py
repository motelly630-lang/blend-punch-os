"""협업사 포털 CS — 협업사 담당자(role=="partner") + 내부 직원 미리보기. /portal/cs

두 방향의 CS를 한 목록에서 다룬다:
  - 전달받은 CS : 블렌드펀치가 협업사에게 전달한 고객 CS (is_forwarded_to_partner)
  - 직접 접수   : 협업사가 포털에서 우리 쪽으로 올린 CS (submitted_by_partner)

보안(요구사항 16·21):
  - 컨텍스트의 partner_id 일치 + (전달된 건 | 직접 접수한 건)만 조회
  - 고객정보 마스킹, 공개 첨부(is_public)만 노출, 내부 메모/공급가/수수료 등 미포함
    (단, 협업사가 직접 접수해 본인이 입력한 건은 자기 입력값이므로 마스킹하지 않는다)
  - URL 직접입력 접근도 서버단에서 차단
  - 응답/HTML에 비공개 필드를 아예 담지 않는다(마스킹 후 화이트리스트 필드만 전달)
  - 내부 직원 미리보기는 보기 전용 — 답변/등록 POST 를 서버단에서 거부
"""
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import RedirectResponse, FileResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.partner import Partner
from app.models.product import Product
from app.models.cs import CSTicket, CSType, CSActivity, CSAttachment, CSGuide
from app.cs import constants as C
from app.cs.masking import mask_name, mask_phone, mask_address
from app.cs.numbering import gen_cs_number
from app.cs.notify import notify, staff_ids
from app.cs.uploads import save_cs_image
from app.services.portal_access import PortalCtx, portal_context

router = APIRouter(prefix="/portal/cs")
templates = Jinja2Templates(directory="app/templates")


def _scoped_query(db: Session, ctx: PortalCtx):
    """이 협업사에게 전달됐거나, 이 협업사가 직접 접수한 보관되지 않은 CS만."""
    return db.query(CSTicket).filter(
        CSTicket.company_id == ctx.company_id,
        CSTicket.partner_id == ctx.partner_id,
        or_(
            CSTicket.is_forwarded_to_partner == True,
            CSTicket.submitted_by_partner == True,
        ),
        CSTicket.is_archived == False,
    )


def _needs_reply(ticket) -> bool:
    return ticket.status in ("partner_waiting", "partner_pending")


def _no_partner(ctx: PortalCtx):
    """협력사가 특정되지 않은 상태 — 내부 직원이면 선택 화면으로."""
    return RedirectResponse("/portal/select" if ctx.is_admin_view else "/portal", status_code=303)


@router.get("")
def portal_cs_list(
    db: Session = Depends(get_db),
    ctx: PortalCtx = Depends(portal_context),
):
    if not ctx.partner_id:
        if ctx.is_admin_view:
            return RedirectResponse("/portal/select", status_code=303)
        return templates.TemplateResponse("portal/cs_list.html", ctx.tpl(
            tickets=[], active_portal="cs",
            STATUS_LABELS=C.CS_STATUS_LABELS, STATUS_BADGES=C.CS_STATUS_BADGES,
        ))
    tickets = _scoped_query(db, ctx).order_by(CSTicket.created_at.desc()).all()

    # 표시용 이름 매핑 (상품/유형)
    pids = {t.product_id for t in tickets if t.product_id}
    tyids = {t.cs_type_id for t in tickets if t.cs_type_id}
    prod_map = {p.id: p.name for p in db.query(Product.id, Product.name).filter(Product.id.in_(pids))} if pids else {}
    type_map = {t.id: t.name for t in db.query(CSType.id, CSType.name).filter(CSType.id.in_(tyids))} if tyids else {}

    rows = []
    for t in tickets:
        rows.append({
            "id": t.id,
            "cs_number": t.cs_number,
            "received_at": t.received_at,
            "product_name": prod_map.get(t.product_id) or t.external_product_name or "-",
            "cs_type": type_map.get(t.cs_type_id, "-"),
            "status": t.status,
            "is_urgent": t.is_urgent,
            "needs_reply": _needs_reply(t),
            "submitted": bool(t.submitted_by_partner),
            "updated_at": t.updated_at,
        })

    return templates.TemplateResponse("portal/cs_list.html", ctx.tpl(
        tickets=rows, active_portal="cs",
        STATUS_LABELS=C.CS_STATUS_LABELS, STATUS_BADGES=C.CS_STATUS_BADGES,
    ))


# ── 협업사 직접 접수 (협업사 → 블렌드펀치) ──────────────────────────────────────
# 주의: 와일드카드 /{cs_id} 보다 먼저 선언.

@router.get("/new")
def portal_cs_new_form(
    db: Session = Depends(get_db),
    ctx: PortalCtx = Depends(portal_context),
):
    if not ctx.partner_id:
        return _no_partner(ctx)
    products = (
        db.query(Product)
        .filter(Product.partner_id == ctx.partner_id, Product.is_archived == False)
        .order_by(Product.name)
        .all()
    )
    cs_types = (
        db.query(CSType)
        .filter(CSType.company_id == ctx.company_id, CSType.is_active == True)
        .order_by(CSType.sort_order, CSType.name)
        .all()
    )
    return templates.TemplateResponse("portal/cs_new.html", ctx.tpl(
        active_portal="cs", products=products, cs_types=cs_types,
        ORDER_SOURCES=C.ORDER_SOURCES, SALES_CHANNELS=C.SALES_CHANNELS,
    ))


def _parse_dt(v: str):
    if not v:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(v.strip(), fmt)
        except ValueError:
            continue
    return None


def _parse_int(v: str):
    try:
        return int(str(v).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


@router.post("/new")
def portal_cs_create(
    cs_type_id: str = Form(""),
    is_urgent: str = Form(""),
    product_id: str = Form(""),
    external_product_name: str = Form(""),
    product_option: str = Form(""),
    quantity: str = Form(""),
    campaign_name: str = Form(""),
    external_order_number: str = Form(""),
    order_source: str = Form(""),
    sales_channel: str = Form(""),
    customer_name: str = Form(""),
    customer_phone: str = Form(""),
    customer_address: str = Form(""),
    purchased_at: str = Form(""),
    courier: str = Form(""),
    tracking_number: str = Form(""),
    inquiry_content: str = Form(""),
    customer_request: str = Form(""),
    images: list[UploadFile] = File(None),
    db: Session = Depends(get_db),
    ctx: PortalCtx = Depends(portal_context),
):
    if not ctx.partner_id:
        return _no_partner(ctx)
    if ctx.readonly:
        return RedirectResponse("/portal/cs?err=관리자+미리보기에서는+등록할+수+없습니다", status_code=303)
    if not inquiry_content.strip():
        return RedirectResponse("/portal/cs/new?err=문의+내용을+입력하세요", status_code=303)

    cid = ctx.company_id
    user = ctx.user

    # 상품: 내 협력사에 배정된 제품만 인정. 아니면 직접입력으로 처리.
    prod = None
    if product_id:
        prod = db.query(Product).filter(
            Product.id == product_id, Product.partner_id == ctx.partner_id
        ).first()

    now = datetime.utcnow()
    ticket = CSTicket(
        company_id=cid,
        cs_number=gen_cs_number(db, cid),
        received_at=now,
        channel="partner",
        is_urgent=(is_urgent == "1"),
        status=C.CS_STATUS_DEFAULT,
        cs_type_id=cs_type_id or None,
        product_id=prod.id if prod else None,
        external_product_name=None if prod else (external_product_name.strip() or None),
        product_option=product_option.strip() or None,
        quantity=_parse_int(quantity),
        partner_id=ctx.partner_id,
        campaign_name=campaign_name.strip() or None,
        external_order_number=external_order_number.strip() or None,
        order_source=order_source or None,
        sales_channel=sales_channel or None,
        customer_name=customer_name.strip() or None,
        customer_phone=customer_phone.strip() or None,
        customer_address=customer_address.strip() or None,
        purchased_at=_parse_dt(purchased_at),
        courier=courier.strip() or None,
        tracking_number=tracking_number.strip() or None,
        inquiry_content=inquiry_content.strip(),
        customer_request=customer_request.strip() or None,
        # 협업사 접수건 — 등록한 협업사 본인은 계속 열람 가능해야 하므로 전달 플래그를 켠다
        submitted_by_partner=True,
        is_forwarded_to_partner=True,
        forwarded_at=now,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(ticket)
    db.flush()  # ticket.id 확보

    db.add(CSActivity(
        company_id=cid, cs_ticket_id=ticket.id,
        activity_type=C.ACT_CREATED, visibility=C.VIS_PARTNER,
        to_value=C.CS_STATUS_LABELS.get(ticket.status),
        body="협업사가 포털에서 직접 접수",
        actor_id=user.id, actor_name=user.username, actor_role="partner",
    ))

    # 사진 첨부 — 협업사가 올린 것이므로 본인에게도 계속 보이도록 공개(is_public=True)
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
            is_public=True, uploaded_by=user.id, uploaded_by_name=user.username,
            **meta,
        ))
        saved += 1
    if saved:
        db.add(CSActivity(
            company_id=cid, cs_ticket_id=ticket.id,
            activity_type=C.ACT_ATTACHMENT, visibility=C.VIS_PARTNER,
            to_value=f"이미지 {saved}장",
            actor_id=user.id, actor_name=user.username, actor_role="partner",
        ))

    # 내부 직원 전원에게 알림 (담당자 미지정 상태로 들어온다)
    partner_name = ctx.partner.name if ctx.partner else "협업사"
    notify(
        db, cid, staff_ids(db, cid), "new_cs",
        ("긴급 " if ticket.is_urgent else "") + f"협업사 CS 접수({partner_name}): {ticket.cs_number}",
        body=(ticket.inquiry_content or "")[:200], cs_id=ticket.id,
    )
    db.commit()
    return RedirectResponse(f"/portal/cs/{ticket.id}?msg=CS가+접수되었습니다", status_code=303)


@router.get("/attachments/{att_id}")
def portal_cs_attachment(
    att_id: str,
    db: Session = Depends(get_db),
    ctx: PortalCtx = Depends(portal_context),
):
    """공개(is_public) 첨부만, 이 협업사에게 전달된 CS의 것만 스트리밍."""
    if not ctx.partner_id:
        return Response(status_code=404)
    att = db.query(CSAttachment).filter(
        CSAttachment.id == att_id,
        CSAttachment.is_public == True,
        CSAttachment.is_deleted == False,
    ).first()
    if not att:
        return Response(status_code=404)
    # 소속 CS가 이 협업사에게 전달된 건인지 재검증 (URL 직접접근 차단)
    ticket = _scoped_query(db, ctx).filter(CSTicket.id == att.cs_ticket_id).first()
    if not ticket:
        return Response(status_code=404)
    path = Path(att.stored_path)
    if not path.exists():
        return Response(status_code=404)
    headers = None
    if att.file_type != "image" and att.file_name:
        from urllib.parse import quote
        headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(att.file_name)}"}
    return FileResponse(str(path), media_type=att.content_type or "application/octet-stream", headers=headers)


@router.get("/{cs_id}")
def portal_cs_detail(
    cs_id: str,
    db: Session = Depends(get_db),
    ctx: PortalCtx = Depends(portal_context),
):
    if not ctx.partner_id:
        return _no_partner(ctx)
    ticket = _scoped_query(db, ctx).filter(CSTicket.id == cs_id).first()
    if not ticket:
        # 권한 없는/미전달 CS — 존재 여부도 노출하지 않음
        return RedirectResponse("/portal/cs?err=접근+권한이+없습니다", status_code=303)

    product = db.query(Product).filter(Product.id == ticket.product_id).first() if ticket.product_id else None
    cs_type = db.query(CSType).filter(CSType.id == ticket.cs_type_id).first() if ticket.cs_type_id else None

    # 공개 첨부만
    attachments = db.query(CSAttachment).filter(
        CSAttachment.cs_ticket_id == ticket.id,
        CSAttachment.is_public == True,
        CSAttachment.is_deleted == False,
    ).order_by(CSAttachment.created_at.asc()).all()

    # 협업사 공개 가이드(content_partner)만
    guides = []
    if ticket.product_id:
        for g in db.query(CSGuide).filter(
            CSGuide.product_id == ticket.product_id, CSGuide.is_active == True
        ).order_by(CSGuide.sort_order).all():
            if g.content_partner:
                guides.append({"title": g.title, "content": g.content_partner})

    # 타임라인: 협업사 공개(visibility partner/all)만, 내부메모 제외
    acts = []
    for a in db.query(CSActivity).filter(
        CSActivity.cs_ticket_id == ticket.id,
        CSActivity.visibility.in_(C.PARTNER_VISIBLE_VISIBILITIES),
    ).order_by(CSActivity.created_at.asc()).all():
        acts.append({
            "type": a.activity_type, "body": a.body,
            "actor": a.actor_name, "actor_role": a.actor_role,
            "created_at": a.created_at,
        })

    # 화이트리스트 + 마스킹된 뷰만 전달 (내부메모/공급가/수수료 등은 아예 포함하지 않음)
    # 협업사 직접 접수건도 마스킹은 유지한다 — 접수 후 내부에서 채워 넣은 고객정보가
    # 협업사에게 그대로 열리는 걸 막기 위함(입력자 구분 없이 일관 정책).
    own = bool(ticket.submitted_by_partner)
    full_addr = bool(ticket.full_address_visible_to_partner)
    pv = {
        "id": ticket.id,
        "cs_number": ticket.cs_number,
        "status": ticket.status,
        "is_urgent": ticket.is_urgent,
        "submitted": own,
        "cs_type": cs_type.name if cs_type else "-",
        "received_at": ticket.received_at,
        "due_at": ticket.due_at,
        "product_name": (product.name if product else None) or ticket.external_product_name or "-",
        "product_option": ticket.product_option or "-",
        "quantity": ticket.quantity,
        "order_number": ticket.external_order_number or "-",
        "customer_name": mask_name(ticket.customer_name),
        "customer_phone": mask_phone(ticket.customer_phone),
        "customer_address": mask_address(ticket.customer_address, full=full_addr),
        "address_full_disclosed": full_addr,
        "partner_note": ticket.partner_note or "",
        "inquiry_content": ticket.inquiry_content or "",
        "customer_request": ticket.customer_request or "",
        "needs_reply": _needs_reply(ticket),
    }

    return templates.TemplateResponse("portal/cs_detail.html", ctx.tpl(
        active_portal="cs",
        cs=pv, attachments=attachments, guides=guides, activities=acts,
        STATUS_LABELS=C.CS_STATUS_LABELS, STATUS_BADGES=C.CS_STATUS_BADGES,
        RESOLUTIONS=C.CS_RESOLUTIONS,
    ))


@router.post("/{cs_id}/reply")
def portal_cs_reply(
    cs_id: str,
    reply: str = Form(""),
    recommended_resolution: str = Form(""),
    feasibility: str = Form(""),
    resend_available_date: str = Form(""),
    memo: str = Form(""),
    db: Session = Depends(get_db),
    ctx: PortalCtx = Depends(portal_context),
):
    if not ctx.partner_id:
        return _no_partner(ctx)
    if ctx.readonly:
        return RedirectResponse(f"/portal/cs/{cs_id}?err=관리자+미리보기에서는+답변할+수+없습니다", status_code=303)
    ticket = _scoped_query(db, ctx).filter(CSTicket.id == cs_id).first()
    if not ticket:
        return RedirectResponse("/portal/cs?err=접근+권한이+없습니다", status_code=303)
    if not reply.strip() and not recommended_resolution and not feasibility.strip():
        return RedirectResponse(f"/portal/cs/{cs_id}?err=답변+내용을+입력하세요", status_code=303)

    # 구조화된 답변을 하나의 협업사 답변 기록으로 (visibility=partner)
    lines = []
    if reply.strip():
        lines.append(f"[답변] {reply.strip()}")
    if recommended_resolution:
        lines.append(f"[권장 처리방법] {C.CS_RESOLUTION_LABELS.get(recommended_resolution, recommended_resolution)}")
    if feasibility.strip():
        lines.append(f"[처리 가능여부] {feasibility.strip()}")
    if resend_available_date.strip():
        lines.append(f"[재발송 가능일] {resend_available_date.strip()}")
    if memo.strip():
        lines.append(f"[기타] {memo.strip()}")
    body = "\n".join(lines)

    cid = ctx.company_id
    user = ctx.user
    db.add(CSActivity(
        company_id=cid, cs_ticket_id=ticket.id,
        activity_type=C.ACT_PARTNER_REPLY, visibility=C.VIS_PARTNER, body=body,
        actor_id=user.id, actor_name=(user.username), actor_role="partner",
    ))
    # 답변대기 상태였다면 처리중으로 전환
    if ticket.status in ("partner_waiting", "partner_pending"):
        ticket.status = "processing"
    # 내부 담당자·등록자에게 알림 (협업사 접수건은 담당자가 없을 수 있어 스태프 전원)
    recips = [ticket.assigned_user_id, ticket.created_by]
    if not ticket.assigned_user_id:
        recips += staff_ids(db, cid, exclude=user.id)
    notify(db, cid, [r for r in recips if r and r != user.id], "partner_reply",
           f"협업사 답변 등록: {ticket.cs_number}", cs_id=ticket.id)
    db.commit()
    return RedirectResponse(f"/portal/cs/{cs_id}?msg=답변이+등록되었습니다", status_code=303)
