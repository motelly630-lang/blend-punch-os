"""
협력사 판매 집계 — 캠페인(공구) 기록 기준.

이 사업은 공구 판매 결과를 캠페인(Campaign)에 직접 기록한다
(actual_sales=판매수량, actual_revenue=판매금액). 협력사에 배정된
제품(product_ids)이 걸린 캠페인의 기록을 합산한다.

취소(cancelled)·보관(archived) 캠페인은 제외.
※ 쇼핑몰 실주문(Order)이 아니라 캠페인 기록이 판매의 원장(source of truth).
"""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.campaign import Campaign


def product_sales(db: Session, product_ids: list[str]) -> dict:
    """{product_id: {"qty": 판매수량, "revenue": 판매금액}} — 캠페인 기록 합산."""
    if not product_ids:
        return {}
    rows = (
        db.query(
            Campaign.product_id,
            func.coalesce(func.sum(Campaign.actual_sales), 0),
            func.coalesce(func.sum(Campaign.actual_revenue), 0.0),
        )
        .filter(
            Campaign.product_id.in_(product_ids),
            Campaign.is_archived == False,  # noqa: E712
            Campaign.status != "cancelled",
        )
        .group_by(Campaign.product_id)
        .all()
    )
    return {pid: {"qty": int(q or 0), "revenue": float(r or 0)} for pid, q, r in rows}


def sales_summary(db: Session, product_ids: list[str]) -> dict:
    """협력사 전체 합계 {"qty", "revenue", "deal_count", "by_product"}.

    deal_count = 판매금액이 기록된 공구(캠페인) 수.
    """
    by_product = product_sales(db, product_ids)
    total_qty = sum(v["qty"] for v in by_product.values())
    total_revenue = sum(v["revenue"] for v in by_product.values())

    deal_count = 0
    if product_ids:
        deal_count = (
            db.query(func.count(Campaign.id))
            .filter(
                Campaign.product_id.in_(product_ids),
                Campaign.is_archived == False,  # noqa: E712
                Campaign.status != "cancelled",
                Campaign.actual_revenue > 0,
            )
            .scalar()
        ) or 0

    return {
        "qty": total_qty,
        "revenue": total_revenue,
        "deal_count": int(deal_count),
        "by_product": by_product,
    }
