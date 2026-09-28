from app.services.safe_fetch import UnsafeURL, safe_get


def fetch_page(url: str, max_chars: int = 4000) -> str:
    """사용자가 준 주소를 읽는다 — 내부·예약 주소는 거부 (safe_fetch)."""
    try:
        response = safe_get(url, timeout=15.0)
        response.raise_for_status()
        return response.text[:max_chars]
    except UnsafeURL as e:
        return f"페이지 로드 거부: {e}"
    except Exception as e:
        return f"페이지 로드 실패: {e}"
