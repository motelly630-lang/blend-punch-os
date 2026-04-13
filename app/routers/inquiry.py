from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.inquiry import Inquiry
from app.auth.dependencies import require_admin
from app.models.user import User

router = APIRouter(prefix="/inquiries")
templates = Jinja2Templates(directory="app/templates")


# ── API 엔드포인트 (구체적인 경로 먼저) ───────────────────────────────

@router.post("/api/submit")
def inquiry_submit(
    name: str = Form(...),
    contact: str = Form(...),
    category: str = Form(...),
    message: str = Form(...),
    user_id: str = Form(None),
    db: Session = Depends(get_db),
):
    inquiry = Inquiry(
        user_id=user_id or None,
        name=name,
        contact=contact,
        category=category,
        message=message,
    )
    db.add(inquiry)
    db.commit()
    return {"ok": True, "id": inquiry.id}


@router.get("/api/user/{user_id}")
def inquiry_by_user(user_id: str, db: Session = Depends(get_db)):
    inquiries = (
        db.query(Inquiry)
        .filter(Inquiry.user_id == user_id)
        .order_by(Inquiry.created_at.desc())
        .all()
    )
    return {
        "inquiries": [
            {
                "id": inq.id,
                "category": inq.category,
                "message": inq.message,
                "status": inq.status,
                "reply": inq.reply,
                "replied_at": inq.replied_at.isoformat() if inq.replied_at else None,
                "created_at": inq.created_at.isoformat() if inq.created_at else None,
            }
            for inq in inquiries
        ]
    }


# ── 어드민 페이지 (와일드카드 경로는 아래에) ──────────────────────────

@router.get("")
def inquiry_list(
    request: Request,
    status: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    q = db.query(Inquiry).order_by(Inquiry.created_at.desc())
    if status:
        q = q.filter(Inquiry.status == status)
    inquiries = q.all()

    counts = {
        "all": db.query(Inquiry).count(),
        "pending": db.query(Inquiry).filter(Inquiry.status == "pending").count(),
        "read": db.query(Inquiry).filter(Inquiry.status == "read").count(),
        "replied": db.query(Inquiry).filter(Inquiry.status == "replied").count(),
    }

    return templates.TemplateResponse("inquiries/list.html", {
        "request": request,
        "current_user": current_user,
        "active_page": "inquiries",
        "inquiries": inquiries,
        "current_status": status,
        "counts": counts,
    })


@router.get("/{inquiry_id}")
def inquiry_detail(
    inquiry_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    inquiry = db.query(Inquiry).filter(Inquiry.id == inquiry_id).first()
    if not inquiry:
        return RedirectResponse("/inquiries")

    if inquiry.status == "pending":
        inquiry.status = "read"
        db.commit()

    return templates.TemplateResponse("inquiries/detail.html", {
        "request": request,
        "current_user": current_user,
        "active_page": "inquiries",
        "inquiry": inquiry,
    })


@router.post("/{inquiry_id}/reply")
def inquiry_reply(
    inquiry_id: str,
    reply: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    inquiry = db.query(Inquiry).filter(Inquiry.id == inquiry_id).first()
    if inquiry:
        inquiry.reply = reply
        inquiry.replied_at = datetime.now(timezone.utc)
        inquiry.status = "replied"
        db.commit()
    return RedirectResponse(f"/inquiries/{inquiry_id}", status_code=303)
