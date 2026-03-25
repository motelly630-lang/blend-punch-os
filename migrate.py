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
        _add_column(conn, "campaigns", "product_name_manual VARCHAR(300)")
        _add_column(conn, "campaigns", "brand_name_manual VARCHAR(200)")
        _add_column(conn, "campaigns", "category_manual VARCHAR(100)")
        _add_column(conn, "campaigns", "seller_type VARCHAR(30)")

        # --- settlements ---
        _add_column(conn, "settlements", "vat_amount FLOAT DEFAULT 0")

        # --- sales_pages (Commerce Upgrade) ---
        _add_column(conn, "sales_pages", "editor_content TEXT")
        _add_column(conn, "sales_pages", "stock_quantity INTEGER")
        _add_column(conn, "sales_pages", "main_image VARCHAR(500)")
        _add_column(conn, "sales_pages", "extra_images JSON")
        _add_column(conn, "sales_pages", "options JSON")
        _add_column(conn, "sales_pages", "addon_products JSON")
        _add_column(conn, "sales_pages", "shipping_type VARCHAR(20) DEFAULT 'free'")
        _add_column(conn, "sales_pages", "shipping_cost FLOAT DEFAULT 0")
        _add_column(conn, "sales_pages", "carrier VARCHAR(50)")

        # --- orders (Commerce Upgrade) ---
        _add_column(conn, "orders", "addon_items JSON")

        # --- trend_briefings (Trend Engine) ---
        # Table is created by init_db(); no extra columns needed

        # --- outreach_logs (Outreach & Sample Tracking) ---
        # Table is created by init_db(); no extra columns needed

        # --- crm_pipelines / sample_logs (CRM Pipeline) ---
        # Tables are created by init_db(); no extra columns needed

        # --- products (AI Assistant) ---
        _add_column(conn, "products", "product_type VARCHAR(1) DEFAULT 'A'")

        # --- products (Data Completeness) ---
        _add_column(conn, "products", "is_complete INTEGER DEFAULT 0")
        _add_column(conn, "products", "missing_fields JSON")

        # ── SQLite Indexes (성능 최적화) ──────────────────────────────
        indexes = [
            ("idx_products_brand",       "products",    "brand"),
            ("idx_products_category",    "products",    "category"),
            ("idx_products_status",      "products",    "status"),
            ("idx_products_visibility",  "products",    "visibility_status"),
            ("idx_influencers_status",   "influencers", "status"),
            ("idx_influencers_platform", "influencers", "platform"),
            ("idx_campaigns_status",     "campaigns",   "status"),
            ("idx_campaigns_influencer", "campaigns",   "influencer_id"),
            ("idx_campaigns_product",    "campaigns",   "product_id"),
            ("idx_settlements_status",   "settlements", "status"),
            ("idx_settlements_influencer","settlements","influencer_id"),
        ]
        for idx_name, table, col in indexes:
            try:
                conn.execute(text(
                    f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({col})"
                ))
                print(f"  + index {idx_name}")
            except Exception:
                pass

        conn.commit()

    print("Migration complete.")


if __name__ == "__main__":
    migrate()
