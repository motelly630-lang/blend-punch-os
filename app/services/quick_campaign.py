"""공구 한 번에 등록 — 인스타 주소 · 제품 · 기간만으로 인플루언서 · 제품 · 브랜드 · 캠페인을 한 번에 (대표님 2026-09-24).

- 인플루언서: 같은 아이디가 있으면 그 사람을 쓴다(중복 방지). 없으면 만들고 Meta 로 사진·팔로워를 바로 채운다
  (한도·토큰 문제면 새벽 자동 보강이 이어서 채운다).
- 제품: 고른 제품 또는 같은 이름(회사 안)을 쓴다. 없으면 **작성 필요** 상태로 만든다 (제품 목록 '미완성' 필터에 뜬다).
- 브랜드: 없으면 이름만으로 만든다 (브랜드 목록 '정보 입력 필요'에 뜬다).
- 캠페인: 기간으로 상태를 정한다 — 시작 전 planning · 진행 중 active · 끝남 completed.
모든 조회·생성은 company_id 로 묶는다 (RG-002). 기존 표 구조는 바꾸지 않는다 (RG-007).
"""
from __future__ import annotations

import re
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.brand import Brand
from app.models.campaign import Campaign
from app.models.influencer import Influencer
from app.models.product import Product
from app.services.influencer_enrich import RESERVED_HANDLES, clean_handle

_PROFILE = re.compile(r"instagram\.com/([A-Za-z0-9._]{1,30})")
UNCATEGORIZED = "미분류"
BRAND_UNKNOWN = "브랜드 미입력"          # products.brand 는 NOT NULL — 모르면 이 값 + 작성 필요


def extract_handle(raw: str) -> str:
    """인스타 프로필 주소 또는 '@아이디' → 아이디. 게시물·릴스 주소면 ''."""
    s = (raw or "").strip()
    m = _PROFILE.search(s)
    h = clean_handle(m.group(1) if m else s).lower()
    if not re.fullmatch(r"[a-z0-9._]{1,30}", h) or h in RESERVED_HANDLES:
        return ""
    return h


def find_or_create_influencer(db: Session, cid: int, raw: str, name: str = "", fetch: bool = True):
    """→ (influencer | None, created: bool, note: str)"""
    handle = extract_handle(raw)
    if not handle:
        return None, False, "인스타 프로필 주소(instagram.com/아이디)나 아이디를 넣어 주세요 — 게시물·릴스 주소는 아니에요"
    for inf in (db.query(Influencer)
                  .filter(Influencer.company_id == cid, Influencer.is_archived.isnot(True),
                          func.lower(Influencer.handle).like(f"%{handle}%")).all()):
        if clean_handle(inf.handle).lower() == handle:
            return inf, False, ""
    inf = Influencer(company_id=cid, platform="instagram", handle=handle, name=(name or "").strip() or handle,
                     profile_url=f"https://www.instagram.com/{handle}/", status="active")
    db.add(inf)
    note = ""
    if fetch:
        from app.services import meta_instagram as mi
        if mi.available():
            try:
                prof = mi.fetch_profile(handle)
                inf.followers = prof["followers"]
                img = mi.save_profile_image(prof["profile_picture_url"]) if prof["profile_picture_url"] else ""
                if img:
                    inf.profile_image = img
                inf.enriched_at = datetime.utcnow()
                note = f"팔로워 {prof['followers']:,}명"
            except mi.MetaError as e:
                if e.kind == "notfound":                      # 개인 계정 등 → '자동 조회 안 됨' 필터로
                    inf.enriched_at, inf.enrich_error = datetime.utcnow(), str(e)[:190]
                note = str(e)
    return inf, True, note


def ensure_brand(db: Session, cid: int, name: str):
    """→ (brand | None, created). Brand.name 은 전역 unique 라 이름으로만 찾는다."""
    n = (name or "").strip()
    if not n or n == BRAND_UNKNOWN:
        return None, False
    b = db.query(Brand).filter(Brand.name == n).first()
    if b:
        return b, False
    b = Brand(company_id=cid, name=n)
    db.add(b)
    return b, True


