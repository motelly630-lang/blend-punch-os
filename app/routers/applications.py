from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.group_buy_application import GroupBuyApplication
from app.auth.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/applications")
templates = Jinja2Templates(directory="app/templates")

STATUS_KR = {"new": "신규", "reviewing": "검토중", "approved": "승인", "rejected": "거절"}


@router.get("")
def application_list(request: Request, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user),
                     status: str = ""):
    query = db.query(GroupBuyApplication)
    if status:
        query = query.filter(GroupBuyApplication.status == status)
    apps = query.order_by(GroupBuyApplication.created_at.desc()).all()
    counts = {
        "all":       db.query(GroupBuyApplication).count(),
        "new":       db.query(GroupBuyApplication).filter(GroupBuyApplication.status == "new").count(),
        "reviewing": db.query(GroupBuyApplication).filter(GroupBuyApplication.status == "reviewing").count(),
        "approved":  db.query(GroupBuyApplication).filter(GroupBuyApplication.status == "approved").count(),
        "rejected":  db.query(GroupBuyApplication).filter(GroupBuyApplication.status == "rejected").count(),
    }
    return templates.TemplateResponse("applications/index.html", {
        "request": request, "active_page": "applications",
        "current_user": current_user,
        "apps": apps, "status_filter": status,
        "counts": counts, "STATUS_KR": STATUS_KR,
    })


@router.post("/{app_id}/status")
def update_status(app_id: str, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user),
                  status: str = Form(...),
                  admin_note: str = Form("")):
    app = db.query(GroupBuyApplication).filter(GroupBuyApplication.id == app_id).first()
    if app:
        app.status = status
        app.admin_note = admin_note or None
        db.commit()
    return RedirectResponse("/applications?msg=상태가+업데이트되었습니다", status_code=302)


@router.post("/{app_id}/delete")
def delete_application(app_id: str, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    app = db.query(GroupBuyApplication).filter(GroupBuyApplication.id == app_id).first()
    if app:
        db.delete(app)
        db.commit()
    return RedirectResponse("/applications?msg=삭제되었습니다", status_code=302)
