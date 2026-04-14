import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Request, Depends, Form, UploadFile, File
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Product, Influencer
from app.models.brand import Brand as BrandModel
from app.models.user import User
from app.auth.dependencies import get_current_user, require_admin
from app.auth.tenant import get_company_id
from app.services.image_service import save_product_image
from app.services.product_service import validate_product_completeness

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
                 q: str = "", category: str = "", completeness: str = "",
                 current_user: User = Depends(get_current_user)):
    cid = get_company_id(current_user)
    from sqlalchemy import func
    brand_rows = (
        db.query(Product.brand, func.count(Product.id).label("cnt"))
        .filter(Product.company_id == cid, Product.brand.isnot(None), Product.brand != "")
        .group_by(Product.brand)
        .order_by(Product.brand)
        .all()
    )
    brand_logos = {b.name: b.logo for b in db.query(BrandModel).filter(BrandModel.company_id == cid, BrandModel.logo.isnot(None)).all()}
    from sqlalchemy import func as _func2
    first_imgs = {r.brand: r.img for r in db.query(Product.brand, _func2.min(Product.product_image).label("img"))
                  .filter(Product.company_id == cid, Product.product_image.isnot(None), Product.product_image != "")
                  .group_by(Product.brand).all()}
    brand_list = [{"name": r.brand, "count": r.cnt, "logo": brand_logos.get(r.brand), "first_image": first_imgs.get(r.brand)} for r in brand_rows]

    products = []
    if q or category or completeness:
        query = db.query(Product).filter(
            Product.company_id == cid,
            (Product.is_archived == False) | (Product.is_archived == None),
        )
        if q:
            query = query.filter(
                Product.name.ilike(f"%{q}%") | Product.brand.ilike(f"%{q}%")
            )
        if category:
            query = query.filter(Product.category == category)
        if completeness == "complete":
            query = query.filter(Product.is_complete == True)
        elif completeness == "incomplete":
            query = query.filter(Product.is_complete == False)
        products = query.order_by(Product.created_at.desc()).limit(300).all()

    return templates.TemplateResponse(
        "products/list.html",
        {"request": request, "active_page": "products", "current_user": current_user,
         "brand_list": brand_list, "products": products,
         "q": q, "category_filter": category, "completeness": completeness,
         "filter_categories": CATEGORIES},
    )


@router.get("/brand/{brand_name}")
def product_brand(brand_name: str, request: Request, db: Session = Depends(get_db),
                  q: str = "", view: str = "gallery",
                  current_user: User = Depends(get_current_user)):
    cid = get_company_id(current_user)
    from sqlalchemy import func
    query = db.query(Product).filter(Product.company_id == cid, Product.brand == brand_name)
    if q:
        query = query.filter(Product.name.ilike(f"%{q}%"))
    products = query.order_by(Product.created_at.desc()).limit(300).all()
    brand_rows = (
        db.query(Product.brand, func.count(Product.id).label("cnt"))
        .filter(Product.company_id == cid, Product.brand.isnot(None), Product.brand != "")
        .group_by(Product.brand)
        .order_by(Product.brand)
        .all()
    )
    brand_logos = {b.name: b.logo for b in db.query(BrandModel).filter(BrandModel.company_id == cid, BrandModel.logo.isnot(None)).all()}
    brand_list = [{"name": r.brand, "count": r.cnt, "logo": brand_logos.get(r.brand)} for r in brand_rows]
    brand_obj = db.query(BrandModel).filter(BrandModel.company_id == cid, BrandModel.name == brand_name).first()
    return templates.TemplateResponse(
        "products/brand.html",
        {"request": request, "active_page": "products", "current_user": current_user,
         "brand_name": brand_name, "products": products, "q": q, "view": view,
         "brand_list": brand_list, "brand_obj": brand_obj, "filter_categories": CATEGORIES},
    )


@router.get("/new")
def product_new(request: Request, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    cid = get_company_id(current_user)
    from_products = {r.brand for r in db.query(Product.brand)
                     .filter(Product.company_id == cid, Product.brand.isnot(None), Product.brand != "").distinct()}
    from_brands = {b.name for b in db.query(BrandModel).filter(BrandModel.company_id == cid).all()}
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
    notes: str = Form(""),
    is_published: str = Form(""),
):
    cid = get_company_id(current_user)
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
        company_id=cid,
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
        notes=notes or None,
        is_published=bool(is_published),
    )
    completeness = validate_product_completeness(product)
    product.is_complete = completeness["is_complete"]
    product.missing_fields = completeness["missing_fields"] or None
    db.add(product)
    db.commit()
    db.refresh(product)
    return RedirectResponse(f"/products/{product.id}?msg=제품이+등록되었습니다", status_code=302)


