import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Product
from app.models.user import User
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/products")
templates = Jinja2Templates(directory="app/templates")

CATEGORIES = [
    "건강기능식품", "스킨케어", "뷰티/메이크업", "헤어케어", "바디케어",
    "다이어트/슬리밍", "식품/음료", "생활용품", "주방용품", "가전제품",
    "패션/의류", "패션잡화", "홈/인테리어", "유아/육아", "반려동물",
    "스포츠/레저", "전자기기", "기타",
]

CARRIERS = ["CJ대한통운", "한진택배", "로젠택배", "우체국택배", "롯데택배", "기타"]

UPLOAD_DIR = Path("static/uploads/products")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _save_image(file: UploadFile) -> str | None:
    if not file or not file.filename:
        return None
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"
    if ext not in ("jpg", "jpeg", "png", "webp", "gif"):
        ext = "jpg"
    filename = f"{uuid.uuid4().hex}.{ext}"
    dest = UPLOAD_DIR / filename
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return f"/static/uploads/products/{filename}"


def _parse_set_options(raw: str) -> list | None:
    try:
        data = json.loads(raw)
        if isinstance(data, list) and data:
            return [s for s in data if s.get("name") or s.get("price")]
        return None
    except Exception:
        return None


@router.get("")
def product_list(request: Request, db: Session = Depends(get_db), q: str = "",
                 view: str = "gallery", category: str = "",
                 current_user: User = Depends(get_current_user)):
    query = db.query(Product)
    if q:
        query = query.filter(
            Product.name.ilike(f"%{q}%") | Product.brand.ilike(f"%{q}%")
        )
    if category:
        query = query.filter(Product.category == category)
    products = query.order_by(Product.created_at.desc()).all()
    return templates.TemplateResponse(
        "products/list.html",
        {"request": request, "active_page": "products", "current_user": current_user,
         "products": products, "q": q, "view": view,
         "filter_categories": CATEGORIES, "category_filter": category},
    )


@router.get("/new")
def product_new(request: Request, current_user: User = Depends(get_current_user)):
    return templates.TemplateResponse(
        "products/form.html",
        {"request": request, "active_page": "products", "current_user": current_user,
         "product": None, "categories": CATEGORIES, "carriers": CARRIERS},
    )


@router.get("/import")
def product_import_page(request: Request, current_user: User = Depends(get_current_user)):
    return templates.TemplateResponse(
        "products/import.html",
        {"request": request, "active_page": "products", "current_user": current_user},
    )


