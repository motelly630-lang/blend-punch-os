"""캠페인 → Slack 02-공동구매-운영 자동 알림.

- 아침 보고 (08:00): 기존 웹훅 보고를 Slack 앱으로 — 태그 [오픈] [마감] 등. 이벤트 `campaign_digest`
- 새 캠페인 등록 → [오픈예정]. 이벤트 `campaign_created`
- 시작일·종료일 변경 → [일정변경]. 이벤트 `campaign_schedule_changed`

등록·수정 화면에 거는 대신 **10분마다 훑는다.** 캠페인은 OS 화면뿐 아니라 통합시트 동기화·엑셀
임포트로도 들어오기 때문에, 저장 경로마다 알림을 달면 빠지는 곳이 생긴다.

일정 변경은 '마지막으로 알린(또는 기준점으로 기록한) 일정' 과 지금 일정을 비교한다. 처음 보는
캠페인은 알리지 않고 기준점만 남긴다 — 배포 첫날 기존 156건이 한꺼번에 '변경' 으로 뜨지 않게.
발송 기록·중복 방지는 slack_notify 가 맡는다.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from app.services import slack_notify as sn

logger = logging.getLogger(__name__)

CHANNEL = "groupbuy"
EV_DIGEST = "campaign_digest"
EV_CREATED = "campaign_created"
EV_SCHEDULE = "campaign_schedule_changed"
NEW_WINDOW = timedelta(minutes=30)   # 스캔 10분 간격 + 놓친 실행 여유
BATCH_LIMIT = 5                      # 한 번에 이보다 많으면 요약 1통 (엑셀 임포트·시트 일괄 수정 대비)
MAX_FAIL = 3                         # 같은 알림이 이만큼 실패하면 포기하고 기준점만 갱신 (무한 재시도 방지)
DONE = ("sent", "mock")              # 이전 상태 판단은 모드와 무관 — mock→실발송 전환 때 폭탄 방지


def _url(cid: str) -> str:
    from app.config import settings
    return f"{settings.app_base_url.rstrip('/')}/campaigns/{cid}"


def _fmt(d: date | None) -> str:
    return d.strftime("%m/%d") if d else "미정"


def _period(start: date | None, end: date | None) -> str:
    return f"{_fmt(start)} ~ {_fmt(end)}"


def _sched_key(c) -> str:
    return f"sched:{c.id}:{c.start_date or '-'}:{c.end_date or '-'}"


# ── 아침 보고 ─────────────────────────────────────────────────────────

def send_digest(db, company_id: int = 1) -> dict:
    from app.config import settings
    from app.services.campaign_alerts import build_digest, render_slack_text
    d = build_digest(db, company_id=company_id)
    review_url = settings.app_base_url.rstrip("/") + "/campaigns/progress-review"
    res = sn.post(EV_DIGEST, CHANNEL, render_slack_text(d, review_url=review_url),
                  company_id=company_id, dedupe_key=f"digest:{d['date']}")
    res["counts"] = {k: len(d[k]) for k in ("ending_today", "ending_tomorrow", "starting_today",
                                            "starting_tomorrow", "running", "no_end_date")}
    return res


# ── 10분 스캔 ─────────────────────────────────────────────────────────

def scan(db, company_id: int) -> dict:
    """새 캠페인·일정 변경을 찾아 알린다. 반환: 건수 요약."""
    from app.models.campaign import Campaign
    out = {"created": 0, "created_batched": 0, "schedule_changed": 0, "schedule_batched": 0,
           "baseline": 0, "failed": 0}
    campaigns = db.query(Campaign).filter(
        Campaign.company_id == company_id,
        (Campaign.is_archived == False) | (Campaign.is_archived.is_(None)),  # noqa: E712
    ).all()
    if sn.is_enabled(EV_CREATED):
        _scan_created(campaigns, company_id, out)
    if sn.is_enabled(EV_SCHEDULE):
        _scan_schedule(db, campaigns, company_id, out)
    return out


def _scan_created(campaigns, company_id: int, out: dict) -> None:
    since = datetime.utcnow() - NEW_WINDOW
    done = _handled_created_keys(company_id)
    fresh = sorted((c for c in campaigns if c.created_at and c.created_at >= since
                    and f"campaign_created:{c.id}" not in done),
                   key=lambda c: c.created_at)
    if not fresh:
        return
    if len(fresh) > BATCH_LIMIT:
        # 엑셀 임포트 등 대량 등록 — 요약 1통, 개별 건은 '이미 처리' 로 기록해 따로 안 나가게
        pending = [c for c in fresh if sn.record(company_id, EV_CREATED, CHANNEL,
                                                  f"campaign_created:{c.id}", "sending",
                                                  "대량 등록 요약에 포함")]
        if not pending:
            return
        lines = [f"[오픈예정] 새 캠페인 {len(pending)}건 등록"]
        lines += [f"· {c.name} ({_period(c.start_date, c.end_date)})" for c in pending[:BATCH_LIMIT]]
        if len(pending) > BATCH_LIMIT:
            lines.append(f"· 외 {len(pending) - BATCH_LIMIT}건")
        res = sn.post(EV_CREATED, CHANNEL, "\n".join(lines), company_id=company_id)
        _settle_batch([f"campaign_created:{c.id}" for c in pending], company_id, res)
        if res["status"] in ("sent", "mock"):
            out["created_batched"] += len(pending)
        else:
            out["failed"] += 1
        return
    for c in fresh:
        text = (f"[오픈예정] 새 캠페인 등록 — *{c.name}*\n"
                f"기간 {_period(c.start_date, c.end_date)}\n→ {_url(c.id)}")
        res = sn.post(EV_CREATED, CHANNEL, text, company_id=company_id,
                      dedupe_key=f"campaign_created:{c.id}")
        if res["status"] in ("sent", "mock"):
            out["created"] += 1
        elif res["status"] == "failed":
            out["failed"] += 1


def _handled_created_keys(company_id: int) -> set[str]:
    """이미 알렸거나 알리는 중인 새 캠페인 키 (현재 모드 기준)."""
    from app.models.slack_notification_log import SlackNotificationLog as L
    db = sn._session()
    try:
        now = datetime.utcnow()
        since = now - NEW_WINDOW - timedelta(days=1)
        rows = db.query(L.dedupe_key, L.status, L.created_at).filter(
            L.company_id == company_id, L.event == EV_CREATED, L.created_at >= since,
            L.status.in_(DONE + ("sending",))).all()
        # 요약 도중 프로세스가 죽어 남은 오래된 sending 은 처리 안 된 것으로 본다
        return {k for k, st, at in rows if st != "sending" or at >= now - sn._STALE_SENDING}
    except Exception as e:
        logger.warning("새 캠페인 기록 조회 실패: %s", e)
        return set()
    finally:
        db.close()


def _settle_batch(keys: list[str], company_id: int, res: dict) -> None:
    """요약 발송 결과로 개별 선점 행을 확정한다. 실패면 풀어서 다음 스캔에 다시 시도."""
    from app.models.slack_notification_log import SlackNotificationLog as L
    final = sn.done_status() if res["status"] in ("sent", "mock") else "failed"
    db = sn._session()
    try:
        db.query(L).filter(L.company_id == company_id, L.dedupe_key.in_(keys),
                           L.status == "sending").update(
            {"status": final, "reason": f"요약 발송에 포함 — {res.get('reason', '')}"[:500]},
            synchronize_session=False)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("요약 기록 확정 실패: %s", e)
    finally:
        db.close()


def _last_schedule(db, company_id: int) -> dict[str, tuple[str, str]]:
    """캠페인별 마지막 '확정' 일정 → (일정 상태, 그 기록의 id).

    기록 키 = "sched:<캠페인>:<시작>:<종료>|<직전 기록 id 또는 base>". 직전 기록 id 를 붙여서
    A→B→A→B 처럼 같은 일정으로 여러 번 바뀌어도 매번 새 변경으로 알린다.
    sent/mock/baseline 을 모드와 무관하게 본다 (mock 으로 알린 것도 '알린 것' — 실발송 전환 때 폭탄 방지).
    failed 는 무시 → 다음 스캔에 재시도 (MAX_FAIL 까지).
    """
    from app.models.slack_notification_log import SlackNotificationLog as L
    rows = db.query(L.id, L.dedupe_key).filter(
        L.company_id == company_id, L.event == EV_SCHEDULE,
        L.status.in_(DONE + ("baseline",)),
    ).order_by(L.created_at, L.updated_at).all()
    last: dict[str, tuple[str, str]] = {}
    for rid, key in rows:
        if key and key.startswith("sched:"):
            state = key.split("|")[0]
            last[state.split(":")[1]] = (state, rid)
    return last


def _dates(state: str) -> str:
    _, _, ps, pe = state.split(":", 3)
    f = lambda v: "미정" if v == "-" else f"{v[5:7]}/{v[8:10]}"
    return f"{f(ps)} ~ {f(pe)}"


def _fail_counts(company_id: int) -> dict[str, int]:
    """일정 변경 키별 실패 횟수."""
    from sqlalchemy import func
    from app.models.slack_notification_log import SlackNotificationLog as L
    db = sn._session()
    try:
        return dict(db.query(L.dedupe_key, func.count(L.id)).filter(
            L.company_id == company_id, L.event == EV_SCHEDULE, L.status == "failed",
        ).group_by(L.dedupe_key).all())
    except Exception as e:
        logger.warning("실패 횟수 조회 실패: %s", e)
        return {}
    finally:
        db.close()


def _scan_schedule(db, campaigns, company_id: int, out: dict) -> None:
    last = _last_schedule(db, company_id)
    fails = _fail_counts(company_id)
    changes = []   # (캠페인, 새 상태, 기록 키, 이전 상태)
    for c in campaigns:
        state = _sched_key(c)
        prev = last.get(c.id)
        if prev is None:
            if sn.record(company_id, EV_SCHEDULE, CHANNEL, f"{state}|base", "baseline", "처음 본 일정 — 기준점"):
                out["baseline"] += 1
            continue
        prev_state, prev_id = prev
        if prev_state == state:
            continue
        key = f"{state}|{prev_id}"
        if prev_state.endswith(":-:-"):
            # 날짜 없이 등록됐다가 처음 채운 것 — 변경이 아니라 입력이라 조용히 기준점만
            sn.record(company_id, EV_SCHEDULE, CHANNEL, key, "baseline", "미정 → 첫 입력 (알림 생략)")
            continue
        if fails.get(key, 0) >= MAX_FAIL:
            sn.record(company_id, EV_SCHEDULE, CHANNEL, key, "baseline", f"{MAX_FAIL}회 실패 — 포기, 기준점 갱신")
            continue
        changes.append((c, state, key, prev_state))

    if len(changes) > BATCH_LIMIT:
        # 시트에서 날짜를 한꺼번에 고친 경우 — 요약 1통
        claimed = [ch for ch in changes if sn.record(company_id, EV_SCHEDULE, CHANNEL, ch[2], "sending", "요약 발송 대기")]
        if not claimed:
            return
        lines = [f"[일정변경] 캠페인 {len(claimed)}건 일정 변경"]
        lines += [f"· {c.name}: {_dates(ps)} → {_period(c.start_date, c.end_date)}" for c, _, _, ps in claimed[:BATCH_LIMIT]]
        if len(claimed) > BATCH_LIMIT:
            lines.append(f"· 외 {len(claimed) - BATCH_LIMIT}건")
        res = sn.post(EV_SCHEDULE, CHANNEL, "\n".join(lines), company_id=company_id)
        _settle_batch([ch[2] for ch in claimed], company_id, res)
        if res["status"] in ("sent", "mock"):
            out["schedule_batched"] += len(claimed)
        else:
            out["failed"] += 1
        return

    for c, state, key, prev_state in changes:
        text = (f"[일정변경] *{c.name}*\n"
                f"{_dates(prev_state)}  →  {_period(c.start_date, c.end_date)}\n→ {_url(c.id)}")
        res = sn.post(EV_SCHEDULE, CHANNEL, text, company_id=company_id, dedupe_key=key)
        if res["status"] in ("sent", "mock"):
            out["schedule_changed"] += 1
        elif res["status"] == "failed":
            out["failed"] += 1
