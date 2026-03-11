from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.auth.service import verify_password, create_access_token

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
