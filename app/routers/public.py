from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Product
from app.models.brand import Brand as BrandModel
from app.models.group_buy_application import GroupBuyApplication

router = APIRouter(prefix="/public")
templates = Jinja2Templates(directory="app/templates")


def _brand_list(db: Session) -> list[dict]:
    rows = (
        db.query(Product.brand, func.count(Product.id).label("cnt"))
        .filter(Product.status == "active", Product.brand.isnot(None), Product.brand != "")
        .group_by(Product.brand)
        .order_by(Product.brand)
        .all()
    )
    brand_logos = {b.name: b.logo for b in db.query(BrandModel).filter(BrandModel.logo.isnot(None)).all()}
    return [{"name": r.brand, "count": r.cnt, "logo": brand_logos.get(r.brand)} for r in rows]


FILTER_CATEGORIES = [
    "건강기능식품", "스킨케어", "뷰티/메이크업", "헤어케어", "바디케어",
    "다이어트/슬리밍", "식품/음료", "생활용품", "주방용품", "가전제품",
    "패션/의류", "패션잡화", "홈/인테리어", "유아/육아", "반려동물",
    "스포츠/레저", "전자기기", "욕실용품", "기타",
]


# ── /public/products — 브랜드 목록 + 검색/카테고리 필터 ──────────
@router.get("/products")
def public_product_list(request: Request, db: Session = Depends(get_db),
                        q: str = "", category: str = ""):
    brands = _brand_list(db)
    products = []
    if q or category:
        query = db.query(Product).filter(Product.status == "active")
        if q:
            query = query.filter(
                Product.name.ilike(f"%{q}%") | Product.brand.ilike(f"%{q}%")
            )
        if category:
            query = query.filter(Product.category == category)
        products = query.order_by(Product.created_at.desc()).all()
    return templates.TemplateResponse(
        "public/products.html",
        {"request": request, "brands": brands, "products": products,
         "q": q, "category_filter": category, "filter_categories": FILTER_CATEGORIES},
    )


# ── /public/products/brand/{brand} — 브랜드별 제품 목록 ─────────
@router.get("/products/brand/{brand_name}")
def public_brand_products(brand_name: str, request: Request, db: Session = Depends(get_db)):
    products = (
        db.query(Product)
        .filter(Product.status == "active", Product.brand == brand_name)
        .order_by(Product.created_at.desc())
        .all()
    )
    brands = _brand_list(db)
    brand_obj = db.query(BrandModel).filter(BrandModel.name == brand_name).first()
    return templates.TemplateResponse(
        "public/brand.html",
        {"request": request, "brand_name": brand_name,
         "products": products, "total": len(products), "brands": brands,
         "brand_obj": brand_obj},
    )


# ── /public/products/product/{id} — 제품 상세 ──────────────────
@router.get("/products/product/{product_id}")
def public_product_detail(product_id: str, request: Request, db: Session = Depends(get_db)):
    product = db.query(Product).filter(
        Product.id == product_id, Product.status == "active"
    ).first()
    if not product:
        return RedirectResponse("/public/products", status_code=302)
    return templates.TemplateResponse(
        "public/product_detail.html",
        {"request": request, "product": product},
    )


# ── /public/apply — 공구 신청 POST ──────────────────────────────
@router.post("/apply")
def submit_application(
    product_id: str = Form(""),
    product_name: str = Form(...),
    brand: str = Form(""),
    applicant_name: str = Form(...),
    contact_type: str = Form(...),
    contact_value: str = Form(...),
    channel_handle: str = Form(""),
    followers: str = Form(""),
    message: str = Form(""),
    db: Session = Depends(get_db),
):
    app = GroupBuyApplication(
        product_id=product_id or None,
        product_name=product_name,
        brand=brand or None,
        applicant_name=applicant_name,
        contact_type=contact_type,
        contact_value=contact_value,
        channel_handle=channel_handle or None,
        followers=followers or None,
        message=message or None,
    )
    db.add(app)
    db.commit()
    return RedirectResponse(f"/public/products/brand/{brand}?applied=1", status_code=302)


# ── 하위 호환 리다이렉트 ────────────────────────────────────────
@router.get("/brand/{brand_name}")
def public_brand_redirect(brand_name: str):
    return RedirectResponse(f"/public/products/brand/{brand_name}", status_code=301)


@router.get("/products/{product_id}")
def public_product_redirect(product_id: str):
    return RedirectResponse(f"/public/products/product/{product_id}", status_code=301)
