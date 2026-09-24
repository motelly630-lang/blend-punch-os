"""공구 한 번에 등록 (대표님 2026-09-24).

- 인스타 주소 · 제품 이름 · 기간만으로 인플루언서 · 제품(작성 필요) · 브랜드(정보 입력 필요) · 캠페인을 만든다
- 같은 아이디의 인플루언서 · 같은 이름의 제품은 새로 만들지 않고 그대로 쓴다 (중복 방지)
- 잘못된 입력이면 아무것도 만들지 않는다
- 다른 회사 제품은 연결되지 않는다
"""
from tests import _env  # noqa: F401  (app 보다 먼저)
from tests._env import SessionLocal, client_for, make_user, uid

import unittest
from datetime import timedelta
from unittest import mock

from app.models.brand import Brand
from app.models.campaign import Campaign
from app.models.influencer import Influencer
from app.models.product import Product
from app.routers.campaigns import _kst_today
from app.services import meta_instagram as mi
from app.services import quick_campaign as qc


def _count(model, **kw):
    db = SessionLocal()
    try:
        return db.query(model).filter_by(**kw).count()
    finally:
        db.close()


class QuickTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = client_for(make_user("admin", company_id=1))

    def setUp(self):
        self.p = mock.patch.object(mi, "available", return_value=False)   # 기본: Meta 호출 안 함
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def _post(self, **data):
        r = self.c.post("/campaigns/quick", data=data)
        self.assertEqual(r.status_code, 302)
        return r.headers["location"]

    def test_모두_새로_만든다(self):
        h, prod, brand = "gasang" + uid(), "가상제품" + uid(), "가상브랜드" + uid()
        t = _kst_today()
        loc = self._post(insta=f"https://www.instagram.com/{h}/", influencer_name="가상맘", product_pick=prod,
                         brand_name=brand, groupbuy_price="29000", rate_pct="15",
                         start_date=(t - timedelta(1)).isoformat(), end_date=(t + timedelta(3)).isoformat(),
                         reel_url="https://www.instagram.com/reel/GasangReel1/?igsh=x")
        self.assertIn("/campaigns/", loc)
        self.assertIn("msg=", loc)
        db = SessionLocal()
        try:
            inf = db.query(Influencer).filter_by(handle=h).one()
            p = db.query(Product).filter_by(name=prod).one()
            camp = db.query(Campaign).filter_by(influencer_id=inf.id).one()
            self.assertEqual(inf.name, "가상맘")
            self.assertEqual((p.brand, p.category, p.is_complete), (brand, qc.UNCATEGORIZED, False))
            self.assertIn("카테고리", p.missing_fields)
            self.assertEqual(db.query(Brand).filter_by(name=brand).count(), 1)
            self.assertEqual((camp.product_id, camp.status, camp.seller_commission_rate), (p.id, "active", 0.15))
            self.assertEqual(camp.content_urls, ["https://www.instagram.com/reel/GasangReel1/"])
        finally:
            db.close()

    def test_있는_인플루언서와_제품은_그대로_쓴다(self):
        h = "gasang" + uid()
        db = SessionLocal()
        inf = Influencer(name="기존맘", platform="instagram", handle=f"@{h.upper()} ·", company_id=1)
        p = Product(name="기존제품" + uid(), brand="가상", category="식품", company_id=1, seller_commission_rate=0.2)
        db.add_all([inf, p]); db.commit(); iid, pid, pname = inf.id, p.id, p.name; db.close()
        self._post(insta=h, product_pick=f"{pname} · 가상  [#{pid}]")
        self._post(insta=f"instagram.com/{h}", product_pick=pname)          # 같은 이름이면 같은 제품
        self.assertEqual(_count(Influencer, company_id=1, name="기존맘"), 1)
        self.assertEqual(_count(Product, company_id=1, name=pname), 1)
        db = SessionLocal()
        try:
            camps = db.query(Campaign).filter_by(influencer_id=iid).all()
            self.assertEqual(len(camps), 2)
            self.assertTrue(all(c.product_id == pid and c.seller_commission_rate == 0.2 for c in camps))
        finally:
            db.close()

    def test_기간으로_상태를_정한다(self):
        t = _kst_today()
        self.assertEqual(qc.status_for(t + timedelta(2), t + timedelta(5), t), "planning")
        self.assertEqual(qc.status_for(t - timedelta(9), t - timedelta(2), t), "completed")
        self.assertEqual(qc.status_for(t, t, t), "active")
        self.assertEqual(qc.status_for(None, None, t), "planning")

    def test_잘못된_입력이면_아무것도_안_만든다(self):
        h, prod = "gasang" + uid(), "가상제품" + uid()
        for data in ({"insta": "https://www.instagram.com/reel/AbcDef123/", "product_pick": prod},   # 릴스 주소
                     {"insta": h, "product_pick": ""},                                               # 제품 없음
                     {"insta": h, "product_pick": prod, "reel_url": "https://example.com/x"},        # 이상한 릴스
                     {"insta": h, "product_pick": prod, "rate_pct": "150"}):
            loc = self._post(**data)
            self.assertIn("err=", loc)
        self.assertEqual(_count(Influencer, handle=h), 0)
        self.assertEqual(_count(Product, name=prod), 0)

    def test_다른_회사_제품은_연결되지_않는다(self):
        db = SessionLocal()
        other = Product(name="남의제품" + uid(), brand="남", category="식품", company_id=2)
        db.add(other); db.commit(); oid = other.id; db.close()
        loc = self._post(insta="gasang" + uid(), product_pick=f"남의제품  [#{oid}]")
        self.assertIn("err=", loc)
        self.assertEqual(_count(Campaign, product_id=oid), 0)

    def test_새_인플루언서는_메타로_팔로워를_채운다(self):
        h = "gasang" + uid()
        prof = {"handle": h, "display_name": "", "followers": 12345, "media_count": 1, "biography": "",
                "profile_picture_url": ""}
        with mock.patch.object(mi, "available", return_value=True), mock.patch.object(mi, "fetch_profile", return_value=prof):
            self._post(insta=h, product_pick="가상제품" + uid())
        db = SessionLocal()
        try:
            self.assertEqual(db.query(Influencer).filter_by(handle=h).one().followers, 12345)
            camp = db.query(Campaign).join(Influencer, Influencer.id == Campaign.influencer_id).filter(Influencer.handle == h).one()
            p = db.get(Product, camp.product_id)
            self.assertEqual(p.brand, qc.BRAND_UNKNOWN)          # 브랜드를 안 적으면 표시값 + 작성 필요
            self.assertIn("브랜드", p.missing_fields)
            self.assertEqual(db.query(Brand).filter_by(name=qc.BRAND_UNKNOWN).count(), 0)
        finally:
            db.close()

    def test_브랜드_정보_입력_필요_표시(self):
        name = "빈브랜드" + uid()
        db = SessionLocal()
        db.add(Brand(name=name, company_id=1)); db.commit(); db.close()
        r = self.c.get("/brands?need=1")
        self.assertEqual(r.status_code, 200)
        self.assertIn(name, r.text)
        self.assertIn("정보 입력 필요", r.text)
        self.assertEqual(self.c.get("/campaigns/quick").status_code, 200)


if __name__ == "__main__":
    unittest.main()
