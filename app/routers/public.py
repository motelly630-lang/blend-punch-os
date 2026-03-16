from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Product

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
    return [{"name": r.brand, "count": r.cnt} for r in rows]


# ── /public/products — 브랜드 목록 ─────────────────────────────
@router.get("/products")
def public_product_list(request: Request, db: Session = Depends(get_db)):
    brands = _brand_list(db)
    return templates.TemplateResponse(
        "public/products.html",
        {"request": request, "brands": brands},
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
    return templates.TemplateResponse(
        "public/brand.html",
        {"request": request, "brand_name": brand_name,
         "products": products, "total": len(products), "brands": brands},
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


# ── 하위 호환 리다이렉트 ────────────────────────────────────────
@router.get("/brand/{brand_name}")
def public_brand_redirect(brand_name: str):
    return RedirectResponse(f"/public/products/brand/{brand_name}", status_code=301)


@router.get("/products/{product_id}")
def public_product_redirect(product_id: str):
    return RedirectResponse(f"/public/products/product/{product_id}", status_code=301)
