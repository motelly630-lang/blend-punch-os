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
    _scheduler.start()
    print("[Scheduler] Started — trend briefing 09:00 KST | S3 backup 02:00 KST")


def stop_scheduler():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
