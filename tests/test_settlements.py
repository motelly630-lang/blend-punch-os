"""정산서 한 장 (2026-09-24 대표님 확정 규칙).

- 계산: 정산 대상 = 판매금액 × 수수료율(부가세 포함). 사업자 전액 · 간이 ÷1.1 · 프리랜서 ÷1.1 에서 3.3% 뗌
- 계산은 한 곳 — 정산 화면·자동 정산·소싱 시뮬레이션이 같은 금액
- 수수료율 자동 찾기: 캠페인 → 제품 → 인플루언서 기본값
- 흐름: 작성중 → 발행(지급 대기) → 지급 완료. 순서를 건너뛰거나 발행·지급된 걸 지우지 못한다
- 사람이 고친 실지급액(수동 조정)은 자동 재계산이 덮지 않는다
- 다른 회사 정산서는 보거나 바꾸지 못한다
"""
from tests import _env  # noqa: F401  (app 보다 먼저)
from tests._env import SessionLocal, client_for, make_user, uid

import unittest

from app.models.campaign import Campaign
from app.models.influencer import Influencer
from app.models.product import Product
from app.models.settlement import Settlement
from app.services import settlement_calc as sc

CID = 1


def _get(oid):
    db = SessionLocal()
    try:
        return db.get(Settlement, oid)
    finally:
        db.close()


def _inf(**kw):
    db = SessionLocal()
    try:
        i = Influencer(name="가상셀러" + uid(), platform="instagram", handle="h" + uid(), company_id=kw.pop("company_id", CID),
                       bank_name="가상은행", account_number="000-111", account_holder="가상", **kw)
        db.add(i); db.commit()
        return i.id
    finally:
        db.close()


class CalcTest(unittest.TestCase):
    def test_대표님_표_금액(self):
        for t, final in (("사업자", 100000), ("간이사업자", 90909), ("프리랜서", 87909)):
            c = sc.calc(1_000_000, 0.10, t)
            self.assertEqual(c["commission_amount"], 100000)
            self.assertEqual(c["final_payment"], final, t)
        self.assertEqual(sc.calc(1_000_000, 0.10, "프리랜서")["tax_amount"], 3000)
        self.assertEqual(sc.calc(1_000_000, 0.10, "사업자")["supply_amount"], 90909)
        self.assertEqual(sc.calc(1_000_000, 0.10, "사업자")["vat_amount"], 9091)

    def test_반올림과_모르는_유형(self):
        c = sc.calc(1_234_567, 0.15, "프리랜서")
        self.assertEqual((c["commission_amount"], c["supply_amount"], c["tax_amount"], c["final_payment"]),
                         (185185, 168350, 5556, 162794))
        self.assertEqual(sc.calc(100000, 1, "이상한값")["seller_type"], "사업자")
        self.assertEqual(sc.calc(0, 0.1, "프리랜서")["final_payment"], 0)

    def test_소싱_시뮬레이션도_같은_금액(self):
        from app.sourcing import pricing
        for t in sc.SELLER_TYPES:
            self.assertEqual(pricing.settle(1_000_000, 0.10, t).settlement_amount,
                             sc.calc(1_000_000, 0.10, t)["final_payment"])

    def test_수수료율_자동_찾기_순서(self):
        camp, prod, inf = Campaign(seller_commission_rate=0), Product(seller_commission_rate=0.12), Influencer(commission_preference=0.2)
        self.assertEqual(sc.resolve_rate(camp, prod, inf), (0.12, "제품"))
        camp.seller_commission_rate = 0.1
        self.assertEqual(sc.resolve_rate(camp, prod, inf), (0.1, "캠페인"))
        self.assertEqual(sc.resolve_rate(None, None, inf), (0.2, "인플루언서 기본값"))
        self.assertEqual(sc.resolve_rate(None, None, None), (None, ""))


class FlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = client_for(make_user("admin", company_id=CID))

    def _new(self, **data):
        base = {"influencer_id": _inf(), "sales_amount": "1000000", "commission_rate_pct": "10", "seller_type": "프리랜서"}
        base.update(data)
        r = self.c.post("/settlements/new", data=base)
        self.assertEqual(r.status_code, 302)
        return r.headers["location"].split("/settlements/")[1].split("?")[0]

    def test_만들기_발행_지급_흐름(self):
        sid = self._new()
        s = _get(sid)
        self.assertEqual((s.status, s.final_payment, s.supply_amount, s.calc_version), ("pending", 87909, 90909, sc.CALC_VERSION))
        self.assertEqual(s.account_number_snapshot, "000-111")
        self.assertEqual(self.c.get(f"/settlements/{sid}").status_code, 200)
        # 지급은 발행 전에 못 한다
        self.c.post(f"/settlements/{sid}/paid")
        self.assertEqual(_get(sid).status, "pending")
        self.c.post(f"/settlements/{sid}/confirm")
        s = _get(sid)
        self.assertEqual(s.status, "confirmed")
        self.assertIsNotNone(s.issued_at)
        # 발행된 건 고치지도 지우지도 못한다
        self.c.post(f"/settlements/{sid}/edit", data={"sales_amount": "5", "commission_rate_pct": "10", "seller_type": "사업자"})
        self.c.post(f"/settlements/{sid}/delete")
        self.assertEqual(_get(sid).final_payment, 87909)
        self.c.post(f"/settlements/{sid}/paid")
        s = _get(sid)
        self.assertEqual(s.status, "paid")
        self.assertIsNotNone(s.paid_at)
        self.c.post(f"/settlements/{sid}/unissue")                     # 지급 완료는 발행 취소 불가
        self.assertEqual(_get(sid).status, "paid")
        self.assertIn("지급 완료", _get(sid).notes)                     # 처리 기록이 남는다

    def test_발행_취소하면_다시_고칠_수_있다(self):
        sid = self._new(seller_type="사업자")
        self.c.post(f"/settlements/{sid}/confirm")
        self.c.post(f"/settlements/{sid}/unissue")
        self.assertEqual(_get(sid).status, "pending")
        self.c.post(f"/settlements/{sid}/edit", data={"sales_amount": "2000000", "commission_rate_pct": "10", "seller_type": "간이사업자"})
        self.assertEqual(_get(sid).final_payment, 181818)

    def test_0원은_발행하지_않는다(self):
        sid = self._new(sales_amount="0")
        self.c.post(f"/settlements/{sid}/confirm")
        self.assertEqual(_get(sid).status, "pending")

    def test_수동_조정은_자동_정산이_덮지_않는다(self):
        from app.routers.campaigns import _auto_settle
        inf = _inf(business_type="사업자")
        db = SessionLocal()
        camp = Campaign(name="가상공구" + uid(), influencer_id=inf, company_id=CID, actual_revenue=1_000_000,
                        seller_commission_rate=0.1, status="completed")
        db.add(camp); db.commit()
        _auto_settle(db, camp); db.commit()
        s = db.query(Settlement).filter_by(campaign_id=camp.id).first()
        self.assertEqual(s.final_payment, 100000)
        s.is_manual = True; s.final_payment = 95000; db.commit()
        camp.actual_revenue = 3_000_000
        _auto_settle(db, camp); db.commit()
        db.refresh(s)
        self.assertEqual(s.final_payment, 95000)
        sid = s.id
        db.close()
        self.c.post(f"/settlements/{sid}/confirm")
        self.assertEqual(_get(sid).final_payment, 95000)

    def test_자동_정산은_제품_수수료율을_쓴다(self):
        from app.routers.campaigns import _auto_settle
        inf = _inf(business_type="프리랜서")
        db = SessionLocal()
        p = Product(name="가상상품" + uid(), brand="가상", category="뷰티", company_id=CID, seller_commission_rate=0.2)
        db.add(p); db.commit()
        camp = Campaign(name="가상공구" + uid(), influencer_id=inf, product_id=p.id, company_id=CID,
                        actual_revenue=500_000, status="completed")
        db.add(camp); db.commit()
        _auto_settle(db, camp); db.commit()
        s = db.query(Settlement).filter_by(campaign_id=camp.id).first()
        self.assertEqual((s.commission_rate, s.final_payment), (0.2, sc.calc(500_000, 0.2, "프리랜서")["final_payment"]))
        db.close()

    def test_미리보기는_서버_계산식(self):
        r = self.c.post("/settlements/preview", data={"sales_amount": "1000000", "commission_rate_pct": "10", "seller_type": "간이사업자"})
        self.assertEqual(r.json()["final_payment"], 90909)

    def test_목록_탭과_검색(self):
        name_inf = _inf()
        sid = self._new(influencer_id=name_inf)
        inf_name = SessionLocal().get(Influencer, name_inf).name
        r = self.c.get("/settlements?tab=pending&q=" + inf_name)
        self.assertEqual(r.status_code, 200)
        self.assertIn(f"/settlements/{sid}", r.text)
        for tab in ("confirmed", "paid", "calc"):
            self.assertEqual(self.c.get(f"/settlements?tab={tab}").status_code, 200)
        self.assertEqual(self.c.get("/settlements/export").status_code, 200)

    def test_예전_계산_정산서는_확인해야_새_금액으로_발행(self):
        inf = _inf()
        db = SessionLocal()
        old = Settlement(company_id=CID, influencer_id=inf, seller_type="프리랜서", sales_amount=1_000_000,
                         commission_rate=0.1, commission_amount=100000, tax_amount=3000, final_payment=97000,
                         status="pending", calc_version=None)
        paid_old = Settlement(company_id=CID, influencer_id=inf, seller_type="프리랜서", sales_amount=1_000_000,
                              commission_rate=0.1, final_payment=97000, status="paid", calc_version=None)
        db.add_all([old, paid_old]); db.commit(); oid, pid = old.id, paid_old.id; db.close()
        self.c.post(f"/settlements/{oid}/confirm")                    # 확인 없이 → 막힘
        self.assertEqual((_get(oid).status, _get(oid).final_payment), ("pending", 97000))
        self.c.post(f"/settlements/{oid}/confirm", data={"accept_new_calc": "1"})
        s = _get(oid)
        self.assertEqual((s.status, s.final_payment), ("confirmed", 87909))
        self.assertIn("97,000원 → 87,909원", s.notes)
        self.assertEqual(_get(pid).final_payment, 97000)               # 지급 완료된 예전 건은 그대로

    def test_수동값을_비우면_자동으로_돌아간다(self):
        sid = self._new(final_payment_manual="50000")
        self.assertTrue(_get(sid).is_manual)
        self.assertEqual(_get(sid).final_payment, 50000)
        self.c.post(f"/settlements/{sid}/edit", data={"sales_amount": "1000000", "commission_rate_pct": "10",
                                                      "seller_type": "프리랜서", "final_payment_manual": ""})
        self.assertEqual((_get(sid).is_manual, _get(sid).final_payment), (False, 87909))

    def test_수수료율_범위와_소수(self):
        sid = self._new(commission_rate_pct="12.345", seller_type="사업자")
        self.assertAlmostEqual(_get(sid).commission_rate, 0.12345)
        r = self.c.post("/settlements/new", data={"sales_amount": "1000", "commission_rate_pct": "150"})
        self.assertIn("err=", r.headers["location"])

    def test_다른_회사_인플루언서_캠페인은_연결되지_않는다(self):
        other_inf = _inf(company_id=2)
        sid = self._new(influencer_id=other_inf)
        self.assertIsNone(_get(sid).influencer_id)

    def test_지급월은_한국_시간_기준(self):
        from datetime import datetime
        inf = _inf()
        db = SessionLocal()
        s = Settlement(company_id=CID, influencer_id=inf, seller_type="사업자", final_payment=12345, status="paid",
                       paid_at=datetime(2026, 9, 30, 23, 0), calc_version=sc.CALC_VERSION)   # 한국 10/1 08:00
        db.add(s); db.commit(); sid = s.id; db.close()
        self.assertIn(f"/settlements/{sid}", self.c.get("/settlements?tab=paid&month=2026-10").text)
        self.assertNotIn(f"/settlements/{sid}", self.c.get("/settlements?tab=paid&month=2026-09").text)

    def test_정산서가_있는_캠페인은_지우지_못한다(self):
        db = SessionLocal()
        keep = Campaign(name="가상공구" + uid(), company_id=CID)
        free = Campaign(name="가상공구" + uid(), company_id=CID)
        db.add_all([keep, free]); db.commit()
        s = Settlement(company_id=CID, campaign_id=keep.id, final_payment=1000, status="paid", calc_version=sc.CALC_VERSION)
        db.add(s); db.commit(); kid, fid, sid = keep.id, free.id, s.id; db.close()
        self.c.post(f"/campaigns/{kid}/delete")
        self.c.post("/campaigns/bulk-delete", data={"ids": f"{kid},{fid}"})
        db = SessionLocal()
        try:
            self.assertIsNotNone(db.get(Campaign, kid))
            self.assertIsNone(db.get(Campaign, fid))                   # 정산서 없는 건 지워진다
            self.assertIsNotNone(db.get(Settlement, sid))
        finally:
            db.close()


class TenantTest(unittest.TestCase):
    def test_다른_회사_정산서는_못_본다(self):
        a = client_for(make_user("admin", company_id=1))
        b = client_for(make_user("admin", company_id=2))
        r = a.post("/settlements/new", data={"sales_amount": "100000", "commission_rate_pct": "10", "seller_type": "사업자"})
        sid = r.headers["location"].split("/settlements/")[1].split("?")[0]
        self.assertEqual(b.get(f"/settlements/{sid}").status_code, 302)       # 목록으로 돌려보냄
        b.post(f"/settlements/{sid}/confirm")
        b.post(f"/settlements/{sid}/delete")
        s = _get(sid)
        self.assertIsNotNone(s)
        self.assertEqual(s.status, "pending")


if __name__ == "__main__":
    unittest.main()