@router.post("/new")
def product_create(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    name: str = Form(...),
    brand: str = Form(...),
    category: str = Form(...),
    price: float = Form(0),
    source_url: str = Form(""),
    description: str = Form(""),
    internal_notes: str = Form(""),
    key_benefits_raw: str = Form(""),
    unique_selling_point: str = Form(""),
    recommended_commission_rate: float = Form(15),
    content_angle: str = Form(""),
    positioning: str = Form(""),
    set_options_json: str = Form("[]"),
    categories_json: str = Form("[]"),
    group_buy_guideline: str = Form(""),
    status: str = Form("draft"),
    visibility_status: str = Form("active"),
    product_image: UploadFile = File(None),
    shipping_type: str = Form(""),
    shipping_cost: str = Form(""),
    carrier: str = Form(""),
    ship_origin: str = Form(""),
    dispatch_days: str = Form(""),
    sample_type: str = Form(""),
    sample_price: str = Form(""),
    # Phase 5 pricing fields
    consumer_price: str = Form(""),
    lowest_price: str = Form(""),
    supplier_price: str = Form(""),
    groupbuy_price: str = Form(""),
    discount_rate: str = Form(""),
    seller_commission_rate: str = Form(""),
    vendor_commission_rate: str = Form(""),
    product_link: str = Form(""),
):
    key_benefits = [b.strip() for b in key_benefits_raw.splitlines() if b.strip()]
    image_path = _save_image(product_image)
    set_opts = _parse_set_options(set_options_json)
    try:
        cats = json.loads(categories_json)
        cats = [c for c in cats if isinstance(c, str) and c.strip()] or None
    except Exception:
        cats = None
    commission = recommended_commission_rate / 100.0  # form sends %, DB stores 0-1

    product = Product(
        name=name, brand=brand, category=category, price=price,
        source_url=source_url or None, description=description or None,
        internal_notes=internal_notes or None,
        key_benefits=key_benefits or None,
        unique_selling_point=unique_selling_point or None,
        recommended_commission_rate=commission,
        visibility_status=visibility_status,
        content_angle=content_angle or None,
        positioning=positioning or None,
        set_options=set_opts,
        categories=cats,
        group_buy_guideline=group_buy_guideline or None,
        product_image=image_path,
        status=status,
        shipping_type=shipping_type or None,
        shipping_cost=float(shipping_cost) if shipping_cost else None,
        carrier=carrier or None,
        ship_origin=ship_origin or None,
        dispatch_days=dispatch_days or None,
        sample_type=sample_type or None,
        sample_price=float(sample_price) if sample_price else None,
        consumer_price=float(consumer_price) if consumer_price else 0.0,
        lowest_price=float(lowest_price) if lowest_price else 0.0,
        supplier_price=float(supplier_price) if supplier_price else 0.0,
        groupbuy_price=float(groupbuy_price) if groupbuy_price else 0.0,
        discount_rate=float(discount_rate) / 100.0 if discount_rate else 0.0,
        seller_commission_rate=float(seller_commission_rate) / 100.0 if seller_commission_rate else 0.0,
        vendor_commission_rate=float(vendor_commission_rate) / 100.0 if vendor_commission_rate else 0.0,
        product_link=product_link or None,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return RedirectResponse(f"/products/{product.id}?msg=제품이+등록되었습니다", status_code=302)


@router.get("/{product_id}")
def product_detail(product_id: str, request: Request, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return RedirectResponse("/products?err=제품을+찾을+수+없습니다", status_code=302)
    return templates.TemplateResponse(
        "products/detail.html",
        {"request": request, "active_page": "products", "current_user": current_user, "product": product},
    )


@router.get("/{product_id}/edit")
def product_edit(product_id: str, request: Request, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return RedirectResponse("/products", status_code=302)
    return templates.TemplateResponse(
        "products/form.html",
        {"request": request, "active_page": "products", "current_user": current_user,
         "product": product, "categories": CATEGORIES, "carriers": CARRIERS},
    )


@router.post("/{product_id}/edit")
def product_update(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    name: str = Form(...),
    brand: str = Form(...),
    category: str = Form(...),
    price: float = Form(0),
    source_url: str = Form(""),
    description: str = Form(""),
    internal_notes: str = Form(""),
    key_benefits_raw: str = Form(""),
    unique_selling_point: str = Form(""),
    recommended_commission_rate: float = Form(15),
    content_angle: str = Form(""),
    positioning: str = Form(""),
    set_options_json: str = Form("[]"),
    categories_json: str = Form("[]"),
    group_buy_guideline: str = Form(""),
    status: str = Form("draft"),
    visibility_status: str = Form("active"),
    product_image: UploadFile = File(None),
    shipping_type: str = Form(""),
    shipping_cost: str = Form(""),
    carrier: str = Form(""),
    ship_origin: str = Form(""),
    dispatch_days: str = Form(""),
    sample_type: str = Form(""),
    sample_price: str = Form(""),
    # Phase 5 pricing fields
    consumer_price: str = Form(""),
    lowest_price: str = Form(""),
    supplier_price: str = Form(""),
    groupbuy_price: str = Form(""),
    discount_rate: str = Form(""),
    seller_commission_rate: str = Form(""),
    vendor_commission_rate: str = Form(""),
    product_link: str = Form(""),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return RedirectResponse("/products", status_code=302)

    key_benefits = [b.strip() for b in key_benefits_raw.splitlines() if b.strip()]
    new_image = _save_image(product_image)
    set_opts = _parse_set_options(set_options_json)
    try:
        cats = json.loads(categories_json)
        cats = [c for c in cats if isinstance(c, str) and c.strip()] or None
    except Exception:
        cats = None
    commission = recommended_commission_rate / 100.0  # form sends %, DB stores 0-1

    product.name = name
    product.brand = brand
    product.category = category
    product.price = price
    product.source_url = source_url or None
    product.description = description or None
    product.internal_notes = internal_notes or None
    product.key_benefits = key_benefits or None
    product.unique_selling_point = unique_selling_point or None
    product.recommended_commission_rate = commission
    product.content_angle = content_angle or None
    product.positioning = positioning or None
    product.set_options = set_opts
    product.categories = cats
    product.group_buy_guideline = group_buy_guideline or None
    product.status = status
    product.visibility_status = visibility_status
    product.shipping_type = shipping_type or None
    product.shipping_cost = float(shipping_cost) if shipping_cost else None
    product.carrier = carrier or None
    product.ship_origin = ship_origin or None
    product.dispatch_days = dispatch_days or None
    product.sample_type = sample_type or None
    product.sample_price = float(sample_price) if sample_price else None
    product.consumer_price = float(consumer_price) if consumer_price else 0.0
    product.lowest_price = float(lowest_price) if lowest_price else 0.0
    product.supplier_price = float(supplier_price) if supplier_price else 0.0
    product.groupbuy_price = float(groupbuy_price) if groupbuy_price else 0.0
    product.discount_rate = float(discount_rate) / 100.0 if discount_rate else 0.0
    product.seller_commission_rate = float(seller_commission_rate) / 100.0 if seller_commission_rate else 0.0
    product.vendor_commission_rate = float(vendor_commission_rate) / 100.0 if vendor_commission_rate else 0.0
    product.product_link = product_link or None
    if new_image:
        product.product_image = new_image

    db.commit()
    return RedirectResponse(f"/products/{product_id}?msg=수정되었습니다", status_code=302)


@router.post("/{product_id}/delete")
def product_delete(product_id: str, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if product:
        db.delete(product)
        db.commit()
    return RedirectResponse("/products?msg=삭제되었습니다", status_code=302)
