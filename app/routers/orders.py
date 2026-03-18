"""
어드민 주문 관리
"""
import io
from datetime import datetime
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.order import Order
from app.models.sales_page import SalesPage
from app.models.product import Product
from app.models.seller import Seller
from app.auth.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/orders")
templates = Jinja2Templates(directory="app/templates")


def _get_orders(db: Session, status: str = "", seller_code: str = "",
                page_id: str = "", search: str = ""):
    q = db.query(Order)
    if status == "new":
        q = q.filter(Order.payment_status == "paid", Order.order_status == "confirmed")
    elif status == "pending":
        q = q.filter(Order.payment_status == "pending")
    elif status == "shipping":
        q = q.filter(Order.order_status == "shipping")
    elif status == "delivered":
        q = q.filter(Order.order_status == "delivered")
    elif status == "cancelled":
        q = q.filter(Order.order_status == "cancelled")
    elif status == "paid":
        q = q.filter(Order.payment_status == "paid")
    if seller_code:
        q = q.filter(Order.seller_code == seller_code)
    if page_id:
        q = q.filter(Order.sales_page_id == page_id)
    if search:
        q = q.filter(
            Order.customer_name.contains(search) |
            Order.customer_phone.contains(search) |
            Order.order_number.contains(search)
        )
    return q.order_by(Order.created_at.desc()).all()


@router.get("")
def orders_list(
    request: Request,
    status: str = "",
    seller_code: str = "",
    page_id: str = "",
    search: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    orders = _get_orders(db, status, seller_code, page_id, search)
    pages = db.query(SalesPage).order_by(SalesPage.created_at.desc()).all()
    sellers = db.query(Seller).filter(Seller.is_active == True).all()

    # 탭 카운트
    counts = {
        "all": db.query(Order).count(),
        "new": db.query(Order).filter(Order.payment_status == "paid", Order.order_status == "confirmed").count(),
        "pending": db.query(Order).filter(Order.payment_status == "pending").count(),
        "shipping": db.query(Order).filter(Order.order_status == "shipping").count(),
        "delivered": db.query(Order).filter(Order.order_status == "delivered").count(),
        "cancelled": db.query(Order).filter(Order.order_status == "cancelled").count(),
    }
    return templates.TemplateResponse("orders/index.html", {
        "request": request, "orders": orders, "pages": pages,
        "sellers": sellers, "counts": counts,
        "cur_status": status, "cur_seller": seller_code,
        "cur_page": page_id, "search": search,
        "user": user, "active_page": "orders",
    })


@router.get("/export")
def orders_export(
    status: str = "",
    seller_code: str = "",
    page_id: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return RedirectResponse("/orders?err=openpyxl+미설치", status_code=302)

    orders = _get_orders(db, status, seller_code, page_id)
    pages_map = {p.id: p for p in db.query(SalesPage).all()}
    products_map = {p.id: p for p in db.query(Product).all()}

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "주문목록"

    headers = ["주문번호", "주문일시", "상품명", "옵션", "수량", "결제금액",
               "구매자명", "연락처", "결제상태", "주문상태",
               "셀러코드", "배송지", "우편번호", "택배사", "송장번호"]
    header_fill = PatternFill(fill_type="solid", fgColor="1E40AF")
    header_font = Font(bold=True, color="FFFFFF")

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    status_kr = {
        "pending": "결제대기", "paid": "결제완료",
        "cancelled": "취소", "refunded": "환불",
    }
    order_kr = {
        "pending": "주문대기", "confirmed": "주문확인",
        "shipping": "배송중", "delivered": "배송완료",
        "cancelled": "취소",
    }

    for row, o in enumerate(orders, 2):
        page = pages_map.get(o.sales_page_id)
        product = products_map.get(o.product_id)
        ws.append([
            o.order_number,
            o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else "",
            page.title if page and page.title else (product.name if product else ""),
            o.option_name or "",
            o.quantity,
            int(o.total_price),
            o.customer_name,
            o.customer_phone,
            status_kr.get(o.payment_status, o.payment_status),
            order_kr.get(o.order_status, o.order_status),
            o.seller_code or "",
            o.shipping_address + (" " + o.shipping_address2 if o.shipping_address2 else ""),
            o.shipping_zipcode,
            o.carrier_name or "",
            o.tracking_number or "",
        ])

    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 15

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"orders_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@router.get("/{order_id}")
def order_detail(order_id: str, request: Request,
                 db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        return RedirectResponse("/orders?err=주문을+찾을+수+없습니다", status_code=302)
    page = db.query(SalesPage).filter(SalesPage.id == order.sales_page_id).first()
    product = db.query(Product).filter(Product.id == order.product_id).first()
    seller = db.query(Seller).filter(Seller.id == order.seller_id).first() if order.seller_id else None
    return templates.TemplateResponse("orders/detail.html", {
        "request": request, "order": order, "page": page,
        "product": product, "seller": seller,
        "user": user, "active_page": "orders",
    })


@router.post("/{order_id}/ship")
def order_ship(
    order_id: str,
    carrier_name: str = Form(""),
    tracking_number: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if order:
        order.order_status = "shipping"
        order.carrier_name = carrier_name or None
        order.tracking_number = tracking_number or None
        order.shipped_at = datetime.utcnow()
        db.commit()
    return RedirectResponse(f"/orders/{order_id}?msg=배송처리됨", status_code=302)


@router.post("/{order_id}/deliver")
def order_deliver(order_id: str, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if order:
        order.order_status = "delivered"
        db.commit()
    return RedirectResponse(f"/orders/{order_id}?msg=배송완료처리됨", status_code=302)


@router.post("/{order_id}/cancel")
def order_cancel(
    order_id: str,
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if order:
        order.order_status = "cancelled"
        order.payment_status = "cancelled"
        if notes:
            order.notes = notes
        db.commit()
    return RedirectResponse(f"/orders/{order_id}?msg=취소처리됨", status_code=302)


@router.post("/{order_id}/notes")
def order_notes(
    order_id: str,
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = db.query(Order).filter(Order.id == order_id).first()
    if order:
        order.notes = notes or None
        db.commit()
    return RedirectResponse(f"/orders/{order_id}?msg=메모저장됨", status_code=302)
