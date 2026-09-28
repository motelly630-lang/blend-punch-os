"""코덱스 카탈로그 검토(2026-09-28) 반영 — 서버 쪽 회귀 시험 (#1 브랜드 XSS, #3 범위, #6 배너, #7 최종 주소, 기록 실패 내성)."""
from tests import _env  # noqa: F401
from tests._env import SessionLocal, client_for, make_user, seed_companies, uid

import unittest
from unittest import mock

import httpx

from app.models import Product


def _p(db, **kw):
    base = dict(name=f"검토 {uid()}", brand=f"브랜드{uid()}", category="기타", company_id=1, status="active")
    base.update(kw)
    p = Product(**base)
    db.add(p)
    db.commit()
    return p


class Base(unittest.TestCase):
    def setUp(self):
        seed_companies()
        self.db = SessionLocal()
        self.c1 = client_for(make_user("admin", company_id=1))

    def tearDown(self):
        self.db.close()


class BrandCardXssTests(Base):
    def test_brand_name_not_inside_script(self):
        evil = f"';window.__brandXss=1;//{uid()}"
        _p(self.db, brand=evil, product_image="/static/does-not-exist.png")
        html = self.c1.get("/products?tab=brands").text
        self.assertNotIn("innerHTML=", html)
        self.assertNotIn(evil, html, "브랜드명이 그대로(따옴표 포함) 들어가면 안 됨")
        self.assertIn("&#39;;window.__brandXss=1;//", html, "글자로만 보여야")


class RangeTests(Base):
    def patch(self, pid, field, value):
        return self.c1.patch(f"/products/{pid}/field", json={"field": field, "value": value}).json()

    def test_rejects_negative_out_of_range_and_non_numbers(self):
        p = _p(self.db, groupbuy_price=1000, seller_commission_rate=0.1)
        for field, value in (("groupbuy_price", "-100"), ("consumer_price", "-1"), ("groupbuy_price", "inf"),
                             ("groupbuy_price", "nan"), ("groupbuy_price", "abc"),
                             ("seller_commission_rate", "150"), ("seller_commission_rate", "-5")):
            self.assertFalse(self.patch(p.id, field, value)["ok"], (field, value))
        self.db.expire_all()
        got = self.db.get(Product, p.id)
        self.assertEqual((got.groupbuy_price, got.seller_commission_rate), (1000, 0.1), "거부된 값은 저장되면 안 됨")

    def test_accepts_valid_and_blank(self):
        p = _p(self.db)
        self.assertTrue(self.patch(p.id, "groupbuy_price", "19999")["ok"])
        self.assertTrue(self.patch(p.id, "seller_commission_rate", "100")["ok"])
        self.assertTrue(self.patch(p.id, "groupbuy_price", "")["ok"])
        self.db.expire_all()
        got = self.db.get(Product, p.id)
        self.assertEqual((got.groupbuy_price, got.seller_commission_rate), (None, 1.0))


class PublicBannerTests(Base):
    def test_banner_only_on_first_page(self):
        for _ in range(30):
            _p(self.db, visibility_status="active")
        c = client_for()
        self.assertIn("공구 가능 제품", c.get("/public/products").text)
        page2 = c.get("/public/products?page=2").text
        self.assertNotIn("공구 가능 제품", page2, "2페이지에 0으로 된 배너가 나오면 안 됨")


class FinalUrlTests(Base):
    def test_relative_image_resolved_against_final_url(self):
        p = _p(self.db)
        page = '<meta property="og:image" content="photo.jpg"><meta property="og:title" content="x">'
        fake = httpx.Response(200, text=page, request=httpx.Request("GET", "https://shop.example/new/item/"))
        with mock.patch("app.services.safe_fetch.safe_get", return_value=fake):
            d = self.c1.post(f"/products/{p.id}/suggest", json={"source_url": "https://shop.example/old"}).json()
        self.assertEqual(d["suggestions"]["image"], "https://shop.example/new/item/photo.jpg")


class LogFailureTests(Base):
    def test_field_save_works_even_if_log_fails(self):
        p = _p(self.db, groupbuy_price=0)

        class Boom:
            def __init__(self, **kw):
                raise RuntimeError("log table missing")

        with mock.patch("app.routers.products.ProductFieldLog", Boom):
            d = self.c1.patch(f"/products/{p.id}/field", json={"field": "groupbuy_price", "value": "5000"}).json()
            self.assertTrue(d["ok"])
        self.db.expire_all()
        self.assertEqual(self.db.get(Product, p.id).groupbuy_price, 5000)


if __name__ == "__main__":
    unittest.main()
