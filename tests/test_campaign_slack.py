"""캠페인 → Slack 02: 새 등록 [오픈예정] 1회, 대량 등록은 요약 1통, 첫 스캔은 기준점만(알림 폭탄 없음),
일정 변경 [일정변경] 1회 · 왔다갔다 해도 매번, 보관 캠페인 제외, 아침 보고 태그·하루 1회."""
from tests import _env
from tests._env import SessionLocal, uid

import unittest
from datetime import date, datetime, timedelta
from unittest import mock

from app.config import settings
from app.models.campaign import Campaign
from app.models.slack_notification_log import SlackNotificationLog
from app.services import campaign_slack, slack_notify
from tests.test_slack_notify import _FakeClient

CID = 2   # 다른 테스트의 캠페인(회사 1)과 섞이지 않게


def _mk(name=None, start=None, end=None, created_ago=timedelta(0), archived=False):
    db = SessionLocal()
    try:
        c = Campaign(company_id=CID, name=name or f"가상캠페인{uid()}", start_date=start, end_date=end,
                     is_archived=archived, created_at=datetime.utcnow() - created_ago)
        db.add(c); db.commit()
        return c.id
    finally:
        db.close()


def _set_dates(cid_, start, end):
    db = SessionLocal()
    try:
        c = db.query(Campaign).get(cid_); c.start_date, c.end_date = start, end; db.commit()
    finally:
        db.close()


def _archive_all():
    db = SessionLocal()
    try:
        db.query(Campaign).filter(Campaign.company_id == CID).update({"is_archived": True})
        db.query(SlackNotificationLog).filter(SlackNotificationLog.company_id == CID).delete()
        db.commit()
    finally:
        db.close()


def _scan():
    db = SessionLocal()
    try:
        return campaign_slack.scan(db, CID)
    finally:
        db.close()


def _texts():
    return [p["text"] for m, p, _ in _FakeClient.calls if m == "chat.postMessage"]


class CampaignSlackBase(unittest.TestCase):
    def setUp(self):
        _env.seed_companies()
        _archive_all()   # 테스트마다 깨끗한 상태
        self._saved = {k: getattr(settings, k) for k in
                       ("alert_mock", "slack_bot_token", "slack_channels", "slack_events")}
        settings.alert_mock = False
        settings.slack_bot_token = "xoxb-test-only"
        settings.slack_channels = "groupbuy=C0GROUPBUY1"
        settings.slack_events = "campaign_created,campaign_schedule_changed,campaign_digest"
        _FakeClient.calls = []
        _FakeClient.post_result = {"ok": True}
        _FakeClient.post_status = 200
        self._patch = mock.patch.object(slack_notify.httpx, "Client", _FakeClient)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        for k, v in self._saved.items():
            setattr(settings, k, v)


