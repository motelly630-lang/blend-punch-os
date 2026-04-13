"""
BLEND PUNCH Public API v1
shop.blendpunch.com (BLEND PICK) 전용 외부 API

Base: /api/v1
인증: GET 엔드포인트는 인증 불필요 / POST는 Bearer 토큰 선택
CORS: shop.blendpunch.com 허용
"""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.product import Product
from app.models.influencer import Influencer
from app.models.sales_page import SalesPage
from app.models.order import Order
from app.models.campaign import Campaign
from app.models.trend import TrendItem
from app.models.user import User
from app.models.group_buy_application import GroupBuyApplication
from app.auth.service import verify_password, create_access_token, decode_token

router = APIRouter(prefix="/api/v1", tags=["Public API v1"])


# ── 공통 헬퍼 ──────────────────────────────────────────────────────────────────

def _order_number() -> str:
    now = datetime.utcnow()
    return f"BP-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


def _get_current_user(authorization: Optional[str]) -> Optional[dict]:
    """Bearer 토큰 파싱 — 없으면 None (비로그인 허용)."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]
    return decode_token(token)


# ── Pydantic 스키마 ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class OrderCreateRequest(BaseModel):
    sales_page_id: str
    seller_code: Optional[str] = None
    option_name: Optional[str] = None
    quantity: int = 1
    customer_name: str
    customer_phone: str
    customer_email: Optional[str] = None
    shipping_name: str
    shipping_phone: str
    shipping_address: str
    shipping_address2: Optional[str] = None
    shipping_zipcode: str
    shipping_memo: Optional[str] = None


class ApplicationCreateRequest(BaseModel):
    product_id: Optional[str] = None
    product_name: str
    brand: Optional[str] = None
    applicant_name: str
    contact_type: str                   # 카카오|인스타|전화|이메일
    contact_value: str
    channel_handle: Optional[str] = None
    followers: Optional[str] = None     # "5만", "12,000" 등 문자열
    message: Optional[str] = None


# ── 인증 ──────────────────────────────────────────────────────────────────────

@router.post("/auth/login")
def shop_login(body: LoginRequest, db: Session = Depends(get_db)):
    """Shop 소비자/인플루언서 로그인 → Bearer 토큰 반환."""
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="비활성화된 계정입니다.")

    token = create_access_token(user.username, user.role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "subscription": user.subscription,
        },
    }


# ── 제품 ──────────────────────────────────────────────────────────────────────

@router.get("/products")
def list_products(
    category: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    """SHOP 노출 제품 목록 (is_published=True)."""
    qs = db.query(Product).filter(
        Product.is_published == True,
        Product.is_archived == False,
    )
    if category:
        qs = qs.filter(Product.category == category)
    if q:
        qs = qs.filter(Product.name.ilike(f"%{q}%"))

    total = qs.count()
    products = qs.order_by(Product.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [_serialize_product(p) for p in products],
    }


@router.get("/products/{product_id}")
def get_product(product_id: str, db: Session = Depends(get_db)):
    """제품 상세."""
    p = db.query(Product).filter(
        Product.id == product_id,
        Product.is_published == True,
        Product.is_archived == False,
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="제품을 찾을 수 없습니다.")
    return _serialize_product(p, detail=True)


def _serialize_product(p: Product, detail: bool = False) -> dict:
    data = {
        "id": p.id,
        "name": p.name,
        "brand": p.brand,
        "category": p.category,
        "consumer_price": p.consumer_price,
        "groupbuy_price": p.groupbuy_price,
        "discount_rate": p.discount_rate,
        "product_image": p.product_image,
        "shipping_type": p.shipping_type,
        "shipping_cost": p.shipping_cost,
    }
    if detail:
        data.update({
            "description": p.description,
            "key_benefits": p.key_benefits,
            "unique_selling_point": p.unique_selling_point,
            "target_audience": p.target_audience,
            "usage_scenes": p.usage_scenes,
            "categories": p.categories,
            "group_buy_guideline": p.group_buy_guideline,
            "set_options": p.set_options,
            "dispatch_days": p.dispatch_days,
            "carrier": p.carrier,
        })
    return data


# ── 판매 페이지 (공구 단위) ────────────────────────────────────────────────────

@router.get("/sales-pages")
def list_sales_pages(
    product_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    """활성 판매 페이지(공구) 목록."""
    qs = db.query(SalesPage).filter(SalesPage.is_published == True)
    if product_id:
        qs = qs.filter(SalesPage.product_id == product_id)
    if status:
        qs = qs.filter(SalesPage.status == status)
    else:
        qs = qs.filter(SalesPage.status.in_(["scheduled", "active"]))

    total = qs.count()
    pages = qs.order_by(SalesPage.starts_at.asc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [_serialize_sales_page(sp) for sp in pages],
    }


@router.get("/sales-pages/{page_id}")
def get_sales_page(page_id: str, db: Session = Depends(get_db)):
    """판매 페이지 상세."""
    sp = db.query(SalesPage).filter(
        SalesPage.id == page_id,
        SalesPage.is_published == True,
    ).first()
    if not sp:
        raise HTTPException(status_code=404, detail="판매 페이지를 찾을 수 없습니다.")
    return _serialize_sales_page(sp, detail=True)


def _serialize_sales_page(sp: SalesPage, detail: bool = False) -> dict:
    data = {
        "id": sp.id,
        "slug": sp.slug,
        "product_id": sp.product_id,
        "campaign_id": sp.campaign_id,
        "title": sp.title,
        "price": sp.price,
        "original_price": sp.original_price,
        "main_image": sp.main_image,
        "status": sp.status,
        "starts_at": sp.starts_at.isoformat() if sp.starts_at else None,
        "ends_at": sp.ends_at.isoformat() if sp.ends_at else None,
        "shipping_type": sp.shipping_type,
        "shipping_cost": sp.shipping_cost,
        "options": sp.options,
        "stock_quantity": sp.stock_quantity,
    }
    if detail:
        data.update({
            "description": sp.description,
            "editor_content": sp.editor_content,
            "extra_images": sp.extra_images,
            "addon_products": sp.addon_products,
            "carrier": sp.carrier,
        })
    return data


# ── 인플루언서 ────────────────────────────────────────────────────────────────

@router.get("/influencers")
def list_influencers(
    platform: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    featured: Optional[bool] = Query(None),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    """인플루언서 목록."""
    qs = db.query(Influencer).filter(Influencer.status == "active")
    if platform:
        qs = qs.filter(Influencer.platform == platform)
    if q:
        qs = qs.filter(Influencer.name.ilike(f"%{q}%"))

    total = qs.count()
    items = qs.order_by(Influencer.followers.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [_serialize_influencer(inf) for inf in items],
    }


@router.get("/influencers/{influencer_id}")
def get_influencer(influencer_id: str, db: Session = Depends(get_db)):
    inf = db.query(Influencer).filter(
        Influencer.id == influencer_id,
        Influencer.status == "active",
    ).first()
    if not inf:
        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다.")
    return _serialize_influencer(inf)


def _serialize_influencer(inf: Influencer) -> dict:
    return {
        "id": inf.id,
        "name": inf.name,
        "platform": inf.platform,
        "handle": inf.handle,
        "followers": inf.followers,
        "categories": inf.categories,
        "profile_image": inf.profile_image,
        "profile_url": inf.profile_url,
        "audience_age_range": inf.audience_age_range,
    }


# ── 트렌드 ────────────────────────────────────────────────────────────────────

@router.get("/trends")
def list_trends(
    limit: int = Query(10, le=50),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """
    트렌드 목록.
    비구독자: 첫 1개 전체 공개, 나머지는 메타(제목/점수)만 반환.
    구독자: 전체 공개.
    """
    user = _get_current_user(authorization)
    is_subscriber = False

    if user:
        u = db.query(User).filter(User.username == user.get("sub")).first()
        is_subscriber = bool(u and u.subscription)

    items = (
        db.query(TrendItem)
        .filter(TrendItem.is_actionable == True)
        .order_by(TrendItem.trend_score.desc())
        .limit(limit)
        .all()
    )

    result = []
    for idx, t in enumerate(items):
        if is_subscriber or idx == 0:
            result.append(_serialize_trend(t, full=True))
        else:
            result.append(_serialize_trend(t, full=False))

    return {"items": result, "is_subscriber": is_subscriber}


def _serialize_trend(t: TrendItem, full: bool = True) -> dict:
    base = {
        "id": t.id,
        "title": t.title,
        "category": t.category,
        "trend_score": t.trend_score,
        "full_access": full,
    }
    if full:
        base.update({
            "summary": t.summary,
            "tags": t.tags,
            "brands": t.brands,
            "season": t.season,
            "matched_products": t.matched_products,
        })
    return base


# ── 주문 ──────────────────────────────────────────────────────────────────────

@router.post("/orders")
def create_order(
    body: OrderCreateRequest,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Shop 주문 생성 (결제 전 pending 상태)."""
    sp = db.query(SalesPage).filter(
        SalesPage.id == body.sales_page_id,
        SalesPage.is_published == True,
        SalesPage.status == "active",
    ).first()
    if not sp:
        raise HTTPException(status_code=404, detail="판매 중인 페이지를 찾을 수 없습니다.")

    # 재고 확인
    if sp.stock_quantity is not None and sp.stock_quantity <= 0:
        raise HTTPException(status_code=400, detail="재고가 없습니다.")

    # seller_code → seller_id 조회
    seller_id = None
    if body.seller_code:
        from app.models.seller import Seller
        seller = db.query(Seller).filter(
            Seller.seller_code == body.seller_code,
            Seller.is_active == True,
        ).first()
        if seller:
            seller_id = seller.id

    unit_price = sp.price
    total_price = unit_price * body.quantity

    order = Order(
        id=str(uuid.uuid4()),
        order_number=_order_number(),
        sales_page_id=sp.id,
        product_id=sp.product_id,
        seller_id=seller_id,
        seller_code=body.seller_code,
        customer_name=body.customer_name,
        customer_phone=body.customer_phone,
        customer_email=body.customer_email,
        shipping_name=body.shipping_name,
        shipping_phone=body.shipping_phone,
        shipping_address=body.shipping_address,
        shipping_address2=body.shipping_address2,
        shipping_zipcode=body.shipping_zipcode,
        shipping_memo=body.shipping_memo,
        option_name=body.option_name,
        quantity=body.quantity,
        unit_price=unit_price,
        total_price=total_price,
        payment_status="pending",
        order_status="pending",
        company_id=sp.company_id,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "total_price": order.total_price,
        "payment_status": order.payment_status,
    }


@router.get("/orders/{order_id}")
def get_order_status(
    order_id: str,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """주문 상태 조회."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")
    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "order_status": order.order_status,
        "payment_status": order.payment_status,
        "total_price": order.total_price,
        "created_at": order.created_at.isoformat(),
    }


# ── 공구 신청 ─────────────────────────────────────────────────────────────────

@router.post("/applications")
def create_application(
    body: ApplicationCreateRequest,
    db: Session = Depends(get_db),
):
    """인플루언서 공구 신청."""
    app_obj = GroupBuyApplication(
        id=str(uuid.uuid4()),
        product_id=body.product_id,
        product_name=body.product_name,
        brand=body.brand,
        applicant_name=body.applicant_name,
        contact_type=body.contact_type,
        contact_value=body.contact_value,
        channel_handle=body.channel_handle,
        followers=body.followers,
        message=body.message,
        status="new",
    )
    db.add(app_obj)
    db.commit()

    return {"status": "ok", "message": "신청이 접수되었습니다."}
