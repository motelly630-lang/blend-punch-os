"""외부 API(/api/v1) 보안 점검 2026-09-28 — B2 로그인·B3 인플루언서·B4 회사 범위·B6 수량."""
from tests import _env  # noqa: F401
from tests._env import SessionLocal, client_for, make_user, seed_companies, uid

import unittest

from app.auth.service import hash_password
from app.models import Product, Influencer
from app.models.user import User


class ApiLoginTests(unittest.TestCase):
    def setUp(self):
        from app.api import public_v1
        public_v1._LOGIN_FAILS.clear()   # 시도 제한 기록은 시험마다 비운다
        seed_companies()
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def user(self, **kw):
        u = User(username=f"api_{uid()}", hashed_password=hash_password("pw"), role="admin", company_id=1,
                 is_active=True, **kw)
        self.db.add(u)
        self.db.commit()
        return u

    def test_unverified_email_rejected(self):
        u = self.user(email=f"{uid()}@example.com", email_verified=False)
        r = client_for().post("/api/v1/auth/login", json={"username": u.username, "password": "pw"})
        self.assertEqual(r.status_code, 403)

    def test_api_token_cannot_open_os_screens(self):
        u = self.user()
        r = client_for().post("/api/v1/auth/login", json={"username": u.username, "password": "pw"})
        self.assertEqual(r.status_code, 200)
        c = client_for()
        c.cookies.set("access_token", r.json()["access_token"])
        r = c.get("/products")
        self.assertNotEqual(r.status_code, 200, "외부 API 열쇠로 OS 관리 화면이 열리면 안 됨")
        c.cookies.set("access_token", __import__("app.auth.service", fromlist=["x"]).create_access_token(u.username, u.role))
        self.assertEqual(c.get("/products").status_code, 200, "보통 OS 열쇠는 그대로 됨")

    def test_brute_force_limited(self):
        c = client_for()
        codes = [c.post("/api/v1/auth/login", json={"username": "nobody", "password": f"x{i}"}).status_code
                 for i in range(12)]
        self.assertIn(429, codes)


class ApiScopeTests(unittest.TestCase):
    def setUp(self):
        seed_companies()
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_influencer_endpoints_removed(self):
        inf = Influencer(name=f"명단 {uid()}", handle="h", platform="instagram", status="active", company_id=1)
        self.db.add(inf)
        self.db.commit()
        c = client_for()
        self.assertEqual(c.get("/api/v1/influencers").status_code, 404)
        self.assertEqual(c.get(f"/api/v1/influencers/{inf.id}").status_code, 404)

    def test_other_company_products_not_exposed(self):
        p2 = Product(name=f"회사2공개 {uid()}", brand="x", category="기타", company_id=2, is_published=True,
                     status="active")
        p1 = Product(name=f"회사1공개 {uid()}", brand="x", category="기타", company_id=1, is_published=True,
                     status="active")
        self.db.add_all([p1, p2])
        self.db.commit()
        c = client_for()
        self.assertEqual(c.get(f"/api/v1/products/{p2.id}").status_code, 404)
        self.assertNotIn(p2.name, c.get("/api/v1/products?limit=100").text)
        self.assertEqual(c.get(f"/api/v1/products/{p1.id}").status_code, 200)

    def test_negative_quantity_rejected(self):
        r = client_for().post("/api/v1/orders", json={
            "sales_page_id": "x", "quantity": -5, "customer_name": "a", "customer_phone": "0", "shipping_name": "a",
            "shipping_phone": "0", "shipping_address": "a", "shipping_zipcode": "0"})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
