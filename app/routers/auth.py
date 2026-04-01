import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.feature_flag import Company
from app.auth.service import verify_password, create_access_token, hash_password
from app.auth.dependencies import get_current_user, require_super_admin

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

_COOKIE_KEY = "access_token"
_COOKIE_MAX_AGE = 60 * 60 * 8  # 8 hours


# ── 로그인 ────────────────────────────────────────────────────────────────────

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
    # username 또는 email 둘 다 허용
    user = (
        db.query(User).filter(User.username == username).first()
        or db.query(User).filter(User.email == username).first()
    )
    if not user or not user.is_active or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "아이디(이메일) 또는 비밀번호가 올바르지 않습니다."},
            status_code=401,
        )
    # 이메일 미인증 계정 차단 (email 필드가 있는 경우만)
    if user.email and not user.email_verified:
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "이메일 인증이 필요합니다. 가입 시 발송된 인증 메일을 확인해주세요."},
            status_code=401,
        )
    token = create_access_token(username=user.username, role=user.role)
    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        key=_COOKIE_KEY, value=token,
        httponly=True, max_age=_COOKIE_MAX_AGE,
        samesite="lax", domain=".blendpunch.com",
    )
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(_COOKIE_KEY, domain=".blendpunch.com")
    return response


# ── 회원가입 ──────────────────────────────────────────────────────────────────

@router.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    if request.cookies.get(_COOKIE_KEY):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("auth/signup.html", {"request": request})


@router.post("/signup")
def signup(
    request: Request,
    db: Session = Depends(get_db),
    company_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
):
    email = email.strip().lower()

    if password != password2:
        return templates.TemplateResponse("auth/signup.html", {
            "request": request, "error": "비밀번호가 일치하지 않습니다.",
            "v_company": company_name, "v_email": email,
        })
    if len(password) < 8:
        return templates.TemplateResponse("auth/signup.html", {
            "request": request, "error": "비밀번호는 8자 이상이어야 합니다.",
            "v_company": company_name, "v_email": email,
        })
    if db.query(User).filter(User.email == email).first():
        return templates.TemplateResponse("auth/signup.html", {
            "request": request, "error": "이미 등록된 이메일입니다.",
            "v_company": company_name, "v_email": email,
        })

    # username = 이메일 @ 앞 부분 (중복 시 숫자 붙임)
    base_username = email.split("@")[0].replace(".", "_").replace("+", "_")[:50]
    username = base_username
    suffix = 2
    while db.query(User).filter(User.username == username).first():
        username = f"{base_username}{suffix}"
        suffix += 1

    # 회사 생성 (beta 플랜)
    from app.services.feature_flags import apply_plan
    company = Company(name=company_name.strip(), plan="beta", is_active=True)
    db.add(company)
    db.flush()
    apply_plan(db, "beta", company.id)

    # 인증 토큰 생성
    verify_token = secrets.token_urlsafe(32)

    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        role="admin",
        is_active=True,
        email_verified=False,
        company_id=company.id,
        verify_token=verify_token,
        verify_token_exp=datetime.utcnow() + timedelta(hours=24),
    )
    db.add(user)
    db.commit()

    # 인증 메일 발송
    try:
        from app.services.system_email import send_verify_email
        send_verify_email(db, user)
    except Exception:
        pass

    return RedirectResponse(
        f"/signup/done?email={email}",
        status_code=302,
    )


@router.get("/signup/done", response_class=HTMLResponse)
def signup_done(request: Request, email: str = ""):
    return templates.TemplateResponse("auth/signup_done.html", {
        "request": request, "email": email,
    })


# ── 이메일 인증 ───────────────────────────────────────────────────────────────

@router.get("/verify-email", response_class=HTMLResponse)
def verify_email(request: Request, token: str = "", db: Session = Depends(get_db)):
    user = db.query(User).filter(User.verify_token == token).first()
    if not user:
        return templates.TemplateResponse("auth/verify_result.html", {
            "request": request, "success": False,
            "message": "유효하지 않은 인증 링크입니다.",
        })
    if user.verify_token_exp and datetime.utcnow() > user.verify_token_exp:
        return templates.TemplateResponse("auth/verify_result.html", {
            "request": request, "success": False,
            "message": "인증 링크가 만료되었습니다. 다시 인증 메일을 요청해주세요.",
        })
    user.email_verified = True
    user.verify_token = None
    user.verify_token_exp = None
    db.commit()

    # 환영 메일 발송
    try:
        from app.services.system_email import send_welcome
        send_welcome(db, user)
    except Exception:
        pass

    return templates.TemplateResponse("auth/verify_result.html", {
        "request": request, "success": True,
        "message": "이메일 인증이 완료되었습니다. 로그인하세요.",
    })


# ── 비밀번호 찾기 ─────────────────────────────────────────────────────────────

