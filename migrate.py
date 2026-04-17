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
        _add_column(conn, "products", "notes TEXT")

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
        _add_column(conn, "settlements", "bank_name_snapshot VARCHAR(100)")
        _add_column(conn, "settlements", "account_number_snapshot VARCHAR(100)")
        _add_column(conn, "settlements", "account_holder_snapshot VARCHAR(100)")

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

        # --- trend_items (Claw 연동) ---
        _add_column(conn, "trend_items", "source VARCHAR(50)")
        _add_column(conn, "trend_items", "brands JSON")
        _add_column(conn, "trend_items", "season VARCHAR(20)")
        _add_column(conn, "trend_items", "source_name VARCHAR(100)")

        # --- outreach_logs (Outreach & Sample Tracking) ---
        # Table is created by init_db(); no extra columns needed

        # --- crm_pipelines / sample_logs (CRM Pipeline) ---
        # Tables are created by init_db(); no extra columns needed

        # --- products (AI Assistant) ---
        _add_column(conn, "products", "product_type VARCHAR(1) DEFAULT 'A'")

        # --- products (Data Completeness) ---
        _add_column(conn, "products", "is_complete INTEGER DEFAULT 0")
        _add_column(conn, "products", "missing_fields JSON")

        # --- companies / company_features (기능 플래그 + 멀티테넌트) ---
        _add_column(conn, "companies", "name VARCHAR(200)")
        _add_column(conn, "companies", "plan VARCHAR(20) DEFAULT 'pro'")
        _add_column(conn, "companies", "is_active INTEGER DEFAULT 1")
        _add_column(conn, "companies", "created_at DATETIME")
        _add_column(conn, "companies", "updated_at DATETIME")
        _add_column(conn, "company_features", "enabled INTEGER DEFAULT 1")
        _add_column(conn, "company_features", "updated_at DATETIME")
        # --- users: company 소속 추가 ---
        _add_column(conn, "users", "company_id INTEGER REFERENCES companies(id)")

        # --- business_infos (전자상거래 법적 필수 정보) ---
        # 테이블은 init_db()가 생성; 컬럼 누락분만 보완
        _add_column(conn, "business_infos", "company_name VARCHAR(200)")
        _add_column(conn, "business_infos", "ceo_name VARCHAR(100)")
        _add_column(conn, "business_infos", "biz_reg_number VARCHAR(50)")
        _add_column(conn, "business_infos", "mail_order_number VARCHAR(100)")
        _add_column(conn, "business_infos", "address TEXT")
        _add_column(conn, "business_infos", "phone VARCHAR(50)")
        _add_column(conn, "business_infos", "email VARCHAR(200)")
        _add_column(conn, "business_infos", "shipping_guide TEXT")
        _add_column(conn, "business_infos", "return_policy TEXT")
        _add_column(conn, "business_infos", "payment_guide TEXT")

        # ── 멀티테넌트: company_id 컬럼 추가 ────────────────────────────────────────
        for tbl in [
            "products", "influencers", "campaigns", "proposals",
            "brands", "sellers", "outreach_logs", "crm_pipelines",
            "sample_logs", "group_buy_applications", "playbooks",
            "orders", "sales_pages",
            "settlements", "trend_items", "trend_briefings",
        ]:
            _add_column(conn, tbl, "company_id INTEGER DEFAULT 1 REFERENCES companies(id)")

        # 기존 데이터 전부 company_id=1 (블렌드펀치) 로 설정
        for tbl in [
            "products", "influencers", "campaigns", "proposals",
            "brands", "sellers", "outreach_logs", "crm_pipelines",
            "sample_logs", "group_buy_applications", "playbooks",
            "orders", "sales_pages",
            "settlements", "trend_items", "trend_briefings",
        ]:
            try:
                conn.execute(text(f"UPDATE {tbl} SET company_id = 1 WHERE company_id IS NULL"))
                print(f"  migrated {tbl}.company_id → 1")
            except Exception:
                pass

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

        # ── Outreach KPI Upgrade ─────────────────────────────────────────────────
        _add_column(conn, "outreach_logs", "sent_at DATETIME")
        _add_column(conn, "outreach_logs", "response_at DATETIME")
        _add_column(conn, "outreach_logs", "status_detail TEXT")
        _add_column(conn, "outreach_logs", "campaign_id VARCHAR(36) REFERENCES campaigns(id)")

        # ── Commerce Upgrade — OS-SHOP 연결 ─────────────────────────────────────
        _add_column(conn, "sales_pages", "campaign_id VARCHAR(36) REFERENCES campaigns(id)")
        _add_column(conn, "sales_pages", "is_published INTEGER DEFAULT 0")
        _add_column(conn, "products",    "is_published INTEGER DEFAULT 0")
        _add_column(conn, "users",       "subscription INTEGER DEFAULT 0")

        # ── 소프트 삭제 (archive) 컬럼 추가 ──────────────────────────────────────
        for tbl in ["products", "brands", "influencers"]:
            _add_column(conn, tbl, "is_archived INTEGER DEFAULT 0")

        # ── AI 에이전트 파이프라인 컬럼 ──────────────────────────────────────────
        _add_column(conn, "products", "review_status VARCHAR(30) DEFAULT 'draft'")
        _add_column(conn, "products", "priority_score FLOAT")
        _add_column(conn, "brands",   "review_status VARCHAR(30) DEFAULT 'draft'")
        _add_column(conn, "brands",   "priority_score FLOAT")

        # ── 사용자 이메일 인증 / 비밀번호 재설정 ──────────────────────────────
        _add_column(conn, "users", "email_verified INTEGER DEFAULT 1")   # 기존 계정은 인증됨 처리
        _add_column(conn, "users", "verify_token VARCHAR(100)")
        _add_column(conn, "users", "verify_token_exp DATETIME")
        _add_column(conn, "users", "reset_token VARCHAR(100)")
        _add_column(conn, "users", "reset_token_exp DATETIME")

        # ── AI 에이전트 v2 — Decision Engine / Memory / Trigger ──────────────
        _add_column(conn, "agent_logs", "score FLOAT")
        _add_column(conn, "agent_logs", "confidence FLOAT")
        _add_column(conn, "agent_logs", "risk_level VARCHAR(10)")

        # products: pending_review 상태
        # pipeline_jobs, human_review_queue, agent_memory, trigger_logs → init_db() 생성

        # ── Transaction 레이어 (손익 연동) ────────────────────────────────────────
        # 테이블은 init_db()가 생성 (Transaction 모델이 Base에 등록됨)
        try:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_transactions_company ON transactions(company_id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_transactions_campaign ON transactions(campaign_id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions(type)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(transaction_date)"
            ))
            print("  + indexes for transactions")
        except Exception:
            pass

        conn.commit()

    print("Migration complete.")


if __name__ == "__main__":
    migrate()
