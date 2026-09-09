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


def _backup_job():
    from app.backup import run_backup
    try:
        result = run_backup()
        print(f"[Scheduler] Backup complete: {result}")
    except Exception as e:
        print(f"[Scheduler] Backup job error: {e}")


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
            print(f"[Scheduler] Sheet sync NOT OK: "
                  f"{(r.get('import') or {}).get('error') or (r.get('export') or {}).get('error')}")
    except Exception as e:
        print(f"[Scheduler] Sheet sync error: {e}")
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
    """공구 알림 웹훅 발송. 알릴 게 없는 날은 발송 생략."""
    from app.database import SessionLocal
    from app.services.webhook_notify import send_campaign_digest
    db = SessionLocal()
    try:
        r = send_campaign_digest(db)
        if r.get("skipped"):
            print("[Scheduler] Campaign alert — 알릴 공구 없음, 발송 생략")
        elif r.get("sent"):
            print(f"[Scheduler] Campaign alert 발송 완료 — {r.get('counts')}")
        else:
            print(f"[Scheduler] Campaign alert NOT sent: {r.get('reason')}")
    except Exception as e:
        print(f"[Scheduler] Campaign alert error: {e}")
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

    # 공구 알림 웹훅 발송 (웹훅 URL 없으면 등록 자체를 안 한다)
    if _cfg.campaign_alert and _cfg.alert_webhook_url:
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

    _scheduler.start()
    print("[Scheduler] Started — trend briefing 09:00 KST | S3 backup 02:00 KST | "
          "CS due-scan hourly" + extra)


def stop_scheduler():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
