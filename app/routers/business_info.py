"""
어드민 — 사업자 정보 / 쇼핑몰 정책 설정
GET  /settings/business-info  — 설정 폼
POST /settings/business-info  — 저장 (upsert id=1)
"""
from datetime import datetime
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.business_info import BusinessInfo
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.services.image_service import save_upload, UPLOAD_DIR_BRANDING

router = APIRouter(prefix="/settings")
templates = Jinja2Templates(directory="app/templates")

_DEFAULTS = {
    "shipping_guide": (
        "• 평일 오후 2시 이전 결제 완료 시 당일 발송됩니다.\n"
        "• 주말 및 공휴일은 발송이 없으며, 다음 영업일에 처리됩니다.\n"
        "• 도서·산간 지역은 추가 배송비가 발생할 수 있습니다.\n"
        "• 배송 완료 후 1~3일 내 수령이 원칙이며, 천재지변 등으로 지연될 수 있습니다."
    ),
    "return_policy": (
        "• 수령일로부터 7일 이내 교환/환불 신청이 가능합니다.\n"
        "• 단순 변심의 경우 왕복 배송비(6,000원)는 고객 부담입니다.\n"
        "• 제품 불량·오배송의 경우 배송비 전액 판매자 부담으로 교환/환불 처리됩니다.\n"
        "• 사용·세탁·훼손된 제품은 교환/환불이 불가합니다.\n"
        "• 교환/환불 문의: 하단 연락처로 연락해 주세요."
    ),
    "payment_guide": (
        "• 결제는 토스페이먼츠를 통해 안전하게 처리됩니다.\n"
        "• 신용카드, 체크카드, 계좌이체, 가상계좌 결제를 지원합니다.\n"
        "• 결제 완료 후 주문 확정까지 최대 1~2 영업일이 소요될 수 있습니다.\n"
        "• 환불은 결제 수단에 따라 3~5 영업일 내 처리됩니다."
    ),
}


def _get_or_create(db: Session) -> BusinessInfo:
    info = db.query(BusinessInfo).filter(BusinessInfo.id == 1).first()
    if not info:
        info = BusinessInfo(
            id=1,
            shipping_guide=_DEFAULTS["shipping_guide"],
            return_policy=_DEFAULTS["return_policy"],
            payment_guide=_DEFAULTS["payment_guide"],
        )
        db.add(info)
        db.commit()
        db.refresh(info)
    return info


@router.get("/business-info")
def biz_info_form(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    info = _get_or_create(db)
    return templates.TemplateResponse("business_info/form.html", {
        "request": request,
        "info": info,
        "user": user,
        "active_page": "business_info",
    })


@router.post("/business-info")
def biz_info_save(
    request: Request,
    company_name:      str = Form(""),
    ceo_name:          str = Form(""),
    biz_reg_number:    str = Form(""),
    mail_order_number: str = Form(""),
    address:           str = Form(""),
    phone:             str = Form(""),
    email:             str = Form(""),
    shipping_guide:    str = Form(""),
    return_policy:     str = Form(""),
    payment_guide:     str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    info = _get_or_create(db)
    info.company_name      = company_name.strip() or None
    info.ceo_name          = ceo_name.strip() or None
    info.biz_reg_number    = biz_reg_number.strip() or None
    info.mail_order_number = mail_order_number.strip() or None
    info.address           = address.strip() or None
    info.phone             = phone.strip() or None
    info.email             = email.strip() or None
    info.shipping_guide    = shipping_guide.strip() or None
    info.return_policy     = return_policy.strip() or None
    info.payment_guide     = payment_guide.strip() or None
    info.updated_at        = datetime.utcnow()
    db.commit()
    return RedirectResponse("/settings/business-info?msg=저장되었습니다", status_code=302)


@router.post("/branding/login-bg")
async def upload_login_bg(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    file: UploadFile = File(...),
):
    info = _get_or_create(db)
    url = await save_upload(file, UPLOAD_DIR_BRANDING)
    info.login_bg_image = url
    info.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse("/settings/business-info?msg=로그인+배경+이미지가+저장되었습니다", status_code=302)


@router.post("/branding/orders-banner")
async def upload_orders_banner(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    file: UploadFile = File(...),
):
    info = _get_or_create(db)
    url = await save_upload(file, UPLOAD_DIR_BRANDING)
    info.orders_banner_image = url
    info.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse("/settings/business-info?msg=주문+페이지+배너+이미지가+저장되었습니다", status_code=302)


@router.post("/branding/login-bg/delete")
def delete_login_bg(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    info = _get_or_create(db)
    info.login_bg_image = None
    info.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse("/settings/business-info?msg=로그인+배경+이미지가+삭제되었습니다", status_code=302)


@router.post("/branding/orders-banner/delete")
def delete_orders_banner(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    info = _get_or_create(db)
    info.orders_banner_image = None
    info.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse("/settings/business-info?msg=주문+페이지+배너+이미지가+삭제되었습니다", status_code=302)
