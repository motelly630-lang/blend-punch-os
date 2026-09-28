from datetime import date, timedelta, timezone, datetime

KST = timezone(timedelta(hours=9))

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.attendance import AttendanceLog
from app.models.page_visit import PageVisitLog
from app.models.user import User
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/attendance")
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def attendance_index(
    request: Request,
    target_date: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role != "admin":
        return RedirectResponse("/", status_code=302)

    if target_date:
        try:
            selected_date = date.fromisoformat(target_date)
        except ValueError:
            selected_date = datetime.now(KST).date()
    else:
        selected_date = datetime.now(KST).date()

    logs = (
        db.query(AttendanceLog, User)
        .join(User, AttendanceLog.user_id == User.id)
        .filter(AttendanceLog.date == selected_date,
                *(() if user.company_id is None else (User.company_id == user.company_id,)))   # 수퍼어드민만 전체
        .order_by(AttendanceLog.first_login_at)
        .all()
    )

    return templates.TemplateResponse("attendance/index.html", {
        "request": request,
        "user": user,
        "active_page": "attendance",
        "logs": logs,
        "selected_date": selected_date,
    })


@router.get("/{user_id}/visits")
def user_visits(
    user_id: str,
    request: Request,
    target_date: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role != "admin":
        return RedirectResponse("/", status_code=302)

    target = db.query(User).filter(User.id == user_id).first()
    if target and user.company_id is not None and target.company_id != user.company_id:
        target = None   # 다른 회사 직원 기록은 볼 수 없음
    if not target:
        return RedirectResponse("/attendance", status_code=302)

    if target_date:
        try:
            selected_date = date.fromisoformat(target_date)
        except ValueError:
            selected_date = datetime.now(KST).date()
    else:
        selected_date = datetime.now(KST).date()

    next_day = selected_date + timedelta(days=1)
    visits = (
        db.query(PageVisitLog)
        .filter(
            PageVisitLog.user_id == user_id,
            PageVisitLog.visited_at >= datetime(selected_date.year, selected_date.month, selected_date.day, 0, 0, 0),
            PageVisitLog.visited_at < datetime(next_day.year, next_day.month, next_day.day, 0, 0, 0),
        )
        .order_by(PageVisitLog.visited_at)
        .all()
    )

    return templates.TemplateResponse("attendance/visits.html", {
        "request": request,
        "user": user,
        "active_page": "attendance",
        "target": target,
        "visits": visits,
        "selected_date": selected_date,
    })