@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request):
    return templates.TemplateResponse("auth/forgot_password.html", {"request": request})


@router.post("/forgot-password")
def forgot_password(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
):
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    # 이메일이 없어도 동일한 응답 (보안)
    if user and user.is_active:
        token = secrets.token_urlsafe(32)
        user.reset_token = token
        user.reset_token_exp = datetime.utcnow() + timedelta(hours=1)
        db.commit()
        try:
            from app.services.system_email import send_password_reset
            send_password_reset(db, user)
        except Exception:
            pass

    return templates.TemplateResponse("auth/forgot_password.html", {
        "request": request,
        "sent": True,
        "email": email,
    })


@router.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(request: Request, token: str = "", db: Session = Depends(get_db)):
    user = db.query(User).filter(User.reset_token == token).first()
    if not user or (user.reset_token_exp and datetime.utcnow() > user.reset_token_exp):
        return templates.TemplateResponse("auth/verify_result.html", {
            "request": request, "success": False,
            "message": "유효하지 않거나 만료된 링크입니다. 비밀번호 찾기를 다시 시도해주세요.",
        })
    return templates.TemplateResponse("auth/reset_password.html", {
        "request": request, "token": token,
    })


@router.post("/reset-password")
def reset_password(
    request: Request,
    db: Session = Depends(get_db),
    token: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
):
    user = db.query(User).filter(User.reset_token == token).first()
    if not user or (user.reset_token_exp and datetime.utcnow() > user.reset_token_exp):
        return templates.TemplateResponse("auth/verify_result.html", {
            "request": request, "success": False,
            "message": "링크가 만료되었습니다.",
        })
    if password != password2:
        return templates.TemplateResponse("auth/reset_password.html", {
            "request": request, "token": token,
            "error": "비밀번호가 일치하지 않습니다.",
        })
    if len(password) < 8:
        return templates.TemplateResponse("auth/reset_password.html", {
            "request": request, "token": token,
            "error": "비밀번호는 8자 이상이어야 합니다.",
        })
    user.hashed_password = hash_password(password)
    user.reset_token = None
    user.reset_token_exp = None
    db.commit()
    return templates.TemplateResponse("auth/verify_result.html", {
        "request": request, "success": True,
        "message": "비밀번호가 변경되었습니다. 새 비밀번호로 로그인하세요.",
    })


# ── 사용자 관리 (슈퍼어드민) ──────────────────────────────────────────────────

ROLES = [("admin", "관리자"), ("staff", "스태프"), ("partner", "파트너")]


@router.get("/users")
def user_list(request: Request, db: Session = Depends(get_db),
              current_user: User = Depends(require_super_admin)):
    users = db.query(User).order_by(User.created_at).all()
    return templates.TemplateResponse("auth/users.html", {
        "request": request, "active_page": "users",
        "current_user": current_user, "users": users, "roles": ROLES,
    })


@router.post("/users/new")
def user_create(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
    username: str = Form(...),
    email: str = Form(""),
    password: str = Form(...),
    role: str = Form("partner"),
):
    if db.query(User).filter(User.username == username).first():
        return RedirectResponse("/users?err=이미+존재하는+아이디입니다", status_code=302)
    if email and db.query(User).filter(User.email == email.strip().lower()).first():
        return RedirectResponse("/users?err=이미+존재하는+이메일입니다", status_code=302)
    user = User(
        username=username,
        email=email.strip().lower() or None,
        hashed_password=hash_password(password),
        role=role,
        is_active=True,
        email_verified=True,  # 관리자가 직접 생성한 계정은 인증 생략
    )
    db.add(user)
    db.commit()
    return RedirectResponse("/users?msg=사용자가+등록되었습니다", status_code=302)


@router.post("/users/{user_id}/edit")
def user_edit(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
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
    current_user: User = Depends(require_super_admin),
    new_password: str = Form(...),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse("/users?err=사용자를+찾을+수+없습니다", status_code=302)
    user.hashed_password = hash_password(new_password)
    db.commit()
    return RedirectResponse("/users?msg=비밀번호가+초기화되었습니다", status_code=302)


@router.get("/users/changelog")
def changelog(request: Request, current_user: User = Depends(get_current_user)):
    from app.changelog import CHANGELOG, CATEGORY_COLORS
    return templates.TemplateResponse("auth/changelog.html", {
        "request": request, "active_page": "users",
        "current_user": current_user,
        "changelog": CHANGELOG,
        "category_colors": CATEGORY_COLORS,
    })


@router.post("/users/{user_id}/delete")
def user_delete(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    if user_id == current_user.id:
        return RedirectResponse("/users?err=자신의+계정은+삭제할+수+없습니다", status_code=302)
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        db.delete(user)
        db.commit()
    return RedirectResponse("/users?msg=삭제되었습니다", status_code=302)
