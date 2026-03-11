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
    "다이어트/슬리밍", "식품/음료", "생활용품", "패션/의류", "패션잡화",
    "홈/인테리어", "유아/육아", "반려동물", "스포츠/레저", "전자기기", "기타",
]

FILTER_CATEGORIES = ["식품", "주방", "리빙", "뷰티", "건강", "다이어트", "육아", "반려동물"]

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
    products = query.order_by(Product.created_at.desc()).all()
    if category:
        products = [p for p in products if category in (p.categories or [])]
    return templates.TemplateResponse(
        "products/list.html",
        {"request": request, "active_page": "products", "current_user": current_user,
         "products": products, "q": q, "view": view,
         "filter_categories": FILTER_CATEGORIES, "category_filter": category},
    )


@router.get("/new")
def product_new(request: Request, current_user: User = Depends(get_current_user)):
    return templates.TemplateResponse(
        "products/form.html",
        {"request": request, "active_page": "products", "current_user": current_user,
         "product": None, "categories": CATEGORIES},
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
    target_audience: str = Form(""),
    key_benefits_raw: str = Form(""),
    unique_selling_point: str = Form(""),
    estimated_demand: str = Form("medium"),
    recommended_commission_rate: float = Form(0.15),
    content_angle: str = Form(""),
    positioning: str = Form(""),
    usage_scenes: str = Form(""),
    recommended_inf_categories_raw: str = Form(""),
    set_options_json: str = Form("[]"),
    categories_json: str = Form("[]"),
    group_buy_guideline: str = Form(""),
    status: str = Form("draft"),
    product_image: UploadFile = File(None),
):
    key_benefits = [b.strip() for b in key_benefits_raw.splitlines() if b.strip()]
    rec_cats = [c.strip() for c in recommended_inf_categories_raw.splitlines() if c.strip()]
    image_path = _save_image(product_image)
    set_opts = _parse_set_options(set_options_json)
    try:
        cats = json.loads(categories_json)
        cats = [c for c in cats if isinstance(c, str) and c.strip()] or None
    except Exception:
        cats = None

    product = Product(
        name=name, brand=brand, category=category, price=price,
        source_url=source_url or None, description=description or None,
        target_audience=target_audience or None,
        key_benefits=key_benefits or None,
        unique_selling_point=unique_selling_point or None,
        estimated_demand=estimated_demand,
        recommended_commission_rate=recommended_commission_rate,
        content_angle=content_angle or None,
        positioning=positioning or None,
        usage_scenes=usage_scenes or None,
        recommended_inf_categories=rec_cats or None,
        set_options=set_opts,
        categories=cats,
        group_buy_guideline=group_buy_guideline or None,
        product_image=image_path,
        status=status,
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
         "product": product, "categories": CATEGORIES},
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
    target_audience: str = Form(""),
    key_benefits_raw: str = Form(""),
    unique_selling_point: str = Form(""),
    estimated_demand: str = Form("medium"),
    recommended_commission_rate: float = Form(0.15),
    content_angle: str = Form(""),
    positioning: str = Form(""),
    usage_scenes: str = Form(""),
    recommended_inf_categories_raw: str = Form(""),
    set_options_json: str = Form("[]"),
    categories_json: str = Form("[]"),
    group_buy_guideline: str = Form(""),
    status: str = Form("draft"),
    product_image: UploadFile = File(None),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return RedirectResponse("/products", status_code=302)

    key_benefits = [b.strip() for b in key_benefits_raw.splitlines() if b.strip()]
    rec_cats = [c.strip() for c in recommended_inf_categories_raw.splitlines() if c.strip()]
    new_image = _save_image(product_image)
    set_opts = _parse_set_options(set_options_json)
    try:
        cats = json.loads(categories_json)
        cats = [c for c in cats if isinstance(c, str) and c.strip()] or None
    except Exception:
        cats = None

    product.name = name
    product.brand = brand
    product.category = category
    product.price = price
    product.source_url = source_url or None
    product.description = description or None
    product.target_audience = target_audience or None
    product.key_benefits = key_benefits or None
    product.unique_selling_point = unique_selling_point or None
    product.estimated_demand = estimated_demand
    product.recommended_commission_rate = recommended_commission_rate
    product.content_angle = content_angle or None
    product.positioning = positioning or None
    product.usage_scenes = usage_scenes or None
    product.recommended_inf_categories = rec_cats or None
    product.set_options = set_opts
    product.categories = cats
    product.group_buy_guideline = group_buy_guideline or None
    product.status = status
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
