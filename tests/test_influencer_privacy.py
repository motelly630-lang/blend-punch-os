"""인플루언서 개인정보: 주민등록번호는 OS 에 저장하지 않는다 (DE-005) — 등록·수정 폼으로 보내도 무시하고,
수정하면 남아 있던 값도 지운다. 폼·정산 상세에 주민번호 입력·표시가 없다."""
from tests import _env
from tests._env import SessionLocal, client_for, make_user, uid

import unittest

from app.models.influencer import Influencer

RRN = "900101-1234567"   # 가짜 값


def _form(**kw):
    base = {"name": f"가상셀러{uid()}", "platform": "instagram", "handle": f"h{uid()}",
            "business_type": "프리랜서", "legal_name": "가상실명", "resident_registration_number": RRN}
    base.update(kw)
    return base


def _get(**filt):
    db = SessionLocal()
    try:
        return db.query(Influencer).filter_by(**filt).first()
    finally:
        db.close()


class ResidentNumberNotStored(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = client_for(make_user("admin", company_id=1))

    def test_등록할_때_주민번호를_보내도_저장하지_않는다(self):
        f = _form()
        r = self.c.post("/influencers/new", data=f)
        self.assertIn(r.status_code, (302, 303), r.text[:200])
        inf = _get(handle=f["handle"])
        self.assertIsNotNone(inf)
        self.assertIsNone(inf.resident_registration_number)
        self.assertEqual(inf.legal_name, "가상실명")   # 다른 정산 정보는 그대로 저장

    def test_수정하면_남아있던_주민번호도_지운다(self):
        db = SessionLocal()
        try:
            inf = Influencer(company_id=1, name=f"가상셀러{uid()}", platform="instagram", handle=f"h{uid()}",
                             resident_registration_number=RRN)
            db.add(inf); db.commit(); iid, handle = inf.id, inf.handle
        finally:
            db.close()
        r = self.c.post(f"/influencers/{iid}/edit", data=_form(handle=handle))
        self.assertIn(r.status_code, (302, 303), r.text[:200])
        self.assertIsNone(_get(id=iid).resident_registration_number)

    def test_등록_화면에_주민번호_입력칸이_없다(self):
        r = self.c.get("/influencers/new")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('name="resident_registration_number"', r.text)
        self.assertIn("주민등록번호는 OS 에 저장하지 않아요", r.text)


if __name__ == "__main__":
    unittest.main()
