"""CS(고객서비스) 통합 관리 모델.

블렌드펀치 내부 직원과 협업사가 함께 사용하는 수기 기반 CS 관리.
현재 shop 주문과 연동하지 않으므로 주문·고객 정보는 전부 수기 문자열로 저장한다.
다만 향후 shop/외부 쇼핑몰 연동을 위해 확장 필드(integration_status, synced_at,
external_* )를 미리 둔다. (지금은 수기 입력값이거나 비워둔다.)

멀티테넌트: 기존 관례대로 company_id(Integer FK→companies)로 격리하고,
라우터에서 get_company_id(user) 로 수동 필터링한다.
협업사 격리: cs_tickets.partner_id 기준으로 서버단에서 강제한다.
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Integer, Boolean, Float, ForeignKey, JSON
from app.models.base import Base


class CSTicket(Base):
    """CS 기본정보 (요구사항 5·20)."""

    __tablename__ = "cs_tickets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)

    cs_number = Column(String(30), nullable=False, index=True)   # CS-YYYYMMDD-#### (회사별 순번)

    # ── 접수 기본 ──
    received_at = Column(DateTime, default=datetime.utcnow)       # 접수일시
    channel = Column(String(30), nullable=True)                  # 접수경로 (kakao/dm/phone/partner/…)
    is_urgent = Column(Boolean, default=False)                   # 긴급 여부
    status = Column(String(30), default="received", index=True)  # 시스템 고정값 (cs.constants)
    cs_type_id = Column(String(36), ForeignKey("cs_types.id"), nullable=True, index=True)
    assigned_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)  # 내부 담당자

    # ── 상품정보 ──
    # 규칙: product_id(기존 OS 상품) 와 external_product_name(미등록 직접입력) 중 정확히 하나.
    #  - 상품 선택 시: product_id 세팅, partner_id 는 product.partner_id 스냅샷
    #  - 미등록 입력 시: external_product_name 세팅, partner_id 수동 선택(선택)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=True, index=True)
    external_product_name = Column(String(300), nullable=True)
    product_option = Column(String(200), nullable=True)
    quantity = Column(Integer, nullable=True)
    partner_id = Column(String(36), ForeignKey("partners.id"), nullable=True, index=True)      # 협업사(격리 기준)
    influencer_id = Column(String(36), ForeignKey("influencers.id"), nullable=True, index=True)
    campaign_name = Column(String(200), nullable=True)           # 캠페인/공동구매명 (자유 입력)

    # ── 주문·고객 정보 (전부 수기 문자열, shop FK 아님) ──
    external_order_number = Column(String(100), nullable=True, index=True)  # 외부 주문번호 (일반 문자열)
    order_source = Column(String(50), nullable=True)             # 주문 출처
    sales_channel = Column(String(50), nullable=True)            # 판매채널
    customer_name = Column(String(100), nullable=True)
    customer_phone = Column(String(50), nullable=True, index=True)
    customer_address = Column(Text, nullable=True)               # 주소/배송메모
    customer_memo = Column(Text, nullable=True)
    purchased_at = Column(DateTime, nullable=True)               # 구매일
    shipped_at = Column(DateTime, nullable=True)                 # 출고일
    delivered_at = Column(DateTime, nullable=True)               # 배송완료일
    courier = Column(String(50), nullable=True)                  # 택배사
    tracking_number = Column(String(100), nullable=True, index=True)  # 송장번호
    payment_amount = Column(Float, nullable=True)                # 결제금액

    # ── CS 내용 ──
    inquiry_content = Column(Text, nullable=True)                # 고객 문의내용
    customer_request = Column(Text, nullable=True)               # 고객 요청사항
    internal_memo = Column(Text, nullable=True)                  # 최초 내부 메모 (이후 메모는 cs_activities)
    partner_note = Column(Text, nullable=True)                   # 협업사 공개용 전달내용
    due_at = Column(DateTime, nullable=True)                     # 처리 예정일
    completed_at = Column(DateTime, nullable=True)               # 처리완료 일시

    # ── 처리방법·결과 ──
    resolution_type = Column(String(40), nullable=True)          # 시스템 고정값 (cs.constants)
    refund_amount = Column(Float, nullable=True)                 # 환불금액 (통계용 first-class)
    resolution_detail = Column(JSON, nullable=True)              # 처리방법별 세부(재발송/회수/환불일 등)

    # ── 협업사 노출 제어 ──
    submitted_by_partner = Column(Boolean, default=False, index=True)  # 협업사가 포털에서 직접 접수한 건
    is_forwarded_to_partner = Column(Boolean, default=False)     # 협업사 전달 여부(전달된 건만 협업사 노출)
    forwarded_at = Column(DateTime, nullable=True)
    full_address_visible_to_partner = Column(Boolean, default=False)  # 이 건에 한해 전체주소 공개

    # ── 향후 shop 연동 확장 (지금은 수기/공백) — 요구사항 6 ──
    integration_status = Column(String(20), default="manual")   # manual | linked | synced
    synced_at = Column(DateTime, nullable=True)
    external_order_id = Column(String(100), nullable=True)
    external_customer_id = Column(String(100), nullable=True)
    external_product_id = Column(String(100), nullable=True)

    # ── 감사/소프트삭제 ──
    is_archived = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)


class CSActivity(Base):
    """처리 타임라인 + 댓글 통합 로그 (요구사항 11).

    시스템 이벤트(상태변경·담당지정·전달·첨부·처리방법변경 등)와
    사람 댓글(내부메모·협업사공개댓글·협업사답변·고객안내)을 하나의 시간순 로그로 둔다.
    협업사 노출은 visibility 로 통제한다 (internal 은 절대 미노출).
    """

    __tablename__ = "cs_activities"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    cs_ticket_id = Column(String(36), ForeignKey("cs_tickets.id"), nullable=False, index=True)

    activity_type = Column(String(40), nullable=False)   # cs.constants 의 ACT_*
    visibility = Column(String(20), default="internal")  # internal | partner | all
    body = Column(Text, nullable=True)                   # 댓글 본문
    from_value = Column(String(120), nullable=True)      # 변경 전 (상태/담당 등)
    to_value = Column(String(120), nullable=True)        # 변경 후

    actor_id = Column(String(36), ForeignKey("users.id"), nullable=True)  # NULL = 시스템/자동
    actor_name = Column(String(100), nullable=True)      # 표시용 스냅샷 (계정 삭제 대비)
    actor_role = Column(String(20), nullable=True)       # staff/admin/partner (표시용)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class CSAttachment(Base):
    """CS 첨부파일 (요구사항 10).

    보안상 /static 공개 경로가 아니라 비공개 저장소에 저장하고(stored_path),
    인증 라우트를 통해서만 스트리밍한다. is_public=False 는 협업사 미노출.
    """

    __tablename__ = "cs_attachments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    cs_ticket_id = Column(String(36), ForeignKey("cs_tickets.id"), nullable=False, index=True)

    stored_path = Column(String(500), nullable=False)    # 비공개 저장 경로 (static 밖)
    file_name = Column(String(300), nullable=True)       # 원본 파일명
    file_type = Column(String(20), nullable=True)        # image | video | file
    content_type = Column(String(100), nullable=True)    # MIME
    size = Column(Integer, nullable=True)                # bytes
    is_public = Column(Boolean, default=False)           # 협업사 공개 여부

    uploaded_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    uploaded_by_name = Column(String(100), nullable=True)
    is_deleted = Column(Boolean, default=False)          # 소프트 삭제

    created_at = Column(DateTime, default=datetime.utcnow)


class CSType(Base):
    """CS 유형 (요구사항 7) — 관리자 편집형 테이블. 삭제보다 비활성 우선."""

    __tablename__ = "cs_types"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    name = Column(String(50), nullable=False)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CSGuide(Base):
    """상품별 CS 처리 가이드 (요구사항 12). 내부용/협업사 공개용 구분."""

    __tablename__ = "cs_guides"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=True, index=True)

    title = Column(String(200), nullable=False)          # 가이드 제목 (예: 진공풀림)
    content_internal = Column(Text, nullable=True)        # 내부용 처리기준
    content_partner = Column(Text, nullable=True)         # 협업사 공개용
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CSTemplate(Base):
    """답변 템플릿 (요구사항 13). 상품/유형에 맞춰 추천, 클릭 시 입력창에 삽입(자동전송 없음)."""

    __tablename__ = "cs_templates"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)

    name = Column(String(200), nullable=False)            # 템플릿명
    product_id = Column(String(36), ForeignKey("products.id"), nullable=True, index=True)  # 적용 상품
    cs_type_id = Column(String(36), ForeignKey("cs_types.id"), nullable=True, index=True)  # 적용 CS 유형
    customer_message = Column(Text, nullable=True)        # 고객 안내문
    internal_guide = Column(Text, nullable=True)          # 내부 처리 가이드
    is_partner_visible = Column(Boolean, default=False)   # 협업사 공개 여부
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CSNotification(Base):
    """CS 인앱 알림 (요구사항 17). 사용자별. 향후 이메일/문자/카카오 확장을 위해 channel 보유."""

    __tablename__ = "cs_notifications"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)   # 수신자
    cs_ticket_id = Column(String(36), ForeignKey("cs_tickets.id"), nullable=True, index=True)

    notif_type = Column(String(40), nullable=True)        # new_cs/assigned/forwarded/replied/status/due_soon/overdue/urgent
    title = Column(String(200), nullable=True)
    body = Column(Text, nullable=True)
    channel = Column(String(20), default="inapp")         # 향후 email/sms/kakao 확장
    is_read = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    read_at = Column(DateTime, nullable=True)


class CSDownloadLog(Base):
    """엑셀 다운로드 이력 (요구사항 19) — 개인정보 포함 내보내기 감사용."""

    __tablename__ = "cs_download_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    username = Column(String(100), nullable=True)          # 표시용 스냅샷
    filter_summary = Column(Text, nullable=True)           # 적용된 필터 요약
    row_count = Column(Integer, default=0)                 # 내보낸 행 수
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
