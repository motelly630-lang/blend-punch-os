"""
migrate_sqlite_to_postgres.py — SQLite → PostgreSQL 데이터 이전
"""
import sqlite3
import sys
from pathlib import Path
from sqlalchemy import text, inspect

SQLITE_PATH = "blendpunch.db"


def get_pg_engine():
    from app.config import settings
    from sqlalchemy import create_engine
    return create_engine(settings.database_url, echo=False)


def get_boolean_columns(pg_engine, table_name):
    inspector = inspect(pg_engine)
    try:
        cols = inspector.get_columns(table_name)
        return {c["name"] for c in cols if str(c["type"]).upper() == "BOOLEAN"}
    except Exception:
        return set()


def convert_row(row_dict, bool_cols):
    result = dict(row_dict)
    for col in bool_cols:
        if col in result and result[col] is not None:
            result[col] = bool(result[col])
    return result


def migrate():
    if not Path(SQLITE_PATH).exists():
        print(f"❌ SQLite DB 없음: {SQLITE_PATH}")
        sys.exit(1)

    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    pg_engine = get_pg_engine()

    tables = sqlite_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [t[0] for t in tables]

    print(f"총 {len(table_names)}개 테이블 이전 시작\n")

    success = fail = skip = 0

    # FK 체크 비활성화 후 전체 이전, 완료 후 재활성화
    with pg_engine.begin() as pg_conn:
        pg_conn.execute(text("SET session_replication_role = replica"))

        for table_name in table_names:
            rows = sqlite_conn.execute(f'SELECT * FROM "{table_name}"').fetchall()
            if not rows:
                print(f"  ⏭  {table_name}: 0개 (스킵)")
                skip += 1
                continue

            columns = list(rows[0].keys())
            col_str = ", ".join(f'"{c}"' for c in columns)
            placeholders = ", ".join(f":{c}" for c in columns)
            bool_cols = get_boolean_columns(pg_engine, table_name)

            try:
                pg_conn.execute(text(f'DELETE FROM "{table_name}"'))
                for row in rows:
                    data = convert_row(dict(row), bool_cols)
                    pg_conn.execute(
                        text(f'INSERT INTO "{table_name}" ({col_str}) VALUES ({placeholders})'),
                        data
                    )
                print(f"  ✓  {table_name}: {len(rows)}개")
                success += 1
            except Exception as e:
                print(f"  ✗  {table_name}: {e}")
                fail += 1

        pg_conn.execute(text("SET session_replication_role = DEFAULT"))

    sqlite_conn.close()
    print(f"\n완료 — 성공: {success}개, 실패: {fail}개, 스킵: {skip}개")
    if fail == 0:
        print("✅ 전체 이전 성공!")
    else:
        print("⚠️  일부 테이블 실패 — 위 오류 확인 필요")


if __name__ == "__main__":
    migrate()
