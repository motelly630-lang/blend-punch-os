"""인플루언서 등록/편집 화면 — 간소화한 폼이 기존 값을 그대로 보여주고 저장하는지."""
import unittest

from tests._env import SessionLocal, client_for, make_user, uid
from app.models.influencer import Influencer


class InfluencerFormTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = client_for(make_user("admin", company_id=1))

    def _make(self, **kw) -> str:
        db = SessionLocal()
        try:
            i = Influencer(name="테스트", platform="instagram", handle="h_" + uid(), company_id=1, **kw)
            db.add(i)
            db.commit()
            return i.id
        finally:
            db.close()

    def test_폼이_보내는_주소가_실제_저장주소다(self):
        r = self.c.get("/influencers/new")
        self.assertIn('action="/influencers/new"', r.text)
        iid = self._make()
        r = self.c.get(f"/influencers/{iid}/edit")
        self.assertIn(f'action="/influencers/{iid}/edit"', r.text)

    def test_카테고리가_있어도_편집화면_속성이_깨지지_않는다(self):
        iid = self._make(categories=["뷰티", "푸드"])
        r = self.c.get(f"/influencers/{iid}/edit")
        self.assertEqual(r.status_code, 200)
        # JSON 큰따옴표가 그대로 들어가면 x-data="..." 속성이 중간에 끊긴다
        self.assertNotIn('selected: ["', r.text)
        self.assertIn("selected: [&#34;", r.text)

    def test_선택안한_유형의_칸은_비우고_나머지는_저장한다(self):
        h = "h_" + uid()
        r = self.c.post("/influencers/new", data={
            "name": "홍길동", "platform": "instagram", "handle": h,
            "categories_json": '["뷰티"]', "business_type": "프리랜서", "has_campaign_history": "true",
            "legal_name": "홍실명", "account_number": "3333",
            # 브라우저: 숨겨진 사업자 칸의 옛 값 + 뒤따르는 빈 hidden 칸
            "business_name": ["옛상호", ""],
        }, files={"profile_image": ("", b"", "application/octet-stream")})
        self.assertEqual(r.status_code, 302)
        db = SessionLocal()
        try:
            i = db.query(Influencer).filter_by(handle=h).first()
            self.assertEqual(i.categories, ["뷰티"])
            self.assertEqual(i.business_type, "프리랜서")
            self.assertEqual(i.has_campaign_history, "true")
            self.assertEqual(i.legal_name, "홍실명")
            self.assertEqual(i.account_number, "3333")
            self.assertFalse(i.business_name)
        finally:
            db.close()

    def test_추가정보에_값이_있으면_펼쳐서_보여준다(self):
        iid = self._make(past_gmv=5000000)
        r = self.c.get(f"/influencers/{iid}/edit")
        self.assertIn("showMore: true", r.text)
        self.assertIn('value="5000000"', r.text)


if __name__ == "__main__":
    unittest.main()