class CampaignSlackTests(CampaignSlackBase):
    def test_새_캠페인은_오픈예정으로_한_번만(self):
        name = f"신규공구{uid()}"
        _mk(name, date(2026, 10, 1), date(2026, 10, 7))
        first = _scan(); second = _scan()
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        created = [t for t in _texts() if t.startswith("[오픈예정]")]
        self.assertEqual(len(created), 1)
        self.assertIn(name, created[0]); self.assertIn("10/01 ~ 10/07", created[0])

    def test_오래된_캠페인은_새_등록으로_알리지_않는다(self):
        _mk(created_ago=timedelta(days=3))
        self.assertEqual(_scan()["created"], 0)
        self.assertFalse([t for t in _texts() if t.startswith("[오픈예정]")])

    def test_대량_등록은_요약_한_통(self):
        for _ in range(8):
            _mk()
        out = _scan(); again = _scan()
        created = [t for t in _texts() if t.startswith("[오픈예정]")]
        self.assertEqual(len(created), 1)
        self.assertIn("8건", created[0]); self.assertIn("외 3건", created[0])
        self.assertEqual(out["created_batched"], 8)
        self.assertEqual(again["created"] + again["created_batched"], 0)

    def test_첫_스캔은_기준점만_남기고_일정변경을_보내지_않는다(self):
        for _ in range(3):
            _mk(start=date(2026, 9, 1), end=date(2026, 9, 5), created_ago=timedelta(days=5))
        out = _scan()
        self.assertEqual(out["baseline"], 3)
        self.assertEqual(out["schedule_changed"], 0)
        self.assertEqual(_texts(), [])

    def test_일정이_바뀌면_전후를_알리고_한_번만(self):
        cid_ = _mk(f"변경공구{uid()}", date(2026, 9, 1), date(2026, 9, 5), created_ago=timedelta(days=5))
        _scan()
        _set_dates(cid_, date(2026, 9, 1), date(2026, 9, 10))
        out = _scan(); again = _scan()
        self.assertEqual(out["schedule_changed"], 1)
        self.assertEqual(again["schedule_changed"], 0)
        msg = [t for t in _texts() if t.startswith("[일정변경]")]
        self.assertEqual(len(msg), 1)
        self.assertIn("09/01 ~ 09/05", msg[0]); self.assertIn("09/01 ~ 09/10", msg[0])

    def test_일정이_왔다갔다해도_매번_알린다(self):
        a, b = (date(2026, 9, 1), date(2026, 9, 5)), (date(2026, 9, 1), date(2026, 9, 9))
        cid_ = _mk(start=a[0], end=a[1], created_ago=timedelta(days=5))
        _scan()
        for dates in (b, a, b):
            _set_dates(cid_, *dates); _scan()
        self.assertEqual(len([t for t in _texts() if t.startswith("[일정변경]")]), 3)

    def test_발송이_실패한_일정변경은_다음_스캔에_다시_보낸다(self):
        cid_ = _mk(start=date(2026, 9, 1), end=date(2026, 9, 5), created_ago=timedelta(days=5))
        _scan()
        _set_dates(cid_, date(2026, 9, 2), date(2026, 9, 5))
        _FakeClient.post_result = {"ok": False, "error": "internal_error"}
        self.assertEqual(_scan()["schedule_changed"], 0)
        _FakeClient.post_result = {"ok": True}
        self.assertEqual(_scan()["schedule_changed"], 1)

    def test_보관된_캠페인은_제외(self):
        _mk(archived=True)
        out = _scan()
        self.assertEqual(out["created"] + out["baseline"], 0)

    def test_이벤트가_꺼져_있으면_아무것도_하지_않는다(self):
        settings.slack_events = ""
        _mk()
        out = _scan()
        self.assertEqual(sum(out.values()), 0)
        self.assertEqual(_FakeClient.calls, [])

    def test_아침_보고는_태그를_붙여_하루_한_번(self):
        db = SessionLocal()
        try:
            first = campaign_slack.send_digest(db, company_id=CID)
            second = campaign_slack.send_digest(db, company_id=CID)
        finally:
            db.close()
        self.assertTrue(first["sent"], first)
        self.assertEqual(second["status"], "duplicate")
        self.assertTrue(_texts()[0].startswith("*[BP OS]"))

    def test_mock에서_실발송으로_바꿔도_알림_폭탄이_없다(self):
        """리뷰 재현: mock 기간에 알린 일정 변경이 실발송 전환 때 다시 쏟아지면 안 된다."""
        settings.alert_mock = True
        ids = [_mk(start=date(2026, 9, 1), end=date(2026, 9, 5), created_ago=timedelta(days=5)) for _ in range(4)]
        _scan()
        for i in ids:
            _set_dates(i, date(2026, 9, 1), date(2026, 9, 20))
        _scan(); _scan()
        settings.alert_mock = False
        out = _scan()
        self.assertEqual(out["schedule_changed"] + out["schedule_batched"], 0)
        self.assertEqual(_texts(), [])

    def test_mock으로_알린_새_캠페인은_전환_후_다시_안_나간다(self):
        settings.alert_mock = True
        _mk(); _scan()
        settings.alert_mock = False
        self.assertEqual(_scan()["created"], 0)
        self.assertEqual(_texts(), [])

    def test_일정을_한꺼번에_바꾸면_요약_한_통(self):
        ids = [_mk(start=date(2026, 9, 1), end=date(2026, 9, 5), created_ago=timedelta(days=5)) for _ in range(7)]
        _scan()
        for i in ids:
            _set_dates(i, date(2026, 9, 2), date(2026, 9, 6))
        out = _scan(); again = _scan()
        msgs = [t for t in _texts() if t.startswith("[일정변경]")]
        self.assertEqual(len(msgs), 1)
        self.assertIn("7건", msgs[0]); self.assertIn("외 2건", msgs[0])
        self.assertEqual(out["schedule_batched"], 7)
        self.assertEqual(again["schedule_changed"] + again["schedule_batched"], 0)

    def test_계속_실패하면_3번_뒤_포기한다(self):
        cid_ = _mk(start=date(2026, 9, 1), end=date(2026, 9, 5), created_ago=timedelta(days=5))
        _scan()
        _set_dates(cid_, date(2026, 9, 3), date(2026, 9, 5))
        _FakeClient.post_result = {"ok": False, "error": "not_in_channel"}
        fails = [_scan()["failed"] for _ in range(5)]
        self.assertEqual(fails, [1, 1, 1, 0, 0])
        self.assertEqual(len(_texts()), 3)

    def test_날짜를_처음_채우면_일정변경으로_알리지_않는다(self):
        cid_ = _mk(created_ago=timedelta(days=5))   # 날짜 없이 등록
        _scan()
        _set_dates(cid_, date(2026, 10, 1), date(2026, 10, 7))
        self.assertEqual(_scan()["schedule_changed"], 0)
        _set_dates(cid_, date(2026, 10, 1), date(2026, 10, 9))   # 그 뒤 변경은 알린다
        self.assertEqual(_scan()["schedule_changed"], 1)

    def test_요약_도중_멈춘_선점은_10분_뒤_다시_처리된다(self):
        cid_ = _mk()
        db = SessionLocal()
        db.add(SlackNotificationLog(company_id=CID, event="campaign_created", channel="groupbuy",
                                    dedupe_key=f"campaign_created:{cid_}", status="sending",
                                    created_at=datetime.utcnow() - timedelta(minutes=15)))
        db.commit(); db.close()
        self.assertEqual(_scan()["created"], 1)


if __name__ == "__main__":
    unittest.main()
