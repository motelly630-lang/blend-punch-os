import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Text, DateTime, Date, ForeignKey, Boolean, JSON, UniqueConstraint
from sqlalchemy.orm import relationship
from app.models.base import Base


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    partner_id = Column(String(36), ForeignKey("partners.id"), nullable=True, index=True)  # 협력사(공급사) 출처
    name = Column(String(300), nullable=False)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=True)
    influencer_id = Column(String(36), ForeignKey("influencers.id"), nullable=True)
    status = Column(String(30), default="planning")
    # planning|negotiating|contracted|active|completed|cancelled
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    commission_rate = Column(Float, nullable=True)
    expected_sales = Column(Integer, default=0)
    actual_sales = Column(Integer, default=0)
    actual_revenue = Column(Float, default=0.0)
    notes = Column(Text, nullable=True)

    # Phase 5 additions — commission split
    unit_price = Column(Float, default=0.0)
    seller_commission_rate = Column(Float, default=0.0)      # 셀러 커미션율
    vendor_commission_rate = Column(Float, default=0.0)      # 벤더 마진율
    seller_commission_amount = Column(Float, default=0.0)    # 셀러 지급액 (calculated)
    vendor_commission_amount = Column(Float, default=0.0)    # 벤더 수익액 (calculated)
    is_archived = Column(Boolean, default=False)
    # 직접입력 제품 정보 (DB 연결 없이 캠페인 생성 시)
    product_name_manual = Column(String(300), nullable=True)
    brand_name_manual = Column(String(200), nullable=True)
    category_manual = Column(String(100), nullable=True)
    # 셀러 유형
    seller_type = Column(String(30), nullable=True)  # 사업자/간이사업자/프리랜서
    # 내부/외부 구분
    campaign_type = Column(String(20), default="internal")  # internal|external
    external_url = Column(Text, nullable=True)               # 외부 링크 (external일 때)
    content_urls = Column(JSON, nullable=True)               # 인플루언서가 올린 릴스·게시물 링크 목록 (공구 아카이브, 2026-09-24)

    # 통합 운영 스프레드시트 미러 (OS가 진실, 시트는 읽기전용)
    sheet_code   = Column(String(50), nullable=True, index=True)
    sheet_status = Column(String(30), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = relationship("Product", foreign_keys=[product_id])
    influencer = relationship("Influencer", foreign_keys=[influencer_id])


class ArchiveContent(Base):
    """공개 공구 아카이브에 올릴 영상 한 개 (2026-10-03).

    링크 자체는 Campaign.content_urls 가 원본이고, 이 표는 링크마다 붙는 '공개용 정보'만 담는다.
    - 기본은 비공개. 직원이 공구 상세에서 체크해야 /public/archive 에 나간다.
    - 숫자(조회수·좋아요·댓글)는 대표님 결정으로 직접 입력 — 자동 갱신하지 않는다.
    """
    __tablename__ = "archive_contents"
    __table_args__ = (UniqueConstraint("campaign_id", "url", name="uq_archive_contents_campaign_url"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    campaign_id = Column(String(36), ForeignKey("campaigns.id"), nullable=False, index=True)
    url = Column(String(500), nullable=False)          # content_embed.parse() 로 정리한 주소
    is_public = Column(Boolean, nullable=False, default=False)
    thumbnail = Column(String(500), nullable=True)     # 직원이 올린 썸네일 (게시물이 내려가도 카드는 남게)
    views = Column(Integer, nullable=True)
    likes = Column(Integer, nullable=True)
    comments = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    campaign = relationship("Campaign", foreign_keys=[campaign_id])
