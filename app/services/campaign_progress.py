"""캠페인 진행 상태 정리 — GET /campaigns 에서 분리한 '명시적 실행 경로'.

이전 동작 (제거됨): 캠페인 목록을 열 때마다 날짜만 보고 모든 캠페인 상태를 덮어쓰고
(협의중·기획중도 진행중/완료로), 지난달 캠페인을 보관하고, 정산을 자동 생성했다.

현재 규칙
  실행 주체   관리자가 /campaigns/progress-review 화면에서 미리보기 후 선택 항목만 적용.
              스케줄러에 등록하지 않는다 (초안이 무인으로 진행되지 않게).
  상태 전환   확정 상태만 대상:
                contracted → active     : 시작일 ≤ 오늘 ≤ 종료일
                contracted/active → completed : 종료일 < 오늘
              planning·negotiating(미확정)은 날짜와 무관하게 절대 바꾸지 않는다 (안내만 표시).
  보관        completed·cancelled 이고 종료월이 이번 달 이전인 캠페인만.
  정산        기본값은 생성하지 않는다. 적용 시 create_settlements=True 를 명시한 경우에만,
              완료로 전환된 캠페인 중 **정산이 하나도 없는** 캠페인에 pending 정산을 만든다.
              기존 정산(금액·confirmed/paid)은 읽지도 고치지도 않는다.
              → 날짜 기준 완료 시 정산을 자동 생성할지는 업무 결정 사항 (docs 참조).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.models.campaign import Campaign
from app.models.settlement import Settlement
from app.services.campaign_service import (
    CLOSED_STATUSES,
    CONFIRMED_OPEN_STATUSES,
    UNCONFIRMED_STATUSES,
    schedule_note,
    schedule_phase,
)


@dataclass
class ProgressProposal:
    status_changes: list[dict] = field(default_factory=list)   # {id, name, from, to, reason}
    archives: list[dict] = field(default_factory=list)          # {id, name, status, end_date}
    needs_review: list[dict] = field(default_factory=list)      # 미확정인데 일정이 지난 것 등 (변경 없음)
    completed_without_settlement: list[dict] = field(default_factory=list)  # 참고용 (변경 없음)


def _proposed_status(c: Campaign, today: date) -> str | None:
    if c.status not in CONFIRMED_OPEN_STATUSES:
        return None
    phase = schedule_phase(c.start_date, c.end_date, today)
    if phase == "ended":
        return "completed"
    if c.status == "contracted" and phase == "ongoing":
        return "active"
    return None


def _should_archive(c: Campaign, today: date) -> bool:
    return (
        not c.is_archived
        and c.status in CLOSED_STATUSES
        and c.end_date is not None
        and c.end_date < today.replace(day=1)
    )


def build_proposal(db: Session, company_id: int, today: date) -> ProgressProposal:
    """읽기 전용. 무엇을 바꿀지 계산만 한다."""
    p = ProgressProposal()
    campaigns = (db.query(Campaign)
                 .filter(Campaign.company_id == company_id, Campaign.is_archived == False)  # noqa: E712
                 .order_by(Campaign.start_date.asc())
                 .all())
    settled = {r[0] for r in db.query(Settlement.campaign_id)
               .filter(Settlement.company_id == company_id, Settlement.campaign_id.isnot(None)).all()}
    for c in campaigns:
        to = _proposed_status(c, today)
        if to:
            p.status_changes.append({"id": c.id, "name": c.name, "from": c.status, "to": to,
                                     "start_date": c.start_date, "end_date": c.end_date})
        elif _should_archive(c, today):
            p.archives.append({"id": c.id, "name": c.name, "status": c.status, "end_date": c.end_date})
        if c.status in UNCONFIRMED_STATUSES:
            note = schedule_note(c.status, c.start_date, c.end_date, today)
            if note:
                p.needs_review.append({"id": c.id, "name": c.name, "status": c.status, "note": note,
                                       "start_date": c.start_date, "end_date": c.end_date})
        if c.status == "completed" and c.id not in settled:
            p.completed_without_settlement.append({"id": c.id, "name": c.name})
    return p


def apply_selected(db: Session, company_id: int, today: date,
                   status_ids: set[str], archive_ids: set[str],
                   create_settlements: bool, settle_fn) -> dict:
    """선택 항목만 적용. 제안은 서버에서 다시 계산해 **지금도 유효한 항목만** 반영한다.

    settle_fn(db, campaign): 정산 생성 함수 (campaigns._auto_settle). 정산이 없는 캠페인에만 호출.
    """
    proposal = build_proposal(db, company_id, today)
    allowed_status = {x["id"]: x["to"] for x in proposal.status_changes}
    allowed_archive = {x["id"] for x in proposal.archives}

    changed, archived, settlements_created, skipped = [], [], [], []
    for cid_ in status_ids:
        to = allowed_status.get(cid_)
        if not to:
            skipped.append(cid_)
            continue
        c = db.query(Campaign).filter(Campaign.company_id == company_id, Campaign.id == cid_).first()
        if not c:
            skipped.append(cid_)
            continue
        c.status = to
        changed.append(cid_)
        if to == "completed" and create_settlements:
            exists = db.query(Settlement.id).filter(
                Settlement.company_id == company_id, Settlement.campaign_id == c.id).first()
            if not exists:
                before = db.query(Settlement.id).filter(Settlement.campaign_id == c.id).count()
                settle_fn(db, c)
                db.flush()
                if db.query(Settlement.id).filter(Settlement.campaign_id == c.id).count() > before:
                    settlements_created.append(cid_)
    for cid_ in archive_ids:
        if cid_ not in allowed_archive:
            skipped.append(cid_)
            continue
        c = db.query(Campaign).filter(Campaign.company_id == company_id, Campaign.id == cid_).first()
        if c:
            c.is_archived = True
            archived.append(cid_)
    db.commit()
    return {"changed": changed, "archived": archived,
            "settlements_created": settlements_created, "skipped": skipped}