def find_or_create_product(db: Session, cid: int, product_id: str = "", name: str = "", brand: str = "",
                           groupbuy_price: float = 0.0, rate: float | None = None):
    """→ (product | None, created: bool)"""
    from app.services.product_service import validate_product_completeness
    if product_id:
        p = db.query(Product).filter(Product.company_id == cid, Product.id == product_id).first()
        if p:
            return p, False
    n = (name or "").strip()
    if not n:
        return None, False
    q = db.query(Product).filter(Product.company_id == cid, func.lower(Product.name) == n.lower(),
                                 Product.is_archived.isnot(True))
    if brand.strip():
        same = q.filter(func.lower(Product.brand) == brand.strip().lower()).first()
        if same:
            return same, False
    p = q.first()
    if p:
        return p, False
    p = Product(company_id=cid, name=n, brand=brand.strip() or BRAND_UNKNOWN, category=UNCATEGORIZED,
                groupbuy_price=groupbuy_price or 0.0, seller_commission_rate=rate or 0.0,
                notes="공구 한 번에 등록으로 만든 제품 — 정보를 채워 주세요")
    comp = validate_product_completeness(p)
    missing = list(comp["missing_fields"] or [])
    if "카테고리" not in missing:
        missing.insert(0, "카테고리")                      # '미분류'는 채운 게 아니다
    if p.brand == BRAND_UNKNOWN and "브랜드" not in missing:
        missing.insert(0, "브랜드")
    p.is_complete, p.missing_fields = False, missing
    db.add(p)
    return p, True


def status_for(start: date | None, end: date | None, today: date) -> str:
    if start and start > today:
        return "planning"
    if end and end < today:
        return "completed"
    return "active" if start else "planning"


def create(db: Session, cid: int, today: date, *, insta: str, influencer_name: str = "", product_id: str = "",
           product_name: str = "", brand_name: str = "", groupbuy_price: float = 0.0, rate_pct: float = 0.0,
           start: date | None = None, end: date | None = None, reel_url: str = "", fetch: bool = True) -> dict:
    """한 번에 만들고 커밋한다. 실패하면 ValueError (아무것도 만들지 않음)."""
    from app.services import content_embed
    if not (0 <= (rate_pct or 0) <= 100):
        raise ValueError("수수료율은 0~100% 사이여야 해요")
    if start and end and end < start:
        raise ValueError("끝나는 날이 시작하는 날보다 빨라요")
    rate = (rate_pct or 0) / 100 or None
    # 싼 검사부터 — 틀린 입력으로 Meta 를 부르거나 사진을 받지 않게
    media = content_embed.parse(reel_url) if reel_url else None
    if reel_url and not media:
        raise ValueError("릴스 주소는 인스타 릴스·게시물 또는 유튜브 링크만 돼요")
    if not (product_id or (product_name or "").strip()):
        raise ValueError("제품을 고르거나 제품 이름을 적어 주세요")
    if not extract_handle(insta):
        raise ValueError("인스타 프로필 주소(instagram.com/아이디)나 아이디를 넣어 주세요 — 게시물·릴스 주소는 아니에요")
    inf, inf_new, inf_note = find_or_create_influencer(db, cid, insta, influencer_name, fetch=fetch)
    if not inf:
        raise ValueError(inf_note)
    prod, prod_new = find_or_create_product(db, cid, product_id, product_name, brand_name, groupbuy_price, rate)
    if not prod:
        db.rollback()
        raise ValueError("제품을 고르거나 제품 이름을 적어 주세요")
    brand, brand_new = ensure_brand(db, cid, prod.brand or brand_name)
    camp = Campaign(company_id=cid, name=f"{prod.name} × {inf.name}"[:300], product_id=prod.id if prod.id else None,
                    influencer_id=inf.id, start_date=start, end_date=end, status=status_for(start, end, today),
                    seller_commission_rate=rate or prod.seller_commission_rate or 0.0,
                    unit_price=groupbuy_price or prod.groupbuy_price or 0.0,
                    content_urls=[media["url"]] if media else None)
    db.flush()                                             # 새 인플루언서·제품 id 확정
    camp.product_id, camp.influencer_id = prod.id, inf.id
    db.add(camp)
    db.commit()
    return {"campaign": camp, "influencer": inf, "influencer_new": inf_new, "influencer_note": inf_note,
            "product": prod, "product_new": prod_new, "brand": brand, "brand_new": brand_new}
