"""
APScheduler — daily 9 AM briefing job (Asia/Seoul).
"""
from apscheduler.schedulers.background import BackgroundScheduler

_scheduler = BackgroundScheduler(timezone="Asia/Seoul")


def _daily_briefing_job():
    from app.database import SessionLocal
    from app.services.trend_matcher import run_briefing

    db = SessionLocal()
    try:
        briefing = run_briefing(db)
        print(f"[Scheduler] Daily briefing complete: {briefing.report_date} "
              f"| {briefing.event_count} events | {briefing.product_match_count} matches")
    except Exception as e:
        print(f"[Scheduler] Briefing job error: {e}")
    finally:
        db.close()


def _admin_alert(text: str, key: str):
    """시스템 이상을 대표님 Slack DM 으로 (이벤트 system_alert 가 켜져 있을 때만, 같은 종류는 하루 1번).

    알림 실패가 작업을 죽이면 안 되므로 모든 예외를 삼킨다.
    """
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from app.services.slack_notify import notify_admin
        day = datetime.now(ZoneInfo("Asia/Seoul")).date()
        notify_admin(text, company_id=1, dedupe_key=f"system:{key}:{day}")
    except Exception as e:
        print(f"[Scheduler] admin alert error: {e}")


def _backup_job():
    from app.backup import run_backup
    try:
        result = run_backup()
        print(f"[Scheduler] Backup complete: {result}")
    except Exception as e:
        print(f"[Scheduler] Backup job error: {e}")
        _admin_alert(f"일일 백업 실패 — {type(e).__name__}: {e}"[:300], "backup")


def _cs_due_scan_job():
    """CS 처리 예정일 임박/초과 알림 스캔 (매시간)."""
    from app.database import SessionLocal
    from app.cs.notify import scan_due_notifications
    db = SessionLocal()
    try:
        n = scan_due_notifications(db)
        if n:
            print(f"[Scheduler] CS due-date notifications created: {n}")
    except Exception as e:
        print(f"[Scheduler] CS due-scan error: {e}")
    finally:
        db.close()


def _sheet_autosync_job():
    """통합시트 ↔ OS 자동 동기화. .env SHEET_AUTOSYNC=true 일 때만 등록된다."""
    from app.database import SessionLocal
    from app.services.sheet_autosync import run_once
    db = SessionLocal()
    try:
        r = run_once(db, trigger="auto")
        imp = (r.get("import") or {}).get("totals") or {}
        exp = (r.get("export") or {}).get("totals") or {}
        if imp.get("created") or imp.get("updated") or exp.get("appended") or exp.get("updated"):
            print(f"[Scheduler] Sheet sync — 시트→OS 신규 {imp.get('created', 0)}"
                  f"/수정 {imp.get('updated', 0)} · OS→시트 추가 {exp.get('appended', 0)}"
                  f"/수정 {exp.get('updated', 0)}")
        if not r.get("ok"):
            err = (r.get('import') or {}).get('error') or (r.get('export') or {}).get('error')
            print(f"[Scheduler] Sheet sync NOT OK: {err}")
            _admin_alert(f"통합시트 동기화 실패 — {err}"[:300], "sheet_sync")
    except Exception as e:
        print(f"[Scheduler] Sheet sync error: {e}")
        _admin_alert(f"통합시트 동기화 오류 — {type(e).__name__}: {e}"[:300], "sheet_sync")
    finally:
        db.close()


def _influencer_enrich_job():
    """인플루언서 인스타 프로필 수집. 하루 1회, 소량씩 (차단 방지)."""
    from app.database import SessionLocal
    from app.config import settings
    from app.services.influencer_enrich import enrich_batch
    db = SessionLocal()
    try:
        rep = enrich_batch(db, limit=settings.influencer_enrich_limit)
        print(f"[Scheduler] Influencer enrich — 수집 {rep['updated']} · 실패 {rep['failed']} "
              f"· 남은 대기 {rep['remaining']}")
        if rep.get("error"):
            print(f"[Scheduler] Influencer enrich NOT OK: {rep['error']}")
    except Exception as e:
        print(f"[Scheduler] Influencer enrich error: {e}")
    finally:
        db.close()


