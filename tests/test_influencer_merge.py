"""인플루언서 중복 합치기 (T9).

- 같은 아이디(복사 찌꺼기·@·대소문자 무시)끼리 묶고, 기록 많은 줄·진짜 이름 줄을 남길 줄로 추천한다
- 합치면 남길 줄의 빈 칸만 채우고, 캠페인·정산 기록을 옮기고, 나머지는 지우지 않고 보관한다
- 계좌 등 값이 서로 다르면 합치지 않는다
- 되돌리면 기록과 칸이 원래대로 돌아간다
- 다른 회사 인플루언서는 합치지 못한다 (RG-002)
- 관리자만 합칠 수 있다
"""
from tests import _env  # noqa: F401  (app 보다 먼저)
from tests._env import SessionLocal, client_for, make_user, uid

import unittest

from app.models.campaign import Campaign
from app.models.influencer import Influencer
from app.models.influencer_merge_log import InfluencerMergeLog
from app.models.settlement import Settlement
from app.services import influencer_merge as im

CID = 2


def _inf(**kw):
    db = SessionLocal()
    try:
        kw.setdefault("company_id", CID)
        kw.setdefault("platform", "instagram")
        i = Influencer(**kw)
        db.add(i)
        db.commit()
        return i.id
    finally:
        db.close()


def _campaign(iid, company_id=CID):
    db = SessionLocal()
    try:
        c = Campaign(name=f"가상공구{uid()}", influencer_id=iid, company_id=company_id)
        db.add(c)
        db.commit()
        return c.id
    finally:
        db.close()


def _get(model, oid):
    db = SessionLocal()
    try:
        return db.get(model, oid)
    finally:
        db.close()


