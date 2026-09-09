"""웹훅 알림 발송 — 슬랙 / 카카오워크 / 디스코드 공용.

`campaign_alerts.render_text()` 가 만든 문장을 그대로 실어보낸다.
문장 생성과 발송 통로를 분리한 기존 설계를 그대로 따른다.

카카오톡 '나에게 보내기' 는 웹훅이 아니라 OAuth 가 필요해서 여기 없다.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 슬랙·카카오워크는 {"text": ...}, 디스코드는 {"content": ...} 를 받는다.
_DISCORD_HOSTS = ("discord.com", "discordapp.com")


def _payload_for(url: str, text: str) -> dict:
    if any(h in url for h in _DISCORD_HOSTS):
        return {"content": text}
    return {"text": text}


def send_webhook(text: str, url: str | None = None) -> dict:
    """웹훅으로 텍스트 발송.

    반환: {"sent": bool, "reason": str}
    실패해도 예외를 올리지 않는다 — 알림 실패가 스케줄러를 죽이면 안 된다.
    """
    from app.config import settings

    target = url or settings.alert_webhook_url
    if not target:
        return {"sent": False, "reason": "ALERT_WEBHOOK_URL 미설정"}
    if not text or not text.strip():
        return {"sent": False, "reason": "빈 메시지"}

    if settings.alert_mock:
        logger.info("[webhook mock] 발송 생략 — 본문:\n%s", text)
        return {"sent": False, "reason": "mock 모드 (ALERT_MOCK=false 로 실발송)"}

    try:
        import httpx
        with httpx.Client(timeout=10) as c:
            r = c.post(target, json=_payload_for(target, text))
        if r.status_code // 100 == 2:
            return {"sent": True, "reason": f"HTTP {r.status_code}"}
        # 본문을 남긴다 — 슬랙은 실패 이유를 본문에 담아 200이 아닌 코드로 준다
        return {"sent": False, "reason": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        logger.warning("웹훅 발송 실패: %s", e)
        return {"sent": False, "reason": f"{type(e).__name__}: {e}"}


def send_campaign_digest(db, company_id: int = 1) -> dict:
    """공구 알림을 만들어 웹훅으로 발송. 알릴 게 없으면 발송 생략."""
    from app.services.campaign_alerts import build_digest, has_anything, render_text

    d = build_digest(db, company_id=company_id)
    if not has_anything(d):
        return {"sent": False, "reason": "알릴 공구 없음 (발송 생략)", "skipped": True}

    res = send_webhook(render_text(d))
    res["counts"] = {k: len(d[k]) for k in
                     ("ending_today", "ending_tomorrow", "starting_today",
                      "starting_tomorrow", "running", "no_end_date")}
    return res
