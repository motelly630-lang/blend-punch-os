"""공개 공구 아카이브(/public/archive) — 공개해도 되는 영상만 골라 PublicArchiveItem 으로 바꾼다.

나가는 조건 (전부 만족해야 함)
  - 블랜드펀치(1번 회사) 공구이고, 아카이브 행도 1번 회사
  - 직원이 '아카이브 공개'를 체크함 (기본 비공개)
  - 공구가 보관·취소되지 않음
  - 링크가 아직 그 공구의 콘텐츠 목록(content_urls)에 있음
연결된 제품·인플루언서도 1번 회사 것만 쓴다 (예전 자료의 잘못된 연결 대비).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session, joinedload

from app.models.campaign import ArchiveContent, Campaign
from app.models.product import Product
from app.schemas.public_archive import PublicArchiveItem
from app.services import content_embed

# /public 과 같은 회사 (app.routers.public.PUBLIC_COMPANY_ID — 라우터를 여기서 불러오면 순환 import)
PUBLIC_COMPANY_ID = 1
MAX_ITEMS = 600            # 한 번에 읽는 상한 — 넘으면 DB 단계 페이지 나누기로 바꿀 것

TABS = [("all", "전체"), ("live", "진행 중"), ("soon", "예정"), ("done", "지난 공구")]
TYPES = [("", "모든 유형"), ("reel", "릴스"), ("post", "게시물"), ("youtube", "유튜브")]
SORTS = [("new", "최신순"), ("views", "조회수순"), ("likes", "좋아요순")]


def status_of(start: date | None, end: date | None, today: date) -> str | None:
    """공구 상태 — 사내 아카이브(/campaigns/gallery)와 같은 날짜 기준."""
    if end and end < today:
        return "done"
    if not start:
        return None
    return "soon" if start > today else "live"


def _safe_url(media: dict) -> str:
    """밖으로 내보낼 원본 주소. 유튜브는 parse() 가 입력 그대로를 돌려주므로 영상 번호로 다시 만든다
    (예: 'javascript:...youtube.com/shorts/xxx' 같은 입력이 링크로 나가지 않게)."""
    if media["kind"] == "youtube":
        return f"https://www.youtube.com/watch?v={media['code']}"
    return media["url"]          # 인스타는 parse() 가 이미 https://www.instagram.com/... 로 정리


def _type_key(media: dict) -> str:
    if media["kind"] == "youtube":
        return "youtube"
    return "reel" if "/reel/" in media["url"] else "post"


def _public_product_ids(db: Session, ids: set[str]) -> set[str]:
    if not ids:
        return set()
    from app.routers.public import _public_filter   # 공개 카탈로그와 같은 조건을 그대로 쓴다
    return {pid for (pid,) in _public_filter(db.query(Product.id)).filter(Product.id.in_(ids)).all()}


def to_public(row: ArchiveContent, today: date, public_ids: set[str]) -> PublicArchiveItem | None:
    camp = row.campaign
    media = content_embed.parse(row.url)
    if not camp or not media:
        return None
    links = {(content_embed.parse(u) or {}).get("url") for u in (camp.content_urls or [])}
    if media["url"] not in links:                 # 공구 상세에서 뺀 링크
        return None
    product = camp.product if camp.product and camp.product.company_id == PUBLIC_COMPANY_ID else None
    inf = camp.influencer if camp.influencer and camp.influencer.company_id == PUBLIC_COMPANY_ID else None
    name = (product.name if product else camp.product_name_manual) or ""
    brand = (product.brand if product else camp.brand_name_manual) or ""
    category = (product.category if product and product.category else camp.category_manual) or ""
    listed = bool(product and product.id in public_ids)
    return PublicArchiveItem(
        id=row.id,
        url=_safe_url(media), kind=media["kind"], label=media["label"], type_key=_type_key(media), embed=media["embed"],
        thumbnail=row.thumbnail or None,
        views=row.views, likes=row.likes, comments=row.comments,
        status=status_of(camp.start_date, camp.end_date, today),
        start_date=camp.start_date, end_date=camp.end_date,
        product_name=name, brand=brand, category=category,
        product_image=product.product_image if listed else None,
        product_public_id=product.id if listed else None,
        product_key=f"p:{product.id}" if product else (f"m:{brand}|{name}" if name else f"c:{camp.id}"),
        handle=((inf.handle or "").lstrip("@").strip() if inf else ""),
        profile_image=inf.profile_image if inf else None,
    )


def load_items(db: Session, today: date) -> list[PublicArchiveItem]:
    rows = (
        db.query(ArchiveContent)
        .join(Campaign, Campaign.id == ArchiveContent.campaign_id)
        .options(joinedload(ArchiveContent.campaign).joinedload(Campaign.product),
                 joinedload(ArchiveContent.campaign).joinedload(Campaign.influencer))
        .filter(
            ArchiveContent.company_id == PUBLIC_COMPANY_ID,
            ArchiveContent.is_public.is_(True),
            Campaign.company_id == PUBLIC_COMPANY_ID,
            Campaign.is_archived.isnot(True),
            (Campaign.status != "cancelled") | (Campaign.status.is_(None)),
        )
        .order_by(Campaign.start_date.desc().nullslast(), ArchiveContent.created_at.desc())
        .limit(MAX_ITEMS)
        .all()
    )
    public_ids = _public_product_ids(db, {r.campaign.product_id for r in rows if r.campaign.product_id})
    return [it for it in (to_public(r, today, public_ids) for r in rows) if it]


_ORDER = {"live": 0, "soon": 1, "done": 2, None: 3}


def select(items: list[PublicArchiveItem], tab: str, q: str, cat: str, typ: str, sort: str) -> list[PublicArchiveItem]:
    """목록 화면의 탭·검색·필터·정렬 (검색은 제품명·브랜드·인플루언서 핸들만 — 실명은 대상 아님)."""
    needle = (q or "").strip().casefold()
    out = [
        it for it in items
        if (tab == "all" or it.status == tab)
        and (not cat or it.category == cat)
        and (not typ or it.type_key == typ)
        and (not needle or needle in f"{it.product_name} {it.brand} {it.handle}".casefold())
    ]
    if sort == "views":
        out.sort(key=lambda it: -(it.views or 0))
    elif sort == "likes":
        out.sort(key=lambda it: -(it.likes or 0))
    else:   # 진행 중 → 예정 → 지난 공구, 같은 상태 안에서는 시작일 최근 순 (load_items 순서 유지)
        out.sort(key=lambda it: _ORDER.get(it.status, 3))
    return out


def tab_counts(items: list[PublicArchiveItem]) -> dict[str, int]:
    c = {"all": len(items), "live": 0, "soon": 0, "done": 0}
    for it in items:
        if it.status in c:
            c[it.status] += 1
    return c


def categories(items: list[PublicArchiveItem]) -> list[str]:
    return sorted({it.category for it in items if it.category})
