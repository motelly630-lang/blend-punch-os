"""캠페인: 상품 연결 유지, 상태·회사 소속 검증, 수수료 소수점, 조회 부작용 제거, 명시적 진행 정리."""
from tests import _env
from tests._env import SessionLocal, client_for, make_user, uid

import re
import unittest
from datetime import date, timedelta

from app.models.campaign import Campaign
from app.models.influencer import Influencer
from app.models.product import Product
from app.models.settlement import Settlement


def _mk_product(company_id=1, **kw):
    db = SessionLocal()
    try:
        p = Product(company_id=company_id, name=f"가상상품{uid()}", brand="가상브랜드", category="기타",
                    groupbuy_price=29900, seller_commission_rate=0.15, **kw)
        db.add(p)
        db.commit()
        return p.id
    finally:
        db.close()


def _mk_influencer(company_id=1):
    db = SessionLocal()
    try:
        i = Influencer(company_id=company_id, name=f"가상셀러{uid()}", platform="instagram", handle=f"h{uid()}")
        db.add(i)
        db.commit()
        return i.id
    finally:
        db.close()


def _mk_campaign(company_id=1, **kw):
    db = SessionLocal()
    try:
        c = Campaign(company_id=company_id, name=kw.pop("name", f"가상캠페인{uid()}"), **kw)
        db.add(c)
        db.commit()
        return c.id
    finally:
        db.close()


def _get_campaign(cid_):
    db = SessionLocal()
    try:
        c = db.query(Campaign).filter(Campaign.id == cid_).first()
        db.expunge(c)
        return c
    finally:
        db.close()


def _form(**kw):
    base = {"name": f"폼캠페인{uid()}", "status": "planning", "commission_rate": "0",
            "unit_price": "29900", "seller_commission_rate_pct": "", "vendor_commission_rate_pct": "",
            "expected_sales": "0", "actual_sales": "0", "actual_revenue": "0",
            "campaign_type": "internal"}
    base.update(kw)
    return base


class CampaignFormProductLink(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.user = make_user("admin", 1)
        cls.client = client_for(cls.user)

    def test_form_renders_single_product_id_input(self):
        r = self.client.get("/campaigns/new")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(re.findall(r'name="product_id"', r.text)), 1)
        cid_ = _mk_campaign(product_id=_mk_product())
        r = self.client.get(f"/campaigns/{cid_}/edit")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(re.findall(r'name="product_id"', r.text)), 1)
        # 직접입력 모드 저장 시에만 product_id 를 비우는 @submit 코드가 있어야 한다
        self.assertIn("productMode === 'manual'", r.text)

    def test_create_and_update_keep_product_link(self):
        pid = _mk_product()
        r = self.client.post("/campaigns/new", data=_form(product_id=pid))
        self.assertEqual(r.status_code, 302, r.text)
        new_id = r.headers["location"].split("/campaigns/")[1].split("?")[0]
        self.assertEqual(_get_campaign(new_id).product_id, pid)

        # 수정 저장(같은 상품) → 유지
        r = self.client.post(f"/campaigns/{new_id}/edit", data=_form(name="수정", product_id=pid))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(_get_campaign(new_id).product_id, pid)

        # 직접입력 모드 저장 = 브라우저가 product_id 를 빈 값으로 보냄 → 해제
        r = self.client.post(f"/campaigns/{new_id}/edit",
                             data=_form(name="수정2", product_id="", product_name_manual="미등록 가상상품"))
        c = _get_campaign(new_id)
        self.assertIsNone(c.product_id)
        self.assertEqual(c.product_name_manual, "미등록 가상상품")


class CampaignValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.user = make_user("admin", 1)
        cls.client = client_for(cls.user)

    def _count(self):
        db = SessionLocal()
        try:
            return db.query(Campaign).count()
        finally:
            db.close()

    def test_rejects_other_company_product_and_influencer(self):
        other_pid, other_iid = _mk_product(company_id=2), _mk_influencer(company_id=2)
        before = self._count()
        r = self.client.post("/campaigns/new", data=_form(product_id=other_pid))
        self.assertEqual(r.status_code, 302)
        self.assertIn("err=", r.headers["location"])
        r = self.client.post("/campaigns/new", data=_form(influencer_id=other_iid))
        self.assertIn("err=", r.headers["location"])
        r = self.client.post("/campaigns/inline-create", json={"name": "x", "product_id": other_pid})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self._count(), before)

        cid_ = _mk_campaign()
        r = self.client.post(f"/campaigns/{cid_}/inline-update", json={"influencer_id": other_iid})
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(_get_campaign(cid_).influencer_id)

    def test_rejects_unknown_status(self):
        before = self._count()
        r = self.client.post("/campaigns/new", data=_form(status="finished"))
        self.assertIn("err=", r.headers["location"])
        r = self.client.post("/campaigns/inline-create", json={"name": "x", "status": "done"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self._count(), before)
        cid_ = _mk_campaign(status="planning")
        r = self.client.post(f"/campaigns/{cid_}/inline-update", json={"status": "done"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(_get_campaign(cid_).status, "planning")

    def test_legacy_values_unchanged_do_not_block_other_edits(self):
        cid_ = _mk_campaign(status="legacy_status")
        r = self.client.post(f"/campaigns/{cid_}/inline-update",
                             json={"status": "legacy_status", "unit_price": 12000})
        self.assertEqual(r.status_code, 200, r.text)
        c = _get_campaign(cid_)
        self.assertEqual((c.status, c.unit_price), ("legacy_status", 12000))

    def test_commission_decimals_preserved(self):
        r = self.client.post("/campaigns/new", data=_form(seller_commission_rate_pct="12.5",
                                                          vendor_commission_rate_pct="7.25",
                                                          actual_revenue="100000"))
        new_id = r.headers["location"].split("/campaigns/")[1].split("?")[0]
        c = _get_campaign(new_id)
        self.assertEqual((c.seller_commission_rate, c.vendor_commission_rate), (0.125, 0.0725))
        self.assertEqual(c.seller_commission_amount, 12500)
        r = self.client.get(f"/campaigns/{new_id}/edit")
        self.assertIn("sellerPct: 12.5,", r.text)

        r = self.client.post(f"/campaigns/{new_id}/inline-update", json={"seller_commission_rate_pct": 12.5})
        self.assertEqual(r.json()["seller_commission_rate_pct"], 12.5)
        self.assertEqual(_get_campaign(new_id).seller_commission_rate, 0.125)


def _snapshot(company_id):
    db = SessionLocal()
    try:
        camps = sorted((c.id, c.status, bool(c.is_archived)) for c in
                       db.query(Campaign).filter(Campaign.company_id == company_id).all())
        sets = sorted((s.id, s.campaign_id, s.status, s.final_payment, s.commission_amount, s.sales_amount)
                      for s in db.query(Settlement).filter(Settlement.company_id == company_id).all())
        return camps, sets
    finally:
        db.close()


class CampaignReadsHaveNoSideEffects(unittest.TestCase):
    """회사 3 전용 데이터로 격리."""

    @classmethod
    def setUpClass(cls):
        from app.models.feature_flag import Company
        db = SessionLocal()
        try:
            if not db.query(Company).filter(Company.id == 3).first():
                db.add(Company(id=3, name="테스트회사C", plan="pro", is_active=True))
                db.commit()
        finally:
            db.close()
        cls.admin = make_user("admin", 3)
        cls.client = client_for(cls.admin)
        today = date.today()
        long_ago = today - timedelta(days=90)
        inf = _mk_influencer(3)
        cls.negotiating_past = _mk_campaign(3, status="negotiating", start_date=long_ago,
                                            end_date=long_ago + timedelta(days=7))
        cls.planning_now = _mk_campaign(3, status="planning", start_date=today - timedelta(days=1),
                                        end_date=today + timedelta(days=5))
        cls.contracted_past = _mk_campaign(3, status="contracted", start_date=long_ago,
                                           end_date=long_ago + timedelta(days=7), influencer_id=inf,
                                           actual_revenue=100000, seller_commission_rate=0.1)
        cls.contracted_now = _mk_campaign(3, status="contracted", start_date=today - timedelta(days=1),
                                          end_date=today + timedelta(days=5))
        cls.completed_no_settle = _mk_campaign(3, status="completed", start_date=long_ago,
                                               end_date=long_ago + timedelta(days=7), influencer_id=inf,
                                               actual_revenue=50000, seller_commission_rate=0.1)
        cls.completed_paid = _mk_campaign(3, status="completed", start_date=long_ago,
                                          end_date=long_ago + timedelta(days=7), influencer_id=inf,
                                          actual_revenue=80000, seller_commission_rate=0.2)
        db = SessionLocal()
        try:
            for st, amt in (("confirmed", 11111), ("paid", 22222)):
                db.add(Settlement(company_id=3, campaign_id=cls.completed_paid, influencer_id=inf,
                                  status=st, sales_amount=80000, commission_rate=0.2,
                                  commission_amount=16000, final_payment=amt))
            db.commit()
        finally:
            db.close()

    def test_get_pages_do_not_change_campaigns_or_settlements(self):
        before = _snapshot(3)
        for path in ("/campaigns", "/campaigns?tab=archive", f"/campaigns/{self.contracted_past}",
                     f"/campaigns/{self.negotiating_past}/edit", "/campaigns/new",
                     "/campaigns/progress-review"):
            with self.subTest(path=path):
                r = self.client.get(path)
                self.assertEqual(r.status_code, 200, r.text[:300])
        self.assertEqual(_snapshot(3), before)

    def test_list_shows_stored_status_with_schedule_note(self):
        past = date.today() - timedelta(days=20)
        _mk_campaign(3, name="안내확인용 계약완료", status="contracted", start_date=past,
                     end_date=past + timedelta(days=3))
        r = self.client.get("/campaigns")
        self.assertTrue("일정 종료 · 상태 미확정" in r.text, "미확정 안내 없음")
        self.assertTrue("종료일 지남 · 완료 처리 필요" in r.text, "확정 안내 없음")

    def test_apply_changes_only_confirmed_and_never_touches_existing_settlements(self):
        before_camps, before_sets = _snapshot(3)
        # 미확정 캠페인 id 를 억지로 보내도 적용되지 않아야 한다
        r = self.client.post("/campaigns/progress-review/apply", data={
            "status_ids": [self.contracted_past, self.contracted_now, self.negotiating_past, self.planning_now],
        })
        self.assertEqual(r.status_code, 303)
        self.assertEqual(_get_campaign(self.contracted_past).status, "completed")
        self.assertEqual(_get_campaign(self.contracted_now).status, "active")
        self.assertEqual(_get_campaign(self.negotiating_past).status, "negotiating")
        self.assertEqual(_get_campaign(self.planning_now).status, "planning")
        # create_settlements 미선택 → 정산 불변
        self.assertEqual(_snapshot(3)[1], before_sets)

    def test_archive_and_optional_settlement_creation(self):
        _, before_sets = _snapshot(3)
        target = _mk_campaign(3, status="contracted", start_date=date.today() - timedelta(days=60),
                              end_date=date.today() - timedelta(days=50), influencer_id=_mk_influencer(3),
                              actual_revenue=200000, seller_commission_rate=0.1)
        r = self.client.post("/campaigns/progress-review/apply", data={
            "status_ids": [target], "create_settlements": "1",
            "archive_ids": [self.completed_paid],
        })
        self.assertEqual(r.status_code, 303)
        after_camps, after_sets = _snapshot(3)
        new_sets = [s for s in after_sets if s not in before_sets]
        self.assertEqual(len(new_sets), 1)
        self.assertEqual((new_sets[0][1], new_sets[0][2]), (target, "pending"))
        # 기존 confirmed/paid 금액 불변
        for s in before_sets:
            self.assertIn(s, after_sets)
        self.assertTrue(_get_campaign(self.completed_paid).is_archived)

    def test_progress_review_requires_admin(self):
        staff = client_for(make_user("staff", 3))
        r = staff.get("/campaigns/progress-review")
        self.assertEqual(r.status_code, 302)
        r = staff.post("/campaigns/progress-review/apply", data={"status_ids": [self.contracted_now]})
        self.assertEqual(r.status_code, 302)


if __name__ == "__main__":
    unittest.main()
