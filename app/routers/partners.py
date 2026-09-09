"""
협력사(공급사) 관리 — 내부용 (staff/admin)
/partners

- 협력사 등록 / 목록 / 상세 / 수정
- 협력사에 제품 배정 (배정된 제품 기준으로 포털 일정이 자동 파생)
- 협력사 포털 로그인 계정 발급 / 비밀번호 초기화

협력사 담당자는 role="partner" + user.partner_id 계정으로 /portal 에서
자기 것만 보기 전용으로 확인한다.
"""
from datetime import datetime
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.user import User
from app.models.partner import Partner, PartnerContact
from app.models.product import Product
from app.models.cs import CSTicket
from app.cs import constants as CSC
from app.auth.dependencies import require_staff
from app.auth.service import hash_password
from app.auth.tenant import get_company_id
from app.services.partner_stats import sales_summary

router = APIRouter(prefix="/partners")
templates = Jinja2Templates(directory="app/templates")


# ── 목록 ─────────────────────────────────────────────────────────────────────

@router.get("")
def partners_list(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
):
    cid = get_company_id(user)
    partners = (
        db.query(Partner)
        .filter(Partner.company_id == cid)
        .order_by(Partner.is_active.desc(), Partner.created_at.desc())
        .all()
    )
    # 협력사별 제품 수 / 계정 수 (N+1 방지: GROUP BY 한 번씩)
    pids = [p.id for p in partners]
    prod_counts = dict(
        db.query(Product.partner_id, func.count(Product.id))
        .filter(Product.partner_id.in_(pids))
        .group_by(Product.partner_id)
        .all()
    ) if pids else {}
    acct_counts = dict(
        db.query(User.partner_id, func.count(User.id))
        .filter(User.partner_id.in_(pids))
        .group_by(User.partner_id)
        .all()
    ) if pids else {}
    stats = {
        p.id: {"products": prod_counts.get(p.id, 0), "accounts": acct_counts.get(p.id, 0)}
        for p in partners
    }

    return templates.TemplateResponse("partners/index.html", {
        "request": request,
        "partners": partners,
        "stats": stats,
        "user": user,
        "active_page": "partners",
    })


# ── 등록 ─────────────────────────────────────────────────────────────────────

@router.post("/new")
def partner_create(
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
    name: str = Form(...),
    contact_name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    settlement_days: int = Form(14),
):
    name = name.strip()
    if not name:
        return RedirectResponse("/partners?err=협력사명을+입력해주세요", status_code=302)
    partner = Partner(
        company_id=get_company_id(user),
        name=name,
        contact_name=contact_name.strip() or None,
        phone=phone.strip() or None,
        email=email.strip() or None,
        settlement_days=settlement_days or 14,
    )
    db.add(partner)
    db.commit()
    db.refresh(partner)
    return RedirectResponse(f"/partners/{partner.id}?msg=협력사가+등록되었습니다", status_code=302)


# ── 상세 / 편집 ───────────────────────────────────────────────────────────────

@router.get("/{partner_id}")
def partner_detail(
    partner_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
):
    cid = get_company_id(user)
    partner = db.query(Partner).filter(
        Partner.id == partner_id, Partner.company_id == cid
    ).first()
    if not partner:
        return RedirectResponse("/partners?err=협력사를+찾을+수+없습니다", status_code=302)

    assigned = (
        db.query(Product)
        .filter(Product.partner_id == partner.id)
        .order_by(Product.created_at.desc())
        .all()
    )
    # 미배정 제품 (다른 협력사에 안 물린 것)
    unassigned = (
        db.query(Product)
        .filter(Product.company_id == cid, Product.partner_id.is_(None),
                Product.is_archived == False)
        .order_by(Product.created_at.desc())
        .all()
    )
    # 담당자 + 각자의 포털 계정
    contacts = (
        db.query(PartnerContact)
        .filter(PartnerContact.partner_id == partner.id)
        .order_by(PartnerContact.created_at.asc())
        .all()
    )
    accounts = db.query(User).filter(User.partner_id == partner.id).all()
    account_map = {a.id: a for a in accounts}
    contact_rows = [{"c": c, "account": account_map.get(c.user_id)} for c in contacts]

    # 판매 현황 (배정 제품 기준, 결제완료 실주문)
    sales = sales_summary(db, [p.id for p in assigned])

    # 담당 매니저 후보 (내부 직원)
    staff_users = (
        db.query(User)
        .filter(User.company_id == cid, User.role.in_(["admin", "staff", "manager"]), User.is_active == True)
        .order_by(User.username)
        .all()
    )

    # ④ 협력사 CS 요약 (이 협력사 건, 보관 제외)
    cs_base = db.query(CSTicket).filter(CSTicket.company_id == cid,
                                        CSTicket.partner_id == partner.id,
                                        CSTicket.is_archived == False)
    cs_summary = {
        "total": cs_base.count(),
        "open": cs_base.filter(CSTicket.status.in_(CSC.CS_STATUS_OPEN)).count(),
        "partner_waiting": cs_base.filter(CSTicket.status == "partner_waiting").count(),
        "completed": cs_base.filter(CSTicket.status == "completed").count(),
    }

    return templates.TemplateResponse("partners/detail.html", {
        "request": request,
        "partner": partner,
        "assigned": assigned,
        "unassigned": unassigned,
        "contact_rows": contact_rows,
        "sales": sales,
        "staff_users": staff_users,
        "cs_summary": cs_summary,
        "user": user,
        "active_page": "partners",
    })


