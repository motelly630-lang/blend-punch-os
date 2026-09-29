from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Request, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Product
from app.models.brand import Brand as BrandModel
from app.models.campaign import Campaign
from app.models.group_buy_application import GroupBuyApplication
from app.schemas.public_product import PublicProduct

router = APIRouter(prefix="/public")
templates = Jinja2Templates(directory="app/templates")

PAGE_SIZE = 24

# 공개 카탈로그의 소속 회사.
# /public 은 "블렌드펀치 전용 카탈로그"로 확정(2026-09-08). 멀티테넌트 공개몰이 아니므로
# 회사별 분기 없이 1번 회사(블렌드펀치)만 노출한다. 인증이 없는 경로여서 스코프가 빠지면
# 두 번째 회사가 제품을 등록하는 순간 그 제품이 외부에 그대로 공개된다.
# 멀티테넌트 공개몰로 방향이 바뀌면 호스트/서브도메인 → company 매핑으로 대체할 것.
PUBLIC_COMPANY_ID = 1

# 정렬 옵션: (key, 표시라벨)
SORT_OPTIONS = [
    ("newest", "신상품순"),
    ("commission", "커미션 높은순"),
    ("price_asc", "공구가 낮은순"),
    ("price_desc", "공구가 높은순"),
]

# 정렬용 유효가격 = 공구가(0이면 소비자가)
def _eff_price():
    return func.coalesce(func.nullif(Product.groupbuy_price, 0), Product.consumer_price)

# ── 공개 제품 필터 조건 ────────────────────────────────────────────
# visibility_status = 'hidden' 제품은 절대 노출 금지
def _public_filter(query):
    return query.filter(
        Product.company_id == PUBLIC_COMPANY_ID,  # 전용 카탈로그 — 타사 제품 노출 금지
        Product.status == "active",
        (Product.visibility_status == "active") | (Product.visibility_status == None),
        Product.is_archived.isnot(True),  # 보관(삭제) 제품 노출 금지
    )


def _brand_list(db: Session) -> list[dict]:
    rows = (
        _public_filter(db.query(Product.brand, func.count(Product.id).label("cnt")))
        .filter(Product.brand.isnot(None), Product.brand != "")
        .group_by(Product.brand)
        .order_by(Product.brand)
        .all()
    )
    brand_logos = {
        b.name: b.logo
        for b in db.query(BrandModel)
        .filter(BrandModel.company_id == PUBLIC_COMPANY_ID, BrandModel.logo.isnot(None))
        .all()
    }
    first_imgs = {
        r.brand: r.img
        for r in _public_filter(
            db.query(Product.brand, func.min(Product.product_image).label("img"))
        )
        .filter(Product.product_image.isnot(None), Product.product_image != "")
        .group_by(Product.brand)
        .all()
    }
    return [
        {"name": r.brand, "count": r.cnt,
         "logo": brand_logos.get(r.brand), "first_image": first_imgs.get(r.brand)}
        for r in rows
    ]


def _no_image_last():
    """사진 없는 제품을 뒤로 (정렬 첫 기준)."""
    return case((func.coalesce(Product.product_image, "") == "", 1), else_=0)


def _category_counts(db: Session) -> list[tuple[str, int]]:
    """공개 제품이 있는 카테고리와 제품 수 (많은 순)."""
    rows = (
        _public_filter(db.query(Product.category, func.count(Product.id)))
        .filter(Product.category.isnot(None), Product.category != "")
        .group_by(Product.category)
        .order_by(func.count(Product.id).desc(), Product.category)
        .all()
    )
    return [(c, n) for c, n in rows]


def _catalog_stats(db: Session, brand_count: int) -> dict:
    """첫 화면 숫자 — 모두 공개 조건(_public_filter) 안에서만 센다."""
    month_ago = datetime.utcnow() - timedelta(days=30)
    return {
        "products": _public_filter(db.query(func.count(Product.id))).scalar() or 0,
        "brands": brand_count,
        "new_month": _public_filter(db.query(func.count(Product.id)))
        .filter(Product.created_at >= month_ago).scalar() or 0,
        "sample": _public_filter(db.query(func.count(Product.id)))
        .filter(Product.sample_type == "무상").scalar() or 0,
    }


FILTER_CATEGORIES = [
    "건강기능식품", "스킨케어", "뷰티/메이크업", "헤어케어", "바디케어",
    "다이어트/슬리밍", "식품/음료", "생활용품", "주방용품", "가전제품",
    "패션/의류", "패션잡화", "홈/인테리어", "유아/육아", "반려동물",
    "스포츠/레저", "전자기기", "욕실용품", "기타",
]


