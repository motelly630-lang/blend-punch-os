import json
import re
import shutil
import uuid
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.sales_page import SalesPage
from app.models.product import Product
from app.models.order import Order
from app.auth.dependencies import get_current_user
from app.auth.tenant import get_company_id
from app.models.user import User

router = APIRouter(prefix="/sales-pages")
templates = Jinja2Templates(directory="app/templates")

UPLOAD_DIR = Path("static/uploads/sales_pages")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _save_image(file: UploadFile) -> str | None:
    if not file or not file.filename:
        return None
    ext = Path(file.filename).suffix.lower()
    if ext not in _IMAGE_EXTS:
        return None
    fname = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / fname
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return f"/static/uploads/sales_pages/{fname}"


def _parse_dt(val: str):
    if not val:
        return None
    try:
        return datetime.fromisoformat(val)
    except Exception:
        return None


def _parse_json_list(val: str) -> list | None:
    if not val:
        return None
    try:
        data = json.loads(val)
        return data if isinstance(data, list) else None
    except Exception:
        return None


def _effective_status(page) -> str:
    today = datetime.now(KST).date()
    if page.starts_at and today < page.starts_at.date():
        return "waiting"
    sold_out = page.stock_quantity is not None and page.stock_quantity <= 0
    expired = page.ends_at is not None and today > page.ends_at.date()
    if sold_out or expired:
        return "closed"
    return "active"


