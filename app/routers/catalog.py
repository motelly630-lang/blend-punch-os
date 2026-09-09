"""
/catalog — 구버전 공개 카탈로그.
2026-07 부로 /public 카탈로그로 일원화되어, 모든 경로를 /public 으로 301 리다이렉트한다.
(라우트는 남겨 기존 링크·북마크 호환을 유지하고, 삭제하지 않는다.)
"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db

router = APIRouter(prefix="/catalog")
# main.py _setup_filters() 가 각 라우터 모듈의 templates.env 에 필터를 주입하므로 유지한다.
templates = Jinja2Templates(directory="app/templates")


@router.get("/brand/{brand_name}")
def catalog_brand(brand_name: str):
    return RedirectResponse(f"/public/products/brand/{quote(brand_name)}", status_code=301)


@router.get("")
def catalog_list(q: str = "", category: str = "", brand: str = "", page: int = 1):
    params = []
    if q:
        params.append(f"q={quote(q)}")
    if category:
        params.append(f"category={quote(category)}")
    if brand:
        params.append(f"brand={quote(brand)}")
    qs = ("?" + "&".join(params)) if params else ""
    return RedirectResponse(f"/public/products{qs}", status_code=301)


@router.get("/product/{product_id}")
def catalog_detail(product_id: str):
    return RedirectResponse(f"/public/products/product/{product_id}", status_code=301)


@router.post("/inquiry")
async def catalog_inquiry(
    request: Request,
    product_id: str = Form(...),
    product_name: str = Form(""),
    contact_name: str = Form(""),
    contact_info: str = Form(""),
    message: str = Form(""),
    db: Session = Depends(get_db),
):
    """레거시 문의 접수 — 신규 공구신청(/public/apply)으로 안내 리다이렉트."""
    return RedirectResponse("/public/products", status_code=303)
