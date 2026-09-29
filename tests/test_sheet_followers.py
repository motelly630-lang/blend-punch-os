"""통합시트 동기화가 OS 팔로워를 0 으로 덮지 않는다 (2026-09-29 운영 사고: 새벽 Meta 수집 597명이 10분 뒤 0 으로).

시트 팔로워 칸의 '0' 은 '모름' 으로 보고 건너뛴다. 진짜 숫자는 그대로 받는다.
"""
from tests import _env  # noqa: F401
from tests._env import SessionLocal, uid

import unittest

from app.integrations import sheets_bridge as sb
from app.integrations import sheets_import
from app.models.influencer import Influencer


class FollowersTest(unittest.TestCase):
    def test_시트의_0과_빈칸은_모름(self):
        for raw in ("0", " 0 ", "", "-", "0.0"):
            self.assertIsNone(sb.convert("followers", raw), raw)
        self.assertEqual(sb.convert("followers", "12,345"), 12345)

    def test_OS의_진짜_팔로워를_0으로_덮지_않는다(self):
        code, name = "SEL-T-" + uid(), "가상인플루언서" + uid()
        db = SessionLocal()
        db.add(Influencer(company_id=1, name=name, platform="instagram", handle="gasang" + uid(),
                          followers=104901, sheet_code=code))
        db.commit(); db.close()
        rows = [{"seller_id": code, "seller_name": name, "instagram_handle": "", "followers": "0"},
                {"seller_id": code, "seller_name": name, "instagram_handle": "", "followers": "5,000"}]
        db = SessionLocal()
        try:
            orig = sb.read_tab
            sb.read_tab = lambda tab, sh=None: (list(rows[0]), rows[:1])
            sheets_import.import_sellers(db, company_id=1, dry_run=False)
            db.commit()
            self.assertEqual(db.query(Influencer).filter_by(sheet_code=code).one().followers, 104901)
            sb.read_tab = lambda tab, sh=None: (list(rows[1]), rows[1:])      # 진짜 숫자는 받는다
            sheets_import.import_sellers(db, company_id=1, dry_run=False)
            db.commit()
            self.assertEqual(db.query(Influencer).filter_by(sheet_code=code).one().followers, 5000)
        finally:
            sb.read_tab = orig
            db.close()


if __name__ == "__main__":
    unittest.main()
