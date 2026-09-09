"""CS 인앱 알림 (요구사항 17).

이벤트 기반 트리거 + 예정일 임박/초과 스캔. 사용자별(user_id) 알림.
이메일/문자/카카오는 미포함(향후 channel 확장). caller 가 commit 한다(scan 은 자체 commit).
"""
from datetime import datetime, timedelta
from app.models.cs import CSNotification, CSTicket
from app.models.user import User

OPEN_STATES = ["received", "internal_review", "partner_pending", "partner_waiting", "processing", "customer_waiting", "hold"]


def notify(db, company_id, user_ids, notif_type, title, body="", cs_id=None):
    """수신자별 알림 생성 (중복 user 제거). commit 은 호출측."""
    seen = set()
    for uid in user_ids or []:
        if not uid or uid in seen:
            continue
        seen.add(uid)
        db.add(CSNotification(
            company_id=company_id, user_id=uid, cs_ticket_id=cs_id,
            notif_type=notif_type, title=title, body=body or None,
        ))


def staff_ids(db, company_id, exclude=None):
    rows = db.query(User.id).filter(
        User.company_id == company_id,
        User.role.in_(["admin", "staff", "manager"]),
        User.is_active == True,
    ).all()
    return [r[0] for r in rows if r[0] != exclude]


def partner_user_ids(db, partner_id, exclude=None):
    if not partner_id:
        return []
    rows = db.query(User.id).filter(
        User.partner_id == partner_id, User.role == "partner", User.is_active == True,
    ).all()
    return [r[0] for r in rows if r[0] != exclude]


def scan_due_notifications(db):
    """처리 예정일 임박(24h 이내)/초과 건에 대해 담당자(없으면 스태프)에게 1회 알림."""
    now = datetime.utcnow()
    soon = now + timedelta(hours=24)
    created = 0
    tickets = db.query(CSTicket).filter(
        CSTicket.is_archived == False,
        CSTicket.due_at.isnot(None),
        CSTicket.status.in_(OPEN_STATES),
    ).all()
    for t in tickets:
        if t.due_at < now:
            ntype, title = "overdue", f"처리 예정일 초과: {t.cs_number}"
        elif t.due_at <= soon:
            ntype, title = "due_soon", f"처리 예정일 임박: {t.cs_number}"
        else:
            continue
        # 티켓+유형별 1회만
        exists = db.query(CSNotification).filter(
            CSNotification.cs_ticket_id == t.id, CSNotification.notif_type == ntype
        ).first()
        if exists:
            continue
        cid = t.company_id or 1
        recips = [t.assigned_user_id] if t.assigned_user_id else staff_ids(db, cid)
        notify(db, cid, recips, ntype, title, cs_id=t.id)
        created += 1
    if created:
        db.commit()
    return created
