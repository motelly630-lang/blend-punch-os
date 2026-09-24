"""매출 입력 — 여러 입구(한 화면 · 붙여넣기 · 상세), 로직은 하나 (대표님 2026-09-24).

- 끝난 공구에 매출을 넣으면 정산서가 자동으로 생긴다 (종료일 지났으면 완료 처리 선택)
- 진행 중 공구는 중간 매출로만 저장 (정산서 없음)
- 수량만 넣으면 수량 × 단가
- 이미 발행된 정산서 금액은 매출이 바뀌어도 그대로
- 붙여넣기는 미리보기로 짝을 보여주고, 고른 것만 저장
- 다른 회사 공구는 건드리지 못한다
"""
from tests import _env  # noqa: F401  (app 보다 먼저)
from tests._env import SessionLocal, client_for, make_user, uid

import unittest
from datetime import timedelta

from app.models.campaign import Campaign
from app.models.influencer import Influencer
from app.models.product import Product
from app.models.settlement import Settlement
from app.routers.campaigns import _kst_today, _parse_paste
from app.services import settlement_calc as sc


def _setup(s, e, company_id=1, status="active", **kw):
    t = _kst_today()
    db = SessionLocal()
    try:
        inf = Influencer(name="가상맘" + uid(), platform="instagram", handle="h" + uid(), company_id=company_id,
                         business_type="프리랜서")
        p = Product(name="가상상품" + uid(), brand="가상", category="식품", company_id=company_id,
                    seller_commission_rate=0.1, groupbuy_price=10000)
        db.add_all([inf, p]); db.flush()
        c = Campaign(name="가상공구" + uid(), company_id=company_id, influencer_id=inf.id, product_id=p.id,
                     start_date=t + timedelta(s), end_date=t + timedelta(e), status=status, **kw)
        db.add(c); db.commit()
        return c.id, c.name, p.name, inf.name
    finally:
        db.close()


def _camp(cid):
    db = SessionLocal()
    try:
        return db.get(Campaign, cid)
    finally:
        db.close()


def _settle(cid):
    db = SessionLocal()
    try:
        return db.query(Settlement).filter_by(campaign_id=cid).first()
    finally:
        db.close()


class RevenueTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = client_for(make_user("admin", company_id=1))

    def test_한꺼번에_저장_끝난공구는_정산서_진행중은_매출만(self):
        ended, *_ = _setup(-10, -2)                      # 종료일 지났지만 상태는 active
        running, *_ = _setup(-2, 5)
        r = self.c.post("/campaigns/revenue", data={
            "tab": "ended", "complete_if_ended": "1",
            f"rev_{ended}": "1,000,000", f"qty_{ended}": "",
            f"rev_{running}": "300000", f"qty_{running}": "",
        })
        self.assertIn("msg=", r.headers["location"])
        e, a = _camp(ended), _camp(running)
        self.assertEqual((e.status, e.actual_revenue), ("completed", 1_000_000))
        self.assertEqual((a.status, a.actual_revenue), ("active", 300000))
        s = _settle(ended)
        self.assertEqual((s.status, s.final_payment), ("pending", sc.calc(1_000_000, 0.1, "프리랜서")["final_payment"]))
        self.assertIsNone(_settle(running))

    def test_매출은_있는데_정산서가_빠진_공구는_저장만_눌러도_생긴다(self):
        cid, *_ = _setup(-10, -2, status="completed", actual_revenue=400000)
        untouched, *_ = _setup(-10, -2, actual_revenue=300000)              # 체크 끄면 그대로
        self.c.post("/campaigns/revenue", data={"tab": "ended", f"rev_{cid}": "400000",
                                                f"rev_{untouched}": "300000"})
        self.assertIsNotNone(_settle(cid))
        self.assertIsNone(_settle(untouched))
        self.assertEqual(_camp(untouched).status, "active")

    def test_수량만_넣으면_수량_곱하기_단가(self):
        cid, *_ = _setup(-2, 3)
        self.c.post("/campaigns/revenue", data={"tab": "active", f"qty_{cid}": "25", f"rev_{cid}": ""})
        self.assertEqual((_camp(cid).actual_sales, _camp(cid).actual_revenue), (25, 250000))

    def test_발행된_정산서는_그대로(self):
        cid, *_ = _setup(-10, -2, status="completed", actual_revenue=500000)
        db = SessionLocal()
        db.add(Settlement(company_id=1, campaign_id=cid, influencer_id=_camp(cid).influencer_id, status="confirmed",
                          final_payment=43954, sales_amount=500000, commission_rate=0.1, seller_type="프리랜서",
                          calc_version=sc.CALC_VERSION))
        db.commit(); db.close()
        self.c.post(f"/campaigns/{cid}/revenue", data={"revenue": "900000"})
        self.assertEqual(_camp(cid).actual_revenue, 900000)
        self.assertEqual(_settle(cid).final_payment, 43954)

    def test_상세에서_입력과_잘못된_값(self):
        cid, *_ = _setup(-10, -1, status="completed")
        r = self.c.post(f"/campaigns/{cid}/revenue", data={"revenue": "-5"})
        self.assertIn("err=", r.headers["location"])
        r = self.c.post(f"/campaigns/{cid}/revenue", data={"revenue": "abc"})
        self.assertIn("err=", r.headers["location"])
        self.c.post(f"/campaigns/{cid}/revenue", data={"revenue": "200000"})
        self.assertIsNotNone(_settle(cid))

    def test_상세에서_종료일_지난_공구는_완료로_바꾸고_정산서(self):
        cid, *_ = _setup(-10, -2)                                            # 끝났는데 상태 active
        self.assertIn('name="complete_if_ended"', self.c.get(f"/campaigns/{cid}").text)
        self.c.post(f"/campaigns/{cid}/revenue", data={"revenue": "150000", "complete_if_ended": "1"})
        self.assertEqual(_camp(cid).status, "completed")
        self.assertIsNotNone(_settle(cid))

    def test_다른_회사_공구는_건드리지_못한다(self):
        other, *_ = _setup(-10, -2, company_id=2)
        self.c.post("/campaigns/revenue", data={"tab": "ended", f"rev_{other}": "999"})
        self.c.post(f"/campaigns/{other}/revenue", data={"revenue": "999"})
        self.assertFalse(_camp(other).actual_revenue)

    def test_화면이_열린다(self):
        for u in ("/campaigns/revenue", "/campaigns/revenue?tab=active", "/campaigns/revenue?tab=all", "/campaigns/revenue/paste"):
            self.assertEqual(self.c.get(u).status_code, 200, u)


class PasteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = client_for(make_user("admin", company_id=1))

    def test_붙여넣기_해석(self):
        rows = _parse_paste("공구명\t매출\t수량\nA공구\t1,234,000\t40\nB공구, 560000\nC공구  98,000원\nD공구: 50000\n합계\t1892000")
        self.assertEqual([(r["key"], r["revenue"], r["sales"]) for r in rows if r["revenue"]],
                         [("A공구", 1234000.0, 40), ("B공구", 560000.0, None), ("C공구", 98000.0, None),
                          ("D공구", 50000.0, None), ("합계", 1892000.0, None)])

    def test_짝짓기_미리보기와_고른것만_저장(self):
        cid, cname, pname, iname = _setup(-10, -2)
        cid2, *_ = _setup(-10, -3)
        text = f"{cname}\t700000\n{pname} {iname}\t800000\n없는공구{uid()}\t5000"
        page = self.c.post("/campaigns/revenue/paste", data={"text": text}).text
        self.assertIn("못 찾음", page)
        self.assertIsNone(_camp(cid).actual_revenue or None)           # 미리보기는 저장 안 함
        r = self.c.post("/campaigns/revenue/paste/apply", data={
            "complete_if_ended": "1", "camp_1": cid, "rev_1": "700000", "qty_1": "",
            "camp_2": "", "rev_2": "800000", "qty_2": "",                 # 저장 안 함 선택
            "camp_3": cid2, "rev_3": "", "qty_3": "",                      # 숫자 없음 → 건너뜀
        })
        self.assertIn("msg=", r.headers["location"])
        self.assertEqual(_camp(cid).actual_revenue, 700000)
        self.assertEqual(_camp(cid).status, "completed")
        self.assertFalse(_camp(cid2).actual_revenue)


if __name__ == "__main__":
    unittest.main()
