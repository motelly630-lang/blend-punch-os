"""
PublicArchiveItem DTO — 공개 공구 아카이브(/public/archive) 전용 데이터 구조

공구(Campaign) 행에는 커미션·매출·정산·메모가 같이 들어 있어서 그대로 템플릿에 넘기면 안 된다.
이 구조에 적힌 칸만 밖으로 나간다.

절대 포함 금지:
  Campaign: commission_rate, seller/vendor_commission_*, unit_price, expected/actual_sales,
            actual_revenue, notes, campaign_type, external_url, sheet_*, partner_id, name(내부 공구명)
  Influencer: name(실명), 연락처·계좌·사업자 정보 전부 — 핸들과 프로필 사진만
  Product: PublicProduct 와 같은 기준 (커미션 포함 금지)
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class PublicArchiveItem:
    id: str
    # 영상
    url: str                     # 원본 게시물 주소
    kind: str                    # instagram | youtube
    label: str                   # 인스타 릴스 / 인스타 게시물 / 유튜브
    type_key: str                # reel | post | youtube (필터용)
    embed: str                   # 상세에서 누를 때만 띄우는 플레이어 주소
    thumbnail: Optional[str] = None
    # 숫자 (직접 입력)
    views: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    # 공구
    status: Optional[str] = None          # live | soon | done | None(날짜 없음)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    # 제품
    product_name: str = ""
    brand: str = ""
    category: str = ""
    product_image: Optional[str] = None
    product_public_id: Optional[str] = None   # 공개 카탈로그에 있는 제품일 때만 (상세 링크)
    product_key: str = ""                     # 같은 제품 영상 묶기용
    # 인플루언서 (핸들·프로필 사진만)
    handle: str = ""
    profile_image: Optional[str] = None
