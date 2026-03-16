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
        # Phase 3
        _add_column(conn, "products", "visibility_status VARCHAR(20) DEFAULT 'active'")
        _add_column(conn, "products", "internal_notes TEXT")
        _add_column(conn, "products", "shipping_type VARCHAR(20)")
        _add_column(conn, "products", "shipping_cost FLOAT")
        _add_column(conn, "products", "carrier VARCHAR(50)")
        _add_column(conn, "products", "ship_origin VARCHAR(20)")
        _add_column(conn, "products", "dispatch_days VARCHAR(20)")
        _add_column(conn, "products", "sample_type VARCHAR(20)")
        _add_column(conn, "products", "sample_price FLOAT")

        # --- products (Phase 5) ---
        _add_column(conn, "products", "consumer_price FLOAT DEFAULT 0")
        _add_column(conn, "products", "lowest_price FLOAT DEFAULT 0")
        _add_column(conn, "products", "supplier_price FLOAT DEFAULT 0")
        _add_column(conn, "products", "groupbuy_price FLOAT DEFAULT 0")
        _add_column(conn, "products", "discount_rate FLOAT DEFAULT 0")
        _add_column(conn, "products", "seller_commission_rate FLOAT DEFAULT 0")
        _add_column(conn, "products", "vendor_commission_rate FLOAT DEFAULT 0")
        _add_column(conn, "products", "product_link TEXT")

        # --- influencers ---
        _add_column(conn, "influencers", "profile_image VARCHAR(500)")

        # --- influencers (Phase 5) ---
        _add_column(conn, "influencers", "has_campaign_history VARCHAR(5) DEFAULT 'false'")
        _add_column(conn, "influencers", "business_type VARCHAR(20)")
        _add_column(conn, "influencers", "bank_name VARCHAR(100)")
        _add_column(conn, "influencers", "account_number VARCHAR(100)")
        _add_column(conn, "influencers", "account_holder VARCHAR(100)")
        _add_column(conn, "influencers", "business_name VARCHAR(200)")
        _add_column(conn, "influencers", "business_registration_number VARCHAR(50)")
        _add_column(conn, "influencers", "representative_name VARCHAR(100)")
        _add_column(conn, "influencers", "business_address TEXT")
        _add_column(conn, "influencers", "tax_invoice_email VARCHAR(200)")
        _add_column(conn, "influencers", "legal_name VARCHAR(100)")
        _add_column(conn, "influencers", "resident_registration_number VARCHAR(30)")

        # --- campaigns (Phase 5) ---
        _add_column(conn, "campaigns", "unit_price FLOAT DEFAULT 0")
        _add_column(conn, "campaigns", "seller_commission_rate FLOAT DEFAULT 0")
        _add_column(conn, "campaigns", "vendor_commission_rate FLOAT DEFAULT 0")
        _add_column(conn, "campaigns", "seller_commission_amount FLOAT DEFAULT 0")
        _add_column(conn, "campaigns", "vendor_commission_amount FLOAT DEFAULT 0")
        _add_column(conn, "campaigns", "is_archived INTEGER DEFAULT 0")

        # --- settlements ---
        _add_column(conn, "settlements", "vat_amount FLOAT DEFAULT 0")

        # --- trend_briefings (Trend Engine) ---
        # Table is created by init_db(); no extra columns needed

        # --- outreach_logs (Outreach & Sample Tracking) ---
        # Table is created by init_db(); no extra columns needed

        conn.commit()

    print("Migration complete.")


if __name__ == "__main__":
    migrate()
