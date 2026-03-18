import shutil
import logging
from pathlib import Path
from datetime import datetime

BACKUP_DIR = Path("backups")
DB_PATH = Path("blendpunch.db")
KEEP_DAYS = 7

logger = logging.getLogger(__name__)


def run_backup() -> Path | None:
    """Copy blendpunch.db → backups/backup_YYYY_MM_DD.db, keep last 7 days."""
    if not DB_PATH.exists():
        return None
    BACKUP_DIR.mkdir(exist_ok=True)
    dest = BACKUP_DIR / f"backup_{datetime.now().strftime('%Y_%m_%d_%H%M')}.db"
    shutil.copy2(DB_PATH, dest)
    logger.info(f"[Backup] Saved → {dest} ({dest.stat().st_size // 1024}KB)")
    _rotate()
    return dest


def _rotate():
    """오래된 백업 파일 삭제 — 최근 KEEP_DAYS일치만 보관."""
    backups = sorted(BACKUP_DIR.glob("backup_*.db"), key=lambda p: p.stat().st_mtime)
    for old in backups[:-KEEP_DAYS]:
        old.unlink()
        logger.info(f"[Backup] Removed old backup: {old.name}")


def upload_to_cloud(backup_path: Path) -> bool:
    """TODO: Cloudflare R2 or S3 upload."""
    return False
