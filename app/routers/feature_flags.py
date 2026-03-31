"""
어드민 — 기능 플래그 관리
GET  /settings/features         — 기능 목록 + 토글 UI
POST /settings/features/plan    — 플랜 프리셋 일괄 적용
POST /settings/features/toggle  — 단일 기능 토글 (JSON API)
"""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth.dependencies import get_current_user, require_admin
from app.models.user import User
from app.services.feature_flags import (
    ALL_FEATURES, PLAN_FEATURES,
    get_or_create_company, get_enabled_features,
    apply_plan, toggle_feature,
)

router = APIRouter(prefix="/settings")
templates = Jinja2Templates(directory="app/templates")


@router.get("/features")
def features_index(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    company = get_or_create_company(db)
    enabled = get_enabled_features(db, company.id)

    # 그룹별 분류
    os_features = {k: v for k, v in ALL_FEATURES.items() if v["group"] == "os"}
    commerce_features = {k: v for k, v in ALL_FEATURES.items() if v["group"] == "commerce"}

    plan_counts = {p: len(keys) for p, keys in PLAN_FEATURES.items()}

    return templates.TemplateResponse("feature_flags/index.html", {
        "request": request,
        "company": company,
        "enabled": enabled,
        "os_features": os_features,
        "commerce_features": commerce_features,
        "plan_counts": plan_counts,
        "plan_features": PLAN_FEATURES,
        "user": user,
        "active_page": "feature_flags",
    })


@router.post("/features/plan")
def features_apply_plan(
    plan: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """플랜 프리셋 일괄 적용 (admin 전용)."""
    try:
        apply_plan(db, plan)
    except ValueError as e:
        return RedirectResponse(f"/settings/features?err={e}", status_code=302)
    plan_kr = {"beta": "베타", "basic": "기본", "pro": "프로"}
    return RedirectResponse(
        f"/settings/features?msg={plan_kr.get(plan, plan)}+플랜이+적용되었습니다",
        status_code=302,
    )


@router.post("/features/toggle")
async def features_toggle(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """단일 기능 토글 — JSON API (admin 전용)."""
    body = await request.json()
    key = body.get("key", "")
    enabled = bool(body.get("enabled", True))

    try:
        toggle_feature(db, key, enabled)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    return JSONResponse({"ok": True, "key": key, "enabled": enabled})