@router.post("/{partner_id}/update")
def partner_update(
    partner_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
    name: str = Form(...),
    contact_name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    settlement_cycle: str = Form(""),
    settlement_days: int = Form(14),
    contract_terms: str = Form(""),
    notes: str = Form(""),
    is_active: str = Form("on"),
    # 사업자 정보
    business_name: str = Form(""),
    biz_reg_number: str = Form(""),
    representative_name: str = Form(""),
    business_type: str = Form(""),
    business_address: str = Form(""),
    tax_invoice_email: str = Form(""),
    # 정산 계좌
    bank_name: str = Form(""),
    account_number: str = Form(""),
    account_holder: str = Form(""),
    # 계약
    contract_start: str = Form(""),
    contract_end: str = Form(""),
    commission_rate: str = Form(""),
    manager_user_id: str = Form(""),
):
    cid = get_company_id(user)
    partner = db.query(Partner).filter(
        Partner.id == partner_id, Partner.company_id == cid
    ).first()
    if not partner:
        return RedirectResponse("/partners?err=협력사를+찾을+수+없습니다", status_code=302)

    def _date(v):
        v = (v or "").strip()
        if not v:
            return None
        try:
            return datetime.strptime(v, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _float(v):
        v = (v or "").strip().replace(",", "")
        if not v:
            return None
        try:
            return float(v)
        except ValueError:
            return None

    partner.name = name.strip() or partner.name
    partner.contact_name = contact_name.strip() or None
    partner.phone = phone.strip() or None
    partner.email = email.strip() or None
    partner.settlement_cycle = settlement_cycle.strip() or None
    partner.settlement_days = settlement_days or 14
    partner.contract_terms = contract_terms.strip() or None
    partner.notes = notes.strip() or None
    partner.is_active = (is_active == "on")
    # 사업자 정보
    partner.business_name = business_name.strip() or None
    partner.biz_reg_number = biz_reg_number.strip() or None
    partner.representative_name = representative_name.strip() or None
    partner.business_type = business_type.strip() or None
    partner.business_address = business_address.strip() or None
    partner.tax_invoice_email = tax_invoice_email.strip() or None
    # 정산 계좌
    partner.bank_name = bank_name.strip() or None
    partner.account_number = account_number.strip() or None
    partner.account_holder = account_holder.strip() or None
    # 계약
    partner.contract_start = _date(contract_start)
    partner.contract_end = _date(contract_end)
    partner.commission_rate = _float(commission_rate)
    partner.manager_user_id = manager_user_id or None
    db.commit()
    return RedirectResponse(f"/partners/{partner_id}?msg=저장되었습니다", status_code=302)


# ── 제품 배정 ─────────────────────────────────────────────────────────────────

@router.post("/{partner_id}/products/assign")
def partner_assign_products(
    partner_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
    product_ids: list[str] = Form(default=[]),
):
    cid = get_company_id(user)
    partner = db.query(Partner).filter(
        Partner.id == partner_id, Partner.company_id == cid
    ).first()
    if not partner:
        return RedirectResponse("/partners?err=협력사를+찾을+수+없습니다", status_code=302)

    n = 0
    for pid in product_ids:
        prod = db.query(Product).filter(
            Product.id == pid, Product.company_id == cid
        ).first()
        if prod:
            prod.partner_id = partner.id
            n += 1
    db.commit()
    return RedirectResponse(f"/partners/{partner_id}?msg={n}개+제품이+배정되었습니다", status_code=302)


@router.post("/{partner_id}/products/{product_id}/remove")
def partner_remove_product(
    partner_id: str,
    product_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
):
    cid = get_company_id(user)
    prod = db.query(Product).filter(
        Product.id == product_id, Product.partner_id == partner_id,
        Product.company_id == cid,
    ).first()
    if prod:
        prod.partner_id = None
        db.commit()
    return RedirectResponse(f"/partners/{partner_id}?msg=제품+배정이+해제되었습니다", status_code=302)


# ── 담당자 ─────────────────────────────────────────────────────────────────────

@router.post("/{partner_id}/contacts/new")
def partner_contact_create(
    partner_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
    name: str = Form(...),
    title: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
):
    cid = get_company_id(user)
    partner = db.query(Partner).filter(
        Partner.id == partner_id, Partner.company_id == cid
    ).first()
    if not partner:
        return RedirectResponse("/partners?err=협력사를+찾을+수+없습니다", status_code=302)
    name = name.strip()
    if not name:
        return RedirectResponse(f"/partners/{partner_id}?err=담당자명을+입력해주세요", status_code=302)
    contact = PartnerContact(
        partner_id=partner.id,
        name=name,
        title=title.strip() or None,
        phone=phone.strip() or None,
        email=email.strip() or None,
    )
    db.add(contact)
    db.commit()
    return RedirectResponse(f"/partners/{partner_id}?msg=담당자가+추가되었습니다", status_code=302)


@router.post("/{partner_id}/contacts/{contact_id}/update")
def partner_contact_update(
    partner_id: str,
    contact_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
    name: str = Form(...),
    title: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
):
    contact = db.query(PartnerContact).filter(
        PartnerContact.id == contact_id, PartnerContact.partner_id == partner_id
    ).first()
    if contact:
        contact.name = name.strip() or contact.name
        contact.title = title.strip() or None
        contact.phone = phone.strip() or None
        contact.email = email.strip() or None
        db.commit()
    return RedirectResponse(f"/partners/{partner_id}?msg=담당자가+수정되었습니다", status_code=302)


@router.post("/{partner_id}/contacts/{contact_id}/delete")
def partner_contact_delete(
    partner_id: str,
    contact_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
):
    contact = db.query(PartnerContact).filter(
        PartnerContact.id == contact_id, PartnerContact.partner_id == partner_id
    ).first()
    if contact:
        # 연결된 포털 계정도 함께 삭제 (고아 로그인 방지)
        if contact.user_id:
            acct = db.query(User).filter(User.id == contact.user_id).first()
            if acct:
                db.delete(acct)
        db.delete(contact)
        db.commit()
    return RedirectResponse(f"/partners/{partner_id}?msg=담당자가+삭제되었습니다", status_code=302)


# ── 포털 계정 발급 (담당자별) ───────────────────────────────────────────────────

@router.post("/{partner_id}/contacts/{contact_id}/account")
def partner_contact_account_create(
    partner_id: str,
    contact_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
    username: str = Form(...),
    password: str = Form(...),
):
    cid = get_company_id(user)
    partner = db.query(Partner).filter(
        Partner.id == partner_id, Partner.company_id == cid
    ).first()
    contact = db.query(PartnerContact).filter(
        PartnerContact.id == contact_id, PartnerContact.partner_id == partner_id
    ).first()
    if not partner or not contact:
        return RedirectResponse("/partners?err=대상을+찾을+수+없습니다", status_code=302)
    if contact.user_id:
        return RedirectResponse(
            f"/partners/{partner_id}?err=이미+계정이+발급된+담당자입니다", status_code=302
        )

    username = username.strip()
    if not username or len(password) < 6:
        return RedirectResponse(
            f"/partners/{partner_id}?err=아이디와+6자+이상+비밀번호를+입력해주세요",
            status_code=302,
        )
    if db.query(User).filter(User.username == username).first():
        return RedirectResponse(
            f"/partners/{partner_id}?err=이미+존재하는+아이디입니다", status_code=302
        )

    account = User(
        username=username,
        # email 미설정: User.email 은 unique 제약 — 담당자간 공용 이메일 중복 시
        # IntegrityError(500) 방지. 협력사는 아이디로 로그인한다.
        email=None,
        hashed_password=hash_password(password),
        role="partner",
        is_active=True,
        email_verified=True,   # 관리자 발급 계정 — 인증 생략
        company_id=cid,
        partner_id=partner.id,
    )
    db.add(account)
    try:
        db.flush()
    except Exception:
        db.rollback()
        return RedirectResponse(
            f"/partners/{partner_id}?err=계정+생성+실패(아이디+중복+등)", status_code=302
        )
    contact.user_id = account.id
    db.commit()
    return RedirectResponse(
        f"/partners/{partner_id}?msg={contact.name}+담당자+포털+계정이+발급되었습니다", status_code=302
    )


@router.post("/{partner_id}/account/{user_id}/reset")
def partner_account_reset(
    partner_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
    new_password: str = Form(...),
):
    account = db.query(User).filter(
        User.id == user_id, User.partner_id == partner_id
    ).first()
    if account and len(new_password) >= 6:
        account.hashed_password = hash_password(new_password)
        account.current_token = None  # 기존 세션 무효화
        db.commit()
        return RedirectResponse(
            f"/partners/{partner_id}?msg=비밀번호가+초기화되었습니다", status_code=302
        )
    return RedirectResponse(
        f"/partners/{partner_id}?err=6자+이상+비밀번호를+입력해주세요", status_code=302
    )


@router.post("/{partner_id}/account/{user_id}/toggle")
def partner_account_toggle(
    partner_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
):
    account = db.query(User).filter(
        User.id == user_id, User.partner_id == partner_id
    ).first()
    if account:
        account.is_active = not account.is_active
        if not account.is_active:
            account.current_token = None
        db.commit()
    return RedirectResponse(f"/partners/{partner_id}?msg=계정+상태가+변경되었습니다", status_code=302)