class MergeTest(unittest.TestCase):
    def setUp(self):
        db = SessionLocal()
        db.query(InfluencerMergeLog).filter(InfluencerMergeLog.company_id == CID).delete()
        db.query(Influencer).filter(Influencer.company_id == CID).update({"is_archived": True})
        db.commit()
        db.close()
        self.h = "dup_" + uid()

    def _groups(self):
        db = SessionLocal()
        try:
            return [g for g in im.find_groups(db, CID) if g["key"] == self.h]
        finally:
            db.close()

    def test_기록많고_진짜이름인_줄을_남길줄로_추천한다(self):
        bare = _inf(name=self.h, handle=self.h)                                   # 아이디만 적힌 줄
        real = _inf(name="가상릴리맘", handle=f"@{self.h.upper()} ·", followers=16000)
        _campaign(real)
        g = self._groups()
        self.assertEqual(len(g), 1)
        self.assertEqual(g[0]["keeper_id"], real)
        self.assertEqual({m["inf"].id for m in g[0]["members"]}, {bare, real})
        self.assertEqual(g[0]["blocked"], [])

    def test_합치면_빈칸만_채우고_기록을_옮기고_보관한다(self):
        keep = _inf(name=self.h, handle=self.h, contact_phone="010-1111-2222", categories=["뷰티"])
        other = _inf(name="가상사당이네", handle=self.h, followers=11000, bank_name="가상은행",
                     contact_phone="01011112222", categories=["푸드"], sheet_code="SEL-9" + uid()[:3])
        cid1, cid2 = _campaign(keep), _campaign(other)
        db = SessionLocal()
        s = Settlement(influencer_id=other, company_id=CID)
        db.add(s); db.commit(); sid = s.id; db.close()
        code = _get(Influencer, other).sheet_code

        db = SessionLocal()
        logs = im.merge_group(db, CID, keep, [other], by="tester")
        db.close()
        self.assertEqual(len(logs), 1)
        k, o = _get(Influencer, keep), _get(Influencer, other)
        self.assertEqual(k.name, "가상사당이네")                 # 아이디만 적힌 이름 → 진짜 이름
        self.assertEqual(k.followers, 11000)
        self.assertEqual(k.bank_name, "가상은행")                # 빈 칸 채움
        self.assertEqual(k.contact_phone, "010-1111-2222")      # 있던 값은 그대로 (숫자만 같으면 충돌 아님)
        self.assertEqual(k.categories, ["뷰티", "푸드"])
        self.assertEqual(k.sheet_code, code)                    # 시트 연결은 남길 줄로
        self.assertTrue(o.is_archived)
        self.assertIsNone(o.sheet_code)
        self.assertIn("[병합", o.notes)
        self.assertEqual(_get(Campaign, cid2).influencer_id, keep)
        self.assertEqual(_get(Campaign, cid1).influencer_id, keep)
        self.assertEqual(_get(Settlement, sid).influencer_id, keep)
        self.assertEqual(self._groups(), [])                    # 더 이상 중복 아님

    def test_되돌리면_원래대로(self):
        keep = _inf(name=self.h, handle=self.h)
        other = _inf(name="가상온맘", handle=self.h, followers=39000, sheet_code="SEL-8" + uid()[:3])
        c = _campaign(other)
        code = _get(Influencer, other).sheet_code
        db = SessionLocal()
        log_id = im.merge_group(db, CID, keep, [other])[0].id
        im.undo(db, CID, log_id)
        db.close()
        k, o = _get(Influencer, keep), _get(Influencer, other)
        self.assertFalse(o.is_archived)
        self.assertEqual(o.sheet_code, code)
        self.assertEqual((k.name, k.followers or 0, k.sheet_code), (self.h, 0, None))
        self.assertEqual(_get(Campaign, c).influencer_id, other)
        self.assertIsNotNone(_get(InfluencerMergeLog, log_id).undone_at)
        with self.assertRaises(ValueError):                      # 두 번 되돌리기 불가
            db = SessionLocal()
            try:
                im.undo(db, CID, log_id)
            finally:
                db.close()

    def test_계좌가_서로_다르면_합치지_않는다(self):
        a = _inf(name="가상A", handle=self.h, account_number="111-222")
        b = _inf(name="가상B", handle=self.h, account_number="999-888")
        g = self._groups()
        self.assertTrue(any("account_number" in x for x in g[0]["blocked"]))
        db = SessionLocal()
        with self.assertRaises(ValueError):
            im.merge_group(db, CID, a, [b])
        db.close()
        self.assertFalse(_get(Influencer, b).is_archived)

    def test_다른_회사_인플루언서는_합치지_못한다(self):
        a = _inf(name="가상A", handle=self.h)
        b = _inf(name="가상B", handle=self.h, company_id=1)
        db = SessionLocal()
        with self.assertRaises(ValueError):
            im.merge_group(db, CID, a, [b])
        db.close()
        self.assertFalse(_get(Influencer, b).is_archived)

    def test_예약어_아이디는_중복으로_묶지_않는다(self):
        _inf(name="가상A", handle="reels")
        _inf(name="가상B", handle="reels")
        db = SessionLocal()
        try:
            self.assertFalse([g for g in im.find_groups(db, CID) if g["key"] == "reels"])
        finally:
            db.close()

    def test_세줄_묶음에서_나머지끼리_계좌가_다르면_막는다(self):
        a = _inf(name="가상A", handle=self.h)                           # 남길 줄 후보 — 계좌 빔
        b = _inf(name="가상B", handle=self.h, account_number="111")
        c = _inf(name="가상C", handle=self.h, account_number="222")
        _campaign(a); _campaign(a)
        g = self._groups()
        self.assertTrue(any("account_number" in x for x in g[0]["blocked"]))
        db = SessionLocal()
        with self.assertRaises(ValueError):
            im.merge_group(db, CID, a, [b, c])
        db.close()
        self.assertFalse(_get(Influencer, b).is_archived)

    def test_블랙리스트가_섞이면_막는다(self):
        a = _inf(name="가상A", handle=self.h, status="active")
        b = _inf(name="가상B", handle=self.h, status="blacklist")
        self.assertTrue(any("블랙리스트" in x for x in self._groups()[0]["blocked"]))

    def test_되돌리기는_최근_것부터(self):
        a = _inf(name="가상A", handle=self.h, notes="A메모")
        b = _inf(name="가상B", handle=self.h, notes="B메모")
        c = _inf(name="가상C", handle=self.h, notes="C메모")
        db = SessionLocal()
        l1 = im.merge_group(db, CID, a, [b])[0].id
        l2 = im.merge_group(db, CID, a, [c])[0].id
        with self.assertRaises(ValueError):                       # 먼저 합친 B 부터는 못 되돌린다
            im.undo(db, CID, l1)
        im.undo(db, CID, l2)
        im.undo(db, CID, l1)
        db.close()
        self.assertEqual(_get(Influencer, a).notes, "A메모")
        self.assertFalse(_get(Influencer, b).is_archived)
        self.assertFalse(_get(Influencer, c).is_archived)

    def test_합친_뒤_직접_고친_칸은_되돌리기가_덮지_않는다(self):
        a = _inf(name=self.h, handle=self.h)
        b = _inf(name="가상진짜이름", handle=self.h, bank_name="가상은행")
        db = SessionLocal()
        log_id = im.merge_group(db, CID, a, [b])[0].id
        db.close()
        db = SessionLocal()
        k = db.get(Influencer, a); k.bank_name = "직원이고친은행"; db.commit(); db.close()
        db = SessionLocal()
        log = im.undo(db, CID, log_id)
        db.close()
        self.assertIn("bank_name", log.skipped)
        self.assertEqual(_get(Influencer, a).bank_name, "직원이고친은행")
        self.assertEqual(_get(Influencer, a).name, self.h)         # 안 고친 칸은 원래대로

    def test_남긴줄이_다시_합쳐졌으면_되돌리지_않는다(self):
        a = _inf(name="가상A", handle=self.h)
        b = _inf(name="가상B", handle=self.h)
        db = SessionLocal()
        log_id = im.merge_group(db, CID, a, [b])[0].id
        k = db.get(Influencer, a); k.is_archived = True; db.commit()
        with self.assertRaises(ValueError):
            im.undo(db, CID, log_id)
        db.close()

    def test_시트번호가_둘다_있으면_막지않고_지울_줄로_알려준다(self):
        a = _inf(name="가상A", handle=self.h, sheet_code="SEL-A" + uid()[:4])
        b = _inf(name=self.h, handle=self.h, sheet_code="SEL-B" + uid()[:4])
        _campaign(a)
        ca, cb = _get(Influencer, a).sheet_code, _get(Influencer, b).sheet_code
        self.assertEqual(self._groups()[0]["blocked"], [])
        db = SessionLocal()
        im.merge_group(db, CID, a, [b])
        lst = im.sheet_cleanup_list(db, CID)
        db.close()
        self.assertEqual(_get(Influencer, a).sheet_code, ca)
        self.assertEqual(_get(Influencer, b).sheet_code, cb)       # 보관 줄이 자기 번호를 그대로
        row = [r for r in lst if r["delete_code"] == cb]
        self.assertEqual(len(row), 1)
        self.assertEqual(row[0]["keep_code"], ca)