@router.get("")
def pages_list(request: Request, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    cid = get_company_id(user)
    pages = db.query(SalesPage).filter(SalesPage.company_id == cid).order_by(SalesPage.created_at.desc()).all()
    products = {p.id: p for p in db.query(Product).filter(Product.company_id == cid).all()}

    page_ids = [p.id for p in pages]

    # 판매 페이지별 주문 수 + 매출 (SQL 집계)
    rows = db.query(
        Order.sales_page_id,
        func.count(Order.id),
        func.sum(Order.total_price),
    ).filter(
        Order.sales_page_id.in_(page_ids),
        Order.payment_status == "paid",
    ).group_by(Order.sales_page_id).all()

    order_counts = {r[0]: r[1] for r in rows}
    page_revenue = {r[0]: r[2] or 0 for r in rows}
    effective_statuses = {p.id: _effective_status(p) for p in pages}

    base_url = str(request.base_url).rstrip("/")
    return templates.TemplateResponse("sales_pages/index.html", {
        "request": request, "pages": pages, "products": products,
        "order_counts": order_counts, "page_revenue": page_revenue,
        "effective_statuses": effective_statuses,
        "base_url": base_url,
        "user": user, "active_page": "sales_pages",
    })


@router.get("/new")
def pages_new(request: Request, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    cid = get_company_id(user)
    products = db.query(Product).filter(Product.company_id == cid, Product.status == "active").order_by(Product.name).all()
    return templates.TemplateResponse("sales_pages/form.html", {
        "request": request, "page": None, "products": products,
        "user": user, "active_page": "sales_pages",
    })


@router.post("/new")
async def pages_create(
    slug: str = Form(...),
    product_id: str = Form(...),
    title: str = Form(""),
    description: str = Form(""),
    editor_content: str = Form(""),
    price: float = Form(...),
    original_price: float = Form(0),
    stock_quantity: str = Form(""),
    options_json: str = Form(""),
    addon_products_json: str = Form(""),
    shipping_type: str = Form("free"),
    shipping_cost: float = Form(0),
    carrier: str = Form(""),
    starts_at: str = Form(""),
    ends_at: str = Form(""),
    main_image_file: UploadFile = File(None),
    extra_image_files: list[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    slug = slug.strip().lower()
    if not re.match(r'^[a-z0-9\-]{2,80}$', slug):
        return RedirectResponse("/sales-pages/new?err=슬러그는+영문소문자·숫자·하이픈만+가능", status_code=302)
    cid = get_company_id(user)
    if db.query(SalesPage).filter(SalesPage.slug == slug).first():
        return RedirectResponse("/sales-pages/new?err=이미+사용중인+슬러그입니다", status_code=302)

    main_img = _save_image(main_image_file)
    extra_imgs = []
    if extra_image_files:
        for f in extra_image_files:
            url = _save_image(f)
            if url:
                extra_imgs.append(url)

    p = SalesPage(
        id=str(uuid.uuid4()),
        company_id=cid,
        slug=slug,
        product_id=product_id,
        title=title or None,
        description=description or None,
        editor_content=editor_content or None,
        price=price,
        original_price=original_price or None,
        stock_quantity=int(stock_quantity) if stock_quantity.strip() else None,
        main_image=main_img,
        extra_images=extra_imgs or None,
        options=_parse_json_list(options_json),
        addon_products=_parse_json_list(addon_products_json),
        shipping_type=shipping_type or "free",
        shipping_cost=shipping_cost or 0,
        carrier=carrier or None,
        starts_at=_parse_dt(starts_at),
        ends_at=_parse_dt(ends_at),
        status="active",
    )
    db.add(p)
    db.commit()
    return RedirectResponse("/sales-pages?msg=판매페이지+생성됨", status_code=302)


@router.get("/{page_id}/edit")
def pages_edit(page_id: str, request: Request, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    cid = get_company_id(user)
    page = db.query(SalesPage).filter(SalesPage.company_id == cid, SalesPage.id == page_id).first()
    if not page:
        return RedirectResponse("/sales-pages?err=페이지를+찾을+수+없습니다", status_code=302)
    products = db.query(Product).filter(Product.company_id == cid, Product.status == "active").order_by(Product.name).all()
    return templates.TemplateResponse("sales_pages/form.html", {
        "request": request, "page": page, "products": products,
        "user": user, "active_page": "sales_pages",
    })


@router.post("/{page_id}/edit")
async def pages_update(
    page_id: str,
    slug: str = Form(...),
    product_id: str = Form(...),
    title: str = Form(""),
    description: str = Form(""),
    editor_content: str = Form(""),
    price: float = Form(...),
    original_price: float = Form(0),
    stock_quantity: str = Form(""),
    options_json: str = Form(""),
    addon_products_json: str = Form(""),
    shipping_type: str = Form("free"),
    shipping_cost: float = Form(0),
    carrier: str = Form(""),
    starts_at: str = Form(""),
    ends_at: str = Form(""),
    main_image_file: UploadFile = File(None),
    extra_image_files: list[UploadFile] = File(None),
    existing_extra_images: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cid = get_company_id(user)
    page = db.query(SalesPage).filter(SalesPage.company_id == cid, SalesPage.id == page_id).first()
    if not page:
        return RedirectResponse("/sales-pages", status_code=302)

    slug = slug.strip().lower()
    dup = db.query(SalesPage).filter(SalesPage.slug == slug, SalesPage.id != page_id).first()
    if dup:
        return RedirectResponse(f"/sales-pages/{page_id}/edit?err=이미+사용중인+슬러그", status_code=302)

    new_main = _save_image(main_image_file)
    if new_main:
        page.main_image = new_main

    # Merge existing + new extra images
    kept = _parse_json_list(existing_extra_images) or []
    if extra_image_files:
        for f in extra_image_files:
            url = _save_image(f)
            if url:
                kept.append(url)
    page.extra_images = kept or None

    page.slug = slug
    page.product_id = product_id
    page.title = title or None
    page.description = description or None
    page.editor_content = editor_content or None
    page.price = price
    page.original_price = original_price or None
    page.stock_quantity = int(stock_quantity) if stock_quantity.strip() else None
    page.options = _parse_json_list(options_json)
    page.addon_products = _parse_json_list(addon_products_json)
    page.shipping_type = shipping_type or "free"
    page.shipping_cost = shipping_cost or 0
    page.carrier = carrier or None
    page.starts_at = _parse_dt(starts_at)
    page.ends_at = _parse_dt(ends_at)
    db.commit()
    return RedirectResponse("/sales-pages?msg=수정됨", status_code=302)


@router.post("/{page_id}/activate")
def pages_activate(page_id: str, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    cid = get_company_id(user)
    page = db.query(SalesPage).filter(SalesPage.company_id == cid, SalesPage.id == page_id).first()
    if page:
        page.status = "active"
        db.commit()
    return RedirectResponse("/sales-pages?msg=공구+오픈됨", status_code=302)


@router.post("/{page_id}/close")
def pages_close(page_id: str, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    cid = get_company_id(user)
    page = db.query(SalesPage).filter(SalesPage.company_id == cid, SalesPage.id == page_id).first()
    if page:
        page.status = "closed"
        db.commit()
    return RedirectResponse("/sales-pages?msg=공구+마감됨", status_code=302)


@router.post("/{page_id}/delete")
def pages_delete(page_id: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    cid = get_company_id(user)
    page = db.query(SalesPage).filter(SalesPage.company_id == cid, SalesPage.id == page_id).first()
    if page:
        db.delete(page)
        db.commit()
    return RedirectResponse("/sales-pages?msg=삭제됨", status_code=302)
