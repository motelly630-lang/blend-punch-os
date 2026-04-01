"""
migrate_uploads_to_s3.py — 기존 로컬 이미지를 S3로 마이그레이션

사용법:
  uv run python migrate_uploads_to_s3.py

수행 작업:
  1. static/uploads/, static/brands/ 의 모든 이미지를 S3에 업로드
  2. DB의 /static/... 경로를 S3 URL로 업데이트
  3. 이미 S3 URL인 경우 스킵
"""
import sys
from pathlib import Path

# ── S3 클라이언트 ──────────────────────────────────────
def get_s3_info():
    from app.config import settings
    if not settings.aws_access_key_id:
        print("❌ AWS_ACCESS_KEY_ID 미설정")
        sys.exit(1)
    bucket = settings.s3_assets_bucket or settings.s3_backup_bucket
    if not bucket:
        print("❌ S3_ASSETS_BUCKET 또는 S3_BACKUP_BUCKET 미설정")
        sys.exit(1)
    import boto3
    client = boto3.client(
        "s3",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    return client, bucket, settings.aws_region


def s3_public_url(bucket, region, key):
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"


# ── 로컬 경로 → S3 key 변환 ───────────────────────────
_PATH_MAP = {
    "static/uploads/products":   "uploads/products",
    "static/uploads/influencers": "uploads/influencers",
    "static/uploads/sales_pages": "uploads/sales_pages",
    "static/brands":             "uploads/brands",
    "static/cache":              "uploads/cache",
}

def local_path_to_s3_key(local_path: str) -> str | None:
    """'/static/uploads/products/abc.webp' → 'uploads/products/abc.webp'"""
    p = local_path.lstrip("/")
    for local_prefix, s3_prefix in _PATH_MAP.items():
        if p.startswith(local_prefix + "/"):
            filename = p[len(local_prefix) + 1:]
            return f"{s3_prefix}/{filename}"
    return None


# ── 파일 업로드 ────────────────────────────────────────
def upload_files(client, bucket, region) -> dict[str, str]:
    """로컬 이미지 전체를 S3에 올리고, local_path → s3_url 매핑 반환."""
    mapping = {}
    dirs = [
        (Path("static/uploads"), "uploads"),
        (Path("static/brands"),  "uploads/brands"),
        (Path("static/cache"),   "uploads/cache"),
    ]
    total = uploaded = skipped = 0

    for base_dir, s3_base in dirs:
        if not base_dir.exists():
            continue
        for file_path in base_dir.rglob("*"):
            if not file_path.is_file():
                continue
            total += 1
            rel = file_path.relative_to(base_dir)
            s3_key = f"{s3_base}/{rel}"
            local_url = f"/{file_path}"

            # 이미 S3에 있는지 확인
            try:
                client.head_object(Bucket=bucket, Key=s3_key)
                s3_url = s3_public_url(bucket, region, s3_key)
                mapping[local_url] = s3_url
                skipped += 1
                continue
            except Exception:
                pass

            # 업로드
            try:
                suffix = file_path.suffix.lower()
                ct_map = {".webp": "image/webp", ".png": "image/png",
                          ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"}
                content_type = ct_map.get(suffix, "application/octet-stream")
                client.upload_file(str(file_path), bucket, s3_key,
                                   ExtraArgs={"ContentType": content_type})
                s3_url = s3_public_url(bucket, region, s3_key)
                mapping[local_url] = s3_url
                uploaded += 1
                print(f"  ✓ {local_url} → {s3_url}")
            except Exception as e:
                print(f"  ✗ {file_path}: {e}")

    print(f"\n[파일 업로드] 총 {total}개 | 신규 {uploaded}개 | 이미 존재 {skipped}개")
    return mapping


# ── DB 업데이트 ────────────────────────────────────────
def update_db(mapping: dict[str, str]):
    """DB의 /static/... URL을 S3 URL로 교체."""
    from app.database import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    updated = 0

    # 업데이트 대상 테이블.컬럼
    columns = [
        ("products", "product_image"),
        ("influencers", "profile_image"),
        ("brands", "logo"),
        ("sales_pages", "main_image"),
        ("sales_pages", "extra_images"),  # JSON 컬럼
    ]

    for table, col in columns:
        try:
            rows = db.execute(text(
                f"SELECT id, {col} FROM {table} WHERE {col} IS NOT NULL AND {col} LIKE '/static/%'"
            )).fetchall()

            for row in rows:
                old_val = row[1]
                # extra_images는 JSON 배열 처리
                if col == "extra_images":
                    import json
                    try:
                        paths = json.loads(old_val)
                        new_paths = [mapping.get(p, p) for p in paths]
                        new_val = json.dumps(new_paths)
                    except Exception:
                        continue
                else:
                    new_val = mapping.get(old_val)
                    if not new_val or new_val == old_val:
                        continue

                db.execute(text(
                    f"UPDATE {table} SET {col} = :new WHERE id = :id"
                ), {"new": new_val, "id": row[0]})
                updated += 1
                print(f"  DB [{table}.{col}] id={row[0]}: {old_val[:50]}... → S3")

        except Exception as e:
            print(f"  ✗ {table}.{col}: {e}")

    db.commit()
    db.close()
    print(f"\n[DB 업데이트] {updated}개 레코드 업데이트 완료")


# ── 메인 ──────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("S3 이미지 마이그레이션 시작")
    print("=" * 60)

    client, bucket, region = get_s3_info()
    print(f"버킷: {bucket} ({region})\n")

    print("[1단계] 로컬 파일 → S3 업로드")
    mapping = upload_files(client, bucket, region)

    if mapping:
        print("\n[2단계] DB URL 업데이트")
        update_db(mapping)
    else:
        print("\n업로드된 파일 없음 — DB 업데이트 스킵")

    print("\n✅ 마이그레이션 완료!")
    print("\n⚠️  중요: S3 버킷에 퍼블릭 읽기 권한이 설정되어 있는지 확인하세요.")
    print(f"   버킷 URL: https://{bucket}.s3.{region}.amazonaws.com/")