class SheetImportArchivedTest(unittest.TestCase):
    def test_이름으로_찾을때_보관된_인플루언서는_고르지_않는다(self):
        from app.integrations.sheets_import import _find
        name = "가상동명" + uid()
        old = _inf(name=name, handle="o" + uid(), is_archived=True)
        db = SessionLocal()
        try:
            self.assertIsNone(_find(db, Influencer, CID, None, "name", name, skip_archived_by_name=True))
            self.assertEqual(_find(db, Influencer, CID, None, "name", name).id, old)   # 기본 동작은 그대로
        finally:
            db.close()


class MergeScreenTest(unittest.TestCase):
    def test_화면과_권한(self):
        h = "scr_" + uid()
        a = _inf(name="가상A", handle=h)
        b = _inf(name="가상B", handle=h)
        admin = client_for(make_user("admin", company_id=CID))
        staff = client_for(make_user("staff", company_id=CID))
        r = admin.get("/influencers/duplicates")
        self.assertEqual(r.status_code, 200)
        self.assertIn(f"@{h}", r.text)
        r = staff.post("/influencers/duplicates/merge", data={"keeper_id": a, "member_ids": f"{a},{b}"})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(_get(Influencer, b).is_archived)        # 직원은 못 합친다
        r = admin.post("/influencers/duplicates/merge", data={"keeper_id": a, "member_ids": f"{a},{b}"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("msg=", r.headers["location"])
        self.assertTrue(_get(Influencer, b).is_archived)


if __name__ == "__main__":
    unittest.main()
