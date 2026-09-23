"""Slack 채널별 알림 발송 (Slack 앱 봇 토큰).

webhook_notify 는 웹훅 1개 = 채널 1개라 채널을 고를 수 없다. 여기서는 봇 토큰 하나로
5개 운영 채널과 대표님 DM 에 나눠 보낸다. 채널 구조는 Obsidian `08_Slack/Slack_MOC`.

지키는 것:
- 이벤트별 켜기/끄기 (`SLACK_EVENTS`). 기본은 전부 꺼짐 — 켠 것만 나간다.
- 같은 이벤트는 한 번만 (`dedupe_key`). 발송 전에 `sending` 행으로 선점하고, DB 부분 유니크
  인덱스가 두 번째 선점을 막는다 (배포 중 프로세스 겹침·수동 실행과 스케줄러 동시 실행 대비).
- 발송 기록은 **호출자의 DB 세션을 쓰지 않는다** — 별도 세션으로 열고 닫는다. 호출자의 미저장
  변경을 대신 commit 하거나 rollback 으로 날리지 않기 위해서다.
- `ALERT_MOCK=true` 면 실제로 보내지 않고 기록만 남긴다 (기존 웹훅과 같은 스위치).
- 무엇이 실패해도(Slack·DB 모두) 예외를 올리지 않는다 — 알림이 업무나 스케줄러를 죽이면 안 된다.

운영에서는 `SLACK_CHANNELS` 에 채널 **ID** 를 직접 넣는 것을 권한다 (이름 조회는 호출 제한이 빡빡하다).
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

# 채널 키 → 기본 채널 이름 (SLACK_CHANNELS 로 ID·다른 이름을 줄 수 있다)
CHANNELS = {
    "notice": "01-공지",
    "groupbuy": "02-공동구매-운영",
    "seller": "03-셀러-브랜드",
    "order": "04-주문-정산-CS",
    "marketing": "05-마케팅-메타",
}
DM = "dm"

_ID_RE = re.compile(r"^[CGDU][A-Z0-9]{6,}$")
_CACHE_TTL = 3600        # 찾은 채널 ID 캐시 1시간
_MISS_TTL = 300          # 못 찾은 결과도 5분 캐시 — conversations.list 호출 제한(분당 약 20회) 보호
_STALE_SENDING = timedelta(minutes=10)   # 이보다 오래된 sending 은 프로세스가 죽은 것으로 본다
_resolved: dict[str, tuple[str | None, float]] = {}   # 이름 → (ID 또는 None, 저장 시각)


def channel_map() -> dict[str, str]:
    from app.config import settings
    m = dict(CHANNELS)
    for part in (settings.slack_channels or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip() and v.strip():
                m[k.strip()] = v.strip().lstrip("#")
    return m


def enabled_events() -> set[str]:
    from app.config import settings
    return {e.strip() for e in (settings.slack_events or "").split(",") if e.strip()}


def is_enabled(event: str) -> bool:
    ev = enabled_events()
    return "all" in ev or event in ev


def _api(method: str, payload: dict, form: bool = False) -> dict:
    """Slack Web API 호출. 조회 메서드는 form, 쓰기(chat.postMessage)는 JSON."""
    from app.config import settings
    headers = {"Authorization": f"Bearer {settings.slack_bot_token}"}
    with httpx.Client(timeout=10) as c:
        if form:
            r = c.post(f"https://slack.com/api/{method}", data=payload, headers=headers)
        else:
            r = c.post(f"https://slack.com/api/{method}", json=payload, headers=headers)
    if r.status_code == 429:
        return {"ok": False, "error": f"ratelimited (Retry-After {r.headers.get('Retry-After', '?')}s)"}
    try:
        return r.json()
    except Exception:
        return {"ok": False, "error": f"HTTP {r.status_code}"}


def _forget(name: str) -> None:
    _resolved.pop(name, None)


def _resolve(target: str) -> tuple[str | None, str]:
    """채널 이름/ID → ID. (id, 실패 이유)"""
    if _ID_RE.match(target):
        return target, ""
    hit = _resolved.get(target)
    if hit:
        cid, at = hit
        if time.monotonic() - at < (_CACHE_TTL if cid else _MISS_TTL):
            return (cid, "") if cid else (None, f"채널 '{target}' 을 찾지 못함 (최근 조회 결과)")
    cursor = None
    now = time.monotonic()
    for _ in range(10):  # 채널 2천 개까지
        payload = {"types": "public_channel,private_channel", "limit": 200, "exclude_archived": "true"}
        if cursor:
            payload["cursor"] = cursor
        res = _api("conversations.list", payload, form=True)
        if not res.get("ok"):
            return None, f"채널 목록 조회 실패: {res.get('error')}"
        for ch in res.get("channels", []):
            _resolved[ch["name"]] = (ch["id"], now)
        if target in _resolved and _resolved[target][0]:
            return _resolved[target][0], ""
        cursor = (res.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    _resolved[target] = (None, now)
    return None, f"채널 '{target}' 을 찾지 못함 (비공개 채널이면 봇을 /invite 해야 보인다)"


# ── 발송 기록 (별도 세션) ─────────────────────────────────────────────────

def _session():
    from app.database import SessionLocal
    return SessionLocal()


def _claim(company_id, event, channel, dedupe_key, mock: bool) -> tuple[str | None, str]:
    """발송 자리를 잡는다. (log id, '' ) / (None, 'duplicate') / (None, 오류)

    실발송은 sending 행을 넣고 유니크 인덱스에 맡긴다. mock 은 동시성 보호가 필요 없어 조회로 충분.
    """
    from sqlalchemy.exc import IntegrityError
    from app.models.slack_notification_log import SlackNotificationLog as L
    db = _session()
    try:
        if dedupe_key:
            # 죽은 프로세스가 남긴 오래된 sending 은 풀어준다 — 영원히 막히지 않게
            db.query(L).filter(L.company_id == company_id, L.dedupe_key == dedupe_key,
                               L.status == "sending",
                               L.created_at < datetime.utcnow() - _STALE_SENDING
                               ).update({"status": "failed", "reason": "sending 상태로 멈춤 — 재시도 허용"},
                                        synchronize_session=False)
            db.commit()
            if mock and db.query(L.id).filter(L.company_id == company_id, L.dedupe_key == dedupe_key,
                                              L.status == "mock").first():
                return None, "duplicate"
        row = L(company_id=company_id, event=event, channel=channel, dedupe_key=dedupe_key,
                status="mock" if mock else "sending",
                reason="mock 모드 (ALERT_MOCK=false 로 실발송)" if mock else None)
        db.add(row)
        db.commit()
        return row.id, ""
    except IntegrityError:
        db.rollback()
        return None, "duplicate"
    except Exception as e:
        db.rollback()
        return None, f"발송 기록 실패: {type(e).__name__}: {e}"
    finally:
        db.close()


def _finish(log_id: str, status: str, reason: str) -> None:
    from app.models.slack_notification_log import SlackNotificationLog as L
    db = _session()
    try:
        db.query(L).filter(L.id == log_id).update(
            {"status": status, "reason": (reason or "")[:500], "updated_at": datetime.utcnow()},
            synchronize_session=False)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("Slack 발송 기록 갱신 실패 (%s → %s): %s", log_id, status, e)
    finally:
        db.close()


# ── 발송 ────────────────────────────────────────────────────────────────

def post(event: str, channel: str, text: str, company_id: int,
         dedupe_key: str | None = None, force: bool = False) -> dict:
    """채널 키(groupbuy 등) 또는 'dm' 으로 발송. 반환 {"sent", "status", "reason"}.

    company_id 는 필수다 (RG-002 — 빠뜨려도 조용히 회사 1로 기록되면 안 된다).
    force=True 는 이벤트 켜짐 여부를 무시한다 (수동 테스트용).
    """
    from app.config import settings
    try:
        if not force and not is_enabled(event):
            return {"sent": False, "status": "off", "reason": f"이벤트 '{event}' 꺼짐 (SLACK_EVENTS)"}
        if not text or not text.strip():
            return {"sent": False, "status": "skipped", "reason": "빈 메시지"}

        mock = bool(settings.alert_mock)
        log_id, err = _claim(company_id, event, channel, dedupe_key, mock)
        if err == "duplicate":
            return {"sent": False, "status": "duplicate", "reason": f"이미 발송됨 ({dedupe_key})"}
        if err:
            # 기록을 못 남기면 중복 방지를 보장할 수 없다 — 중복 방지 대상이면 보내지 않는다
            logger.warning("Slack %s: %s", event, err)
            if dedupe_key:
                return {"sent": False, "status": "failed", "reason": err}

        if mock:
            logger.info("[slack mock] #%s (%s) — 발송 생략:\n%s", channel, event, text[:300])
            return {"sent": False, "status": "mock", "reason": "mock 모드"}

        def done(status, reason, sent=False):
            if log_id:
                _finish(log_id, status, reason)
            return {"sent": sent, "status": status, "reason": reason}

        if not settings.slack_bot_token:
            return done("failed", "SLACK_BOT_TOKEN 미설정")

        name = None
        if channel == DM:
            target_id = settings.slack_dm_user or None
            reason = "" if target_id else "SLACK_DM_USER 미설정"
        else:
            name = channel_map().get(channel)
            target_id, reason = _resolve(name) if name else (None, f"알 수 없는 채널 키 '{channel}'")
        if not target_id:
            return done("failed", reason)

        res = _api("chat.postMessage", {"channel": target_id, "text": text,
                                        "unfurl_links": False, "unfurl_media": False})
        if res.get("ok"):
            return done("sent", "ok", sent=True)
        e = res.get("error") or "unknown"
        if e in ("channel_not_found", "is_archived") and name:
            _forget(name)   # 이름이 바뀌었거나 보관된 채널 — 다음엔 다시 찾는다
        if e == "not_in_channel":
            e += " — 비공개 채널이면 채널에서 /invite @BP OS"
        return done("failed", e)
    except Exception as ex:
        logger.warning("Slack 발송 실패: %s", ex)
        return {"sent": False, "status": "failed", "reason": f"{type(ex).__name__}: {ex}"}


def record(company_id: int, event: str, channel: str, dedupe_key: str, status: str, reason: str = "") -> bool:
    """보내지 않고 기록만 남긴다 (기준점 baseline, 요약에 묶여 개별 발송 생략 등). 성공 여부 반환.

    status 가 sent/sending 이면 유니크 인덱스에 걸려 이미 있을 때 False.
    """
    from sqlalchemy.exc import IntegrityError
    from app.models.slack_notification_log import SlackNotificationLog as L
    db = _session()
    try:
        db.add(L(company_id=company_id, event=event, channel=channel, dedupe_key=dedupe_key,
                 status=status, reason=reason[:500]))
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False
    except Exception as e:
        db.rollback()
        logger.warning("Slack 기록 실패 (%s): %s", dedupe_key, e)
        return False
    finally:
        db.close()


def done_status() -> str:
    """현재 모드에서 '이미 처리됨' 으로 치는 상태 (mock 모드는 mock, 실발송은 sent)."""
    from app.config import settings
    return "mock" if settings.alert_mock else "sent"


def notify_admin(text: str, company_id: int, dedupe_key: str | None = None) -> dict:
    """시스템 이상(백업·동기화·자동화 실패)을 대표님 DM 으로. 이벤트 키: system_alert

    반복되는 실패(예: 매일 백업 실패)는 dedupe_key 에 날짜를 넣어 하루 한 번만 오게 한다.
    """
    return post("system_alert", DM, f"⚠️ [OS 시스템] {text}", company_id=company_id, dedupe_key=dedupe_key)
