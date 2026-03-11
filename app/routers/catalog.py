from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from fastapi import Depends
from app.database import get_db
from app.models import Product
from app.routers.products import CATEGORIES

router = APIRouter(prefix="/catalog")
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def catalog_list(request: Request, db: Session = Depends(get_db),
                 q: str = "", category: str = ""):
    query = db.query(Product).filter(
        Product.status == "active",
        Product.visibility_status == "active",
    )
    if q:
        query = query.filter(
            Product.name.ilike(f"%{q}%") | Product.brand.ilike(f"%{q}%")
        )
    if category:
        query = query.filter(Product.category == category)
    products = query.order_by(Product.created_at.desc()).all()
    return templates.TemplateResponse(
        "catalog/list.html",
        {
            "request": request,
            "products": products,
            "q": q,
            "category_filter": category,
            "all_categories": CATEGORIES,
        },
    )


@router.get("/product/{product_id}")
def catalog_detail(product_id: str, request: Request, db: Session = Depends(get_db)):
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.status == "active",
        Product.visibility_status == "active",
    ).first()
    if not product:
        return RedirectResponse("/catalog", status_code=302)
    return templates.TemplateResponse(
        "catalog/detail.html",
        {"request": request, "product": product},
    )