# ── /public/products ─────────────────────────────────────────────
@router.get("/products")
def public_product_list(request: Request, db: Session = Depends(get_db),
                        q: str = "", category: str = "", brand: str = "",
                        sort: str = "newest", sample: str = "", page: int = 1):
    brands = _brand_list(db)

    # 필터 적용 여부 (기본 랜딩 = 필터 없음 → 추천 섹션 노출)
    has_filter = bool(q or category or brand or sample or (sort and sort != "newest"))

    base = _public_filter(db.query(Product))
    if q:
        base = base.filter(Product.name.ilike(f"%{q}%") | Product.brand.ilike(f"%{q}%"))
    if category:
        base = base.filter(Product.category == category)
    if brand:
        base = base.filter(Product.brand == brand)
    if sample == "1":
        base = base.filter(Product.sample_type.in_(["무상", "유상"]))

    # 정렬
    if sort == "commission":
        base = base.order_by(Product.seller_commission_rate.desc().nullslast(), Product.created_at.desc())
    elif sort == "price_asc":
        base = base.order_by(_eff_price().asc().nullslast(), Product.created_at.desc())
    elif sort == "price_desc":
        base = base.order_by(_eff_price().desc().nullslast(), Product.created_at.desc())
    else:  # newest — 사진 있는 제품을 먼저
        base = base.order_by(_no_image_last(), Product.created_at.desc())

    total = base.count()
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    rows = base.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    products = [PublicProduct.from_orm(p) for p in rows]

    # 추천 섹션 (필터 없는 첫 페이지에서만)
    newest, popular, top_commission, with_sample, category_rows = [], [], [], [], []
    stats, category_counts = {}, []
    if not has_filter and page == 1:
        newest = [
            PublicProduct.from_orm(p) for p in
            _public_filter(db.query(Product)).order_by(_no_image_last(), Product.created_at.desc()).limit(10).all()
        ]
        top_commission = [
            PublicProduct.from_orm(p) for p in
            _public_filter(db.query(Product)).filter(Product.seller_commission_rate > 0)
            .order_by(Product.seller_commission_rate.desc(), _no_image_last(), Product.created_at.desc())
            .limit(10).all()
        ]
        with_sample = [
            PublicProduct.from_orm(p) for p in
            _public_filter(db.query(Product)).filter(Product.sample_type == "무상")
            .order_by(_no_image_last(), Product.created_at.desc()).limit(10).all()
        ]
        category_counts = _category_counts(db)
        for cat, _cnt in category_counts[:4]:
            items = (_public_filter(db.query(Product)).filter(Product.category == cat)
                     .order_by(_no_image_last(), Product.created_at.desc()).limit(10).all())
            category_rows.append({"name": cat, "count": _cnt, "items": [PublicProduct.from_orm(p) for p in items]})
        stats = _catalog_stats(db, len(brands))
        top_ids = (
            db.query(Campaign.product_id, func.sum(Campaign.actual_revenue).label("rev"))
            .filter(Campaign.product_id.isnot(None))
            .group_by(Campaign.product_id)
            .order_by(func.sum(Campaign.actual_revenue).desc())
            .limit(8)
            .all()
        )
        id_order = [r.product_id for r in top_ids]
        if id_order:
            pop_map = {
                p.id: p for p in
                _public_filter(db.query(Product)).filter(Product.id.in_(id_order)).all()
            }
            popular = [PublicProduct.from_orm(pop_map[i]) for i in id_order if i in pop_map]

    return templates.TemplateResponse(
        "public/products.html",
        {"request": request, "brands": brands, "products": products,
         "q": q, "category_filter": category, "brand_filter": brand,
         "sort": sort, "sample_filter": sample,
         "filter_categories": FILTER_CATEGORIES, "sort_options": SORT_OPTIONS,
         "has_filter": has_filter, "newest": newest, "popular": popular,
         "top_commission": top_commission, "with_sample": with_sample,
         "category_rows": category_rows, "category_counts": category_counts, "stats": stats,
         "page": page, "total_pages": total_pages, "total": total},
    )


# ── /public/products/brand/{brand} ───────────────────────────────
@router.get("/products/brand/{brand_name}")
def public_brand_products(brand_name: str, request: Request, db: Session = Depends(get_db)):
    db_products = (
        _public_filter(db.query(Product))
        .filter(Product.brand == brand_name)
        .order_by(Product.created_at.desc())
        .all()
    )
    products = [PublicProduct.from_orm(p) for p in db_products]
    brands = _brand_list(db)
    brand_obj = (
        db.query(BrandModel)
        .filter(BrandModel.company_id == PUBLIC_COMPANY_ID, BrandModel.name == brand_name)
        .first()
    )
    return templates.TemplateResponse(
        "public/brand.html",
        {"request": request, "brand_name": brand_name,
         "products": products, "total": len(products), "brands": brands,
         "brand_obj": brand_obj},
    )


