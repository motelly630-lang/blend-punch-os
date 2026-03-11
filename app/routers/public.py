from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Product

router = APIRouter(prefix="/public")
templates = Jinja2Templates(directory="app/templates")

FILTER_CATEGORIES = ["식품", "주방", "리빙", "뷰티", "건강", "다이어트", "육아", "반려동물"]


@router.get("/products")
def public_product_list(request: Request, db: Session = Depends(get_db),
                        q: str = "", category: str = ""):
    query = db.query(Product).filter(Product.status == "active")
    if q:
        query = query.filter(
            Product.name.ilike(f"%{q}%") | Product.brand.ilike(f"%{q}%")
        )
    products = query.order_by(Product.created_at.desc()).all()
    if category:
        products = [p for p in products if category in (p.categories or [])]
    return templates.TemplateResponse(
        "public/products.html",
        {"request": request, "products": products, "q": q,
         "filter_categories": FILTER_CATEGORIES, "category_filter": category},
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
