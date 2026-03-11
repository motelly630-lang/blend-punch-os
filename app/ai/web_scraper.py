import httpx


def fetch_page(url: str, max_chars: int = 4000) -> str:
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; BlendPunchBot/1.0)"}
            response = client.get(url, headers=headers)
            response.raise_for_status()
            return response.text[:max_chars]
    except Exception as e:
        return f"페이지 로드 실패: {e}"
