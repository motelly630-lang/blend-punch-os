"""캠페인(공구 일정) 공통 규칙 — 화면 라우터와 향후 AI API 가 같은 검증을 쓴다.

상태 의미
  planning     기획중      ┐ 미확정 — 일정(날짜)이 있어도 자동으로 진행·종료되지 않는다
  negotiating  협의중      ┘
  contracted   계약완료    ┐ 확정 — 명시적 실행 경로(campaign_progress)에서만 일정 기준 진행/완료 제안
  active       진행중      ┘
  completed    완료
  cancelled    취소

표시용 '일정 단계'(schedule_phase)는 저장 상태와 별개로 날짜에서만 계산하며 DB 에 쓰지 않는다.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.influencer import Influencer
from app.models.product import Product

KST = ZoneInfo("Asia/Seoul")

CAMPAIGN_STATUSES: list[tuple[str, str]] = [
    ("planning", "기획중"),
    ("negotiating", "협의중"),
    ("contracted", "계약완료"),
    ("active", "진행중"),
    ("completed", "완료"),
    ("cancelled", "취소"),
]
STATUS_CODES = frozenset(code for code, _ in CAMPAIGN_STATUSES)
STATUS_LABELS = dict(CAMPAIGN_STATUSES)

UNCONFIRMED_STATUSES = frozenset({"planning", "negotiating"})
CONFIRMED_OPEN_STATUSES = frozenset({"contracted", "active"})
CLOSED_STATUSES = frozenset({"completed", "cancelled"})


class CampaignValidationError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 검증 오류."""


def kst_today() -> date:
    return datetime.now(KST).date()


def validate_status(status) -> str:
    s = (status or "").strip() if isinstance(status, str) else ""
    if s not in STATUS_CODES:
        raise CampaignValidationError(f"허용되지 않는 캠페인 상태입니다: {status!r}")
    return s


def resolve_product_id(db: Session, company_id: int, product_id) -> str | None:
    """빈 값 → None. 값이 있으면 같은 회사 상품이어야 한다."""
    pid = (product_id or "").strip() if isinstance(product_id, str) else product_id
    if not pid:
        return None
    ok = (db.query(Product.id)
          .filter(Product.id == pid, Product.company_id == company_id).first())
    if not ok:
        raise CampaignValidationError("선택한 상품을 찾을 수 없습니다 (다른 회사 상품이거나 삭제됨)")
    return pid


def resolve_influencer_id(db: Session, company_id: int, influencer_id) -> str | None:
    """업무상 '셀러'는 Influencer 다 (Seller 추적코드 아님). 같은 회사 소속이어야 한다."""
    iid = (influencer_id or "").strip() if isinstance(influencer_id, str) else influencer_id
    if not iid:
        return None
    ok = (db.query(Influencer.id)
          .filter(Influencer.id == iid, Influencer.company_id == company_id).first())
    if not ok:
        raise CampaignValidationError("선택한 인플루언서를 찾을 수 없습니다 (다른 회사 소속이거나 삭제됨)")
    return iid


def validate_dates(start: date | None, end: date | None) -> None:
    if start and end and end < start:
        raise CampaignValidationError("종료일이 시작일보다 빠릅니다")


def schedule_phase(start: date | None, end: date | None, today: date) -> str:
    """날짜만으로 본 일정 단계 (표시 전용): undated | upcoming | ongoing | ended."""
    if not start:
        return "undated"
    if today < start:
        return "upcoming"
    if end and today > end:
        return "ended"
    return "ongoing"


PHASE_LABELS = {"undated": "일정 미정", "upcoming": "시작 전", "ongoing": "일정상 진행 기간", "ended": "일정 종료"}


def schedule_note(status: str, start: date | None, end: date | None, today: date) -> str | None:
    """저장 상태와 일정이 어긋날 때 사람에게 보여줄 안내. DB 는 바꾸지 않는다."""
    phase = schedule_phase(start, end, today)
    if status in UNCONFIRMED_STATUSES:
        if phase == "ongoing":
            return "일정상 진행 기간 · 상태 미확정"
        if phase == "ended":
            return "일정 종료 · 상태 미확정"
        return None
    if status == "contracted" and phase == "ongoing":
        return "시작일 도래 · 진행 처리 필요"
    if status in CONFIRMED_OPEN_STATUSES and phase == "ended":
        return "종료일 지남 · 완료 처리 필요"
    if status == "active" and phase == "upcoming":
        return "시작 전인데 진행중으로 표시됨"
    return None
