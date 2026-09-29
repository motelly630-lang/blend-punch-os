import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Request, Depends, Form, UploadFile, File
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Product, Influencer, ProductFieldLog
from app.models.brand import Brand as BrandModel
from app.models.user import User
from app.auth.dependencies import get_current_user, require_admin
from app.auth.tenant import get_company_id
from app.services.image_service import save_product_image
from app.services.product_service import (
    validate_product_completeness,
    normalize_status,
    normalize_visibility,
)

router = APIRouter(prefix="/products")
templates = Jinja2Templates(directory="app/templates")

CATEGORIES = [
    "건강기능식품", "스킨케어", "뷰티/메이크업", "헤어케어", "바디케어",
    "다이어트/슬리밍", "식품/음료", "생활용품", "주방용품", "가전제품",
    "패션/의류", "패션잡화", "홈/인테리어", "유아/육아", "반려동물",
    "스포츠/레저", "전자기기", "욕실용품", "기타",
]

CARRIERS = ["CJ대한통운", "한진택배", "로젠택배", "우체국택배", "롯데택배", "기타"]

Path("static/uploads/products").mkdir(parents=True, exist_ok=True)


def _save_image(file: UploadFile) -> str | None:
    return save_product_image(file, remove_bg=True)


def _parse_set_options(raw: str) -> list | None:
    try:
        data = json.loads(raw)
        if isinstance(data, list) and data:
            return [s for s in data if s.get("name") or s.get("price")]
        return None
    except Exception:
        return None


def _parse_str_list(raw: str) -> list | None:
    """JSON 문자열 배열 파싱 → 공백 제거된 str 리스트 (실패 시 None)."""
    try:
        data = json.loads(raw)
        cleaned = [c.strip() for c in data if isinstance(c, str) and c.strip()]
        return cleaned or None
    except Exception:
        return None


def _ensure_brand(db: Session, cid: int, brand_name: str) -> None:
    """제품에 지정된 브랜드가 Brand 테이블에 없으면 자동 생성.

    - Product.brand 문자열 구조는 그대로 유지 (FK 아님).
    - Brand.name 은 전역 unique 이므로 이름 기준으로만 존재 여부 확인 → unique 충돌 회피.
    - 커밋은 호출부(제품 저장 트랜잭션)에서 함께 처리.
    """
    name = (brand_name or "").strip()
    if not name:
        return
    exists = db.query(BrandModel).filter(BrandModel.name == name).first()
    if not exists:
        db.add(BrandModel(company_id=cid, name=name))


def _checked_number(value, lo: float, hi: float):
    """빈 값 → None, 범위 안의 유한한 숫자 → float, 그 외(음수·범위 밖·무한대·숫자 아님) → False."""
    import math
    text = (value or "").strip() if isinstance(value, str) else str(value)
    if not text:
        return None
    try:
        num = float(text)
    except (TypeError, ValueError):
        return False
    return num if math.isfinite(num) and lo <= num <= hi else False


def _log_value(v):
    """기록용 문자열 — 목록은 줄바꿈으로, 비어 있으면 None."""
    if v is None or v == "":
        return None
    if isinstance(v, list):
        return "\n".join(str(x) for x in v) or None
    return str(v)


def _log_change(db, cid, product_id, field, before, after, user, *, via=None, source_url=None):
    """사람이 제품 칸을 바꾼 기록 (값이 실제로 바뀐 경우만). 자동 채우기 학습 재료."""
    old, new = _log_value(before), _log_value(after)
    if old == new:
        return
    src = (source_url or "").strip()[:1000]
    src = src if src.lower().startswith(("http://", "https://")) else None   # 링크로 보여주므로 http(s)만
    try:
        with db.begin_nested():   # 기록이 실패해도(예: 표 생성 전) 칸 저장은 되게 — 기록만 건너뛴다
            db.add(ProductFieldLog(company_id=cid, product_id=product_id, field=field, old_value=old, new_value=new,
                                   source_url=src, via=(via or "")[:20] or None,
                                   user_id=getattr(user, "id", None), username=getattr(user, "username", None)))
    except Exception:
        import logging
        logging.getLogger(__name__).exception("제품 입력 기록 저장 실패 — 칸 저장은 계속")


# 빈칸(채워야 할 정보) 필터 — key: (표시 이름, 조건)
def _missing_filters():
    from sqlalchemy import func, or_
    return {
        "image": ("사진 없음", func.coalesce(Product.product_image, "") == ""),
        "price": ("공구가 없음", or_(Product.groupbuy_price.is_(None), Product.groupbuy_price == 0)),
        "commission": ("커미션 없음", or_(Product.seller_commission_rate.is_(None), Product.seller_commission_rate == 0)),
        "usp": ("한 줄 소개 없음", func.coalesce(Product.unique_selling_point, "") == ""),
        "category": ("카테고리 없음", func.coalesce(Product.category, "") == ""),
    }


