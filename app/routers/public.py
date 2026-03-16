from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Product

router = APIRouter(prefix="/public")
templates = Jinja2Templates(directory="app/templates")

FILTER_CATEGORIES = ["식품", "주방", "리빙", "뷰티", "건강", "다이어트", "육아", "반려동물"]


def _brand_list(db: Session) -> list[dict]:
    rows = (
        db.query(Product.brand, func.count(Product.id).label("cnt"))
        .filter(Product.status == "active", Product.brand.isnot(None), Product.brand != "")
        .group_by(Product.brand)
        .order_by(Product.brand)
        .all()
    )
    return [{"name": r.brand, "count": r.cnt} for r in rows]


@router.get("/products")
def public_product_list(request: Request, db: Session = Depends(get_db),
                        q: str = "", category: str = "", brand: str = ""):
    query = db.query(Product).filter(Product.status == "active")
    if q:
        query = query.filter(
            Product.name.ilike(f"%{q}%") | Product.brand.ilike(f"%{q}%")
        )
    if brand:
        query = query.filter(Product.brand == brand)
    products = query.order_by(Product.created_at.desc()).all()
    if category:
        products = [p for p in products if category in (p.categories or [])]
    brands = _brand_list(db)
    return templates.TemplateResponse(
        "public/products.html",
        {"request": request, "products": products, "q": q,
         "filter_categories": FILTER_CATEGORIES, "category_filter": category,
         "brand_filter": brand, "brands": brands},
    )


@router.get("/brand/{brand_name}")
def public_brand(brand_name: str, request: Request, db: Session = Depends(get_db)):
    products = (
        db.query(Product)
        .filter(Product.status == "active", Product.brand == brand_name)
        .order_by(Product.created_at.desc())
        .all()
    )
    brands = _brand_list(db)
    return templates.TemplateResponse(
        "public/brand.html",
        {"request": request, "brand_name": brand_name,
         "products": products, "total": len(products), "brands": brands},
    )


@router.get("/products/{product_id}")
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
