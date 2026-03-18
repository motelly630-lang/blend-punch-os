import json
from pathlib import Path

from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Product, Influencer
from app.models.brand import Brand as BrandModel
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.services.image_service import save_product_image

router = APIRouter(prefix="/products")
templates = Jinja2Templates(directory="app/templates")

CATEGORIES = [
    "건강기능식품", "스킨케어", "뷰티/메이크업", "헤어케어", "바디케어",
    "다이어트/슬리밍", "식품/음료", "생활용품", "주방용품", "가전제품",
    "패션/의류", "패션잡화", "홈/인테리어", "유아/육아", "반려동물",
    "스포츠/레저", "전자기기", "욕실용품", "기타",
]

CARRIERS = ["CJ대한통운", "한진택배", "로젠택배", "우체국택배", "롯데택배", "기타"]

Path("static/uploads/products").mkdir(parents=True, exist_ok=True)


def _save_image(file: UploadFile) -> str | None:
    return save_product_image(file, remove_bg=True)


def _parse_set_options(raw: str) -> list | None:
    try:
        data = json.loads(raw)
        if isinstance(data, list) and data:
            return [s for s in data if s.get("name") or s.get("price")]
        return None
    except Exception:
        return None


@router.get("")
def product_list(request: Request, db: Session = Depends(get_db),
                 q: str = "", category: str = "",
                 current_user: User = Depends(get_current_user)):
    from sqlalchemy import func
    brand_rows = (
        db.query(Product.brand, func.count(Product.id).label("cnt"))
        .filter(Product.brand.isnot(None), Product.brand != "")
        .group_by(Product.brand)
        .order_by(Product.brand)
        .all()
    )
    brand_logos = {b.name: b.logo for b in db.query(BrandModel).filter(BrandModel.logo.isnot(None)).all()}
    from sqlalchemy import func as _func2
    first_imgs = {r.brand: r.img for r in db.query(Product.brand, _func2.min(Product.product_image).label("img"))
                  .filter(Product.product_image.isnot(None), Product.product_image != "")
                  .group_by(Product.brand).all()}
    brand_list = [{"name": r.brand, "count": r.cnt, "logo": brand_logos.get(r.brand), "first_image": first_imgs.get(r.brand)} for r in brand_rows]

    products = []
    if q or category:
        query = db.query(Product)
        if q:
            query = query.filter(
                Product.name.ilike(f"%{q}%") | Product.brand.ilike(f"%{q}%")
            )
        if category:
            query = query.filter(Product.category == category)
        products = query.order_by(Product.created_at.desc()).limit(300).all()

    return templates.TemplateResponse(
        "products/list.html",
        {"request": request, "active_page": "products", "current_user": current_user,
         "brand_list": brand_list, "products": products,
         "q": q, "category_filter": category, "filter_categories": CATEGORIES},
    )


@router.get("/brand/{brand_name}")
def product_brand(brand_name: str, request: Request, db: Session = Depends(get_db),
                  q: str = "", view: str = "gallery",
                  current_user: User = Depends(get_current_user)):
    from sqlalchemy import func
    query = db.query(Product).filter(Product.brand == brand_name)
    if q:
        query = query.filter(Product.name.ilike(f"%{q}%"))
    products = query.order_by(Product.created_at.desc()).limit(300).all()
    brand_rows = (
        db.query(Product.brand, func.count(Product.id).label("cnt"))
        .filter(Product.brand.isnot(None), Product.brand != "")
        .group_by(Product.brand)
        .order_by(Product.brand)
        .all()
    )
    brand_logos = {b.name: b.logo for b in db.query(BrandModel).filter(BrandModel.logo.isnot(None)).all()}
    brand_list = [{"name": r.brand, "count": r.cnt, "logo": brand_logos.get(r.brand)} for r in brand_rows]
    brand_obj = db.query(BrandModel).filter(BrandModel.name == brand_name).first()
    return templates.TemplateResponse(
        "products/brand.html",
        {"request": request, "active_page": "products", "current_user": current_user,
         "brand_name": brand_name, "products": products, "q": q, "view": view,
         "brand_list": brand_list, "brand_obj": brand_obj, "filter_categories": CATEGORIES},
    )


