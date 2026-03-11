from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Settlement, Campaign, Influencer
from app.models.user import User
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/settlements")
templates = Jinja2Templates(directory="app/templates")

SELLER_TYPES = ["사업자", "간이사업자", "프리랜서"]
# 원천세율: 사업자 3.3%, 간이사업자 3.3%, 프리랜서 3.3% (공통 기본값)
TAX_RATES = {"사업자": 0.033, "간이사업자": 0.033, "프리랜서": 0.033}


@router.get("")
def settlement_list(request: Request, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    settlements = db.query(Settlement).order_by(Settlement.created_at.desc()).all()
    total_paid = sum(s.final_payment for s in settlements if s.status == "paid")
    pending_count = sum(1 for s in settlements if s.status == "pending")
    return templates.TemplateResponse("settlements/index.html", {
        "request": request, "active_page": "settlements", "current_user": current_user,
        "settlements": settlements, "total_paid": total_paid, "pending_count": pending_count,
        "seller_types": SELLER_TYPES,
    })


@router.post("/new")
def settlement_create(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    influencer_id: str = Form(""),
    campaign_id: str = Form(""),
    period_label: str = Form(""),
    seller_type: str = Form("사업자"),
    sales_amount: float = Form(0.0),
    commission_rate: float = Form(0.15),
    notes: str = Form(""),
):
    commission_amount = sales_amount * commission_rate
    tax_rate = TAX_RATES.get(seller_type, 0.033)
    tax_amount = commission_amount * tax_rate
    final_payment = commission_amount - tax_amount

    s = Settlement(
        influencer_id=influencer_id or None,
        campaign_id=campaign_id or None,
        period_label=period_label or None,
        seller_type=seller_type,
        sales_amount=sales_amount,
        commission_rate=commission_rate,
        commission_amount=round(commission_amount),
        tax_rate=tax_rate,
        tax_amount=round(tax_amount),
        final_payment=round(final_payment),
        notes=notes or None,
    )
    db.add(s)
    db.commit()
    return RedirectResponse("/settlements?msg=정산+내역이+등록되었습니다", status_code=302)


@router.post("/{settlement_id}/confirm")
def settlement_confirm(settlement_id: str, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    s = db.query(Settlement).filter(Settlement.id == settlement_id).first()
    if s:
        s.status = "confirmed"
        db.commit()
    return RedirectResponse("/settlements?msg=확정되었습니다", status_code=302)


@router.post("/{settlement_id}/paid")
def settlement_paid(settlement_id: str, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    s = db.query(Settlement).filter(Settlement.id == settlement_id).first()
    if s:
        s.status = "paid"
        db.commit()
    return RedirectResponse("/settlements?msg=지급+완료+처리되었습니다", status_code=302)


@router.post("/{settlement_id}/delete")
def settlement_delete(settlement_id: str, db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    s = db.query(Settlement).filter(Settlement.id == settlement_id).first()
    if s:
        db.delete(s)
        db.commit()
    return RedirectResponse("/settlements?msg=삭제되었습니다", status_code=302)
