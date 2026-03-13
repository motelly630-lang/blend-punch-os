import json
import shutil
import uuid
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Influencer
from app.models.user import User
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/influencers")
templates = Jinja2Templates(directory="app/templates")

PLATFORMS = ["instagram", "youtube", "tiktok", "blog", "naver"]

PRESET_CATEGORIES = [
    "요리", "레시피", "뷰티", "육아", "다이어트", "건강관리",
    "리빙", "일상", "반려동물", "패션", "여행", "홈카페", "살림",
]

UPLOAD_DIR = Path("static/uploads/influencers")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _save_image(file: UploadFile) -> str | None:
    if not file or not file.filename:
        return None
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"
    if ext not in ("jpg", "jpeg", "png", "webp", "gif"):
        ext = "jpg"
    filename = f"{uuid.uuid4().hex}.{ext}"
    dest = UPLOAD_DIR / filename
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return f"/static/uploads/influencers/{filename}"


def _parse_categories(json_str: str, fallback_raw: str = "") -> list | None:
    try:
        data = json.loads(json_str)
        if isinstance(data, list):
            return [c for c in data if c] or None
    except Exception:
        pass
    # fallback: newline-separated
    cats = [c.strip() for c in fallback_raw.splitlines() if c.strip()]
    return cats or None


@router.get("")
def influencer_list(request: Request, db: Session = Depends(get_db), q: str = "", platform: str = "",
                    current_user: User = Depends(get_current_user)):
    query = db.query(Influencer)
    if q:
        query = query.filter(Influencer.name.ilike(f"%{q}%") | Influencer.handle.ilike(f"%{q}%"))
    if platform:
        query = query.filter(Influencer.platform == platform)
    influencers = query.order_by(Influencer.followers.desc()).limit(300).all()

    # Stats — SQL aggregates instead of loading all rows into Python
    total = db.query(func.count(Influencer.id)).scalar()
    active_count = db.query(func.count(Influencer.id)).filter(Influencer.status == "active").scalar()
    inactive_count = db.query(func.count(Influencer.id)).filter(Influencer.status == "inactive").scalar()
    blacklist_count = db.query(func.count(Influencer.id)).filter(Influencer.status == "blacklist").scalar()

    platform_rows = db.query(Influencer.platform, func.count(Influencer.id)).group_by(Influencer.platform).all()
    platform_counts = {row[0]: row[1] for row in platform_rows}

    # Category stats — fetch only the JSON column (no full row load)
    cat_counts: Counter = Counter()
    for (cats,) in db.query(Influencer.categories).filter(Influencer.categories.isnot(None)).all():
        for cat in (cats or []):
            cat_counts[cat] += 1
    top_categories = cat_counts.most_common(6)

    return templates.TemplateResponse("influencers/list.html", {
        "request": request, "active_page": "influencers", "current_user": current_user,
        "influencers": influencers, "q": q, "platform_filter": platform, "platforms": PLATFORMS,
        "total": total, "active_count": active_count, "inactive_count": inactive_count, "blacklist_count": blacklist_count,
        "platform_counts": dict(platform_counts), "top_categories": top_categories,
    })


@router.get("/new")
def influencer_new(request: Request, current_user: User = Depends(get_current_user)):
    return templates.TemplateResponse("influencers/form.html", {
        "request": request, "active_page": "influencers", "current_user": current_user,
        "influencer": None, "platforms": PLATFORMS, "preset_categories": PRESET_CATEGORIES,
    })


@router.post("/new")
def influencer_create(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    name: str = Form(...),
    platform: str = Form(...),
    handle: str = Form(...),
    profile_url: str = Form(""),
    followers: int = Form(0),
    categories_json: str = Form("[]"),
    audience_age_range: str = Form(""),
    audience_gender_ratio: str = Form(""),
    contact_email: str = Form(""),
    contact_phone: str = Form(""),
    contact_kakao: str = Form(""),
    agency_name: str = Form(""),
    past_gmv: float = Form(0.0),
    avg_views_per_post: int = Form(0),
    commission_preference_pct: float = Form(0.0),
    notes: str = Form(""),
    status: str = Form("active"),
    profile_image: UploadFile = File(None),
    # Payout / business type fields
    has_campaign_history: str = Form("false"),
    business_type: str = Form(""),
    bank_name: str = Form(""),
    account_number: str = Form(""),
    account_holder: str = Form(""),
    business_name: str = Form(""),
    business_registration_number: str = Form(""),
    representative_name: str = Form(""),
    business_address: str = Form(""),
    tax_invoice_email: str = Form(""),
    legal_name: str = Form(""),
    resident_registration_number: str = Form(""),
    saved_profile_image_path: str = Form(""),
):
    categories = _parse_categories(categories_json)
    image_path = _save_image(profile_image) or (saved_profile_image_path or None)
    influencer = Influencer(
        name=name, platform=platform, handle=handle,
        profile_url=profile_url or None,
        followers=followers,
        categories=categories,
        audience_age_range=audience_age_range or None,
        audience_gender_ratio=audience_gender_ratio or None,
        contact_email=contact_email or None,
        contact_phone=contact_phone or None,
        contact_kakao=contact_kakao or None,
        agency_name=agency_name or None,
        past_gmv=past_gmv,
        avg_views_per_post=avg_views_per_post,
        commission_preference=commission_preference_pct / 100 if commission_preference_pct else None,
        notes=notes or None,
        status=status,
        profile_image=image_path,
        has_campaign_history=has_campaign_history,
        business_type=business_type or None,
        bank_name=bank_name or None,
        account_number=account_number or None,
        account_holder=account_holder or None,
        business_name=business_name or None,
        business_registration_number=business_registration_number or None,
        representative_name=representative_name or None,
        business_address=business_address or None,
        tax_invoice_email=tax_invoice_email or None,
        legal_name=legal_name or None,
        resident_registration_number=resident_registration_number or None,
    )
    db.add(influencer)
    db.commit()
    db.refresh(influencer)
    return RedirectResponse(f"/influencers/{influencer.id}?msg=인플루언서가+등록되었습니다", status_code=302)


