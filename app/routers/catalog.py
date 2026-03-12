from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Product, Campaign
from app.routers.products import CATEGORIES

router = APIRouter(prefix="/catalog")
templates = Jinja2Templates(directory="app/templates")

PAGE_SIZE = 20


def _public_product(p: Product) -> dict:
    """Strip internal-only fields before passing to public templates."""
    return {
        "id": p.id,
        "name": p.name,
        "brand": p.brand,
        "category": p.category,
        "categories": p.categories,
        "description": p.description,
        "unique_selling_point": p.unique_selling_point,
        "product_image": p.product_image,
        "set_options": p.set_options,
        "group_buy_guideline": p.group_buy_guideline,
        "consumer_price": p.consumer_price,
        "groupbuy_price": p.groupbuy_price,
        "discount_rate": p.discount_rate,
        "seller_commission_rate": p.seller_commission_rate,
        "shipping_type": p.shipping_type,
        "shipping_cost": p.shipping_cost,
        "carrier": p.carrier,
        "ship_origin": p.ship_origin,
        "dispatch_days": p.dispatch_days,
        "sample_type": p.sample_type,
        "sample_price": p.sample_price,
        "key_benefits": p.key_benefits,
        "product_link": p.product_link,
        "created_at": p.created_at,
        # Legacy price field for backward compat display
        "price": p.groupbuy_price or p.consumer_price or p.price,
        "recommended_commission_rate": p.seller_commission_rate or p.recommended_commission_rate,
        # NOTE: supplier_price, vendor_commission_rate, internal_notes intentionally excluded
    }


@router.get("")
def catalog_list(
    request: Request,
    db: Session = Depends(get_db),
    q: str = "",
    category: str = "",
    brand: str = "",
    page: int = 1,
):
    base_query = db.query(Product).filter(
        Product.status == "active",
        Product.visibility_status == "active",
    )

    # Search
    if q:
        base_query = base_query.filter(
            Product.name.ilike(f"%{q}%") | Product.brand.ilike(f"%{q}%")
        )
    if category:
        base_query = base_query.filter(Product.category == category)
    if brand:
        base_query = base_query.filter(Product.brand == brand)

    total = base_query.count()
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))

    products_raw = base_query.order_by(Product.created_at.desc()) \
        .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    products = [_public_product(p) for p in products_raw]

    # Recommended sections (shown only on page 1, no filters)
    popular, newest = [], []
    if page == 1 and not q and not category and not brand:
        all_active = db.query(Product).filter(
            Product.status == "active", Product.visibility_status == "active"
        )
        # 인기 공구 제품: top by campaign actual_revenue
        from sqlalchemy import func
        top_ids = (
            db.query(Campaign.product_id, func.sum(Campaign.actual_revenue).label("rev"))
            .filter(Campaign.product_id.isnot(None))
            .group_by(Campaign.product_id)
            .order_by(func.sum(Campaign.actual_revenue).desc())
            .limit(6)
            .all()
        )
        top_id_set = {r.product_id for r in top_ids}
        popular = [
            _public_product(p) for p in all_active.all()
            if p.id in top_id_set
        ][:6]
        # 신규 제품: newest 6
        newest = [_public_product(p) for p in all_active.order_by(Product.created_at.desc()).limit(6).all()]

    # Brand list for filter
    brands = sorted({
        p.brand for p in db.query(Product.brand).filter(
            Product.status == "active", Product.visibility_status == "active"
        ).distinct()
    })

    return templates.TemplateResponse(
        "catalog/list.html",
        {
            "request": request,
            "products": products,
            "q": q,
            "category_filter": category,
            "brand_filter": brand,
            "all_categories": CATEGORIES,
            "brands": brands,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "popular": popular,
            "newest": newest,
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
        {"request": request, "product": _public_product(product)},
    )


@router.post("/inquiry")
async def catalog_inquiry(
    request: Request,
    product_id: str = Form(...),
    product_name: str = Form(""),
    contact_name: str = Form(""),
    contact_info: str = Form(""),
    message: str = Form(""),
):
    """Log 공구 신청 — write to inquiry log file (stub for future DB/email)."""
    from datetime import datetime
    from pathlib import Path
    log_dir = Path("backups")
    log_dir.mkdir(exist_ok=True)
    line = (
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')} | "
        f"product={product_id} | name={contact_name} | "
        f"contact={contact_info} | msg={message}\n"
    )
    (log_dir / "inquiries.txt").open("a", encoding="utf-8").write(line)
    return templates.TemplateResponse(
        "catalog/inquiry_done.html",
        {"request": request, "product_name": product_name, "contact_name": contact_name},
    )
