from datetime import date, timedelta, timezone, datetime

KST = timezone(timedelta(hours=9))

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.attendance import AttendanceLog
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
        .filter(AttendanceLog.date == selected_date)
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
