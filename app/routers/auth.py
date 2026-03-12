from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.auth.service import verify_password, create_access_token, hash_password
from app.auth.dependencies import get_current_user, require_admin

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

_COOKIE_KEY = "access_token"
_COOKIE_MAX_AGE = 60 * 60 * 8  # 8 hours


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.cookies.get(_COOKIE_KEY):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("auth/login.html", {"request": request})


@router.post("/login")
def login(
    request: Request,
    db: Session = Depends(get_db),
    username: str = Form(...),
    password: str = Form(...),
):
    user = db.query(User).filter(User.username == username).first()
    if not user or not user.is_active or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "아이디 또는 비밀번호가 올바르지 않습니다."},
            status_code=401,
        )
    token = create_access_token(username=user.username, role=user.role)
    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        key=_COOKIE_KEY,
        value=token,
        httponly=True,
        max_age=_COOKIE_MAX_AGE,
        samesite="lax",
    )
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(_COOKIE_KEY)
    return response


# ── User Management (admin only) ─────────────────────────────────────────────

ROLES = [("admin", "관리자"), ("staff", "스태프"), ("partner", "파트너")]


@router.get("/users")
def user_list(request: Request, db: Session = Depends(get_db),
              current_user: User = Depends(require_admin)):
    users = db.query(User).order_by(User.created_at).all()
    return templates.TemplateResponse("auth/users.html", {
        "request": request, "active_page": "users",
        "current_user": current_user, "users": users, "roles": ROLES,
    })


@router.post("/users/new")
def user_create(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("partner"),
):
    if db.query(User).filter(User.username == username).first():
        return RedirectResponse("/users?err=이미+존재하는+아이디입니다", status_code=302)
    user = User(
        username=username,
        hashed_password=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    return RedirectResponse("/users?msg=사용자가+등록되었습니다", status_code=302)


@router.post("/users/{user_id}/edit")
def user_edit(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    role: str = Form(...),
    is_active: str = Form("on"),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse("/users?err=사용자를+찾을+수+없습니다", status_code=302)
    if user.id == current_user.id and role != "admin":
        return RedirectResponse("/users?err=자신의+관리자+권한은+변경할+수+없습니다", status_code=302)
    user.role = role
    user.is_active = (is_active == "on")
    db.commit()
    return RedirectResponse("/users?msg=수정되었습니다", status_code=302)


@router.post("/users/{user_id}/reset-password")
def user_reset_password(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    new_password: str = Form(...),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse("/users?err=사용자를+찾을+수+없습니다", status_code=302)
    user.hashed_password = hash_password(new_password)
    db.commit()
    return RedirectResponse("/users?msg=비밀번호가+초기화되었습니다", status_code=302)


@router.post("/users/{user_id}/delete")
def user_delete(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if user_id == current_user.id:
        return RedirectResponse("/users?err=자신의+계정은+삭제할+수+없습니다", status_code=302)
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        db.delete(user)
        db.commit()
    return RedirectResponse("/users?msg=삭제되었습니다", status_code=302)