def _campaign_alert_job():
    """공구 아침 보고. Slack 앱(이벤트 campaign_digest 켜짐 + 토큰)이면 02 채널로, 아니면 기존 웹훅.

    둘 다 보내지 않는다 — 같은 보고가 두 번 오지 않게.
    """
    from app.database import SessionLocal
    from app.config import settings
    from app.services import slack_notify
    db = SessionLocal()
    try:
        via_slack = slack_notify.is_enabled("campaign_digest") and bool(settings.slack_bot_token)
        if via_slack:
            from app.services.campaign_slack import send_digest
            r = send_digest(db, company_id=1)
        elif settings.campaign_alert and settings.alert_webhook_url:
            from app.services.webhook_notify import send_campaign_digest
            r = send_campaign_digest(db)
        else:
            print("[Scheduler] Campaign alert — Slack 토큰 없음·웹훅 보고 꺼짐, 발송 경로 없음")
            return
        if r.get("sent"):
            print(f"[Scheduler] Campaign alert 발송 완료 ({'slack' if via_slack else 'webhook'}) — {r.get('counts')}")
        elif r.get("status") in ("mock", "duplicate"):
            print(f"[Scheduler] Campaign alert — {r.get('reason')}")
        else:
            print(f"[Scheduler] Campaign alert NOT sent: {r.get('reason')}")
            if via_slack:
                _admin_alert(f"아침 공구 보고 발송 실패 — {r.get('reason')}"[:300], "campaign_digest")
    except Exception as e:
        print(f"[Scheduler] Campaign alert error: {e}")
        _admin_alert(f"아침 공구 보고 오류 — {type(e).__name__}: {e}"[:300], "campaign_digest")
    finally:
        db.close()


def _campaign_slack_scan_job():
    """새 캠페인·일정 변경 → Slack 02 (10분마다). 등록 경로(화면·시트·엑셀)와 무관하게 잡는다."""
    from app.database import SessionLocal
    from app.services.campaign_slack import scan
    db = SessionLocal()
    try:
        out = scan(db, company_id=1)
        if any(out.get(k) for k in ("created", "created_batched", "schedule_changed", "schedule_batched", "failed")):
            print(f"[Scheduler] Campaign Slack scan — {out}")
        if out.get("failed"):
            _admin_alert(f"캠페인 Slack 알림 {out['failed']}건 발송 실패 — 봇 초대·토큰·채널 설정 확인", "campaign_scan")
    except Exception as e:
        print(f"[Scheduler] Campaign Slack scan error: {e}")
    finally:
        db.close()


def start_scheduler():
    _scheduler.add_job(
        _daily_briefing_job,
        trigger="cron",
        hour=9, minute=0,
        id="daily_trend_briefing",
        replace_existing=True,
    )
    # 매일 새벽 2시 DB + 이미지 S3 백업
    _scheduler.add_job(
        _backup_job,
        trigger="cron",
        hour=2, minute=0,
        id="daily_s3_backup",
        replace_existing=True,
    )
    # 매시간 CS 예정일 임박/초과 알림 스캔
    _scheduler.add_job(
        _cs_due_scan_job,
        trigger="cron",
        minute=5,
        id="cs_due_scan",
        replace_existing=True,
    )
    # 통합시트 자동 동기화 (설정으로 켜야 등록됨)
    extra = ""
    from app.config import settings as _cfg
    if _cfg.sheet_autosync and _cfg.integrated_sheet_id:
        minutes = max(5, int(_cfg.sheet_autosync_minutes or 10))
        _scheduler.add_job(
            _sheet_autosync_job,
            trigger="interval",
            minutes=minutes,
            id="sheet_autosync",
            replace_existing=True,
            max_instances=1,     # 앞 실행이 안 끝났으면 건너뛴다 (시트를 동시에 만지면 안 됨)
            coalesce=True,       # 밀린 실행은 하나로 합친다
        )
        extra = f" | sheet sync every {minutes}m"

    # 인플루언서 인스타 프로필 수집 (새벽 4시, 소량씩)
    if _cfg.influencer_enrich:
        _scheduler.add_job(
            _influencer_enrich_job,
            trigger="cron",
            hour=4, minute=30,
            id="influencer_enrich",
            replace_existing=True,
            max_instances=1,
        )
        extra += f" | influencer enrich 04:30 ({_cfg.influencer_enrich_limit}/day)"

    from app.services import slack_notify as _sn
    # 공구 아침 보고 — 기존 웹훅 또는 Slack 앱 (둘 다 없으면 등록 자체를 안 한다)
    if (_cfg.campaign_alert and _cfg.alert_webhook_url) or _sn.is_enabled("campaign_digest"):
        hour = max(0, min(23, int(_cfg.campaign_alert_hour or 8)))
        _scheduler.add_job(
            _campaign_alert_job,
            trigger="cron",
            hour=hour, minute=0,
            id="campaign_alert",
            replace_existing=True,
            max_instances=1,
        )
        extra += f" | campaign alert {hour:02d}:00"

    # 새 캠페인·일정 변경 → Slack (이벤트를 켰을 때만)
    # 토큰도 없고 mock 도 아니면 매번 실패만 쌓이므로 등록하지 않는다
    if (_sn.is_enabled("campaign_created") or _sn.is_enabled("campaign_schedule_changed")) \
            and (_cfg.slack_bot_token or _cfg.alert_mock):
        _scheduler.add_job(
            _campaign_slack_scan_job,
            trigger="interval",
            minutes=10,
            id="campaign_slack_scan",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        extra += " | campaign slack scan 10m"

    _scheduler.start()
    print("[Scheduler] Started — trend briefing 09:00 KST | S3 backup 02:00 KST | "
          "CS due-scan hourly" + extra)


def stop_scheduler():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
