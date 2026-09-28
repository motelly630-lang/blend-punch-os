"""판매 페이지에서 제품 칸 후보(대표 사진·가격·소개)를 뽑는다 — AI 없이, 페이지에 들어 있는 표준 정보만.

읽는 순서 (앞에 있을수록 믿는다):
- 구조화 정보(JSON-LD, schema.org Product): name · image · offers.price · description
- 공유용 메타(og:title · og:image · og:description · product:price:amount)
- 기본 메타(description) · <title>

값은 '제안'일 뿐이다. 저장은 사람이 '적용'을 눌렀을 때만 (자동 채우기 1단계, 2026-09-28).
"""
from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

MAX_DESC = 120


class _MetaParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.ld_blocks: list[str] = []
        self.title = ""
        self._in_ld = False
        self._in_title = False
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").strip().lower()
            if key and "content" in a and key not in self.meta:
                self.meta[key] = a["content"].strip()
        elif tag == "script" and "ld+json" in a.get("type", "").lower():
            self._in_ld, self._buf = True, []
        elif tag == "title":
            self._in_title, self._buf = True, []

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self.ld_blocks.append("".join(self._buf))
            self._in_ld = False
        elif tag == "title" and self._in_title:
            self.title = " ".join("".join(self._buf).split())
            self._in_title = False

    def handle_data(self, data):
        if self._in_ld or self._in_title:
            self._buf.append(data)


def _walk_products(node):
    """JSON-LD 안의 Product 를 모두 찾는다 (@graph·목록 안에 있어도)."""
    if isinstance(node, list):
        for x in node:
            yield from _walk_products(x)
    elif isinstance(node, dict):
        t = node.get("@type")
        types = t if isinstance(t, list) else [t]
        if any(isinstance(x, str) and x.lower() == "product" for x in types):
            yield node
        for v in node.values():
            if isinstance(v, (dict, list)):
                yield from _walk_products(v)


def _first(v):
    if isinstance(v, list):
        return _first(v[0]) if v else None
    if isinstance(v, dict):
        return v.get("url") or v.get("contentUrl") or v.get("@id")
    return v


def _price(v) -> int | None:
    """'29,000원' · 29000 · '29000.00' → 29000. 0 이하·이상한 값은 None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        n = float(v)
    else:
        m = re.search(r"\d[\d,]*(?:\.\d+)?", str(v))
        if not m:
            return None
        n = float(m.group(0).replace(",", ""))
    return int(round(n)) if 0 < n < 100_000_000 else None


def _offer_price(offers):
    for o in offers if isinstance(offers, list) else [offers]:
        if isinstance(o, dict):
            p = _price(o.get("price") or o.get("lowPrice"))
            if p:
                return p
    return None


def _clean_text(s: str | None, limit: int = MAX_DESC) -> str | None:
    if not s:
        return None
    s = " ".join(html.unescape(str(s)).split())
    return (s[: limit - 1] + "…") if len(s) > limit else (s or None)


def _abs_url(u, base: str) -> str | None:
    if not u or not isinstance(u, str):
        return None
    u = u.strip()
    if u.startswith("//"):
        u = "https:" + u
    full = urljoin(base, u)
    return full if full.startswith(("http://", "https://")) else None


def extract(page_html: str, base_url: str) -> dict:
    """페이지 HTML → {"name","image","price","description"} (없는 칸은 None) + 각 값의 출처."""
    p = _MetaParser()
    try:
        p.feed(page_html)
    except Exception:
        pass
    out = {"name": None, "image": None, "price": None, "description": None}
    src: dict[str, str] = {}

    for block in p.ld_blocks:
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        for prod in _walk_products(data):
            for key, val, where in (("name", _clean_text(prod.get("name"), 200), "구조화 정보"),
                                    ("image", _abs_url(_first(prod.get("image")), base_url), "구조화 정보"),
                                    ("price", _offer_price(prod.get("offers")), "구조화 정보"),
                                    ("description", _clean_text(prod.get("description")), "구조화 정보")):
                if out[key] is None and val:
                    out[key], src[key] = val, where

    m = p.meta
    fallbacks = (
        ("name", _clean_text(m.get("og:title"), 200), "공유 정보(og:title)"),
        ("image", _abs_url(m.get("og:image") or m.get("og:image:url") or m.get("twitter:image"), base_url),
         "공유 정보(og:image)"),
        ("price", _price(m.get("product:price:amount") or m.get("og:price:amount") or m.get("price")),
         "공유 정보(가격)"),
        ("description", _clean_text(m.get("og:description") or m.get("description")), "공유 정보(설명)"),
        ("name", _clean_text(p.title, 200), "페이지 제목"),
    )
    for key, val, where in fallbacks:
        if out[key] is None and val:
            out[key], src[key] = val, where
    out["sources"] = src
    return out
