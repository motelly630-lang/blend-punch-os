"""
슈퍼어드민 — 회사(테넌트) 관리
/companies

- 회사 목록 / 생성 / 상태 변경
- 회사별 기능 플래그 관리 (플랜 프리셋 + 개별 토글)
- 사용자 ↔ 회사 배정
"""
from datetime import datetime
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth.dependencies import require_super_admin
from app.models.user import User
from app.models.feature_flag import Company, CompanyFeature
from app.services.feature_flags import (
    ALL_FEATURES, PLAN_FEATURES, ALWAYS_ON,
    get_enabled_features, apply_plan, toggle_feature, invalidate,
)

router = APIRouter(prefix="/companies")
templates = Jinja2Templates(directory="app/templates")


# ── 목록 ─────────────────────────────────────────────────────────────────────

@router.get("")
def companies_list(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    companies = db.query(Company).order_by(Company.created_at.asc()).all()

    # 회사별 통계 (user count, active feature count)
    stats = {}
    for c in companies:
        user_cnt = db.query(User).filter(User.company_id == c.id, User.is_active == True).count()
        feat_cnt = db.query(CompanyFeature).filter(
            CompanyFeature.company_id == c.id, CompanyFeature.enabled == True
        ).count() or len(ALL_FEATURES)  # 행 없으면 전체 활성 기본값
        stats[c.id] = {"users": user_cnt, "features": feat_cnt}

    return templates.TemplateResponse("companies/index.html", {
        "request": request,
        "companies": companies,
        "stats": stats,
        "user": user,
        "active_page": "companies",
    })


# ── 생성 ─────────────────────────────────────────────────────────────────────

@router.get("/new")
def companies_new(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    return templates.TemplateResponse("companies/new.html", {
        "request": request,
        "plans": list(PLAN_FEATURES.keys()),
        "user": user,
        "active_page": "companies",
    })


@router.post("/new")
def companies_create(
    name: str = Form(...),
    plan: str = Form("pro"),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    name = name.strip()
    if not name:
        return RedirectResponse("/companies/new?err=회사명을+입력해주세요", status_code=302)

    company = Company(name=name, plan=plan, is_active=True)
    db.add(company)
    db.commit()
    db.refresh(company)

    # 플랜에 맞는 기능 세트 초기 적용
    apply_plan(db, plan, company.id)

    return RedirectResponse(f"/companies/{company.id}?msg=회사가+생성되었습니다", status_code=302)


# ── 상세 / 편집 ───────────────────────────────────────────────────────────────

@router.get("/{company_id}")
def company_detail(
    company_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        return RedirectResponse("/companies?err=회사를+찾을+수+없습니다", status_code=302)

    enabled = get_enabled_features(db, company.id)
    os_features       = {k: v for k, v in ALL_FEATURES.items() if v["group"] == "os"}
    commerce_features = {k: v for k, v in ALL_FEATURES.items() if v["group"] == "commerce"}

    # 소속 사용자
    members = db.query(User).filter(User.company_id == company.id).order_by(User.username).all()
    # 미배정 사용자 (슈퍼어드민 포함)
    unassigned = db.query(User).filter(
        User.company_id == None,
        User.is_active == True,
    ).order_by(User.username).all()

    plan_counts = {p: len(keys) for p, keys in PLAN_FEATURES.items()}

    return templates.TemplateResponse("companies/detail.html", {
        "request": request,
        "company": company,
        "enabled": enabled,
        "os_features": os_features,
        "commerce_features": commerce_features,
        "members": members,
        "unassigned": unassigned,
        "plan_counts": plan_counts,
        "plan_features": PLAN_FEATURES,
        "all_features": ALL_FEATURES,
        "user": user,
        "active_page": "companies",
    })


@router.post("/{company_id}/update")
def company_update(
    company_id: int,
    name: str = Form(...),
    plan: str = Form("pro"),
    is_active: str = Form("on"),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        return RedirectResponse("/companies", status_code=302)

    company.name      = name.strip() or company.name
    company.plan      = plan
    company.is_active = (is_active == "on")
    company.updated_at = datetime.utcnow()
    db.commit()
    invalidate(company_id)

    return RedirectResponse(f"/companies/{company_id}?msg=저장되었습니다", status_code=302)


# ── 기능 관리 ─────────────────────────────────────────────────────────────────

@router.post("/{company_id}/features/plan")
def company_apply_plan(
    company_id: int,
    plan: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        return RedirectResponse("/companies", status_code=302)
    try:
        apply_plan(db, plan, company_id)
    except ValueError as e:
        return RedirectResponse(f"/companies/{company_id}?err={e}", status_code=302)

    plan_kr = {"beta": "베타", "basic": "기본", "pro": "프로"}
    return RedirectResponse(
        f"/companies/{company_id}?msg={plan_kr.get(plan, plan)}+플랜+적용됨",
        status_code=302,
    )


@router.post("/{company_id}/features/toggle")
async def company_toggle_feature(
    company_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    body = await request.json()
    key     = body.get("key", "")
    enabled = bool(body.get("enabled", True))

    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        return JSONResponse({"ok": False, "error": "회사를 찾을 수 없습니다."}, status_code=404)
    try:
        toggle_feature(db, key, enabled, company_id)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    return JSONResponse({"ok": True, "key": key, "enabled": enabled})


# ── 사용자 배정 ───────────────────────────────────────────────────────────────

@router.post("/{company_id}/users/add")
def company_add_user(
    company_id: int,
    user_id: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        return RedirectResponse("/companies", status_code=302)

    target = db.query(User).filter(User.id == user_id).first()
    if target:
        target.company_id = company_id
        db.commit()
        # 사용자 company 캐시 무효화
        from app.services.feature_flags import invalidate_user
        invalidate_user(target.username)

    return RedirectResponse(f"/companies/{company_id}?msg=사용자가+배정되었습니다", status_code=302)


@router.post("/{company_id}/users/{user_id}/remove")
def company_remove_user(
    company_id: int,
    user_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    target = db.query(User).filter(
        User.id == user_id, User.company_id == company_id
    ).first()
    if target:
        target.company_id = None
        db.commit()
        from app.services.feature_flags import invalidate_user
        invalidate_user(target.username)

    return RedirectResponse(f"/companies/{company_id}?msg=배정이+해제되었습니다", status_code=302)
