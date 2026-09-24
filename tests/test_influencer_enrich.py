"""인플루언서 일괄 보강 (T4, DE-006): Meta 공식 조회로 천천히·안전하게 채운다.

- 팔로워·사진·프로필주소를 채우고, 사람이 올린 사진은 덮지 않는다
- 개인 계정(조회 불가)은 실패로 적고 30일간 다시 건드리지 않는다
- 한도 초과·토큰 끊김은 그 사람을 실패로 적지 않고 실행을 멈춘다 (다음 실행에서 다시)
- Meta 사용량이 기준(%)에 닿으면 스스로 멈춘다
- 사진만 비어 있는 사람도 대상이다
"""
from tests import _env  # noqa: F401  (app 보다 먼저)
from tests._env import SessionLocal, client_for, make_user, uid

import unittest
from unittest import mock

from app.models.influencer import Influencer
from app.services import influencer_enrich as ie
from app.services import meta_instagram as mi

CID = 2   # 다른 테스트 데이터와 섞이지 않게 회사 2 에서만 돌린다


def _mk(**kw):
    db = SessionLocal()
    try:
        i = Influencer(name="가상셀러", platform="instagram", handle="h_" + uid(), company_id=CID, **kw)
        db.add(i)
        db.commit()
        return i.id
    finally:
        db.close()


def _get(iid):
    db = SessionLocal()
    try:
        return db.get(Influencer, iid)
    finally:
        db.close()


def _profile(followers=12345):
    return lambda h: {"handle": h, "display_name": "소개문구", "followers": followers, "media_count": 1,
                      "biography": "", "profile_picture_url": "https://scontent.cdninstagram.com/x.jpg"}


