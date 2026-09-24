"""공구 아카이브 (릴스 링크 → 영상 카드) · 캠페인 목록 가독성.

- 인스타 릴스·게시물·유튜브 링크만 받고, 추적 파라미터를 떼고 같은 링크는 한 번만 저장
- 아카이브: 진행 중 / 예정 / 지난 공구로 나눠 보이고, 다른 회사 공구는 안 보인다
"""
from tests import _env  # noqa: F401  (app 보다 먼저)
from tests._env import SessionLocal, client_for, make_user, uid

import unittest
from datetime import timedelta

from app.models.campaign import Campaign
from app.routers.campaigns import _kst_today
from app.services import content_embed as ce


class ParseTest(unittest.TestCase):
    def test_링크_해석(self):
        p = ce.parse("https://www.instagram.com/reel/DcAbC123xyz/?igsh=abc123")
        self.assertEqual((p["url"], p["embed"]), ("https://www.instagram.com/reel/DcAbC123xyz/",
                                                  "https://www.instagram.com/reel/DcAbC123xyz/embed/"))
        self.assertEqual(ce.parse("https://instagram.com/gasang_id/reel/DcAbC123xyz")["code"], "DcAbC123xyz")
        self.assertEqual(ce.parse("https://www.instagram.com/p/Dczh_u2j_-1/")["label"], "인스타 게시물")
        self.assertEqual(ce.parse("https://youtube.com/shorts/abcDEF12345")["embed"], "https://www.youtube.com/embed/abcDEF12345")
        self.assertIsNone(ce.parse("https://www.instagram.com/gasang_id/"))       # 프로필 주소는 아님
        self.assertIsNone(ce.parse("https://example.com/x"))


class GalleryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = client_for(make_user("admin", company_id=1))

    def _camp(self, s, e, company_id=1, **kw):
        t = _kst_today()
        db = SessionLocal()
        try:
            c = Campaign(name="가상공구" + uid(), company_id=company_id, start_date=t + timedelta(s),
                         end_date=t + timedelta(e), status="active", **kw)
            db.add(c); db.commit()
            return c.id, c.name
        finally:
            db.close()

    def test_링크_추가_중복_잘못된_링크_빼기(self):
        cid, _ = self._camp(-1, 3)
        url = "https://www.instagram.com/reel/DcAbC123xyz/?igsh=zz"
        self.c.post(f"/campaigns/{cid}/links", data={"url": url})
        self.c.post(f"/campaigns/{cid}/links", data={"url": "https://www.instagram.com/reel/DcAbC123xyz/"})
        r = self.c.post(f"/campaigns/{cid}/links", data={"url": "https://example.com/x"})
        self.assertIn("err=", r.headers["location"])
        db = SessionLocal()
        self.assertEqual(db.get(Campaign, cid).content_urls, ["https://www.instagram.com/reel/DcAbC123xyz/"])
        db.close()
        page = self.c.get(f"/campaigns/{cid}").text
        self.assertIn("https://www.instagram.com/reel/DcAbC123xyz/embed/", page)
        self.c.post(f"/campaigns/{cid}/links/remove", data={"url": "https://www.instagram.com/reel/DcAbC123xyz/"})
        db = SessionLocal()
        self.assertEqual(db.get(Campaign, cid).content_urls, [])
        db.close()

    def test_진행중_예정_지난_나눠보기와_회사_분리(self):
        _, active = self._camp(-2, 2)
        _, upcoming = self._camp(5, 10)
        _, past = self._camp(-20, -10, content_urls=["https://www.instagram.com/reel/PastReel123/"])
        _, other = self._camp(-2, 2, company_id=2)
        g = lambda show: self.c.get(f"/campaigns/gallery?show={show}").text
        a, u, p = g("active"), g("upcoming"), g("past")
        self.assertIn(active, a); self.assertNotIn(upcoming, a); self.assertNotIn(past, a)
        self.assertIn(upcoming, u); self.assertNotIn(active, u)
        self.assertIn(past, p); self.assertIn("PastReel123/embed/", p)
        self.assertNotIn(other, g("all"))

    def test_캠페인_목록에_급한_것_표시(self):
        self._camp(-3, 0)
        r = self.c.get("/campaigns")
        self.assertEqual(r.status_code, 200)
        self.assertIn("오늘 마감", r.text)


if __name__ == "__main__":
    unittest.main()
