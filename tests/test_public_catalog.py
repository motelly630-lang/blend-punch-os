"""공개 카탈로그(/public/products) 첫 화면 — 숫자·진열 줄이 공개 조건 안에서만 계산되는지."""
from tests import _env  # noqa: F401  (app import 전에 격리 환경)
from tests._env import SessionLocal, client_for, seed_companies, uid

import unittest

from app.models import Product
from app.routers import public


def _product(db, **kw):
    base = dict(name=f"가상 제품 {uid()}", brand=f"가상브랜드{uid()}", category="스킨케어", status="active",
                visibility_status="active", company_id=1, consumer_price=30000, groupbuy_price=24000,
                discount_rate=0.2, seller_commission_rate=0.15, sample_type="무상")
    base.update(kw)
    p = Product(**base)
    db.add(p)
    db.commit()
    return p


class PublicCatalogStatsTests(unittest.TestCase):
    def setUp(self):
        seed_companies()
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def stats(self):
        return public._catalog_stats(self.db, 0)

    def test_hidden_other_company_archived_inactive_not_counted(self):
        before = self.stats()
        _product(self.db, company_id=2)                       # 다른 회사
        _product(self.db, visibility_status="hidden")         # 숨김
        _product(self.db, is_archived=True)                   # 보관
        _product(self.db, status="inactive")                  # 비활성
        self.assertEqual(self.stats(), before, "공개 조건 밖 제품이 숫자에 섞이면 안 됨")
        _product(self.db)
        after = self.stats()
        self.assertEqual(after["products"], before["products"] + 1)
        self.assertEqual(after["new_month"], before["new_month"] + 1)
        self.assertEqual(after["sample"], before["sample"] + 1)

    def test_category_counts_only_public(self):
        cat = f"가상카테고리{uid()}"
        _product(self.db, category=cat)
        _product(self.db, category=cat, company_id=2)
        _product(self.db, category=cat, visibility_status="hidden")
        counts = dict(public._category_counts(self.db))
        self.assertEqual(counts.get(cat), 1)

    def test_landing_renders_without_private_fields(self):
        secret_price = 12345
        p = _product(self.db, supplier_price=secret_price, internal_notes="내부메모-노출금지",
                     product_image="/static/og-image.png")
        _product(self.db, company_id=2, name="타사 제품 노출금지")
        r = client_for().get("/public/products")
        self.assertEqual(r.status_code, 200)
        self.assertIn("공구 가능 제품", r.text)
        self.assertIn(p.name, r.text, "새 제품이 첫 화면 진열에 보여야")
        self.assertNotIn("12,345", r.text)
        self.assertNotIn("내부메모-노출금지", r.text)
        self.assertNotIn("타사 제품 노출금지", r.text)

    def test_filtered_pages_render(self):
        _product(self.db, category="식품/음료")
        c = client_for()
        for url in ("/public/products?category=식품/음료", "/public/products?sort=commission",
                    "/public/products?sample=1", "/public/products?q=가상", "/public/products?sort=price_asc&page=2"):
            self.assertEqual(c.get(url).status_code, 200, url)



class BrandPageCardTests(unittest.TestCase):
    def test_new_cards_and_safe_apply_button(self):
        seed_companies()
        db = SessionLocal()
        brand = f"카드브랜드{uid()}"
        evil = "따옴표');window.__x=1;// 제품"
        pid = _product(db, brand=brand, name=evil, discount_rate=0.2).id
        db.close()
        html = client_for().get(f"/public/products/brand/{brand}").text
        self.assertIn(f'data-apply-id="{pid}"', html)
        self.assertIn("openApply(this.dataset.applyId, this.dataset.applyName)", html)
        self.assertNotIn("openApply('", html, "제품 이름을 스크립트 문자열에 넣으면 안 됨")
        self.assertIn("20%", html)          # 할인율 배지
        self.assertIn("무상 샘플", html)     # 새 카드 배지


if __name__ == "__main__":
    unittest.main()
