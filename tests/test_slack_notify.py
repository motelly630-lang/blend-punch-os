"""Slack 채널별 알림: 꺼진 이벤트는 안 나감, 같은 이벤트 한 번만(선점), mock 은 실발송 없음,
채널 키→채널 해석, 실패 기록·재시도, 기록 실패가 업무를 멈추거나 호출자 세션을 건드리지 않음."""
from tests import _env
from tests._env import SessionLocal, uid

import unittest
from datetime import datetime, timedelta
from unittest import mock

from app.config import settings
from app.models.slack_notification_log import SlackNotificationLog
from app.models.feature_flag import Company
from app.services import slack_notify

CID = 1


class _Resp:
    def __init__(self, data, status=200, headers=None):
        self._d = data
        self.status_code = status
        self.headers = headers or {}

    def json(self):
        return self._d


class _FakeClient:
    """httpx.Client 대역 — 호출을 기록하고 Slack API 응답을 흉내낸다."""
    calls: list = []
    post_result = {"ok": True}
    post_status = 200

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, data=None, headers=None):
        method = url.rsplit("/", 1)[-1]
        _FakeClient.calls.append((method, json if json is not None else data, "json" if json is not None else "form"))
        if method == "conversations.list":
            return _Resp({"ok": True, "channels": [
                {"name": "02-공동구매-운영", "id": "C0GROUPBUY1"},
                {"name": "04-주문-정산-CS", "id": "C0ORDER0001"},
            ], "response_metadata": {"next_cursor": ""}})
        return _Resp(_FakeClient.post_result, _FakeClient.post_status, {"Retry-After": "30"})


def _logs(key):
    db = SessionLocal()
    try:
        return db.query(SlackNotificationLog).filter(SlackNotificationLog.dedupe_key == key).all()
    finally:
        db.close()


def _sent_count():
    return sum(1 for m, _, _ in _FakeClient.calls if m == "chat.postMessage")


class SlackNotifyBase(unittest.TestCase):
    def setUp(self):
        _env.seed_companies()
        self._saved = {k: getattr(settings, k) for k in
                       ("alert_mock", "slack_bot_token", "slack_channels", "slack_dm_user", "slack_events")}
        settings.alert_mock = False
        settings.slack_bot_token = "xoxb-test-only"
        settings.slack_channels = ""
        settings.slack_dm_user = "U0BOSS0001"
        settings.slack_events = "campaign_open,system_alert"
        slack_notify._resolved.clear()
        _FakeClient.calls = []
        _FakeClient.post_result = {"ok": True}
        _FakeClient.post_status = 200
        self._patch = mock.patch.object(slack_notify.httpx, "Client", _FakeClient)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        for k, v in self._saved.items():
            setattr(settings, k, v)


