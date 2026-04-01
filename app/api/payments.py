"""
토스페이먼츠 결제 확인 API
"""
import base64
import httpx
from datetime import datetime, date
from sqlalchemy.orm import Session
from app.models.order import Order
from app.models.sales_page import SalesPage
from app.models.transaction import Transaction
from app.config import settings


async def confirm_toss_payment(payment_key: str, order_id: str, amount: int, db: Session) -> dict:
    """
    토스 confirm API 호출 → 주문 상태 업데이트.
    반환: {"ok": True/False, "error": "...", "order": Order}
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        return {"ok": False, "error": "주문을 찾을 수 없습니다."}

    # 중복 confirm 방지 (멱등성)
    if order.payment_status == "paid":
        return {"ok": True, "order": order}

    if order.payment_status != "pending":
        return {"ok": False, "error": f"처리할 수 없는 주문 상태입니다: {order.payment_status}"}

    # 금액 검증 (위변조 방지)
    if int(order.total_price) != int(amount):
        return {"ok": False, "error": f"결제금액이 일치하지 않습니다. (주문:{int(order.total_price)}, 결제:{amount})"}

    # 토스 Confirm API 호출
    secret = settings.toss_secret_key
    auth = base64.b64encode(f"{secret}:".encode()).decode()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.tosspayments.com/v1/payments/confirm",
                headers={
                    "Authorization": f"Basic {auth}",
                    "Content-Type": "application/json",
                },
                json={
                    "paymentKey": payment_key,
                    "orderId": order_id,
                    "amount": int(amount),
                },
            )
        data = resp.json()
    except Exception as ex:
        return {"ok": False, "error": f"결제 서버 연결 실패: {ex}"}

    if resp.status_code == 200:
        order.payment_key = payment_key
        order.payment_status = "paid"
        order.payment_method = data.get("method", "")
        order.paid_at = datetime.utcnow()
        order.order_status = "confirmed"

        # ── 재고 차감 ────────────────────────────────────────────────────────
        page = db.query(SalesPage).filter(SalesPage.id == order.sales_page_id).first()
        if page:
            qty = order.quantity or 1
            # 전체 재고 차감
            if page.stock_quantity is not None:
                page.stock_quantity = max(0, page.stock_quantity - qty)
            # 옵션별 재고 차감
            if order.option_name and page.options:
                opts = page.options if isinstance(page.options, list) else []
                for opt in opts:
                    if opt.get("name") == order.option_name and opt.get("stock") is not None:
                        opt["stock"] = max(0, int(opt["stock"]) - qty)
                        break
                page.options = opts  # JSON 재할당 필요 (SQLAlchemy mutation tracking)

        # ── 매출 Transaction 자동 생성 ────────────────────────────────────────
        txn = Transaction(
            company_id=order.company_id or 1,
            type="revenue",
            source="smartstore",
            amount=order.total_price,
            transaction_date=date.today(),
            description=f"주문 {order.order_number}",
            notes=order.option_name or None,
        )
        db.add(txn)

        db.commit()
        return {"ok": True, "order": order}
    else:
        err_msg = data.get("message", "결제 확인 실패")
        err_code = data.get("code", "")
        return {"ok": False, "error": f"[{err_code}] {err_msg}"}
