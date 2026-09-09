"""네이버 쇼핑 검색 — 제품 URL + 대표 이미지 자동 보강.

네이버 검색 API(shop)는 상품명으로 검색하면 link/image/lprice 등을 반환한다.
.env: NAVER_CLIENT_ID, NAVER_CLIENT_SECRET (sns-trend 키 재사용).
"""
from __future__ import annotations

import logging
import re

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_ENDPOINT = "https://openapi.naver.com/v1/search/shop.json"
_TAG = re.compile(r"<[^>]+>")


def is_configured() -> bool:
    return bool(settings.naver_client_id and settings.naver_client_secret)


def search_product(query: str, brand: str = "") -> dict:
    """상품명(+브랜드)으로 네이버 쇼핑 검색 → {url, image, title, lprice}. 실패 시 {}."""
    if not is_configured() or not query:
        return {}
    q = f"{brand} {query}".strip() if brand else query
    headers = {
        "X-Naver-Client-Id": settings.naver_client_id,
        "X-Naver-Client-Secret": settings.naver_client_secret,
    }
    try:
        with httpx.Client(timeout=8) as client:
            r = client.get(_ENDPOINT, headers=headers, params={"query": q, "display": 5, "sort": "sim"})
            r.raise_for_status()
            items = r.json().get("items", [])
    except Exception as e:
        log.warning("naver search failed: %s", e)
        return {}
    if not items:
        return {}
    top = items[0]
    return {
        "url": top.get("link", ""),
        "image": top.get("image", ""),
        "title": _TAG.sub("", top.get("title", "")),
        "lprice": top.get("lprice", ""),
    }