@router.get("/new")
def product_new(request: Request, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    from_products = {r.brand for r in db.query(Product.brand)
                     .filter(Product.brand.isnot(None), Product.brand != "").distinct()}
    from_brands = {b.name for b in db.query(BrandModel).all()}
    existing_brands = sorted(from_products | from_brands)
    return templates.TemplateResponse(
        "products/form.html",
        {"request": request, "active_page": "products", "current_user": current_user,
         "product": None, "categories": CATEGORIES, "carriers": CARRIERS,
         "existing_brands": existing_brands},
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
    product_image_url: str = Form(""),
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
    product_type: str = Form("A"),
):
    key_benefits = [b.strip() for b in key_benefits_raw.splitlines() if b.strip()]
    image_path = _save_image(product_image) or (product_image_url.strip() or None)
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
        product_type=product_type or "A",
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

    # 추천 인플루언서: 카테고리 겹치는 활성 인플루언서 top 5
    recommended_influencers = []
    product_cats = set(product.categories or [])
    if product_cats:
        all_active = db.query(Influencer).filter(Influencer.status == "active").all()
        scored = []
        for inf in all_active:
            overlap = len(product_cats & set(inf.categories or []))
            if overlap > 0:
                scored.append((overlap, inf))
        scored.sort(key=lambda x: (-x[0], -(x[1].followers or 0)))
        recommended_influencers = [inf for _, inf in scored[:5]]

    return templates.TemplateResponse(
        "products/detail.html",
        {
            "request": request, "active_page": "products", "current_user": current_user,
            "product": product, "recommended_influencers": recommended_influencers,
        },
    )


@router.get("/{product_id}/edit")
def product_edit(product_id: str, request: Request, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return RedirectResponse("/products", status_code=302)
    from_products = {r.brand for r in db.query(Product.brand)
                     .filter(Product.brand.isnot(None), Product.brand != "").distinct()}
    from_brands = {b.name for b in db.query(BrandModel).all()}
    existing_brands = sorted(from_products | from_brands)
    return templates.TemplateResponse(
        "products/form.html",
        {"request": request, "active_page": "products", "current_user": current_user,
         "product": product, "categories": CATEGORIES, "carriers": CARRIERS,
         "existing_brands": existing_brands},
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
    product_image_url: str = Form(""),
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
    product_type: str = Form("A"),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return RedirectResponse("/products", status_code=302)

    key_benefits = [b.strip() for b in key_benefits_raw.splitlines() if b.strip()]
    new_image = _save_image(product_image) or (product_image_url.strip() or None)
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
    product.product_type = product_type or "A"
    if new_image:
        product.product_image = new_image

    db.commit()
    return RedirectResponse(f"/products/{product_id}?msg=수정되었습니다", status_code=302)


@router.post("/{product_id}/clone")
def product_clone(product_id: str, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    import uuid as _uuid
    src = db.query(Product).filter(Product.id == product_id).first()
    if not src:
        return RedirectResponse("/products", status_code=302)
    clone = Product(
        id=str(_uuid.uuid4()),
        name=src.name + " (복제)",
        brand=src.brand, category=src.category,
        price=src.price, source_url=src.source_url,
        description=src.description, internal_notes=src.internal_notes,
        key_benefits=src.key_benefits, unique_selling_point=src.unique_selling_point,
        recommended_commission_rate=src.recommended_commission_rate,
        visibility_status="hidden", content_angle=src.content_angle,
        positioning=src.positioning, set_options=src.set_options,
        categories=src.categories, group_buy_guideline=src.group_buy_guideline,
        status="draft", shipping_type=src.shipping_type,
        shipping_cost=src.shipping_cost, carrier=src.carrier,
        ship_origin=src.ship_origin, dispatch_days=src.dispatch_days,
        sample_type=src.sample_type, sample_price=src.sample_price,
        consumer_price=src.consumer_price, lowest_price=src.lowest_price,
        supplier_price=src.supplier_price, groupbuy_price=src.groupbuy_price,
        discount_rate=src.discount_rate,
        seller_commission_rate=src.seller_commission_rate,
        vendor_commission_rate=src.vendor_commission_rate,
        product_link=src.product_link, product_type=src.product_type or "A",
        product_image=src.product_image,
    )
    db.add(clone)
    db.commit()
    return RedirectResponse(f"/products/{clone.id}/edit?msg=제품이+복제되었습니다", status_code=302)


@router.post("/{product_id}/delete")
def product_delete(product_id: str, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if product:
        db.delete(product)
        db.commit()
    return RedirectResponse("/products?msg=삭제되었습니다", status_code=302)