@router.get("/{influencer_id}")
def influencer_detail(influencer_id: str, request: Request, db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    influencer = db.query(Influencer).filter(Influencer.id == influencer_id).first()
    if not influencer:
        return RedirectResponse("/influencers?err=인플루언서를+찾을+수+없습니다", status_code=302)
    return templates.TemplateResponse("influencers/detail.html", {
        "request": request, "active_page": "influencers", "current_user": current_user,
        "influencer": influencer,
    })


@router.get("/{influencer_id}/edit")
def influencer_edit(influencer_id: str, request: Request, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    influencer = db.query(Influencer).filter(Influencer.id == influencer_id).first()
    if not influencer:
        return RedirectResponse("/influencers", status_code=302)
    return templates.TemplateResponse("influencers/form.html", {
        "request": request, "active_page": "influencers", "current_user": current_user,
        "influencer": influencer, "platforms": PLATFORMS, "preset_categories": PRESET_CATEGORIES,
    })


@router.post("/{influencer_id}/edit")
def influencer_update(
    influencer_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    name: str = Form(...),
    platform: str = Form(...),
    handle: str = Form(...),
    profile_url: str = Form(""),
    followers: int = Form(0),
    categories_json: str = Form("[]"),
    audience_age_range: str = Form(""),
    audience_gender_ratio: str = Form(""),
    contact_email: str = Form(""),
    contact_phone: str = Form(""),
    contact_kakao: str = Form(""),
    agency_name: str = Form(""),
    past_gmv: float = Form(0.0),
    avg_views_per_post: int = Form(0),
    commission_preference_pct: float = Form(0.0),
    notes: str = Form(""),
    status: str = Form("active"),
    profile_image: UploadFile = File(None),
    # Payout / business type fields
    has_campaign_history: str = Form("false"),
    business_type: str = Form(""),
    bank_name: str = Form(""),
    account_number: str = Form(""),
    account_holder: str = Form(""),
    business_name: str = Form(""),
    business_registration_number: str = Form(""),
    representative_name: str = Form(""),
    business_address: str = Form(""),
    tax_invoice_email: str = Form(""),
    legal_name: str = Form(""),
    resident_registration_number: str = Form(""),
    saved_profile_image_path: str = Form(""),
):
    influencer = db.query(Influencer).filter(Influencer.id == influencer_id).first()
    if not influencer:
        return RedirectResponse("/influencers", status_code=302)

    categories = _parse_categories(categories_json)
    new_image = _save_image(profile_image) or (saved_profile_image_path or None)

    influencer.name = name
    influencer.platform = platform
    influencer.handle = handle
    influencer.profile_url = profile_url or None
    influencer.followers = followers
    influencer.categories = categories
    influencer.audience_age_range = audience_age_range or None
    influencer.audience_gender_ratio = audience_gender_ratio or None
    influencer.contact_email = contact_email or None
    influencer.contact_phone = contact_phone or None
    influencer.contact_kakao = contact_kakao or None
    influencer.agency_name = agency_name or None
    influencer.past_gmv = past_gmv
    influencer.avg_views_per_post = avg_views_per_post
    influencer.commission_preference = commission_preference_pct / 100 if commission_preference_pct else None
    influencer.notes = notes or None
    influencer.status = status
    influencer.has_campaign_history = has_campaign_history
    influencer.business_type = business_type or None
    influencer.bank_name = bank_name or None
    influencer.account_number = account_number or None
    influencer.account_holder = account_holder or None
    influencer.business_name = business_name or None
    influencer.business_registration_number = business_registration_number or None
    influencer.representative_name = representative_name or None
    influencer.business_address = business_address or None
    influencer.tax_invoice_email = tax_invoice_email or None
    influencer.legal_name = legal_name or None
    influencer.resident_registration_number = resident_registration_number or None
    if new_image:
        influencer.profile_image = new_image
    elif saved_profile_image_path and not influencer.profile_image:
        influencer.profile_image = saved_profile_image_path

    db.commit()
    return RedirectResponse(f"/influencers/{influencer_id}?msg=수정되었습니다", status_code=302)


@router.post("/{influencer_id}/delete")
def influencer_delete(influencer_id: str, db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    influencer = db.query(Influencer).filter(Influencer.id == influencer_id).first()
    if influencer:
        db.delete(influencer)
        db.commit()
    return RedirectResponse("/influencers?msg=삭제되었습니다", status_code=302)
