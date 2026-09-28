"""서버가 사용자 입력 주소를 열 때 쓰는 안전한 조회 (SSRF 방지).

- http/https 만 허용
- 호스트를 IP 로 풀어 사설·루프백·링크로컬(169.254.x — AWS 메타데이터 포함)·예약·멀티캐스트 대역이면 거부
- 주소 넘김(redirect)은 자동으로 따라가지 않고, 넘어갈 때마다 다시 검사
- 응답 크기·시간 제한

- 검사한 IP 로만 연결 (연결 순간 DNS 를 다시 묻지 않음 — DNS rebinding 방지). 도메인은 Host·SNI 로 유지
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


def _checked_ips(url: str) -> tuple[list, str | None]:
    """주소를 IP 로 풀어 검사. (통과한 IP 목록, 문제) — 문제가 있으면 IP 목록은 비어 있다."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return [], f"허용하지 않는 주소 형식({parts.scheme or '없음'})"
    host = (parts.hostname or "").strip("[]")
    if not host:
        return [], "호스트 없음"
    try:
        ips = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            ips = [ipaddress.ip_address(ai[4][0].split("%")[0]) for ai in socket.getaddrinfo(host, None)]
        except (socket.gaierror, UnicodeError, ValueError):
            return [], "이름 풀이 실패"
    if not ips:
        return [], "이름 풀이 실패"
    for ip in ips:
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
                or ip.is_unspecified or not ip.is_global):
            return [], f"내부·예약 주소({ip})"
    return ips, None


def address_problem(url: str) -> str | None:
    """서버가 열면 안 되는 주소면 이유를, 괜찮으면 None."""
    return _checked_ips(url)[1]


def _pinned(url: str, ip) -> tuple[httpx.URL, dict, dict]:
    """검사를 통과한 IP 로 바로 연결하는 요청 정보 — 연결 순간 DNS 를 다시 묻지 않는다 (DNS rebinding 방지).
    원래 도메인은 Host 헤더와 HTTPS 인증서 확인(SNI)에 그대로 쓴다."""
    u = httpx.URL(url)
    ascii_host = u.raw_host.decode("ascii")          # 한글 도메인은 IDNA(xn--…) 표기로
    try:
        ipaddress.ip_address(ascii_host)
        is_ip_literal = True
    except ValueError:
        is_ip_literal = False
    shown = f"[{ascii_host}]" if ":" in ascii_host else ascii_host   # IPv6 는 대괄호
    host_header = shown if u.port is None else f"{shown}:{u.port}"
    # 인증서는 원래 도메인으로 확인 (IP 로 적은 주소면 SNI 없이 IP 로 확인)
    extensions = {"sni_hostname": ascii_host} if u.scheme == "https" and not is_ip_literal else {}
    return u.copy_with(host=str(ip)), {"Host": host_header}, extensions


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
            ips, bad = _checked_ips(current)
            if bad:
                raise UnsafeURL(bad)
            target, host_hdr, ext = _pinned(current, ips[0])
            with client.stream("GET", target, headers=host_hdr, extensions=ext) as r:
                if r.status_code in (301, 302, 303, 307, 308) and "location" in r.headers:
                    current = str(httpx.URL(current).join(r.headers["location"]))   # 다음 바퀴에서 다시 검사
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
