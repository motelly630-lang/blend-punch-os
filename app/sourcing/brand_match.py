"""OS Brand 테이블 매칭 — 추출된 브랜드명을 기존 등록 브랜드와 정규화 매칭.

매칭되면 표준 브랜드명(+로고)을 사용, 없으면 원본 유지.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models import Brand


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").lower())


def match(db: Session, raw_brand: str, company_id: int = 1) -> dict:
    """추출 브랜드명 → {name, brand_id, logo, matched}.

    정규화(소문자·공백제거) 후 정확/부분 일치 검색. 미매칭 시 원본 name 반환.
    """
    raw = (raw_brand or "").strip()
    if not raw:
        return {"name": raw, "brand_id": None, "logo": None, "matched": False}

    target = _norm(raw)
    brands = db.query(Brand).filter(Brand.company_id == company_id, Brand.is_archived == False).all()  # noqa: E712
    # 1) 정확 일치
    for b in brands:
        if _norm(b.name) == target:
            return {"name": b.name, "brand_id": b.id, "logo": b.logo, "matched": True}
    # 2) 부분 포함 (한쪽이 다른 쪽을 포함)
    for b in brands:
        nb = _norm(b.name)
        if nb and (nb in target or target in nb):
            return {"name": b.name, "brand_id": b.id, "logo": b.logo, "matched": True}
    return {"name": raw, "brand_id": None, "logo": None, "matched": False}
