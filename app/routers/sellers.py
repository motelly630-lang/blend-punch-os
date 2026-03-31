import re
import uuid
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.seller import Seller
from app.models.order import Order
from app.models.influencer import Influencer
from app.auth.dependencies import get_current_user
from app.auth.tenant import get_company_id
from app.models.user import User

router = APIRouter(prefix="/sellers")
templates = Jinja2Templates(directory="app/templates")


def _valid_code(code: str) -> bool:
    return bool(re.match(r'^[a-z0-9\-_]{2,30}$', code))


@router.get("")
def sellers_list(request: Request, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    cid = get_company_id(user)
    sellers = db.query(Seller).filter(Seller.company_id == cid).order_by(Seller.created_at.desc()).all()
    # 셀러별 주문 수
    order_counts = {}
    for s in sellers:
        order_counts[s.id] = db.query(Order).filter(Order.company_id == cid, Order.seller_id == s.id).count()
    return templates.TemplateResponse("sellers/index.html", {
        "request": request, "sellers": sellers,
        "order_counts": order_counts, "user": user,
        "active_page": "sellers",
    })


@router.post("/new")
def seller_create(
    request: Request,
    name: str = Form(...),
    seller_code: str = Form(...),
    influencer_id: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cid = get_company_id(user)
    seller_code = seller_code.strip().lower()
    if not _valid_code(seller_code):
        return RedirectResponse("/sellers?err=셀러코드는+영문소문자·숫자·하이픈만+2~30자", status_code=302)
    if db.query(Seller).filter(Seller.company_id == cid, Seller.seller_code == seller_code).first():
        return RedirectResponse("/sellers?err=이미+사용중인+셀러코드입니다", status_code=302)
    s = Seller(
        id=str(uuid.uuid4()),
        company_id=cid,
        seller_code=seller_code,
        name=name.strip(),
        influencer_id=influencer_id or None,
        notes=notes or None,
    )
    db.add(s)
    db.commit()
    return RedirectResponse(f"/sellers?msg=셀러+{name}+등록됨", status_code=302)


@router.post("/{seller_id}/edit")
def seller_edit(
    seller_id: str,
    name: str = Form(...),
    seller_code: str = Form(...),
    notes: str = Form(""),
    is_active: str = Form("on"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cid = get_company_id(user)
    s = db.query(Seller).filter(Seller.company_id == cid, Seller.id == seller_id).first()
    if not s:
        return RedirectResponse("/sellers?err=셀러를+찾을+수+없습니다", status_code=302)
    seller_code = seller_code.strip().lower()
    if not _valid_code(seller_code):
        return RedirectResponse("/sellers?err=셀러코드+형식이+올바르지+않습니다", status_code=302)
    dup = db.query(Seller).filter(Seller.company_id == cid, Seller.seller_code == seller_code, Seller.id != seller_id).first()
    if dup:
        return RedirectResponse("/sellers?err=이미+사용중인+셀러코드입니다", status_code=302)
    s.name = name.strip()
    s.seller_code = seller_code
    s.notes = notes or None
    s.is_active = (is_active == "on")
    db.commit()
    return RedirectResponse("/sellers?msg=수정됨", status_code=302)


@router.post("/{seller_id}/delete")
def seller_delete(
    seller_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cid = get_company_id(user)
    s = db.query(Seller).filter(Seller.company_id == cid, Seller.id == seller_id).first()
    if s:
        db.delete(s)
        db.commit()
    return RedirectResponse("/sellers?msg=삭제됨", status_code=302)
