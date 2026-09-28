"""서버가 사용자 입력 주소를 열 때 쓰는 안전한 조회 (SSRF 방지).

- http/https 만 허용
- 호스트를 IP 로 풀어 사설·루프백·링크로컬(169.254.x — AWS 메타데이터 포함)·예약·멀티캐스트 대역이면 거부
- 주소 넘김(redirect)은 자동으로 따라가지 않고, 넘어갈 때마다 다시 검사
- 응답 크기·시간 제한

남는 위험: 검사한 뒤 DNS 가 다른 IP 로 바뀌는 경우(DNS rebinding). 운영에서는 EC2 메타데이터를
IMDSv2(토큰 필수)로 두는 등 네트워크 단 방어도 함께 둔다.
"""
from __future__ import annotations

import ipaddress
import socket
import time
from io import BytesIO
from urllib.parse import urlsplit

import httpx

UA = "Mozilla/5.0 (compatible; BlendPunchBot/1.0)"
MAX_REDIRECTS = 5
MAX_BYTES = 3_000_000
MAX_IMAGE_BYTES = 10_000_000
TOTAL_DEADLINE = 30.0      # 한 번 조회 전체(주소 넘김 포함) 최대 시간


class UnsafeURL(Exception):
    """열면 안 되는 주소 (이유를 메시지로)."""


def address_problem(url: str) -> str | None:
    """서버가 열면 안 되는 주소면 이유를, 괜찮으면 None."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return f"허용하지 않는 주소 형식({parts.scheme or '없음'})"
    host = (parts.hostname or "").strip("[]")
    if not host:
        return "호스트 없음"
    try:
        ips = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            ips = [ipaddress.ip_address(ai[4][0].split("%")[0]) for ai in socket.getaddrinfo(host, None)]
        except (socket.gaierror, UnicodeError):
            return "이름 풀이 실패"
    for ip in ips:
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
                or ip.is_unspecified or not ip.is_global):
            return f"내부·예약 주소({ip})"
    return None


def safe_get(url: str, *, timeout: float = 15.0, max_bytes: int = MAX_BYTES,
             headers: dict | None = None, transport: httpx.BaseTransport | None = None) -> httpx.Response:
    """안전 검사를 통과한 주소만 GET. 본문은 max_bytes 까지만 읽는다. 위험 주소면 UnsafeURL."""
    current = url
    hdrs = {"User-Agent": UA, **(headers or {})}
    deadline = time.monotonic() + TOTAL_DEADLINE
    # trust_env=False: 환경변수 프록시로 새지 않게
    with httpx.Client(timeout=timeout, follow_redirects=False, headers=hdrs, transport=transport,
                      trust_env=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            bad = address_problem(current)
            if bad:
                raise UnsafeURL(bad)
            with client.stream("GET", current) as r:
                if r.status_code in (301, 302, 303, 307, 308) and "location" in r.headers:
                    current = str(httpx.URL(current).join(r.headers["location"]))
                    continue
                body = b""
                for chunk in r.iter_bytes():
                    body += chunk
                    if time.monotonic() > deadline:
                        raise UnsafeURL("응답이 너무 느림")
                    if len(body) > max_bytes:
                        body = body[:max_bytes]
                        break
                keep = {k: v for k, v in r.headers.items()
                        if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")}
                return httpx.Response(r.status_code, headers=keep, content=body,
                                      request=httpx.Request("GET", current))
    raise UnsafeURL("주소 넘김이 너무 많음")


def safe_get_image(url: str, *, headers: dict | None = None, max_bytes: int = MAX_IMAGE_BYTES,
                   timeout: float = 15.0, transport: httpx.BaseTransport | None = None):
    """안전 검사를 통과한 주소에서 '진짜 이미지'만 받는다. (bytes, 확장자) 또는 None.

    content-type 이 image/* 이고 PIL 로 열려야 통과 — 이미지로 위장한 HTML·JSON 은 저장되지 않는다.
    """
    from PIL import Image
    try:
        r = safe_get(url, headers=headers, max_bytes=max_bytes + 1, timeout=timeout, transport=transport)
    except (UnsafeURL, httpx.HTTPError):
        return None
    ct = (r.headers.get("content-type") or "").lower()
    if r.status_code != 200 or not r.content or not ct.startswith("image/") or len(r.content) > max_bytes:
        return None
    old = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = 40_000_000       # 압축 폭탄 방지
    try:
        with Image.open(BytesIO(r.content)) as im:
            im.verify()
            fmt = (im.format or "").lower()
    except Exception:
        return None
    finally:
        Image.MAX_IMAGE_PIXELS = old
    ext = {"png": "png", "webp": "webp", "gif": "gif"}.get(fmt, "jpg")
    return r.content, ext