class SlackNotifyTests(SlackNotifyBase):
    def test_꺼진_이벤트는_보내지_않고_기록도_없다(self):
        key = f"off:{uid()}"
        r = slack_notify.post("settlement_pending", "order", "정산 대기", company_id=CID, dedupe_key=key)
        self.assertEqual(r["status"], "off")
        self.assertEqual(_FakeClient.calls, [])
        self.assertEqual(_logs(key), [])

    def test_채널_이름을_ID로_찾아_발송한다(self):
        key = f"open:{uid()}"
        r = slack_notify.post("campaign_open", "groupbuy", "[오픈] 가상캠페인", company_id=CID, dedupe_key=key)
        self.assertTrue(r["sent"], r)
        self.assertEqual([(m, f) for m, _, f in _FakeClient.calls],
                         [("conversations.list", "form"), ("chat.postMessage", "json")])
        self.assertEqual(_FakeClient.calls[-1][1]["channel"], "C0GROUPBUY1")
        self.assertEqual([l.status for l in _logs(key)], ["sent"])

    def test_같은_이벤트는_한_번만_나간다(self):
        key = f"open:{uid()}"
        first = slack_notify.post("campaign_open", "groupbuy", "[오픈] A", company_id=CID, dedupe_key=key)
        second = slack_notify.post("campaign_open", "groupbuy", "[오픈] A", company_id=CID, dedupe_key=key)
        self.assertTrue(first["sent"])
        self.assertEqual(second["status"], "duplicate")
        self.assertEqual(_sent_count(), 1)

    def test_다른_프로세스가_발송_중이면_보내지_않는다(self):
        """배포 중 두 프로세스가 겹칠 때 — 먼저 잡은 sending 행이 두 번째 발송을 막는다."""
        key = f"race:{uid()}"
        db = SessionLocal()
        db.add(SlackNotificationLog(company_id=CID, event="campaign_open", channel="groupbuy",
                                    dedupe_key=key, status="sending"))
        db.commit(); db.close()
        r = slack_notify.post("campaign_open", "groupbuy", "[오픈] R", company_id=CID, dedupe_key=key)
        self.assertEqual(r["status"], "duplicate")
        self.assertEqual(_sent_count(), 0)

    def test_오래_멈춘_발송중_기록은_풀어서_다시_보낸다(self):
        key = f"stale:{uid()}"
        db = SessionLocal()
        db.add(SlackNotificationLog(company_id=CID, event="campaign_open", channel="groupbuy", dedupe_key=key,
                                    status="sending", created_at=datetime.utcnow() - timedelta(minutes=30)))
        db.commit(); db.close()
        r = slack_notify.post("campaign_open", "groupbuy", "[오픈] S", company_id=CID, dedupe_key=key)
        self.assertTrue(r["sent"], r)

    def test_mock_모드는_실제로_보내지_않는다(self):
        settings.alert_mock = True
        key = f"mock:{uid()}"
        r = slack_notify.post("campaign_open", "groupbuy", "[오픈] B", company_id=CID, dedupe_key=key)
        again = slack_notify.post("campaign_open", "groupbuy", "[오픈] B", company_id=CID, dedupe_key=key)
        self.assertEqual(r["status"], "mock")
        self.assertEqual(again["status"], "duplicate")
        self.assertEqual(_FakeClient.calls, [])
        self.assertEqual([l.status for l in _logs(key)], ["mock"])

    def test_mock_기록은_실발송을_막지_않는다(self):
        key = f"mock2real:{uid()}"
        settings.alert_mock = True
        slack_notify.post("campaign_open", "groupbuy", "[오픈] C", company_id=CID, dedupe_key=key)
        settings.alert_mock = False
        r = slack_notify.post("campaign_open", "groupbuy", "[오픈] C", company_id=CID, dedupe_key=key)
        self.assertTrue(r["sent"], r)

    def test_설정의_채널_ID를_그대로_쓴다(self):
        settings.slack_channels = "groupbuy=C0CUSTOM01"
        r = slack_notify.post("campaign_open", "groupbuy", "[오픈] D", company_id=CID)
        self.assertTrue(r["sent"])
        self.assertEqual([m for m, _, _ in _FakeClient.calls], ["chat.postMessage"])
        self.assertEqual(_FakeClient.calls[0][1]["channel"], "C0CUSTOM01")

    def test_봇이_없는_채널이면_실패를_기록하고_안내한다(self):
        _FakeClient.post_result = {"ok": False, "error": "not_in_channel"}
        key = f"fail:{uid()}"
        r = slack_notify.post("campaign_open", "groupbuy", "[오픈] E", company_id=CID, dedupe_key=key)
        self.assertEqual(r["status"], "failed")
        self.assertIn("/invite", r["reason"])
        self.assertEqual([l.status for l in _logs(key)], ["failed"])

    def test_실패한_이벤트는_다음에_다시_보낼_수_있다(self):
        key = f"retry:{uid()}"
        _FakeClient.post_result = {"ok": False, "error": "internal_error"}
        slack_notify.post("campaign_open", "groupbuy", "[오픈] F", company_id=CID, dedupe_key=key)
        _FakeClient.post_result = {"ok": True}
        r = slack_notify.post("campaign_open", "groupbuy", "[오픈] F", company_id=CID, dedupe_key=key)
        self.assertTrue(r["sent"], r)

    def test_호출_제한이면_대기시간을_기록한다(self):
        _FakeClient.post_status = 429
        r = slack_notify.post("campaign_open", "groupbuy", "[오픈] RL", company_id=CID, dedupe_key=f"rl:{uid()}")
        self.assertEqual(r["status"], "failed")
        self.assertIn("Retry-After 30", r["reason"])

    def test_채널을_못_찾으면_캐시를_지우고_다시_찾는다(self):
        slack_notify.post("campaign_open", "groupbuy", "[오픈] 1", company_id=CID)
        self.assertIn("02-공동구매-운영", slack_notify._resolved)
        _FakeClient.post_result = {"ok": False, "error": "channel_not_found"}
        slack_notify.post("campaign_open", "groupbuy", "[오픈] 2", company_id=CID)
        self.assertNotIn("02-공동구매-운영", slack_notify._resolved)

    def test_토큰이_없으면_보내지_않고_실패로_남긴다(self):
        settings.slack_bot_token = ""
        key = f"notoken:{uid()}"
        r = slack_notify.post("campaign_open", "groupbuy", "[오픈] G", company_id=CID, dedupe_key=key)
        self.assertEqual(r["status"], "failed")
        self.assertEqual(_FakeClient.calls, [])
        self.assertEqual([l.status for l in _logs(key)], ["failed"])

    def test_시스템_이상은_대표님_DM으로_하루_한_번(self):
        key = f"backup-fail:{uid()}"
        r = slack_notify.notify_admin("백업 실패", company_id=CID, dedupe_key=key)
        again = slack_notify.notify_admin("백업 실패", company_id=CID, dedupe_key=key)
        self.assertTrue(r["sent"], r)
        self.assertEqual(again["status"], "duplicate")
        self.assertEqual(_FakeClient.calls[-1][1]["channel"], "U0BOSS0001")

    def test_발송_예외가_나도_예외를_올리지_않는다(self):
        with mock.patch.object(slack_notify, "_api", side_effect=RuntimeError("network down")):
            r = slack_notify.post("campaign_open", "groupbuy", "[오픈] H", company_id=CID, dedupe_key=f"exc:{uid()}")
        self.assertEqual(r["status"], "failed")
        self.assertIn("network down", r["reason"])

    def test_기록_DB가_고장나도_예외를_올리지_않고_보내지도_않는다(self):
        """테이블이 아직 없거나 DB 연결이 끊긴 상황 — 중복 방지를 보장 못 하니 보내지 않는다."""
        with mock.patch.object(slack_notify, "_session", side_effect=RuntimeError("no such table")):
            r = slack_notify.post("campaign_open", "groupbuy", "[오픈] DB", company_id=CID, dedupe_key=f"db:{uid()}")
        self.assertEqual(r["status"], "failed")
        self.assertEqual(_sent_count(), 0)

    def test_호출자의_저장_안_한_변경을_건드리지_않는다(self):
        """알림은 별도 세션 — 호출자 세션의 미저장 변경을 대신 commit 하지 않는다."""
        caller = SessionLocal()
        try:
            name = f"미저장회사{uid()}"
            caller.add(Company(id=9000 + int(uid()[:3], 16) % 900, name=name, plan="pro", is_active=True))
            caller.flush()
            slack_notify.post("campaign_open", "groupbuy", "[오픈] T", company_id=CID, dedupe_key=f"tx:{uid()}")
            caller.rollback()
            check = SessionLocal()
            try:
                self.assertIsNone(check.query(Company).filter(Company.name == name).first())
            finally:
                check.close()
        finally:
            caller.close()


if __name__ == "__main__":
    unittest.main()
