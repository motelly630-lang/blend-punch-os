import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Date, Integer, Float, Boolean, ForeignKey
from app.models.base import Base


class Partner(Base):
    """협력사(공급사) — 블렌드펀치에 제품·공구를 공급하는 파트너.

    ⚠️ company_id(SaaS 테넌트)와 다른 개념. 협력사 제품은 블렌드펀치(company_id=1)
    카탈로그 안에서 돌아가며, 여기서는 '출처'를 나타낸다.

    협력사 담당자에게는 role="partner" + user.partner_id 계정을 발급해
    자기 것만 보이는 포털(/portal)을 제공한다 (보기 전용).
    """

    __tablename__ = "partners"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)

    name = Column(String(200), nullable=False)          # 상호(협력사명)
    business_name = Column(String(200), nullable=True)  # 사업자명(법인/개인사업자명) — 상호와 다를 수 있음
    contact_name = Column(String(100), nullable=True)   # 담당자명
    phone = Column(String(50), nullable=True)           # 연락처
    email = Column(String(200), nullable=True)          # 이메일

    # ── 사업자 정보 ──
    biz_reg_number = Column(String(50), nullable=True)     # 사업자등록번호
    representative_name = Column(String(100), nullable=True)  # 대표자명
    business_type = Column(String(200), nullable=True)     # 업태/종목
    business_address = Column(Text, nullable=True)         # 사업장 주소
    tax_invoice_email = Column(String(200), nullable=True) # 세금계산서 이메일

    # ── 정산 계좌 ──
    bank_name = Column(String(100), nullable=True)
    account_number = Column(String(100), nullable=True)
    account_holder = Column(String(100), nullable=True)

    # ── 계약 ──
    contract_start = Column(Date, nullable=True)
    contract_end = Column(Date, nullable=True)
    commission_rate = Column(Float, nullable=True)         # 수수료율(%)
    manager_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)  # 담당 내부 매니저

    contract_terms = Column(Text, nullable=True)        # 계약/공급 조건 메모
    settlement_cycle = Column(String(100), nullable=True)  # 정산주기 안내 (예: "공구종료 +14일")
    settlement_days = Column(Integer, default=14)       # 공구 종료 후 정산 지급까지 소요일

    notes = Column(Text, nullable=True)                 # 내부 메모
    is_active = Column(Boolean, default=True)

    # 통합 운영 스프레드시트 연동 — 시트 PK(VND-...)와 상태값 한글 원본
    sheet_code   = Column(String(50), nullable=True, index=True)
    sheet_status = Column(String(30), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PartnerContact(Base):
    """협력사 담당자 — 한 협력사에 여러 명 등록 가능.

    각 담당자는 선택적으로 포털 로그인 계정(user_id)을 가질 수 있다.
    계정이 연결되면 해당 담당자가 /portal 에서 협력사 일정을 본다.
    """

    __tablename__ = "partner_contacts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    partner_id = Column(String(36), ForeignKey("partners.id"), nullable=False, index=True)

    name = Column(String(100), nullable=False)          # 담당자명
    title = Column(String(100), nullable=True)          # 직책/역할
    phone = Column(String(50), nullable=True)
    email = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)

    # 포털 로그인 계정 (users.id) — 발급 시 연결
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
