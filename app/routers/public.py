from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
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
    else:  # newest
        base = base.order_by(Product.created_at.desc())

    total = base.count()
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    rows = base.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    products = [PublicProduct.from_orm(p) for p in rows]

    # 추천 섹션 (필터 없는 첫 페이지에서만)
    newest, popular = [], []
    if not has_filter and page == 1:
        newest = [
            PublicProduct.from_orm(p) for p in
            _public_filter(db.query(Product)).order_by(Product.created_at.desc()).limit(8).all()
        ]
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
@router.post("/apply")
def submit_application(
    product_id: str = Form(""),
    product_name: str = Form(...),
    brand: str = Form(""),
    applicant_name: str = Form(...),
    contact_type: str = Form(...),
    contact_value: str = Form(...),
    channel_handle: str = Form(""),
    followers: str = Form(""),
    message: str = Form(""),
    db: Session = Depends(get_db),
):
    # 신청 레코드는 신청 대상 제품의 소속 회사로 귀속시킨다.
    # 모델 default(=1)에 맡기면 타사 제품에 들어온 신청이 1번 회사 받은함으로 섞인다.
    target = (
        _public_filter(db.query(Product)).filter(Product.id == product_id).first()
        if product_id else None
    )
    app = GroupBuyApplication(
        company_id=target.company_id if target else PUBLIC_COMPANY_ID,
        product_id=product_id or None,
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
    return RedirectResponse(f"/public/products/brand/{brand}?applied=1", status_code=302)


# ── 하위 호환 리다이렉트 ────────────────────────────────────────
@router.get("/brand/{brand_name}")
def public_brand_redirect(brand_name: str):
    return RedirectResponse(f"/public/products/brand/{brand_name}", status_code=301)


@router.get("/products/{product_id}")
def public_product_redirect(product_id: str):
    return RedirectResponse(f"/public/products/product/{product_id}", status_code=301)
