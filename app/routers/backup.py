"""
백업 관리 라우터 (슈퍼어드민 전용)

GET  /settings/backup          — 백업 이력 + 로컬 파일 목록
POST /settings/backup/run      — 수동 백업 실행
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.dependencies import require_super_admin
from app.models.user import User
from app.models.backup_log import BackupLog

router = APIRouter(prefix="/settings")
templates = Jinja2Templates(directory="app/templates")


@router.get("/backup")
def backup_list(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    logs = db.query(BackupLog).order_by(BackupLog.created_at.desc()).limit(30).all()
    from app.backup import list_local_backups
    from app.config import settings as cfg
    local_files = list_local_backups()
    return templates.TemplateResponse("backup/index.html", {
        "request": request,
        "active_page": "settings",
        "current_user": user,
        "logs": logs,
        "local_files": local_files,
        "s3_configured": bool(cfg.aws_access_key_id and cfg.s3_backup_bucket),
        "s3_bucket": cfg.s3_backup_bucket or "-",
    })


@router.post("/backup/run")
def backup_run(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    from app.backup import run_backup
    try:
        result = run_backup(trigger="manual", triggered_by=user.username)
        msg = f"백업 완료: {result.name}" if result else "백업 실패"
    except Exception as e:
        msg = f"백업 오류: {e}"
    return RedirectResponse(f"/settings/backup?msg={msg}", status_code=302)
