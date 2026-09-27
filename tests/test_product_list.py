"""내부 제품 관리 목록(/products) — 빈칸 요약·필터가 회사 범위 안에서만 동작하는지."""
from tests import _env  # noqa: F401  (app import 전에 격리 환경)
from tests._env import SessionLocal, client_for, make_user, uid

import re
import unittest

from app.models import Product


def _product(db, **kw):
    base = dict(name=f"목록시험 {uid()}", brand=f"목록브랜드{uid()}", category="스킨케어", status="active",
                company_id=1, product_image="/static/og-image.png", groupbuy_price=20000,
                seller_commission_rate=0.1, unique_selling_point="소개")
    base.update(kw)
    p = Product(**base)
    db.add(p)
    db.commit()
    return p


def _count(html, label):
    m = re.search(re.escape(label) + r'\s*<span[^>]*>(\d+)</span>', html)
    return int(m.group(1)) if m else None


class ProductListTests(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.c1 = client_for(make_user("admin", company_id=1))

    def tearDown(self):
        self.db.close()

    def test_default_shows_products_not_only_brands(self):
        p = _product(self.db)
        r = self.c1.get("/products")
        self.assertEqual(r.status_code, 200)
        self.assertIn(p.name, r.text, "첫 화면에서 제품이 바로 보여야")

    def test_missing_counts_scope(self):
        before = _count(self.c1.get("/products").text, "사진 없음")
        _product(self.db, product_image=None, company_id=2)          # 다른 회사
        _product(self.db, product_image="", is_archived=True)        # 보관
        self.assertEqual(_count(self.c1.get("/products").text, "사진 없음"), before)
        mine = _product(self.db, product_image=None)
        self.assertEqual(_count(self.c1.get("/products").text, "사진 없음"), before + 1)
        r = self.c1.get("/products?missing=image")
        self.assertIn(mine.name, r.text)

    def test_missing_filter_lists_only_matching_own_products(self):
        tag = uid()
        no_price = _product(self.db, name=f"공구가없음 {tag}", groupbuy_price=0)
        full = _product(self.db, name=f"다채움 {tag}")
        other = _product(self.db, name=f"타사공구가없음 {tag}", groupbuy_price=None, company_id=2)
        r = self.c1.get(f"/products?missing=price&q={tag}&view=list")
        self.assertEqual(r.status_code, 200)
        self.assertIn(no_price.name, r.text)
        self.assertNotIn(full.name, r.text)
        self.assertNotIn(other.name, r.text)

    def test_other_company_user_does_not_see_products(self):
        p = _product(self.db, name=f"회사1전용 {uid()}")
        c2 = client_for(make_user("admin", company_id=2))
        self.assertNotIn(p.name, c2.get("/products").text)

    def test_bad_params_are_safe(self):
        for url in ("/products?missing=bogus", "/products?tab=zzz", "/products?view=zzz",
                    "/products?page=999", "/products?page=-3", "/products?tab=brands"):
            self.assertEqual(self.c1.get(url).status_code, 200, url)



class QuickFillTests(unittest.TestCase):
    """빠르게 채우기 화면 + 칸 저장(PATCH /products/{id}/field)의 회사 범위."""

    def setUp(self):
        self.db = SessionLocal()
        self.c1 = client_for(make_user("admin", company_id=1))

    def tearDown(self):
        self.db.close()

    def test_fill_view_renders_inputs_for_own_missing_products(self):
        tag = uid()
        mine = _product(self.db, name=f"채우기 {tag}", product_image=None)
        other = _product(self.db, name=f"타사채우기 {tag}", product_image=None, company_id=2)
        r = self.c1.get(f"/products?view=fill&missing=image&q={tag}")
        self.assertEqual(r.status_code, 200)
        self.assertIn(f'data-pid="{mine.id}"', r.text)
        self.assertNotIn(other.id, r.text)
        self.assertIn('data-field="groupbuy_price"', r.text)

    def test_field_patch_saves_and_is_company_scoped(self):
        p = _product(self.db, groupbuy_price=0, seller_commission_rate=0)
        r = self.c1.patch(f"/products/{p.id}/field", json={"field": "groupbuy_price", "value": "15000"})
        self.assertTrue(r.json()["ok"])
        r = self.c1.patch(f"/products/{p.id}/field", json={"field": "seller_commission_rate", "value": "12.5"})
        self.assertTrue(r.json()["ok"])
        c2 = client_for(make_user("admin", company_id=2))
        r = c2.patch(f"/products/{p.id}/field", json={"field": "groupbuy_price", "value": "1"})
        self.assertEqual(r.status_code, 404, "다른 회사 제품은 고칠 수 없어야")
        self.db.expire_all()
        got = self.db.get(Product, p.id)
        self.assertEqual((got.groupbuy_price, got.seller_commission_rate), (15000.0, 0.125))


if __name__ == "__main__":
    unittest.main()
