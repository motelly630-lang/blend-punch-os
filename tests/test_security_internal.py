"""쇼핑몰 코드 삭제 · 블랜드픽 전용 주소(주문 생성·1:1 문의)는 같은 서버 안 요청만 (보안 점검 2026-09-28)."""
from tests import _env  # noqa: F401
from tests._env import client_for

import unittest

from fastapi.testclient import TestClient

from app.main import app

DENIED = (302, 303, 401, 403)


def local_client():
    return TestClient(app, raise_server_exceptions=True, follow_redirects=False, client=("127.0.0.1", 50000))


class ShopRemovedTests(unittest.TestCase):
    def test_shop_routes_are_gone(self):
        c = client_for()
        self.assertEqual(c.post("/shop/any-slug/prepare", json={}).status_code, 404)
        self.assertIn(c.get("/shop/success?paymentKey=a&orderId=b&amount=1").status_code, (302, 404))
        self.assertNotIn("/shop/", "".join(r.path for r in app.routes if hasattr(r, "path") and r.path.startswith("/shop")))


class InternalOnlyTests(unittest.TestCase):
    ORDER = {"customer_name": "x", "total_price": 1, "payment_key": "k"}

    def counts(self):
        from app.database import SessionLocal
        from app.models.inquiry import Inquiry
        from app.models.order import Order
        db = SessionLocal()
        try:
            return db.query(Order).count(), db.query(Inquiry).count()
        finally:
            db.close()

    def test_outside_requests_rejected(self):
        c = client_for()     # 바깥(테스트 클라이언트 주소)
        before = self.counts()
        self.assertIn(c.post("/orders/api/create", json=self.ORDER).status_code, DENIED)
        self.assertIn(c.get("/inquiries/api/user/u1").status_code, DENIED)
        self.assertIn(c.post("/inquiries/api/submit", data={"name": "a", "contact": "b", "category": "c",
                                                             "message": "d"}).status_code, DENIED)
        self.assertEqual(self.counts(), before, "막힌 요청으로 주문·문의가 생기면 안 됨")

    def test_proxied_requests_rejected_even_from_loopback(self):
        c = local_client()   # nginx 를 거친 요청처럼 전달 헤더가 붙은 경우
        before = self.counts()
        for h in ({"X-Forwarded-For": "203.0.113.5"}, {"X-Real-IP": "203.0.113.5"}):
            self.assertIn(c.get("/inquiries/api/user/u1", headers=h).status_code, DENIED, h)
            self.assertIn(c.post("/orders/api/create", json=self.ORDER, headers=h).status_code, DENIED, h)
        self.assertEqual(self.counts(), before)

    def test_same_server_call_allowed(self):
        c = local_client()
        r = c.post("/inquiries/api/submit", data={"name": "a", "contact": "b", "category": "c", "message": "d"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(c.get("/inquiries/api/user/nobody").status_code, 200)


if __name__ == "__main__":
    unittest.main()