# ── /public/products/product/{id} ────────────────────────────────
@router.get("/products/product/{product_id}")
def public_product_detail(product_id: str, request: Request, db: Session = Depends(get_db)):
    db_product = _public_filter(db.query(Product)).filter(Product.id == product_id).first()
    if not db_product:
        return RedirectResponse("/public/products", status_code=302)
    product = PublicProduct.from_orm(db_product)
    return templates.TemplateResponse(
        "public/product_detail.html",
        {"request": request, "product": product},
    )


# ── /public/apply ────────────────────────────────────────────────
APPLY_SLACK_EVENT = "public_apply"   # 운영 SLACK_EVENTS 에 '직접 적어야' 발송 — all 로는 켜지지 않음
CONTACT_TYPES = ("카카오", "인스타", "전화", "이메일")
APPLY_DUP_WINDOW = timedelta(minutes=10)     # 같은 연락처·같은 제품 재신청은 새로 만들지 않음
APPLY_IP_LIMIT, APPLY_IP_WINDOW = 5, 600.0   # 같은 주소에서 10분에 5건까지
HERE_LIMIT, HERE_WINDOW = 3, timedelta(minutes=10)   # @here 는 10분에 3건까지, 그 뒤는 조용히
_apply_hits: dict[str, list[float]] = {}     # 운영 uvicorn 워커 1개 기준 (DE-004). 워커를 늘리면 공유 저장소로


def _cut(v, n: int) -> str:
    v = " ".join(str(v or "").split())
    return (v[: n - 1] + "…") if len(v) > n else v


def _apply_rate_limited(ip: str) -> bool:
    import time as _t
    now = _t.monotonic()
    hits = [t for t in _apply_hits.get(ip, []) if now - t < APPLY_IP_WINDOW]
    if len(hits) >= APPLY_IP_LIMIT:
        _apply_hits[ip] = hits
        return True
    _apply_hits[ip] = hits + [now]
    return False


def notify_application_slack(app_id: str, company_id: int, info: dict) -> None:
    """공구 신청 → Slack 02-공동구매-운영. 신청 저장 뒤 백그라운드에서 호출.
    - 이 알림은 SLACK_EVENTS 에 public_apply 를 '직접' 적었을 때만 (all 로는 켜지지 않음 — 공개 입력이라 명시적 허용)
    - 신청자 글자는 서식 없는 plain_text 칸에만 — 멘션·링크·굵게 등 슬랙 서식이 먹지 않는다
    - @here 는 10분에 3건까지 (도배 방지)
    실패해도 신청은 이미 저장돼 있다 — 어떤 오류도 밖으로 내보내지 않고 기록만 남긴다."""
    try:
        _notify_application_slack(app_id, company_id, info)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("공구 신청 Slack 알림 실패 (신청은 저장됨) id=%s", app_id)


def _recent_here_count(company_id: int) -> int:
    from app.database import SessionLocal
    from app.models.slack_notification_log import SlackNotificationLog as L
    db = SessionLocal()
    try:
        since = datetime.utcnow() - HERE_WINDOW
        return (db.query(func.count(L.id))
                .filter(L.company_id == company_id, L.event == APPLY_SLACK_EVENT, L.created_at >= since)
                .scalar() or 0)
    finally:
        db.close()


def _notify_application_slack(app_id: str, company_id: int, info: dict) -> None:
    from app.config import settings
    from app.services import slack_notify as sn
    if APPLY_SLACK_EVENT not in sn.enabled_events():   # 'all' 이어도 직접 적지 않았으면 보내지 않음
        return
    here = _recent_here_count(company_id) < HERE_LIMIT
    plain = lambda t: {"type": "plain_text", "text": t, "emoji": False}
    fields = [plain(f"제품: {_cut(info.get('product_name'), 120)}"),
              plain(f"브랜드: {_cut(info.get('brand'), 60) or '-'}"),
              plain(f"신청자: {_cut(info.get('applicant_name'), 60)}"),
              plain(f"연락: {_cut(info.get('contact_type'), 20)} · {_cut(info.get('contact_value'), 100)}")]
    if info.get("channel_handle") or info.get("followers"):
        fields.append(plain(f"채널: {_cut(info.get('channel_handle'), 80) or '-'} · 팔로워 {_cut(info.get('followers'), 30) or '-'}"))
    link = f"{settings.app_base_url.rstrip('/')}/applications"
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "🔥 새 공구 신청", "emoji": True}},
        # 우리가 쓰는 줄만 mrkdwn (@here·링크). 신청자 글자는 아래 plain_text 칸에만
        {"type": "section", "text": {"type": "mrkdwn",
                                     "text": ("<!here> " if here else "") + "공개 카탈로그에서 새 공구 신청이 들어왔어요."}},
        {"type": "section", "fields": fields},
    ]
    if info.get("message"):
        blocks.append({"type": "section", "text": plain(f"메시지: {_cut(info.get('message'), 500)}")})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"<{link}|OS 신청 관리에서 보기>"}]})
    text = f"🔥 새 공구 신청 — {_cut(info.get('product_name'), 60)} / {_cut(info.get('applicant_name'), 30)}"
    sn.post(APPLY_SLACK_EVENT, "groupbuy", text, company_id, dedupe_key=f"{APPLY_SLACK_EVENT}:{app_id}", blocks=blocks)