@router.get("/{product_id}")
def product_detail(product_id: str, request: Request, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    cid = get_company_id(current_user)
    product = db.query(Product).filter(Product.company_id == cid, Product.id == product_id).first()
    if not product:
        return RedirectResponse("/products?err=제품을+찾을+수+없습니다", status_code=302)

    # 추천 인플루언서: 카테고리 겹치는 활성 인플루언서 top 5
    recommended_influencers = []
    product_cats = set(product.categories or [])
    if product_cats:
        all_active = db.query(Influencer).filter(Influencer.company_id == cid, Influencer.status == "active").all()
        scored = []
        for inf in all_active:
            overlap = len(product_cats & set(inf.categories or []))
            if overlap > 0:
                scored.append((overlap, inf))
        scored.sort(key=lambda x: (-x[0], -(x[1].followers or 0)))
        recommended_influencers = [inf for _, inf in scored[:5]]

    # AI 파이프라인이 자동 생성한 캠페인/제안서 조회
    from app.models.campaign import Campaign
    from app.models.proposal import Proposal as ProposalModel
    ai_campaigns = (
        db.query(Campaign)
        .filter(Campaign.company_id == cid, Campaign.product_id == product_id,
                Campaign.notes.like("%AI 파이프라인%"))
        .order_by(Campaign.created_at.desc()).limit(3).all()
    )
    ai_proposals = (
        db.query(ProposalModel)
        .filter(ProposalModel.company_id == cid, ProposalModel.product_id == product_id,
                ProposalModel.ai_generated == True)
        .order_by(ProposalModel.created_at.desc()).limit(3).all()
    )

    return templates.TemplateResponse(
        "products/detail.html",
        {
            "request": request, "active_page": "products", "current_user": current_user,
            "product": product, "recommended_influencers": recommended_influencers,
            "ai_campaigns": ai_campaigns, "ai_proposals": ai_proposals,
        },
    )


@router.get("/{product_id}/edit")
def product_edit(product_id: str, request: Request, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    cid = get_company_id(current_user)
    product = db.query(Product).filter(Product.company_id == cid, Product.id == product_id).first()
    if not product:
        return RedirectResponse("/products", status_code=302)
    from_products = {r.brand for r in db.query(Product.brand)
                     .filter(Product.company_id == cid, Product.brand.isnot(None), Product.brand != "").distinct()}
    from_brands = {b.name for b in db.query(BrandModel).filter(BrandModel.company_id == cid).all()}
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
    notes: str = Form(""),
    is_published: str = Form(""),
):
    cid = get_company_id(current_user)
    product = db.query(Product).filter(Product.company_id == cid, Product.id == product_id).first()
    if not product:
        return RedirectResponse("/products", status_code=302)

    key_benefits = [b.strip() for b in key_benefits_raw.splitlines() if b.strip()]
    new_image = _save_image(product_image) or (product_image_url.strip() or None)

    # set_options: 파싱 성공 시만 업데이트, 실패 시 기존 값 유지
    if set_options_json.strip():
        parsed_opts = _parse_set_options(set_options_json)
        # [] → None (사용자가 명시적 삭제), None이지만 raw가 있으면 기존 유지
        try:
            raw_list = json.loads(set_options_json)
            product.set_options = parsed_opts  # 빈 리스트 포함 정상 파싱
        except Exception:
            pass  # JSON 파싱 실패 → 기존 값 유지

    # categories: 파싱 성공 시만 업데이트
    if categories_json.strip():
        try:
            cats_raw = json.loads(categories_json)
            product.categories = [c for c in cats_raw if isinstance(c, str) and c.strip()] or None
        except Exception:
            pass  # 파싱 실패 → 기존 값 유지

    commission = recommended_commission_rate / 100.0  # form sends %, DB stores 0-1

    product.name = name
    product.brand = brand
    product.category = category
    product.price = price
    product.source_url = source_url or None
    product.description = description or None
    product.internal_notes = internal_notes or None
    product.notes = notes or None
    product.key_benefits = key_benefits or None
    product.unique_selling_point = unique_selling_point or None
    product.recommended_commission_rate = commission
    product.content_angle = content_angle or None
    product.positioning = positioning or None
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
    product.is_published = bool(is_published)
    if new_image:
        product.product_image = new_image

    completeness = validate_product_completeness(product)
    product.is_complete = completeness["is_complete"]
    product.missing_fields = completeness["missing_fields"] or None

    db.commit()
    return RedirectResponse(f"/products/{product_id}?msg=수정되었습니다", status_code=302)


@router.post("/{product_id}/upload-image")
async def product_upload_image(
    product_id: str,
    request: Request,
    product_image: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """이미지 파일만 독립 업로드 (AJAX multipart)"""
    cid = get_company_id(current_user)
    product = db.query(Product).filter(Product.company_id == cid, Product.id == product_id).first()
    if not product:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    new_image = _save_image(product_image)
    if not new_image:
        return JSONResponse({"ok": False, "error": "no valid image"})
    product.product_image = new_image
    completeness = validate_product_completeness(product)
    product.is_complete = completeness["is_complete"]
    product.missing_fields = completeness["missing_fields"] or None
    db.commit()
    return JSONResponse({"ok": True, "image_url": new_image})


@router.patch("/{product_id}/json")
async def product_patch_json(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """탭 저장: JSON 복합 필드 (categories, set_options, key_benefits)"""
    body = await request.json()
    cid = get_company_id(current_user)
    product = db.query(Product).filter(Product.company_id == cid, Product.id == product_id).first()
    if not product:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

    if "categories" in body:
        cats = body["categories"]
        product.categories = [c for c in cats if isinstance(c, str) and c.strip()] or None

    if "set_options" in body:
        opts = body["set_options"]
        if isinstance(opts, list):
            product.set_options = opts or None

    if "key_benefits_raw" in body:
        kbs = [b.strip() for b in body["key_benefits_raw"].splitlines() if b.strip()]
        product.key_benefits = kbs or None

    completeness = validate_product_completeness(product)
    product.is_complete = completeness["is_complete"]
    product.missing_fields = completeness["missing_fields"] or None
    db.commit()
    return JSONResponse({"ok": True, "is_complete": product.is_complete})


@router.patch("/{product_id}/field")
async def product_patch_field(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """자동 저장: 단일 필드 업데이트 (PATCH JSON body: {field, value})"""
    body = await request.json()
    field = body.get("field", "")
    value = body.get("value", "")

    cid = get_company_id(current_user)
    product = db.query(Product).filter(Product.company_id == cid, Product.id == product_id).first()
    if not product:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

    TEXT_FIELDS = {
        "name", "description", "internal_notes", "notes", "unique_selling_point",
        "content_angle", "positioning", "group_buy_guideline", "source_url",
        "product_link", "product_image", "brand", "category", "status",
        "visibility_status", "shipping_type", "carrier", "ship_origin",
        "dispatch_days", "sample_type", "product_type", "key_benefits_raw",
    }
    NUM_FIELDS = {
        "price", "consumer_price", "lowest_price", "supplier_price",
        "groupbuy_price", "shipping_cost", "sample_price",
    }
    PCT_FIELDS = {
        "discount_rate", "seller_commission_rate", "vendor_commission_rate",
        "recommended_commission_rate",
    }

    try:
        if field == "key_benefits_raw":
            kbs = [b.strip() for b in value.splitlines() if b.strip()]
            product.key_benefits = kbs or None
        elif field in TEXT_FIELDS:
            setattr(product, field, value.strip() or None)
        elif field in NUM_FIELDS:
            setattr(product, field, float(value) if value.strip() else None)
        elif field in PCT_FIELDS:
            setattr(product, field, float(value) / 100.0 if value.strip() else 0.0)
        else:
            return JSONResponse({"ok": False, "error": "unknown field"})
    except (ValueError, TypeError):
        return JSONResponse({"ok": False, "error": "invalid value"})

    completeness = validate_product_completeness(product)
    product.is_complete = completeness["is_complete"]
    product.missing_fields = completeness["missing_fields"] or None
    db.commit()
    return JSONResponse({"ok": True, "is_complete": product.is_complete})


@router.post("/{product_id}/clone")
def product_clone(product_id: str, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    cid = get_company_id(current_user)
    import uuid as _uuid
    src = db.query(Product).filter(Product.company_id == cid, Product.id == product_id).first()
    if not src:
        return RedirectResponse("/products", status_code=302)
    clone = Product(
        id=str(_uuid.uuid4()),
        company_id=cid,
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
                   current_user: User = Depends(require_admin)):
    cid = get_company_id(current_user)
    product = db.query(Product).filter(Product.company_id == cid, Product.id == product_id).first()
    if product:
        product.is_archived = True
        db.commit()
    return RedirectResponse("/products?msg=보관처리되었습니다", status_code=302)


@router.post("/remove-bg-batch")
def remove_bg_batch(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """외부 URL 이미지가 있는 모든 제품에 누끼 일괄 적용 (백그라운드)."""
    import logging
    logger = logging.getLogger(__name__)
    cid = get_company_id(current_user)
    targets = db.query(Product.id, Product.product_image).filter(
        Product.company_id == cid,
        Product.is_archived.isnot(True),
        Product.product_image.isnot(None),
        Product.product_image.like("http%"),
        ~Product.product_image.like("%amazonaws.com%"),  # S3 처리완료 제외
    ).all()
    items = [(r.id, r.product_image) for r in targets]

    def _batch(items: list):
        from app.database import SessionLocal
        from app.services.image_service import process_url_with_remove_bg, UPLOAD_DIR_PRODUCTS
        bg_db = SessionLocal()
        try:
            for pid, img_url in items:
                new_url = process_url_with_remove_bg(img_url, UPLOAD_DIR_PRODUCTS)
                if new_url:
                    prod = bg_db.query(Product).filter(Product.id == pid).first()
                    if prod:
                        prod.product_image = new_url
                        bg_db.commit()
        except Exception:
            logger.exception("일괄 누끼 배치 오류")
        finally:
            bg_db.close()

    background_tasks.add_task(_batch, items)
    from urllib.parse import quote
    return RedirectResponse(f"/products?msg={quote(f'{len(items)}개 제품 누끼 작업 시작 (백그라운드 처리 중)')}", status_code=302)
