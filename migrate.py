"""
Phase 2 migration: safely adds new columns to existing tables.
Safe to run multiple times (silently skips already-existing columns).

    uv run python migrate.py
"""
from app.database import engine, init_db
from sqlalchemy import text


def _add_column(conn, table: str, col_def: str):
    try:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_def}"))
        print(f"  + {table}.{col_def.split()[0]}")
    except Exception:
        pass  # column already exists


def migrate():
    # Create any brand-new tables (settlement, trend_items)
    init_db()

    with engine.connect() as conn:
        # --- products ---
        _add_column(conn, "products", "product_image VARCHAR(500)")
        _add_column(conn, "products", "set_options JSON")
        _add_column(conn, "products", "positioning TEXT")
        _add_column(conn, "products", "usage_scenes TEXT")
        _add_column(conn, "products", "recommended_inf_categories JSON")
        _add_column(conn, "products", "categories JSON")
        _add_column(conn, "products", "group_buy_guideline TEXT")

        # --- influencers ---
        _add_column(conn, "influencers", "profile_image VARCHAR(500)")

        conn.commit()

    print("Migration complete.")


if __name__ == "__main__":
    migrate()