class EnrichTest(unittest.TestCase):
    def setUp(self):
        # 회사 2 의 이전 대상은 전부 정리해 순서가 섞이지 않게 한다
        db = SessionLocal()
        db.query(Influencer).filter(Influencer.company_id == CID).delete()
        db.commit()
        db.close()
        self.p = [mock.patch.object(mi, "available", return_value=True),
                  mock.patch.object(mi, "save_profile_image", return_value="/static/uploads/influencers/fake.jpg"),
                  mock.patch.object(mi, "last_usage_pct", 5.0)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def _run(self, fetch, limit=10):
        with mock.patch.object(mi, "fetch_profile", side_effect=fetch):
            db = SessionLocal()
            try:
                return ie.enrich_batch(db, company_id=CID, limit=limit, sleep=False)
            finally:
                db.close()

    def test_팔로워_사진_주소를_채운다(self):
        iid = _mk()
        rep = self._run(_profile())
        self.assertEqual((rep["source"], rep["updated"], rep["failed"]), ("meta", 1, 0))
        i = _get(iid)
        self.assertEqual(i.followers, 12345)
        self.assertEqual(i.profile_image, "/static/uploads/influencers/fake.jpg")
        self.assertTrue(i.profile_url.endswith(f"/{i.handle}/"))
        self.assertIsNotNone(i.enriched_at)
        self.assertEqual(i.name, "가상셀러")          # 이름은 건드리지 않는다

    def test_사람이_올린_사진은_덮지_않고_사진만_빈_사람도_대상(self):
        keep = _mk(profile_image="/static/uploads/influencers/manual.jpg")      # 팔로워만 빔
        photo_only = _mk(followers=500)                                          # 사진만 빔
        rep = self._run(_profile(800))
        self.assertEqual(rep["updated"], 2)
        self.assertEqual(_get(keep).profile_image, "/static/uploads/influencers/manual.jpg")
        self.assertEqual(_get(photo_only).profile_image, "/static/uploads/influencers/fake.jpg")
        self.assertEqual(_get(photo_only).followers, 800)

    def test_개인계정은_실패로_적고_다시_건드리지_않는다(self):
        iid = _mk()

        def fetch(h):
            raise mi.MetaError("조회할 수 없는 계정이에요", "notfound")
        rep = self._run(fetch)
        self.assertEqual((rep["failed"], rep["aborted"]), (1, False))
        self.assertIn("조회할 수 없는", _get(iid).enrich_error)
        self.assertEqual(self._run(_profile())["picked"], 0)     # 30일 안에는 대상 아님

    def test_한도초과면_기록하지_않고_멈춘다(self):
        a, b = _mk(), _mk()

        def fetch(h):
            raise mi.MetaError("Meta 조회 한도에 걸렸어요", "rate")
        rep = self._run(fetch)
        self.assertTrue(rep["aborted"])
        self.assertFalse(rep["ok"])
        self.assertIsNone(_get(a).enriched_at)                   # 다음 실행에서 다시 시도
        self.assertIsNone(_get(b).enriched_at)
        self.assertEqual(self._run(_profile())["updated"], 2)

    def test_토큰이_끊기면_멈춘다(self):
        _mk()

        def fetch(h):
            raise mi.MetaError("Meta 토큰이 만료됐거나 끊겼어요", "token")
        rep = self._run(fetch)
        self.assertTrue(rep["aborted"])
        self.assertEqual(rep["failed"], 0)

    def test_사용량이_기준에_닿으면_스스로_멈춘다(self):
        for _ in range(3):
            _mk()
        with mock.patch.object(mi, "last_usage_pct", ie.USAGE_STOP_PCT):
            rep = self._run(_profile())
        self.assertEqual(rep["updated"], 1)
        self.assertTrue(rep["aborted"])
        self.assertIn("사용량", rep["error"])
        self.assertEqual(rep["remaining"], 2)

    def test_미리보기는_외부에_접속하지_않는다(self):
        _mk()
        with mock.patch.object(mi, "fetch_profile", side_effect=AssertionError("호출되면 안 됨")):
            db = SessionLocal()
            try:
                rep = ie.enrich_batch(db, company_id=CID, limit=5, dry_run=True)
            finally:
                db.close()
        self.assertEqual((rep["picked"], rep["rows"][0]["action"]), (1, "예정"))

    def test_복사_찌꺼기가_붙은_아이디도_정리해서_조회한다(self):
        db = SessionLocal()
        i = Influencer(name="가상셀러", platform="instagram", handle="@uu._.home ·", company_id=CID)
        db.add(i); db.commit(); iid = i.id; db.close()
        seen = []

        def fetch(h):
            seen.append(h)
            return _profile()(h)
        rep = self._run(fetch)
        self.assertEqual(seen, ["uu._.home"])
        self.assertEqual(rep["updated"], 1)
        self.assertEqual(_get(iid).handle, "uu._.home")
        self.assertEqual(ie.clean_handle(" @abc.def/ "), "abc.def")

    def test_reels_같은_예약어_아이디는_조회하지_않는다(self):
        db = SessionLocal()
        a = Influencer(name="가상A", platform="instagram", handle="reels", company_id=CID,
                       profile_url="https://www.instagram.com/gasang_real/")
        b = Influencer(name="가상B", platform="instagram", handle="reels", company_id=CID,
                       profile_url="https://www.instagram.com/reels/C1abc/")
        c = Influencer(name="가상C", platform="instagram", handle="인스타그램", company_id=CID)
        db.add_all([a, b, c]); db.commit(); ids = (a.id, b.id, c.id); db.close()
        seen = []

        def fetch(h):
            seen.append(h)
            return _profile()(h)
        rep = self._run(fetch)
        self.assertEqual(seen, ["gasang_real"])                  # 'reels' 로는 절대 조회하지 않는다
        self.assertEqual((rep["updated"], rep["failed"]), (1, 2))
        self.assertEqual(_get(ids[0]).handle, "gasang_real")
        self.assertIn("잘못 저장", _get(ids[1]).enrich_error)
        self.assertEqual(_get(ids[1]).followers or 0, 0)


class UsageHeaderTest(unittest.TestCase):
    def test_사용량_헤더에서_가장_큰_값을_읽는다(self):
        self.assertEqual(mi._usage_pct({"x-app-usage": '{"call_count":12,"total_cputime":3,"total_time":40}'}), 40.0)
        buc = '{"123":[{"type":"instagram","call_count":55,"total_cputime":1,"total_time":2}]}'
        self.assertEqual(mi._usage_pct({"x-business-use-case-usage": buc}), 55.0)
        self.assertIsNone(mi._usage_pct({}))
        self.assertIsNone(mi._usage_pct({"x-app-usage": "깨진값"}))


class ListFilterTest(unittest.TestCase):
    """인플루언서 목록 '정보 상태' 필터 — 자동 조회 안 됨 / 팔로워·사진 비어 있음."""

    def test_자동조회_안된_사람과_빈_사람을_나눠_보여준다(self):
        user = make_user("admin", company_id=CID)
        db = SessionLocal()
        db.query(Influencer).filter(Influencer.company_id == CID).delete()
        tag = uid()
        rows = [Influencer(name=f"실패{tag}", platform="instagram", handle="a" + tag, company_id=CID,
                           enrich_error="조회할 수 없는 계정이에요"),
                Influencer(name=f"빈사람{tag}", platform="instagram", handle="b" + tag, company_id=CID),
                Influencer(name=f"채움{tag}", platform="instagram", handle="c" + tag, company_id=CID,
                           followers=100, profile_image="/x.jpg"),
                # 조회는 실패했지만 직원이 직접 채운 사람 → 더 이상 '안 됨' 목록에 없어야 한다
                Influencer(name=f"직접채움{tag}", platform="instagram", handle="d" + tag, company_id=CID,
                           followers=100, profile_image="/y.jpg", enrich_error="조회할 수 없는 계정이에요")]
        db.add_all(rows); db.commit(); db.close()
        c = client_for(user)
        failed = c.get("/influencers?view=list&data=failed").text
        empty = c.get("/influencers?view=list&data=empty").text
        self.assertIn(f"실패{tag}", failed)
        self.assertNotIn(f"빈사람{tag}", failed)
        self.assertNotIn(f"직접채움{tag}", failed)
        self.assertIn(f"빈사람{tag}", empty)
        self.assertNotIn(f"실패{tag}", empty)
        self.assertIn("자동 조회 안 됨 1", failed)
        self.assertIn("팔로워·사진 비어 있음 1", failed)


if __name__ == "__main__":
    unittest.main()
