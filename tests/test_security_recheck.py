"""코덱스 재검토(2026-09-28) 1·3·4번 — 제품 소개서·외부 주문 조회·외부 셀러/신청 연결."""
from tests import _env  # noqa: F401
from tests._env import SessionLocal, client_for, make_user, seed_companies, uid

import unittest

from app.models import Product
from app.models.proposal import Proposal
from app.models.order import Order
from app.models.sales_page import SalesPage
from app.models.seller import Seller
from app.models.group_buy_application import GroupBuyApplication


class ProductSheetTests(unittest.TestCase):
    def setUp(self):
        seed_companies()
        self.db = SessionLocal()
        self.p1 = Product(name=f"PRIVATE_PRODUCT_MARKER {uid()}", brand="x", category="기타", company_id=1,
                          unique_selling_point="PRIVATE_USP_MARKER")
        self.db.add(self.p1)
        self.db.commit()
        self.c2 = client_for(make_user("admin", company_id=2))

    def tearDown(self):
        self.db.close()

    def test_cannot_create_product_sheet_with_other_company_product(self):
        before = self.db.query(Proposal).count()
        r = self.c2.post("/proposals/product/new", data={"product_id": self.p1.id, "body": "test"})
        self.assertIn("err=", r.headers.get("location", ""))
        self.assertEqual(self.db.query(Proposal).count(), before)

    def test_old_mislinked_proposal_does_not_show_foreign_product(self):
        pr = Proposal(company_id=2, product_id=self.p1.id, proposal_type="product_sheet", body="x")
        self.db.add(pr)
        self.db.commit()
        for path in (f"/proposals/{pr.id}/card", f"/proposals/{pr.id}", "/proposals"):
            r = self.c2.get(path, follow_redirects=True)
            self.assertNotIn("PRIVATE_PRODUCT_MARKER", r.text, path)
            self.assertNotIn("PRIVATE_USP_MARKER", r.text, path)

    def test_own_product_sheet_still_works(self):
        c1 = client_for(make_user("admin", company_id=1))
        r = c1.post("/proposals/product/new", data={"product_id": self.p1.id, "body": "ok"})
        self.assertNotIn("err=", r.headers.get("location", ""))
        pid = r.headers["location"].split("/proposals/")[1].split("?")[0]
        self.assertEqual(c1.get(f"/proposals/{pid}/card").status_code, 200)


class ApiV1RecheckTests(unittest.TestCase):
    def setUp(self):
        seed_companies()
        self.db = SessionLocal()
        self.prod1 = Product(name=f"공개 {uid()}", brand="x", category="기타", company_id=1, status="active",
                             visibility_status="active")
        self.prod2 = Product(name=f"회사2 {uid()}", brand="x", category="기타", company_id=2, status="active")
        self.db.add_all([self.prod1, self.prod2])
        self.db.flush()
        self.sp = SalesPage(slug=f"v1-{uid()}", product_id=self.prod1.id, company_id=1, price=1000, status="active",
                            is_published=True)
        self.s2 = Seller(name="회사2셀러", seller_code=f"c2{uid()}", company_id=2, is_active=True)
        self.db.add_all([self.sp, self.s2])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_order_status_lookup_removed(self):
        o = Order(order_number=f"BP-{uid()}", company_id=2, product_id=self.prod2.id, customer_name="a",
                  customer_phone="0", shipping_name="a", shipping_phone="0", shipping_address="a",
                  shipping_zipcode="0", quantity=1, unit_price=456, total_price=456, payment_status="paid")
        self.db.add(o)
        self.db.commit()
        r = client_for().get(f"/api/v1/orders/{o.id}")
        self.assertIn(r.status_code, (404, 405))
        self.assertNotIn("456", r.text)

    def test_order_does_not_attach_other_company_seller(self):
        r = client_for().post("/api/v1/orders", json={
            "sales_page_id": self.sp.id, "seller_code": self.s2.seller_code, "quantity": 1, "customer_name": "a",
            "customer_phone": "0", "shipping_name": "a", "shipping_phone": "0", "shipping_address": "a",
            "shipping_zipcode": "0"})
        self.assertEqual(r.status_code, 200, r.text)
        self.db.expire_all()
        o = self.db.get(Order, r.json()["order_id"])
        self.assertIsNone(o.seller_id, "다른 회사 셀러가 붙으면 안 됨")

    def test_application_rejects_other_company_product_and_keeps_own(self):
        base = {"product_name": "x", "applicant_name": "a", "contact_type": "카카오", "contact_value": "b"}
        c = client_for()
        before = self.db.query(GroupBuyApplication).count()
        r = c.post("/api/v1/applications", json={**base, "product_id": self.prod2.id})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.db.query(GroupBuyApplication).count(), before)
        r = c.post("/api/v1/applications", json={**base, "product_id": self.prod1.id})
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
