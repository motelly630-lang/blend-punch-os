import shutil
import logging
import os
from pathlib import Path
from datetime import datetime

BACKUP_DIR = Path("backups")
DB_PATH = Path("blendpunch.db")
UPLOADS_DIR = Path("static/uploads")
KEEP_DAYS = 7

logger = logging.getLogger(__name__)


def run_backup() -> Path | None:
    """DB 백업 → 로컬 저장 + S3 업로드."""
    if not DB_PATH.exists():
        return None
    BACKUP_DIR.mkdir(exist_ok=True)
    dest = BACKUP_DIR / f"backup_{datetime.now().strftime('%Y_%m_%d_%H%M')}.db"
    shutil.copy2(DB_PATH, dest)
    logger.info(f"[Backup] DB 로컬 저장 → {dest} ({dest.stat().st_size // 1024}KB)")
    _rotate()

    # S3 업로드 시도
    s3_ok = _upload_db_to_s3(dest)
    if s3_ok:
        _sync_uploads_to_s3()

    return dest


def _get_s3_client():
    """boto3 S3 클라이언트 반환. 설정 없으면 None."""
    try:
        from app.config import settings
        if not settings.aws_access_key_id or not settings.s3_backup_bucket:
            return None, None
        import boto3
        client = boto3.client(
            "s3",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        return client, settings.s3_backup_bucket
    except Exception as e:
        logger.warning(f"[Backup] S3 클라이언트 생성 실패: {e}")
        return None, None


def _upload_db_to_s3(local_path: Path) -> bool:
    """DB 파일을 S3에 업로드."""
    client, bucket = _get_s3_client()
    if not client:
        return False
    try:
        s3_key = f"db/{local_path.name}"
        client.upload_file(str(local_path), bucket, s3_key)
        # 최신 버전은 항상 latest.db로도 저장
        client.upload_file(str(local_path), bucket, "db/latest.db")
        logger.info(f"[Backup] S3 DB 업로드 완료 → s3://{bucket}/{s3_key}")
        _cleanup_old_s3_db(client, bucket)
        return True
    except Exception as e:
        logger.error(f"[Backup] S3 DB 업로드 실패: {e}")
        return False


def _sync_uploads_to_s3():
    """static/uploads/ 폴더를 S3에 동기화 (새 파일만)."""
    client, bucket = _get_s3_client()
    if not client or not UPLOADS_DIR.exists():
        return

    # 이미 S3에 있는 키 목록 캐싱
    try:
        existing = set()
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix="uploads/"):
            for obj in page.get("Contents", []):
                existing.add(obj["Key"])

        uploaded = 0
        for file_path in UPLOADS_DIR.rglob("*"):
            if not file_path.is_file():
                continue
            s3_key = "uploads/" + str(file_path.relative_to(UPLOADS_DIR))
            if s3_key not in existing:
                client.upload_file(str(file_path), bucket, s3_key)
                uploaded += 1

        if uploaded:
            logger.info(f"[Backup] S3 이미지 동기화 완료 — {uploaded}개 업로드")
        else:
            logger.info("[Backup] S3 이미지 동기화 — 신규 파일 없음")
    except Exception as e:
        logger.error(f"[Backup] S3 이미지 동기화 실패: {e}")


def _cleanup_old_s3_db(client, bucket: str, keep: int = 14):
    """S3에서 오래된 DB 백업 삭제 (최근 14개 유지)."""
    try:
        response = client.list_objects_v2(Bucket=bucket, Prefix="db/backup_")
        objects = sorted(
            response.get("Contents", []),
            key=lambda x: x["LastModified"]
        )
        for old in objects[:-keep]:
            client.delete_object(Bucket=bucket, Key=old["Key"])
            logger.info(f"[Backup] S3 구 백업 삭제: {old['Key']}")
    except Exception as e:
        logger.warning(f"[Backup] S3 구 백업 정리 실패: {e}")


def restore_from_s3(target_filename: str = "latest.db") -> bool:
    """S3에서 DB를 복원. target_filename = 'latest.db' 또는 'backup_YYYY_MM_DD_HHMM.db'"""
    client, bucket = _get_s3_client()
    if not client:
        logger.error("[Restore] S3 설정 없음 — 복원 불가")
        return False
    try:
        s3_key = f"db/{target_filename}"
        restore_path = Path(f"blendpunch_restored_{datetime.now().strftime('%Y%m%d_%H%M')}.db")
        client.download_file(bucket, s3_key, str(restore_path))
        logger.info(f"[Restore] S3에서 복원 완료 → {restore_path}")
        logger.info(f"[Restore] 복원 완료 후 수동으로: mv {restore_path} blendpunch.db 실행 필요")
        return True
    except Exception as e:
        logger.error(f"[Restore] S3 복원 실패: {e}")
        return False


def _rotate():
    """로컬 백업 파일 7일치만 보관."""
    backups = sorted(BACKUP_DIR.glob("backup_*.db"), key=lambda p: p.stat().st_mtime)
    for old in backups[:-KEEP_DAYS]:
        old.unlink()
        logger.info(f"[Backup] 로컬 구 백업 삭제: {old.name}")
