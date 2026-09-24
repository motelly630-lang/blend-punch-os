import uuid
from datetime import datetime
from sqlalchemy import Boolean, Column, Date, Integer, String, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base


class Settlement(Base):
    __tablename__ = "settlements"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    influencer_id = Column(String(36), ForeignKey("influencers.id"), nullable=True)
    campaign_id = Column(String(36), ForeignKey("campaigns.id"), nullable=True)
    period_label = Column(String(50), nullable=True)       # 예: "2024년 3월"
    seller_type = Column(String(20), default="사업자")     # 사업자|간이사업자|프리랜서
    sales_amount = Column(Float, default=0.0)              # 총 매출
    commission_rate = Column(Float, default=0.15)          # 커미션율
    commission_amount = Column(Float, default=0.0)         # 커미션 금액 (매출 × 커미션율)
    vat_amount = Column(Float, default=0.0)                # 부가세 (커미션 × 10%)
    tax_rate = Column(Float, default=0.0)                  # 원천징수율 (프리랜서 0.033)
    tax_amount = Column(Float, default=0.0)                # 원천징수액
    final_payment = Column(Float, default=0.0)             # 최종 지급액
    status = Column(String(20), default="pending")         # pending(작성중)|confirmed(발행·지급대기)|paid(지급완료)
    # 정산서 한 장 개편 (2026-09-24) — 계산은 app/services/settlement_calc.py 하나만
    supply_amount = Column(Float, nullable=True)            # 공급가액 = 정산 대상 ÷ 1.1
    calc_version = Column(String(10), nullable=True)        # NULL = 예전 계산식으로 만든 행 (금액 그대로 보존)
    is_manual = Column(Boolean, default=False)              # 실지급액을 사람이 직접 고침 → 자동 재계산이 덮지 않음
    issued_at = Column(DateTime, nullable=True)             # 발행(확정)한 때
    paid_at = Column(DateTime, nullable=True)               # 지급 완료한 때
    due_date = Column(Date, nullable=True)                  # 지급 예정일
    notes = Column(Text, nullable=True)
    # 정산 생성 시점 스냅샷 (인플루언서 정보 변경 대비)
    bank_name_snapshot = Column(String(100), nullable=True)
    account_number_snapshot = Column(String(100), nullable=True)
    account_holder_snapshot = Column(String(100), nullable=True)
    # 통합 운영 스프레드시트 미러 (OS가 진실, 시트는 읽기전용)
    sheet_code   = Column(String(50), nullable=True, index=True)
    sheet_status = Column(String(30), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    influencer = relationship("Influencer", foreign_keys=[influencer_id])
    campaign = relationship("Campaign", foreign_keys=[campaign_id])
