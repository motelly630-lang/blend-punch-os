"""
B2C 공개 판매 페이지 — 인증 불필요
/shop/{slug}?seller=xxx
"""
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.database import get_db
from app.models.sales_page import SalesPage
from app.models.product import Product
from app.models.seller import Seller
from app.models.order import Order
from app.models.business_info import BusinessInfo
from app.api.payments import confirm_toss_payment
from app.config import settings

router = APIRouter(prefix="/shop")
templates = Jinja2Templates(directory="app/templates")


def _order_number() -> str:
    now = datetime.utcnow()
    suffix = uuid.uuid4().hex[:6].upper()
    return f"BP-{now.strftime('%Y%m%d')}-{suffix}"


def _get_page_and_product(slug: str, db: Session):
    page = db.query(SalesPage).filter(SalesPage.slug == slug).first()
    if not page:
        return None, None
    product = db.query(Product).filter(Product.id == page.product_id).first()
    return page, product


# ── 고정 경로 먼저 등록 ────────────────────────────────────────────────────

@router.get("/success")
async def shop_success(
    request: Request,
    paymentKey: str = "",
    orderId: str = "",
    amount: int = 0,
    db: Session = Depends(get_db),
):
    if not paymentKey or not orderId or not amount:
        return RedirectResponse("/shop/fail?message=잘못된+접근입니다", status_code=302)

    result = await confirm_toss_payment(paymentKey, orderId, amount, db)
    if not result["ok"]:
        return RedirectResponse(f"/shop/fail?message={result['error']}", status_code=302)

    order = result["order"]
    page = db.query(SalesPage).filter(SalesPage.id == order.sales_page_id).first()
    product = db.query(Product).filter(Product.id == order.product_id).first() if order else None
    return templates.TemplateResponse("shop/complete.html", {
        "request": request, "order": order,
        "page": page, "product": product,
    })


@router.get("/fail")
def shop_fail(request: Request, message: str = "결제에 실패했습니다."):
    return templates.TemplateResponse("shop/fail.html", {
        "request": request, "message": message,
    })


# ── 판매 페이지 ───────────────────────────────────────────────────────────

@router.get("/{slug}")
def shop_product(slug: str, request: Request,
                 seller: str = "", db: Session = Depends(get_db)):
    page, product = _get_page_and_product(slug, db)
    if not page or not product:
        return templates.TemplateResponse("shop/closed.html", {
            "request": request, "message": "페이지를 찾을 수 없습니다.",
        }, status_code=404)

    if page.status != "active":
        return templates.TemplateResponse("shop/closed.html", {
            "request": request, "message": "현재 판매가 종료된 페이지입니다.",
            "page": page, "product": product,
        })

    now = datetime.utcnow()
    if page.starts_at and now < page.starts_at:
        return templates.TemplateResponse("shop/closed.html", {
            "request": request, "message": "아직 판매 시작 전입니다.",
            "page": page, "product": product,
        })
    if page.ends_at and now > page.ends_at:
        return templates.TemplateResponse("shop/closed.html", {
            "request": request, "message": "판매가 종료되었습니다.",
            "page": page, "product": product,
        })

    # 셀러 검증
    seller_obj = None
    if seller:
        seller_obj = db.query(Seller).filter(
            Seller.seller_code == seller, Seller.is_active == True
        ).first()

    discount_pct = 0
    if page.original_price and page.original_price > 0 and page.price < page.original_price:
        discount_pct = round((1 - page.price / page.original_price) * 100)

    # 페이지 옵션 우선, 없으면 제품 set_options
    page_options = page.options or (product.set_options if hasattr(product, "set_options") else None) or []
    addon_products = page.addon_products or []

    biz = db.query(BusinessInfo).filter(BusinessInfo.id == 1).first()

    return templates.TemplateResponse("shop/product.html", {
        "request": request,
        "page": page,
        "product": product,
        "seller_code": seller,
        "seller": seller_obj,
        "discount_pct": discount_pct,
        "toss_client_key": settings.toss_client_key,
        "page_options": page_options,
        "addon_products": addon_products,
        "biz": biz,
    })


# ── 주문 준비 (결제 전 주문 pre-create) ──────────────────────────────────

class AddonItem(BaseModel):
    name: str
    price: float
    qty: int = 1


class PrepareBody(BaseModel):
    customer_name: str
    customer_phone: str
    customer_email: str = ""
    shipping_name: str
    shipping_phone: str
    shipping_address: str
    shipping_address2: str = ""
    shipping_zipcode: str
    shipping_memo: str = ""
    option_name: str = ""
    option_price: float = 0
    quantity: int = 1
    seller_code: str = ""
    addon_items: list[AddonItem] = []


@router.post("/{slug}/prepare")
async def shop_prepare(slug: str, body: PrepareBody,
                       db: Session = Depends(get_db)):
    page, product = _get_page_and_product(slug, db)
    if not page or page.status != "active":
        return JSONResponse({"ok": False, "error": "판매 중인 페이지가 아닙니다."}, status_code=400)

    qty = max(1, body.quantity)
    # 옵션 가격이 있으면 옵션가를 기준으로, 없으면 페이지 판매가
    base_price = body.option_price if body.option_price > 0 else page.price
    shipping = page.shipping_cost or 0
    addon_total = sum(item.price * item.qty for item in body.addon_items)
    total = round(base_price * qty + addon_total + shipping)

    # 셀러 찾기
    seller_obj = None
    if body.seller_code:
        seller_obj = db.query(Seller).filter(
            Seller.seller_code == body.seller_code, Seller.is_active == True
        ).first()

    addon_data = [{"name": a.name, "price": a.price, "qty": a.qty} for a in body.addon_items] or None

    order = Order(
        id=str(uuid.uuid4()),
        company_id=page.company_id if hasattr(page, 'company_id') else 1,
        order_number=_order_number(),
        sales_page_id=page.id,
        product_id=product.id,
        seller_id=seller_obj.id if seller_obj else None,
        seller_code=body.seller_code or None,
        customer_name=body.customer_name.strip(),
        customer_phone=body.customer_phone.strip(),
        customer_email=body.customer_email.strip() or None,
        shipping_name=body.shipping_name.strip(),
        shipping_phone=body.shipping_phone.strip(),
        shipping_address=body.shipping_address.strip(),
        shipping_address2=body.shipping_address2.strip() or None,
        shipping_zipcode=body.shipping_zipcode.strip(),
        shipping_memo=body.shipping_memo.strip() or None,
        option_name=body.option_name or None,
        quantity=qty,
        unit_price=base_price,
        total_price=total,
        addon_items=addon_data,
        payment_status="pending",
        order_status="pending",
    )
    db.add(order)
    db.commit()

    return JSONResponse({
        "ok": True,
        "order_id": order.id,
        "order_number": order.order_number,
        "amount": total,
        "order_name": f"{page.title or product.name}" + (f" ({body.option_name})" if body.option_name else ""),
    })
