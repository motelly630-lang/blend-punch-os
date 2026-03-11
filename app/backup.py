import shutil
from pathlib import Path
from datetime import datetime

BACKUP_DIR = Path("backups")
DB_PATH = Path("blendpunch.db")


def run_backup() -> Path | None:
    """Copy blendpunch.db to backups/backup_YYYY_MM_DD.db"""
    if not DB_PATH.exists():
        return None
    BACKUP_DIR.mkdir(exist_ok=True)
    dest = BACKUP_DIR / f"backup_{datetime.now().strftime('%Y_%m_%d')}.db"
    shutil.copy2(DB_PATH, dest)
    return dest


def upload_to_cloud(backup_path: Path) -> bool:
    """TODO: implement S3 upload when cloud storage is configured."""
    return False
