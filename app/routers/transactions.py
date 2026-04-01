from datetime import date
from fastapi import APIRouter, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.transaction import Transaction
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.auth.tenant import get_company_id

router = APIRouter(prefix="/transactions")

REVENUE_SOURCES = [
    ("smartstore", "스마트스토어"),
    ("external_link", "외부 링크"),
    ("manual", "직접 입력"),
]
COST_CATEGORIES = [
    ("supply_price", "브랜드 공급가"),
    ("ad_cost", "광고비"),
    ("other", "기타 비용"),
]


@router.post("/new")
def transaction_create(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    type: str = Form("revenue"),
    source: str = Form("manual"),
    category: str = Form(""),
    campaign_id: str = Form(""),
    amount: float = Form(0.0),
    transaction_date: str = Form(""),
    description: str = Form(""),
    notes: str = Form(""),
    redirect_to: str = Form("/settlements?tab=calc"),
):
    cid = get_company_id(current_user)
    txn_date = None
    if transaction_date:
        try:
            txn_date = date.fromisoformat(transaction_date)
        except ValueError:
            pass
    t = Transaction(
        company_id=cid,
        campaign_id=campaign_id or None,
        type=type,
        source=source,
        category=category or None,
        amount=amount,
        transaction_date=txn_date,
        description=description or None,
        notes=notes or None,
    )
    db.add(t)
    db.commit()
    return RedirectResponse(redirect_to, status_code=302)


@router.post("/{txn_id}/delete")
def transaction_delete(
    txn_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    redirect_to: str = Form("/settlements?tab=calc"),
):
    cid = get_company_id(current_user)
    t = db.query(Transaction).filter(
        Transaction.id == txn_id, Transaction.company_id == cid
    ).first()
    if t:
        db.delete(t)
        db.commit()
    return RedirectResponse(redirect_to, status_code=302)