@router.post("/apply")
def submit_application(
    request: Request,
    background: BackgroundTasks,
    product_id: str = Form(""),
    product_name: str = Form(""),
    brand: str = Form(""),
    applicant_name: str = Form(""),
    contact_type: str = Form(""),
    contact_value: str = Form(""),
    channel_handle: str = Form(""),
    followers: str = Form(""),
    message: str = Form(""),
    return_to: str = Form(""),
    db: Session = Depends(get_db),
):
    target = (
        _public_filter(db.query(Product)).filter(Product.id == product_id).first()
        if product_id else None
    )

    def back(**q):
        qs = "&".join(f"{k}={quote(str(v))}" for k, v in q.items())
        if return_to == "detail" and target:
            return RedirectResponse(f"/public/products/product/{target.id}?{qs}", status_code=302)
        return RedirectResponse(f"/public/products/brand/{quote(brand or '')}?{qs}", status_code=302)

    # 서버 검사 — 화면 제한(maxlength 등)을 우회해도 걸러낸다
    applicant_name, contact_value = applicant_name.strip(), contact_value.strip()
    channel_handle, followers, message = channel_handle.strip(), followers.strip(), message.strip()
    product_name, brand = product_name.strip(), brand.strip()
    if target:   # 공개 제품이면 이름·브랜드는 서버 값으로 (화면이 보낸 값보다 믿을 수 있음)
        product_name, brand = target.name, target.brand or brand
    if (not applicant_name or not contact_value or not product_name or contact_type not in CONTACT_TYPES
            or len(applicant_name) > 100 or len(contact_value) > 200 or len(product_name) > 200
            or len(brand) > 200 or len(channel_handle) > 200 or len(followers) > 50 or len(message) > 2000):
        return back(apply_error="입력한 내용을 확인해주세요 (이름·연락처는 필수, 글자 수 제한)")

    ip = request.client.host if request.client else "?"
    # 같은 연락처·같은 제품으로 10분 안에 다시 신청 → 새로 만들지 않고 알림도 없음
    dup = (db.query(GroupBuyApplication.id)
           .filter(GroupBuyApplication.contact_value == contact_value,
                   GroupBuyApplication.product_name == product_name,
                   GroupBuyApplication.created_at >= datetime.utcnow() - APPLY_DUP_WINDOW)
           .first())
    if dup:
        return back(applied=1, dup=1)
    if _apply_rate_limited(ip):
        return back(apply_error="신청이 너무 많아요. 잠시 후 다시 시도해주세요")

    # 신청 레코드는 신청 대상 제품의 소속 회사로 귀속시킨다.
    # 모델 default(=1)에 맡기면 타사 제품에 들어온 신청이 1번 회사 받은함으로 섞인다.
    app = GroupBuyApplication(
        company_id=target.company_id if target else PUBLIC_COMPANY_ID,
        product_id=target.id if target else None,   # 공개 제품이 아니면 연결하지 않음
        product_name=product_name,
        brand=brand or None,
        applicant_name=applicant_name,
        contact_type=contact_type,
        contact_value=contact_value,
        channel_handle=channel_handle or None,
        followers=followers or None,
        message=message or None,
    )
    db.add(app)
    db.commit()
    background.add_task(notify_application_slack, app.id, app.company_id, {
        "product_name": product_name, "brand": brand, "applicant_name": applicant_name,
        "contact_type": contact_type, "contact_value": contact_value,
        "channel_handle": channel_handle, "followers": followers, "message": message,
    })
    return back(applied=1)


# ── 하위 호환 리다이렉트 ────────────────────────────────────────
@router.get("/brand/{brand_name}")
def public_brand_redirect(brand_name: str):
    return RedirectResponse(f"/public/products/brand/{brand_name}", status_code=301)


@router.get("/products/{product_id}")
def public_product_redirect(product_id: str):
    return RedirectResponse(f"/public/products/product/{product_id}", status_code=301)
