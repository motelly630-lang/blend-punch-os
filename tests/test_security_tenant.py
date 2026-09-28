"""회사 간 격리·권한 보안 점검(2026-09-28) 회귀 시험.

회사 1 자료를 만들어 두고 회사 2 계정으로 읽기·쓰기를 시도한다. 모두 막혀야 한다.
"""
from tests import _env  # noqa: F401
from tests._env import SessionLocal, client_for, make_user, seed_companies, uid

import unittest

from app.models import Product, Influencer, Campaign
from app.models.brand import Brand
from app.models.transaction import Transaction
from app.models.sales_page import SalesPage

DENIED = (302, 303, 401, 403, 404)


class Base(unittest.TestCase):
    def setUp(self):
        seed_companies()
        self.db = SessionLocal()
        self.u1 = make_user("admin", company_id=1)
        self.u2 = make_user("admin", company_id=2)
        self.c1, self.c2 = client_for(self.u1), client_for(self.u2)
        self.p1 = Product(name=f"회사1제품 {uid()}", brand="가상", category="기타", company_id=1)
        self.b1 = Brand(name=f"회사1브랜드 {uid()}", company_id=1)
        self.inf1 = Influencer(name=f"회사1셀러 {uid()}", handle=f"h{uid()}", company_id=1, status="active", platform="instagram",
                               followers=10)
        self.camp1 = Campaign(name=f"회사1캠페인 {uid()}", company_id=1)
        self.db.add_all([self.p1, self.b1, self.inf1, self.camp1])
        self.db.commit()

    def tearDown(self):
        self.db.close()


class PlatformSettingsTests(Base):
    def test_business_info_only_platform_admin(self):
        from app.models.business_info import BusinessInfo
        r = self.c2.post("/settings/business-info", data={"company_name": "HACKED_BY_C2"})
        self.assertIn(r.status_code, DENIED)
        self.db.expire_all()
        info = self.db.query(BusinessInfo).first()
        self.assertNotEqual(getattr(info, "company_name", None), "HACKED_BY_C2")
        self.assertIn(make_staff(1).post("/settings/business-info", data={"company_name": "X"}).status_code, DENIED,
                      "블랜드펀치 직원(관리자 아님)도 불가")
        r = self.c1.post("/settings/business-info", data={"company_name": "블랜드펀치"})
        self.assertIn(r.status_code, (200, 302, 303))
        self.db.expire_all()
        self.assertEqual(self.db.query(BusinessInfo).first().company_name, "블랜드펀치")

    def test_shop_inquiries_admin_and_features_and_briefing_only_platform_admin(self):
        for path in ("/inquiries", "/settings/features"):
            self.assertIn(self.c2.get(path).status_code, DENIED, path)
        self.assertIn(self.c2.post("/trends/engine/run").status_code, DENIED)


def make_staff(company_id):
    return client_for(make_user("staff", company_id=company_id))


class PipelineScopeTests(Base):
    def test_other_company_cannot_view_or_poll_pipeline(self):
        for path in (f"/pipeline/product/{self.p1.id}", f"/pipeline/brand/{self.b1.id}",
                     f"/api/pipeline/status/product/{self.p1.id}", f"/api/pipeline/logs/product/{self.p1.id}",
                     f"/api/pipeline/poll/product/{self.p1.id}"):
            self.assertEqual(self.c2.get(path).status_code, 404, path)
        self.assertEqual(self.c2.post(f"/api/pipeline/product/{self.p1.id}/start").status_code, 404)
        self.assertEqual(self.c1.get(f"/api/pipeline/status/product/{self.p1.id}").status_code, 200)


class TransactionTests(Base):
    def test_cannot_inject_into_other_company_campaign(self):
        r = self.c2.post("/transactions/new", data={"campaign_id": self.camp1.id, "amount": 999999,
                                                    "type": "revenue"})
        self.assertIn(r.status_code, (302, 303))
        n = self.db.query(Transaction).filter(Transaction.campaign_id == self.camp1.id).count()
        self.assertEqual(n, 0)

    def test_open_redirect_blocked(self):
        for target in ("https://evil.example/", "//evil.example/", "/\\evil.example"):
            r = self.c1.post("/transactions/new", data={"amount": 1, "redirect_to": target})
            self.assertEqual(r.headers["location"], "/settlements?tab=calc", target)