PRODUCT_PAGE_SIZE = 60


@router.get("")
def product_list(request: Request, db: Session = Depends(get_db),
                 q: str = "", category: str = "", completeness: str = "",
                 missing: str = "", tab: str = "products", view: str = "gallery", page: int = 1,
                 current_user: User = Depends(get_current_user)):
    cid = get_company_id(current_user)
    from sqlalchemy import func
    live = (Product.company_id == cid, Product.is_archived.isnot(True))
    brand_rows = (
        db.query(Product.brand, func.count(Product.id).label("cnt"))
        .filter(*live, Product.brand.isnot(None), Product.brand != "")
        .group_by(Product.brand)
        .order_by(Product.brand)
        .all()
    )
    brand_logos = {b.name: b.logo for b in db.query(BrandModel).filter(BrandModel.company_id == cid, BrandModel.logo.isnot(None)).all()}
    first_imgs = {r.brand: r.img for r in db.query(Product.brand, func.min(Product.product_image).label("img"))
                  .filter(*live, Product.product_image.isnot(None), Product.product_image != "")
                  .group_by(Product.brand).all()}
    brand_list = [{"name": r.brand, "count": r.cnt, "logo": brand_logos.get(r.brand), "first_image": first_imgs.get(r.brand)} for r in brand_rows]

    # 빈칸 요약 — 회사 범위·보관 제외 안에서만 센다
    mf = _missing_filters()
    total_all = db.query(func.count(Product.id)).filter(*live).scalar() or 0
    missing_counts = {k: db.query(func.count(Product.id)).filter(*live, cond).scalar() or 0
                      for k, (_label, cond) in mf.items()}
    missing_labels = {k: label for k, (label, _c) in mf.items()}
    if missing not in mf:
        missing = ""
    if tab not in ("products", "brands"):
        tab = "products"
    if view not in ("gallery", "list", "fill"):
        view = "gallery"

    products, total, total_pages = [], 0, 1
    if tab == "products":
        query = db.query(Product).filter(*live)
        if q:
            query = query.filter(Product.name.ilike(f"%{q}%") | Product.brand.ilike(f"%{q}%"))
        if category:
            query = query.filter(Product.category == category)
        if completeness == "complete":
            query = query.filter(Product.is_complete == True)
        elif completeness == "incomplete":
            query = query.filter(Product.is_complete == False)
        if missing:
            query = query.filter(mf[missing][1])
        total = query.count()
        total_pages = max(1, (total + PRODUCT_PAGE_SIZE - 1) // PRODUCT_PAGE_SIZE)
        page = max(1, min(page, total_pages))
        products = (query.order_by(Product.created_at.desc())
                    .offset((page - 1) * PRODUCT_PAGE_SIZE).limit(PRODUCT_PAGE_SIZE).all())

    recent_logs = []
    if tab == "products" and view == "fill":
        try:   # 기록 표가 아직 없어도 화면은 열리게
            with db.begin_nested():
                rows = (db.query(ProductFieldLog, Product.name)
                        .outerjoin(Product, (Product.id == ProductFieldLog.product_id) & (Product.company_id == cid))
                        .filter(ProductFieldLog.company_id == cid)
                        .order_by(ProductFieldLog.created_at.desc()).limit(20).all())
            recent_logs = [{"log": lg, "name": nm} for lg, nm in rows]
        except Exception:
            import logging
            logging.getLogger(__name__).exception("제품 입력 기록 조회 실패 — 화면은 기록 없이")

    return templates.TemplateResponse(
        "products/list.html",
        {"request": request, "active_page": "products", "current_user": current_user,
         "brand_list": brand_list, "products": products,
         "q": q, "category_filter": category, "completeness": completeness,
         "missing": missing, "missing_counts": missing_counts, "missing_labels": missing_labels,
         "tab": tab, "view": view, "page": page, "total_pages": total_pages, "total": total,
         "total_all": total_all, "filter_categories": CATEGORIES, "recent_logs": recent_logs},
    )


@router.get("/brand/{brand_name}")
def product_brand(brand_name: str, request: Request, db: Session = Depends(get_db),
                  q: str = "", view: str = "gallery",
                  current_user: User = Depends(get_current_user)):
    cid = get_company_id(current_user)
    from sqlalchemy import func
    query = db.query(Product).filter(
        Product.company_id == cid,
        Product.brand == brand_name,
        Product.is_archived.isnot(True),  # 보관(삭제) 제품 제외
    )
    if q:
        query = query.filter(Product.name.ilike(f"%{q}%"))
    products = query.order_by(Product.created_at.desc()).limit(300).all()
    brand_rows = (
        db.query(Product.brand, func.count(Product.id).label("cnt"))
        .filter(Product.company_id == cid, Product.brand.isnot(None), Product.brand != "",
                Product.is_archived.isnot(True))
        .group_by(Product.brand)
        .order_by(Product.brand)
        .all()
    )
    brand_logos = {b.name: b.logo for b in db.query(BrandModel).filter(BrandModel.company_id == cid, BrandModel.logo.isnot(None)).all()}
    brand_list = [{"name": r.brand, "count": r.cnt, "logo": brand_logos.get(r.brand)} for r in brand_rows]
    brand_obj = db.query(BrandModel).filter(BrandModel.company_id == cid, BrandModel.name == brand_name).first()
    return templates.TemplateResponse(
        "products/brand.html",
        {"request": request, "active_page": "products", "current_user": current_user,
         "brand_name": brand_name, "products": products, "q": q, "view": view,
         "brand_list": brand_list, "brand_obj": brand_obj, "filter_categories": CATEGORIES},
    )


# ── 복사 버튼(북마크) — 대표님 브라우저에서 보고 있는 판매 페이지의 사진·가격·이름·링크를 복사 ──
# 서버가 대신 읽으면 네이버 등이 막는다(2026-09-28 확인). 사람이 보는 페이지에서 사람이 누르는 방식이라 막히지 않는다.
COPY_BUTTON_JS = (
    "(function(){"
    "var q=function(s){var e=document.querySelector(s);return e?(e.getAttribute('content')||''):''};"
    "var o={v:1,url:location.href,name:q('meta[property=\"og:title\"]')||document.title,"
    "image:q('meta[property=\"og:image\"]'),"
    "description:q('meta[property=\"og:description\"]')||q('meta[name=\"description\"]'),"
    "price:q('meta[property=\"product:price:amount\"]')};"
    "try{document.querySelectorAll('script[type=\"application/ld+json\"]').forEach(function(s){"
    "var d=JSON.parse(s.textContent);(Array.isArray(d)?d:(d['@graph']||[d])).forEach(function(n){"
    "if(n&&/product/i.test(String(n['@type']))){o.name=n.name||o.name;var im=n.image;"
    "im=Array.isArray(im)?im[0]:im;im=(im&&im.url)||im;if(typeof im==='string')o.image=im;"
    "var of=Array.isArray(n.offers)?n.offers[0]:n.offers;if(of&&(of.price||of.lowPrice))o.price=of.price||of.lowPrice;}})})}catch(e){}"
    "if(!o.price){var b='';document.querySelectorAll('[class*=price],[class*=Price]').forEach(function(el){"
    "if(b)return;var m=(el.textContent||'').replace(/\\s/g,'').match(/([0-9][0-9,]{2,})원/);if(m)b=m[1]});o.price=b}"
    "var t='BPOS1:'+JSON.stringify(o);"
    "var ok=function(){alert('OS로 복사했어요: '+String(o.name||'').slice(0,40)+'\\nOS 빠르게 채우기에서 [📋 붙여넣기]를 누르세요')};"
    "var no=function(){prompt('자동 복사가 막혔어요. 아래 글자를 전부 복사해서 OS에 붙여넣으세요',t)};"
    "if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(t).then(ok,no)}else{no()}"
    "})();"
)


@router.get("/copy-button")
def product_copy_button(request: Request, current_user: User = Depends(get_current_user)):
    """복사 버튼 설치 안내 (브라우저 즐겨찾기 막대에 끌어다 놓기)."""
    return templates.TemplateResponse("products/copy_button.html", {
        "request": request, "active_page": "products", "current_user": current_user,
        "bookmarklet": "javascript:" + COPY_BUTTON_JS,
    })


@router.get("/new")
def product_new(request: Request, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    cid = get_company_id(current_user)
    from_products = {r.brand for r in db.query(Product.brand)
                     .filter(Product.company_id == cid, Product.brand.isnot(None), Product.brand != "").distinct()}
    from_brands = {b.name for b in db.query(BrandModel).filter(BrandModel.company_id == cid).all()}
    existing_brands = sorted(from_products | from_brands)
    return templates.TemplateResponse(
        "products/form.html",
        {"request": request, "active_page": "products", "current_user": current_user,
         "product": None, "categories": CATEGORIES, "carriers": CARRIERS,
         "existing_brands": existing_brands},
    )


@router.get("/import")
def product_import_page(request: Request, current_user: User = Depends(get_current_user)):
    return templates.TemplateResponse(
        "products/import.html",
        {"request": request, "active_page": "products", "current_user": current_user},
    )


@router.post("/new")
def product_create(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    name: str = Form(...),
    brand: str = Form(...),
    category: str = Form(...),
    price: float = Form(0),
    source_url: str = Form(""),
    description: str = Form(""),
    internal_notes: str = Form(""),
    key_benefits_raw: str = Form(""),
    unique_selling_point: str = Form(""),
    recommended_commission_rate: float = Form(15),
    content_angle: str = Form(""),
    positioning: str = Form(""),
    set_options_json: str = Form("[]"),
    categories_json: str = Form("[]"),
    recommended_inf_json: str = Form("[]"),
    group_buy_guideline: str = Form(""),
    status: str = Form("active"),
    visibility_status: str = Form("active"),
    product_image: UploadFile = File(None),
    product_image_url: str = Form(""),
    shipping_type: str = Form(""),
    shipping_cost: str = Form(""),
    carrier: str = Form(""),
    ship_origin: str = Form(""),
    dispatch_days: str = Form(""),
    sample_type: str = Form(""),
    sample_price: str = Form(""),
    # Phase 5 pricing fields
    consumer_price: str = Form(""),
    lowest_price: str = Form(""),
    supplier_price: str = Form(""),
    groupbuy_price: str = Form(""),
    discount_rate: str = Form(""),
    seller_commission_rate: str = Form(""),
    vendor_commission_rate: str = Form(""),
    product_link: str = Form(""),
    product_type: str = Form("A"),
    notes: str = Form(""),
    is_published: str = Form(""),
):
    cid = get_company_id(current_user)
    key_benefits = [b.strip() for b in key_benefits_raw.splitlines() if b.strip()]
    image_path = _save_image(product_image) or (product_image_url.strip() or None)
    set_opts = _parse_set_options(set_options_json)
    cats = _parse_str_list(categories_json)
    rec_inf = _parse_str_list(recommended_inf_json)
    commission = recommended_commission_rate / 100.0  # form sends %, DB stores 0-1

    product = Product(
        company_id=cid,
        name=name, brand=brand, category=category, price=price,
        source_url=source_url or None, description=description or None,
        internal_notes=internal_notes or None,
        key_benefits=key_benefits or None,
        unique_selling_point=unique_selling_point or None,
        recommended_commission_rate=commission,
        visibility_status=normalize_visibility(visibility_status),
        content_angle=content_angle or None,
        positioning=positioning or None,
        set_options=set_opts,
        categories=cats,
        recommended_inf_categories=rec_inf,
        group_buy_guideline=group_buy_guideline or None,
        product_image=image_path,
        status=normalize_status(status),
        shipping_type=shipping_type or None,
        shipping_cost=float(shipping_cost) if shipping_cost else None,
        carrier=carrier or None,
        ship_origin=ship_origin or None,
        dispatch_days=dispatch_days or None,
        sample_type=sample_type or None,
        sample_price=float(sample_price) if sample_price else None,
        consumer_price=float(consumer_price) if consumer_price else 0.0,
        lowest_price=float(lowest_price) if lowest_price else 0.0,
        supplier_price=float(supplier_price) if supplier_price else 0.0,
        groupbuy_price=float(groupbuy_price) if groupbuy_price else 0.0,
        discount_rate=float(discount_rate) / 100.0 if discount_rate else 0.0,
        seller_commission_rate=float(seller_commission_rate) / 100.0 if seller_commission_rate else 0.0,
        vendor_commission_rate=float(vendor_commission_rate) / 100.0 if vendor_commission_rate else 0.0,
        product_link=product_link or None,
        product_type=product_type or "A",
        notes=notes or None,
        is_published=bool(is_published),
    )
    completeness = validate_product_completeness(product)
    product.is_complete = completeness["is_complete"]
    product.missing_fields = completeness["missing_fields"] or None
    _ensure_brand(db, cid, brand)
    db.add(product)
    db.commit()
    db.refresh(product)
    return RedirectResponse(f"/products/{product.id}?msg=제품이+등록되었습니다", status_code=302)


@router.get("/{product_id}")
def product_detail(product_id: str, request: Request, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    cid = get_company_id(current_user)
    product = db.query(Product).filter(Product.company_id == cid, Product.id == product_id).first()
    if not product:
        return RedirectResponse("/products?err=제품을+찾을+수+없습니다", status_code=302)

    # 추천 인플루언서: 카테고리 겹치는 활성 인플루언서 top 5
    recommended_influencers = []
    product_cats = set(product.categories or [])
    if product_cats:
        all_active = db.query(Influencer).filter(Influencer.company_id == cid, Influencer.status == "active").all()
        scored = []
        for inf in all_active:
            overlap = len(product_cats & set(inf.categories or []))
            if overlap > 0:
                scored.append((overlap, inf))
        scored.sort(key=lambda x: (-x[0], -(x[1].followers or 0)))
        recommended_influencers = [inf for _, inf in scored[:5]]

    # AI 파이프라인이 자동 생성한 캠페인/제안서 조회
    from app.models.campaign import Campaign
    from app.models.proposal import Proposal as ProposalModel
    ai_campaigns = (
        db.query(Campaign)
        .filter(Campaign.company_id == cid, Campaign.product_id == product_id,
                Campaign.notes.like("%AI 파이프라인%"))
        .order_by(Campaign.created_at.desc()).limit(3).all()
    )
    ai_proposals = (
        db.query(ProposalModel)
        .filter(ProposalModel.company_id == cid, ProposalModel.product_id == product_id,
                ProposalModel.ai_generated == True)
        .order_by(ProposalModel.created_at.desc()).limit(3).all()
    )

    # 모집 링크 — 공개 카탈로그 상세 주소 + ?ref=직원아이디-채널 (유입 경로 표시)
    from app.config import settings
    from app.routers.public import _public_filter, recruit_user_code
    recruit = {
        "url": f"{settings.app_base_url.rstrip('/')}/public/products/product/{product.id}",
        "user": recruit_user_code(db, current_user),
        "is_public": _public_filter(db.query(Product.id)).filter(Product.id == product.id).first() is not None,
    }

    return templates.TemplateResponse(
        "products/detail.html",
        {
            "request": request, "active_page": "products", "current_user": current_user,
            "product": product, "recommended_influencers": recommended_influencers,
            "ai_campaigns": ai_campaigns, "ai_proposals": ai_proposals, "recruit": recruit,
        },
    )


@router.get("/{product_id}/edit")
def product_edit(product_id: str, request: Request, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    cid = get_company_id(current_user)
    product = db.query(Product).filter(Product.company_id == cid, Product.id == product_id).first()
    if not product:
        return RedirectResponse("/products", status_code=302)
    from_products = {r.brand for r in db.query(Product.brand)
                     .filter(Product.company_id == cid, Product.brand.isnot(None), Product.brand != "").distinct()}
    from_brands = {b.name for b in db.query(BrandModel).filter(BrandModel.company_id == cid).all()}
    existing_brands = sorted(from_products | from_brands)
    return templates.TemplateResponse(
        "products/form.html",
        {"request": request, "active_page": "products", "current_user": current_user,
         "product": product, "categories": CATEGORIES, "carriers": CARRIERS,
         "existing_brands": existing_brands},
    )


@router.post("/{product_id}/edit")
def product_update(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    name: str = Form(...),
    brand: str = Form(...),
    category: str = Form(...),
    price: float = Form(0),
    source_url: str = Form(""),
    description: str = Form(""),
    internal_notes: str = Form(""),
    key_benefits_raw: str = Form(""),
    unique_selling_point: str = Form(""),
    recommended_commission_rate: float = Form(15),
    content_angle: str = Form(""),
    positioning: str = Form(""),
    set_options_json: str = Form("[]"),
    categories_json: str = Form("[]"),
    recommended_inf_json: str = Form("[]"),
    group_buy_guideline: str = Form(""),
    status: str = Form("active"),
    visibility_status: str = Form("active"),
    product_image: UploadFile = File(None),
    product_image_url: str = Form(""),
    shipping_type: str = Form(""),
    shipping_cost: str = Form(""),
    carrier: str = Form(""),
    ship_origin: str = Form(""),
    dispatch_days: str = Form(""),
    sample_type: str = Form(""),
    sample_price: str = Form(""),
    # Phase 5 pricing fields
    consumer_price: str = Form(""),
    lowest_price: str = Form(""),
    supplier_price: str = Form(""),
    groupbuy_price: str = Form(""),
    discount_rate: str = Form(""),
    seller_commission_rate: str = Form(""),
    vendor_commission_rate: str = Form(""),
    product_link: str = Form(""),
    product_type: str = Form("A"),
    notes: str = Form(""),
    is_published: str = Form(""),
):
    cid = get_company_id(current_user)
    product = db.query(Product).filter(Product.company_id == cid, Product.id == product_id).first()
    if not product:
        return RedirectResponse("/products", status_code=302)

    key_benefits = [b.strip() for b in key_benefits_raw.splitlines() if b.strip()]
    new_image = _save_image(product_image) or (product_image_url.strip() or None)

    # set_options: 파싱 성공 시만 업데이트, 실패 시 기존 값 유지
    if set_options_json.strip():
        parsed_opts = _parse_set_options(set_options_json)
        # [] → None (사용자가 명시적 삭제), None이지만 raw가 있으면 기존 유지
        try:
            raw_list = json.loads(set_options_json)
            product.set_options = parsed_opts  # 빈 리스트 포함 정상 파싱
        except Exception:
            pass  # JSON 파싱 실패 → 기존 값 유지

    # categories: 파싱 성공 시만 업데이트
    if categories_json.strip():
        try:
            cats_raw = json.loads(categories_json)
            product.categories = [c for c in cats_raw if isinstance(c, str) and c.strip()] or None
        except Exception:
            pass  # 파싱 실패 → 기존 값 유지

    # recommended_inf_categories: 파싱 성공 시만 업데이트
    if recommended_inf_json.strip():
        try:
            rec_raw = json.loads(recommended_inf_json)
            product.recommended_inf_categories = [c for c in rec_raw if isinstance(c, str) and c.strip()] or None
        except Exception:
            pass  # 파싱 실패 → 기존 값 유지

    commission = recommended_commission_rate / 100.0  # form sends %, DB stores 0-1

    product.name = name
    product.brand = brand
    product.category = category
    product.price = price
    product.source_url = source_url or None
    product.description = description or None
    product.internal_notes = internal_notes or None
    product.notes = notes or None
    product.key_benefits = key_benefits or None
    product.unique_selling_point = unique_selling_point or None
    product.recommended_commission_rate = commission
    product.content_angle = content_angle or None
    product.positioning = positioning or None
    product.group_buy_guideline = group_buy_guideline or None
    product.status = normalize_status(status, default=product.status or "draft")
    product.visibility_status = normalize_visibility(visibility_status)
    product.shipping_type = shipping_type or None
    product.shipping_cost = float(shipping_cost) if shipping_cost else None
    product.carrier = carrier or None
    product.ship_origin = ship_origin or None
    product.dispatch_days = dispatch_days or None
    product.sample_type = sample_type or None
    product.sample_price = float(sample_price) if sample_price else None
    product.consumer_price = float(consumer_price) if consumer_price else 0.0
    product.lowest_price = float(lowest_price) if lowest_price else 0.0
    product.supplier_price = float(supplier_price) if supplier_price else 0.0
    product.groupbuy_price = float(groupbuy_price) if groupbuy_price else 0.0
    product.discount_rate = float(discount_rate) / 100.0 if discount_rate else 0.0
    product.seller_commission_rate = float(seller_commission_rate) / 100.0 if seller_commission_rate else 0.0
    product.vendor_commission_rate = float(vendor_commission_rate) / 100.0 if vendor_commission_rate else 0.0
    product.product_link = product_link or None
    product.product_type = product_type or "A"
    product.is_published = bool(is_published)
    if new_image:
        product.product_image = new_image

    completeness = validate_product_completeness(product)
    product.is_complete = completeness["is_complete"]
    product.missing_fields = completeness["missing_fields"] or None

    _ensure_brand(db, cid, brand)
    db.commit()
    return RedirectResponse(f"/products/{product_id}?msg=수정되었습니다", status_code=302)


@router.post("/{product_id}/upload-image")
async def product_upload_image(
    product_id: str,
    request: Request,
    product_image: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """이미지 파일만 독립 업로드 (AJAX multipart)"""
    cid = get_company_id(current_user)
    product = db.query(Product).filter(Product.company_id == cid, Product.id == product_id).first()
    if not product:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    new_image = _save_image(product_image)
    if not new_image:
        return JSONResponse({"ok": False, "error": "no valid image"})
    before = product.product_image
    product.product_image = new_image
    form = await request.form()
    _log_change(db, cid, product.id, "product_image", before, new_image, current_user,
                via=form.get("via") or "upload", source_url=form.get("source_url"))
    completeness = validate_product_completeness(product)
    product.is_complete = completeness["is_complete"]
    product.missing_fields = completeness["missing_fields"] or None
    db.commit()
    return JSONResponse({"ok": True, "image_url": new_image})


@router.patch("/{product_id}/json")
async def product_patch_json(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """탭 저장: JSON 복합 필드 (categories, set_options, key_benefits)"""
    body = await request.json()
    cid = get_company_id(current_user)
    product = db.query(Product).filter(Product.company_id == cid, Product.id == product_id).first()
    if not product:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

    if "categories" in body:
        cats = body["categories"]
        product.categories = [c for c in cats if isinstance(c, str) and c.strip()] or None

    if "set_options" in body:
        opts = body["set_options"]
        if isinstance(opts, list):
            product.set_options = opts or None

    if "key_benefits_raw" in body:
        kbs = [b.strip() for b in body["key_benefits_raw"].splitlines() if b.strip()]
        product.key_benefits = kbs or None

    completeness = validate_product_completeness(product)
    product.is_complete = completeness["is_complete"]
    product.missing_fields = completeness["missing_fields"] or None
    db.commit()
    return JSONResponse({"ok": True, "is_complete": product.is_complete})


@router.post("/{product_id}/suggest")
async def product_suggest(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """자동 채우기 1단계: '찾은 곳 링크'의 판매 페이지에서 대표 사진·가격·소개 후보를 뽑아 돌려준다.
    저장하지 않는다 — 사람이 '적용'을 누르면 기존 칸 저장(PATCH /field, via=autofill)으로 저장·기록된다."""
    import asyncio
    import httpx
    from app.services.safe_fetch import UnsafeURL, safe_get
    from app.services.page_suggest import extract

    body = await request.json()
    url = (body.get("source_url") or "").strip()
    cid = get_company_id(current_user)
    if not db.query(Product.id).filter(Product.company_id == cid, Product.id == product_id).first():
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    if not url.lower().startswith(("http://", "https://")):
        return JSONResponse({"ok": False, "error": "찾은 곳 링크(http/https)를 먼저 넣어주세요"})
    try:
        r = await asyncio.to_thread(safe_get, url, timeout=15.0, max_bytes=2_000_000)
    except UnsafeURL as e:
        return JSONResponse({"ok": False, "error": f"열 수 없는 주소입니다 ({e})"})
    except httpx.HTTPError:
        return JSONResponse({"ok": False, "error": "페이지에 연결하지 못했습니다 (시간 초과·연결 실패)"})
    if r.status_code in (401, 403, 429):
        return JSONResponse({"ok": False, "error": f"이 사이트가 자동 조회를 막았습니다 (HTTP {r.status_code}) — 직접 채워주세요"})
    if r.status_code >= 400:
        return JSONResponse({"ok": False, "error": f"페이지를 열지 못했습니다 (HTTP {r.status_code})"})
    # 상대 경로 사진은 '최종' 페이지 주소 기준으로 푼다 — safe_get 은 주소 넘김 뒤의 도메인 주소를 응답에 담는다
    # (연결만 IP 로 고정, 코덱스 검토 2026-09-28 #7)
    final_url = str(r.request.url) if r.request is not None else url
    found = extract(r.text, final_url)
    if not any(found.get(k) for k in ("image", "price", "description", "name")):
        return JSONResponse({"ok": False, "error": "페이지에서 사진·가격 정보를 찾지 못했습니다 (화면을 스크립트로 그리는 사이트일 수 있음)"})
    return JSONResponse({"ok": True, "suggestions": found})


@router.patch("/{product_id}/field")
async def product_patch_field(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """자동 저장: 단일 필드 업데이트 (PATCH JSON body: {field, value})"""
    body = await request.json()
    field = body.get("field", "")
    value = body.get("value", "")

    cid = get_company_id(current_user)
    product = db.query(Product).filter(Product.company_id == cid, Product.id == product_id).first()
    if not product:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

    TEXT_FIELDS = {
        "name", "description", "internal_notes", "notes", "unique_selling_point",
        "content_angle", "positioning", "group_buy_guideline", "source_url",
        "product_link", "product_image", "brand", "category", "status",
        "visibility_status", "shipping_type", "carrier", "ship_origin",
        "dispatch_days", "sample_type", "product_type", "key_benefits_raw",
    }
    NUM_FIELDS = {
        "price", "consumer_price", "lowest_price", "supplier_price",
        "groupbuy_price", "shipping_cost", "sample_price",
    }
    PCT_FIELDS = {
        "discount_rate", "seller_commission_rate", "vendor_commission_rate",
        "recommended_commission_rate",
    }

    log_field = "key_benefits" if field == "key_benefits_raw" else field
    before = _log_value(getattr(product, log_field, None)) if hasattr(product, log_field) else None
    try:
        if field == "key_benefits_raw":
            kbs = [b.strip() for b in value.splitlines() if b.strip()]
            product.key_benefits = kbs or None
        elif field in TEXT_FIELDS:
            setattr(product, field, value.strip() or None)
        elif field in NUM_FIELDS:
            num = _checked_number(value, 0, 10_000_000_000)   # 가격·금액: 0 이상 (코덱스 검토 2026-09-28 #3)
            if num is False:
                return JSONResponse({"ok": False, "error": "out of range"})
            setattr(product, field, num)
        elif field in PCT_FIELDS:
            num = _checked_number(value, 0, 100)             # 비율: 0~100%
            if num is False:
                return JSONResponse({"ok": False, "error": "out of range"})
            setattr(product, field, num / 100.0 if num is not None else 0.0)
        else:
            return JSONResponse({"ok": False, "error": "unknown field"})
    except (ValueError, TypeError):
        return JSONResponse({"ok": False, "error": "invalid value"})

    completeness = validate_product_completeness(product)
    product.is_complete = completeness["is_complete"]
    product.missing_fields = completeness["missing_fields"] or None
    _log_change(db, cid, product.id, log_field, before, getattr(product, log_field, None), current_user,
                via=body.get("via") or "detail", source_url=body.get("source_url"))
    db.commit()
    return JSONResponse({"ok": True, "is_complete": product.is_complete})


@router.post("/{product_id}/clone")
def product_clone(product_id: str, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    cid = get_company_id(current_user)
    import uuid as _uuid
    src = db.query(Product).filter(Product.company_id == cid, Product.id == product_id).first()
    if not src:
        return RedirectResponse("/products", status_code=302)
    clone = Product(
        id=str(_uuid.uuid4()),
        company_id=cid,
        name=src.name + " (복제)",
        brand=src.brand, category=src.category,
        price=src.price, source_url=src.source_url,
        description=src.description, internal_notes=src.internal_notes,
        key_benefits=src.key_benefits, unique_selling_point=src.unique_selling_point,
        recommended_commission_rate=src.recommended_commission_rate,
        visibility_status="hidden", content_angle=src.content_angle,
        positioning=src.positioning, set_options=src.set_options,
        categories=src.categories, group_buy_guideline=src.group_buy_guideline,
        status="draft", shipping_type=src.shipping_type,
        shipping_cost=src.shipping_cost, carrier=src.carrier,
        ship_origin=src.ship_origin, dispatch_days=src.dispatch_days,
        sample_type=src.sample_type, sample_price=src.sample_price,
        consumer_price=src.consumer_price, lowest_price=src.lowest_price,
        supplier_price=src.supplier_price, groupbuy_price=src.groupbuy_price,
        discount_rate=src.discount_rate,
        seller_commission_rate=src.seller_commission_rate,
        vendor_commission_rate=src.vendor_commission_rate,
        product_link=src.product_link, product_type=src.product_type or "A",
        product_image=src.product_image,
    )
    db.add(clone)
    db.commit()
    return RedirectResponse(f"/products/{clone.id}/edit?msg=제품이+복제되었습니다", status_code=302)


@router.post("/{product_id}/delete")
def product_delete(product_id: str, db: Session = Depends(get_db),
                   current_user: User = Depends(require_admin)):
    cid = get_company_id(current_user)
    product = db.query(Product).filter(Product.company_id == cid, Product.id == product_id).first()
    if product:
        product.is_archived = True
        db.commit()
    return RedirectResponse("/products?msg=보관처리되었습니다", status_code=302)


@router.post("/remove-bg-batch")
def remove_bg_batch(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """외부 URL 이미지가 있는 모든 제품에 누끼 일괄 적용 (백그라운드)."""
    import logging
    logger = logging.getLogger(__name__)
    cid = get_company_id(current_user)
    targets = db.query(Product.id, Product.product_image).filter(
        Product.company_id == cid,
        Product.is_archived.isnot(True),
        Product.product_image.isnot(None),
        Product.product_image.like("http%"),
        ~Product.product_image.like("%amazonaws.com%"),  # S3 처리완료 제외
    ).all()
    items = [(r.id, r.product_image) for r in targets]

    def _batch(items: list):
        from app.database import SessionLocal
        from app.services.image_service import process_url_with_remove_bg, UPLOAD_DIR_PRODUCTS
        bg_db = SessionLocal()
        try:
            for pid, img_url in items:
                new_url = process_url_with_remove_bg(img_url, UPLOAD_DIR_PRODUCTS)
                if new_url:
                    prod = bg_db.query(Product).filter(Product.id == pid).first()
                    if prod:
                        prod.product_image = new_url
                        bg_db.commit()
        except Exception:
            logger.exception("일괄 누끼 배치 오류")
        finally:
            bg_db.close()

    background_tasks.add_task(_batch, items)
    from urllib.parse import quote
    return RedirectResponse(f"/products?msg={quote(f'{len(items)}개 제품 누끼 작업 시작 (백그라운드 처리 중)')}", status_code=302)
