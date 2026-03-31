from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.models.brand import Brand
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.auth.tenant import get_company_id
from app.services.image_service import save_brand_logo

router = APIRouter(prefix="/brands")
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def brand_list(request: Request, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_user)):
    cid = get_company_id(current_user)
    brands = db.query(Brand).filter(Brand.company_id == cid).order_by(Brand.name).all()
    return templates.TemplateResponse(
        "brands/list.html",
        {"request": request, "active_page": "brands", "current_user": current_user,
         "brands": brands},
    )


@router.get("/new")
def brand_new(request: Request, current_user: User = Depends(get_current_user)):
    return templates.TemplateResponse(
        "brands/form.html",
        {"request": request, "active_page": "brands", "current_user": current_user,
         "brand": None},
    )


@router.post("/new")
def brand_create(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    name: str = Form(...),
    description: str = Form(""),
    logo_file: UploadFile = File(None),
):
    cid = get_company_id(current_user)
    logo_path = save_brand_logo(logo_file, remove_bg=True)
    brand = Brand(
        company_id=cid,
        name=name,
        description=description or None,
        logo=logo_path,
    )
    db.add(brand)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return RedirectResponse(f"/brands/new?error=이미+존재하는+브랜드명입니다:+{name}", status_code=302)
    return RedirectResponse("/brands?msg=브랜드가+등록되었습니다", status_code=302)


@router.get("/{brand_id}/edit")
def brand_edit(brand_id: str, request: Request, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_user)):
    cid = get_company_id(current_user)
    brand = db.query(Brand).filter(Brand.company_id == cid, Brand.id == brand_id).first()
    if not brand:
        return RedirectResponse("/brands", status_code=302)
    return templates.TemplateResponse(
        "brands/form.html",
        {"request": request, "active_page": "brands", "current_user": current_user,
         "brand": brand},
    )


@router.post("/{brand_id}/edit")
def brand_update(
    brand_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    name: str = Form(...),
    description: str = Form(""),
    logo_file: UploadFile = File(None),
):
    cid = get_company_id(current_user)
    brand = db.query(Brand).filter(Brand.company_id == cid, Brand.id == brand_id).first()
    if not brand:
        return RedirectResponse("/brands", status_code=302)
    brand.name = name
    brand.description = description or None
    new_logo = save_brand_logo(logo_file, remove_bg=True)
    if new_logo:
        brand.logo = new_logo
    db.commit()
    return RedirectResponse("/brands?msg=수정되었습니다", status_code=302)


@router.post("/{brand_id}/delete")
def brand_delete(brand_id: str, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    cid = get_company_id(current_user)
    brand = db.query(Brand).filter(Brand.company_id == cid, Brand.id == brand_id).first()
    if brand:
        db.delete(brand)
        db.commit()
    return RedirectResponse("/brands?msg=삭제되었습니다", status_code=302)