class RecommendTests(Base):
    def test_other_company_influencers_not_listed_and_names_escaped(self):
        # 다른 시험의 자료와 섞이지 않게 이 시험 전용 회사를 만든다 (추천은 상위 10명만 보여줌)
        import random
        from app.models.feature_flag import Company
        cid = random.randint(10_000, 99_999)
        self.db.add(Company(id=cid, name=f"시험회사{cid}", plan="pro", is_active=True))
        self.db.commit()
        evil = Influencer(name=f"<img src=x onerror=alert(1)>{uid()}", handle="evil", company_id=cid,
                          platform="instagram", status="active", followers=5)
        self.db.add(evil)
        self.db.commit()
        cx = client_for(make_user("admin", company_id=cid))
        r = cx.post("/api/ai/recommend-sellers", data={"product_name": "x", "category": "기타"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(self.inf1.name, r.text)
        self.assertNotIn(self.camp1.name, r.text)
        self.assertNotIn("<img src=x", r.text)
        self.assertIn("&lt;img src=x", r.text)

    def test_add_to_campaign_rejects_foreign_ids(self):
        from app.models.automation import CampaignRecommendation
        self.c2.post("/api/automation/add-to-campaign", data={"campaign_id": self.camp1.id,
                                                              "influencer_id": self.inf1.id})
        self.assertEqual(self.db.query(CampaignRecommendation)
                         .filter(CampaignRecommendation.campaign_id == self.camp1.id).count(), 0)


class AttendanceTests(Base):
    def test_other_company_admin_cannot_see_visits(self):
        r = self.c2.get(f"/attendance/{self.u1.id}/visits")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers["location"], "/attendance")


class SalesPageTests(Base):
    def test_cannot_wrap_other_company_product(self):
        slug = f"x-{uid()}"
        r = self.c2.post("/sales-pages/new", data={"slug": slug, "product_id": self.p1.id, "price": 1000})
        self.assertIn(r.status_code, (302, 303))
        self.assertIn("err=", r.headers["location"])
        self.assertIsNone(self.db.query(SalesPage).filter(SalesPage.slug == slug).first())


class SalesRecordTests(Base):
    def test_outreach_proposal_crm_seller_reject_foreign_ids(self):
        from app.models.outreach import OutreachLog
        from app.models.proposal import Proposal
        from app.models.crm import CrmPipeline
        from app.models.seller import Seller
        before = (self.db.query(OutreachLog).count(), self.db.query(Proposal).count(),
                  self.db.query(CrmPipeline).count(), self.db.query(Seller).count())
        cases = (
            ("/outreach/new", {"operator": "x", "influencer_handle": f"h{uid()}", "product_id": self.p1.id,
                               "outreach_date": "2026-09-28"}),
            ("/proposals/new", {"product_id": self.p1.id, "body": "x"}),
            ("/crm/new", {"influencer_id": self.inf1.id}),
            ("/sellers/new", {"name": "x", "seller_code": f"s{uid()}", "influencer_id": self.inf1.id}),
        )
        for path, data in cases:
            r = self.c2.post(path, data=data)
            self.assertIn(r.status_code, (302, 303), path)
            self.assertIn("err=", r.headers.get("location", ""), path)
        self.db.expire_all()
        after = (self.db.query(OutreachLog).count(), self.db.query(Proposal).count(),
                 self.db.query(CrmPipeline).count(), self.db.query(Seller).count())
        self.assertEqual(before, after)

    def test_outreach_auto_created_influencer_belongs_to_own_company(self):
        handle = f"auto{uid()}"
        self.c2.post("/outreach/new", data={"operator": "x", "influencer_handle": handle,
                                            "outreach_date": "2026-09-28"})
        self.db.expire_all()
        inf = self.db.query(Influencer).filter(Influencer.handle == handle).first()
        self.assertIsNotNone(inf)
        self.assertEqual(inf.company_id, 2)


if __name__ == "__main__":
    unittest.main()
