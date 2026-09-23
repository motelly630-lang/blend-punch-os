"""Slack 정기 리포트: 새 브랜드 [신규브랜드], 어제 등록 제품(미완성 표시·없으면 생략), 트렌드(AI 선택·지어낸 것 버림·
AI 실패 시 규칙), 주간 요약, 아침 보고 AI 우선순위(정산 제외·실패해도 보고는 나감)."""
from tests import _env
from tests._env import SessionLocal, uid

import unittest
from datetime import date, datetime, timedelta
from unittest import mock

from app.config import settings
from app.models.brand import Brand
from app.models.campaign import Campaign
from app.models.product import Product
from app.models.trend_engine import TrendBriefing
from app.models.slack_notification_log import SlackNotificationLog
from app.services import campaign_slack, slack_notify, slack_reports
from tests.test_slack_notify import _FakeClient

CID = 2


class _FakeAI:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, []

    def complete_json(self, system, user, max_tokens=0, schema=None):
        self.calls.append((system, user))
        if self.exc:
            raise self.exc
        return self.result


def _texts(channel_id=None):
    return [p["text"] for m, p, _ in _FakeClient.calls
            if m == "chat.postMessage" and (channel_id is None or p["channel"] == channel_id)]


def _add(obj):
    db = SessionLocal()
    try:
        db.add(obj); db.commit(); return obj.id
    finally:
        db.close()


def _clear(model):
    db = SessionLocal()
    try:
        db.query(model).filter(model.company_id == CID).delete(); db.commit()
    finally:
        db.close()


class ReportBase(unittest.TestCase):
    def setUp(self):
        _env.seed_companies()
        for m in (Campaign, Product, TrendBriefing, Brand, SlackNotificationLog):
            _clear(m)
        self._saved = {k: getattr(settings, k) for k in
                       ("alert_mock", "slack_bot_token", "slack_channels", "slack_events")}
        settings.alert_mock = False
        settings.slack_bot_token = "xoxb-test-only"
        settings.slack_channels = "notice=C0NOTICE01,groupbuy=C0GROUPBUY1,seller=C0SELLER01,marketing=C0MARKET01"
        settings.slack_events = ("brand_created,product_daily,trend_digest,weekly_summary,"
                                 "campaign_digest,campaign_digest_ai")
        _FakeClient.calls = []
        _FakeClient.post_result = {"ok": True}
        _FakeClient.post_status = 200
        self._patch = mock.patch.object(slack_notify.httpx, "Client", _FakeClient)
        self._patch.start()
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()
        self._patch.stop()
        for k, v in self._saved.items():
            setattr(settings, k, v)


class BrandAndProductTests(ReportBase):
    def test_새_브랜드는_03채널에_한_번(self):
        name = f"가상브랜드{uid()}"
        _add(Brand(company_id=CID, name=name))
        slack_reports.scan_brands(self.db, CID); slack_reports.scan_brands(self.db, CID)
        msgs = _texts("C0SELLER01")
        self.assertEqual(len(msgs), 1)
        self.assertTrue(msgs[0].startswith("[신규브랜드]")); self.assertIn(name, msgs[0])

    def test_어제_등록_제품은_미완성을_표시한다(self):
        y = datetime.combine(slack_reports.today_kst() - timedelta(days=1), datetime.min.time()) + timedelta(hours=3)  # KST 12시
        _add(Product(company_id=CID, name="가상상품A", brand="가상브랜드", category="기타", is_complete=True, created_at=y))
        _add(Product(company_id=CID, name="가상상품B", brand="가상브랜드", category="기타", is_complete=False, created_at=y))
        r = slack_reports.send_product_daily(self.db, CID)
        self.assertTrue(r["sent"], r)
        msg = _texts("C0SELLER01")[0]
        self.assertIn("2건", msg); self.assertIn("가상상품B (초안)  ⚠️ 입력 미완성", msg)
        self.assertNotIn("가상상품A  ⚠️", msg)

    def test_어제_등록_제품이_없으면_보내지_않는다(self):
        r = slack_reports.send_product_daily(self.db, CID)
        self.assertEqual(r["status"], "skipped")
        self.assertEqual(_texts(), [])


def _briefing(pid):
    """pid: 제품명 → 회사 2 제품 id. 없는 이름은 다른 회사 제품으로 취급된다."""
    ev = lambda k, n, prep, prods: {
        "key": k, "name": n, "season": "가을", "prep_delta": prep, "peak_delta": prep + 20,
        "peak_date": "2026-10-20", "prep_date": "2026-10-01", "trend_score": 80, "description": f"{n} 설명",
        "keywords": [], "matched_products": [{"product_name": p, "product_id": pid.get(p, "other-co"), "score": 5}
                                             for p in prods]}
    return [ev("chuseok", "추석", 3, ["가상배세트", "가상한우"]),
            ev("halloween", "할로윈", 10, ["가상캔디"]),
            ev("nomatch", "제품없는시즌", 1, []),
            ev("othercorp", "남의회사시즌", 2, ["남의회사상품"]),
            ev("bf", "블프", 30, ["가상에어프라이어"]),
            ev("xmas", "크리스마스", 50, ["가상케이크"])]


class TrendTests(ReportBase):
    def setUp(self):
        super().setUp()
        pid = {n: _add(Product(company_id=CID, name=n, brand="가상브랜드", category="기타", status="active"))
               for n in ("가상배세트", "가상한우", "가상캔디", "가상에어프라이어", "가상케이크")}
        _add(TrendBriefing(company_id=CID, report_date=slack_reports.today_kst().isoformat(),
                           event_count=6, report_data=_briefing(pid)))

    def test_AI가_고른_시즌과_제품을_보낸다(self):
        ai = _FakeAI({"items": [{"key": "halloween", "why": "준비가 가장 급해요", "products": ["가상캔디"]},
                                {"key": "chuseok", "why": "선물 수요", "products": ["가상한우"]}]})
        with mock.patch.object(slack_reports, "_ai", return_value=ai):
            r = slack_reports.send_trend_digest(self.db, CID)
        self.assertTrue(r["sent"], r)
        msg = _texts("C0MARKET01")[0]
        self.assertIn("(AI 선택)", msg); self.assertIn("1. *할로윈*", msg); self.assertIn("추천 제품: 가상캔디", msg)
        self.assertIn("3. *블프*", msg)   # AI 가 2개만 고르면 준비 임박 순으로 채운다
        self.assertNotIn("제품없는시즌", ai.calls[0][1])

    def test_다른_회사_제품은_추천하지_않는다(self):
        with mock.patch.object(slack_reports, "_ai", return_value=None):
            slack_reports.send_trend_digest(self.db, CID)
        msg = _texts("C0MARKET01")[0]
        self.assertNotIn("남의회사", msg)

    def test_AI가_지어낸_시즌과_제품은_버린다(self):
        ai = _FakeAI({"items": [{"key": "없는시즌", "why": "x", "products": []},
                                {"key": "chuseok", "why": "선물", "products": ["가상한우", "지어낸상품"]},
                                {"key": "chuseok", "why": "중복", "products": []}]})
        with mock.patch.object(slack_reports, "_ai", return_value=ai):
            slack_reports.send_trend_digest(self.db, CID)
        msg = _texts("C0MARKET01")[0]
        self.assertNotIn("없는시즌", msg); self.assertNotIn("지어낸상품", msg); self.assertNotIn("중복", msg)
        self.assertEqual(msg.count("*추석*"), 1)
        self.assertIn("추천 제품: 가상한우", msg)

    def test_AI가_실패해도_규칙으로_보낸다(self):
        with mock.patch.object(slack_reports, "_ai", return_value=_FakeAI(exc=RuntimeError("API down"))):
            r = slack_reports.send_trend_digest(self.db, CID)
        self.assertTrue(r["sent"], r)
        msg = _texts("C0MARKET01")[0]
        self.assertNotIn("(AI 선택)", msg)
        self.assertIn("1. *추석*", msg)   # 준비 임박 순

    def test_AI_답_형식이_망가져도_규칙으로_보낸다(self):
        for bad in ({"items": None}, {"items": ["문자열"]}, ["목록"], None):
            _clear(SlackNotificationLog); _FakeClient.calls = []
            with mock.patch.object(slack_reports, "_ai", return_value=_FakeAI(bad)):
                r = slack_reports.send_trend_digest(self.db, CID)
            self.assertTrue(r["sent"], (bad, r))

    def test_하루_한_번만(self):
        with mock.patch.object(slack_reports, "_ai", return_value=None):
            slack_reports.send_trend_digest(self.db, CID)
            again = slack_reports.send_trend_digest(self.db, CID)
        self.assertEqual(again["status"], "duplicate")


class WeeklyTests(ReportBase):
    def test_지난주와_이번주를_요약한다(self):
        t = slack_reports.today_kst(); mon = t - timedelta(days=t.weekday())
        _add(Campaign(company_id=CID, name="지난주오픈공구", start_date=mon - timedelta(days=5), end_date=mon + timedelta(days=2)))
        _add(Campaign(company_id=CID, name="이번주오픈공구", start_date=mon + timedelta(days=1), end_date=mon + timedelta(days=20)))
        r = slack_reports.send_weekly_summary(self.db, CID)
        self.assertTrue(r["sent"], r)
        msg = _texts("C0NOTICE01")[0]
        self.assertIn("오픈 1건", msg); self.assertIn("지난주오픈공구", msg)
        self.assertIn("오픈 예정 1건", msg); self.assertIn("마감 예정 1건", msg)

    def test_취소된_공구는_빼고_센다(self):
        t = slack_reports.today_kst(); mon = t - timedelta(days=t.weekday())
        _add(Campaign(company_id=CID, name="취소된공구", status="cancelled", start_date=mon + timedelta(days=1)))
        slack_reports.send_weekly_summary(self.db, CID)
        msg = _texts("C0NOTICE01")[0]
        self.assertNotIn("취소된공구", msg); self.assertIn("오픈 예정 0건", msg)


class DigestAITests(ReportBase):
    def _campaigns(self, n_today=4):
        t = slack_reports.today_kst()
        for i in range(n_today):
            _add(Campaign(company_id=CID, name=f"오늘마감{i}", status="active", start_date=t - timedelta(days=5), end_date=t))

    def _digest(self, ai):
        with mock.patch.object(slack_reports, "_ai", return_value=ai):
            return campaign_slack.send_digest(self.db, company_id=CID)

    def test_AI는_후보_중에서_순서만_고르고_문장은_코드가_쓴다(self):
        self._campaigns(4)
        ai = _FakeAI({"ids": ["ending_today:2", "지어낸id", "ending_today:0"]})
        r = self._digest(ai)
        self.assertTrue(r["sent"], r)
        msg = _texts("C0GROUPBUY1")[0]
        self.assertIn("오늘 먼저 할 일", msg)
        self.assertIn("1. 오늘 마감 '오늘마감2' 마무리 확인", msg)
        self.assertIn("2. 오늘 마감 '오늘마감0' 마무리 확인", msg)
        self.assertNotIn("지어낸id", msg)

    def test_할_일이_3개_이하면_AI도_우선순위도_없다(self):
        self._campaigns(2)
        ai = _FakeAI({"ids": []})
        self._digest(ai)
        self.assertEqual(ai.calls, [])
        self.assertNotIn("오늘 먼저 할 일", _texts("C0GROUPBUY1")[0])

    def test_알릴_게_없으면_우선순위를_붙이지_않는다(self):
        ai = _FakeAI({"ids": []})
        self._digest(ai)
        self.assertEqual(ai.calls, [])
        self.assertNotIn("오늘 먼저 할 일", _texts("C0GROUPBUY1")[0])

    def test_정산은_후보에_넣지_않는다(self):
        d = {"pending": {"no_settlement": 5, "to_active": 1}, "no_end_date": []}
        self.assertFalse(any("정산" in c["todo"] for c in slack_reports.priority_candidates(d)))

    def test_AI가_실패해도_아침_보고는_나간다(self):
        self._campaigns(4)
        r = self._digest(_FakeAI(exc=RuntimeError("API down")))
        self.assertTrue(r["sent"], r)
        self.assertNotIn("오늘 먼저 할 일", _texts("C0GROUPBUY1")[0])

    def test_이미_보낸_날은_AI를_부르지_않는다(self):
        self._campaigns(4)
        self._digest(_FakeAI({"ids": []}))
        ai = _FakeAI({"ids": []})
        r = self._digest(ai)
        self.assertEqual(r["status"], "duplicate")
        self.assertEqual(ai.calls, [])

    def test_AI_이벤트를_끄면_AI를_부르지_않는다(self):
        self._campaigns(4)
        settings.slack_events = "campaign_digest"
        ai = _FakeAI({"ids": ["ending_today:0"]})
        self._digest(ai)
        self.assertEqual(ai.calls, [])


class EscapeTests(ReportBase):
    def test_이름에_섞인_Slack_전체알림_문법을_무력화한다(self):
        y = datetime.combine(slack_reports.today_kst() - timedelta(days=1), datetime.min.time()) + timedelta(hours=3)
        _add(Product(company_id=CID, name="<!channel> 긴급 <http://x.io|클릭>", brand="가상&브랜드", category="기타", created_at=y))
        slack_reports.send_product_daily(self.db, CID)
        msg = _texts("C0SELLER01")[0]
        self.assertNotIn("<!channel>", msg); self.assertIn("&lt;!channel&gt;", msg)
        self.assertIn("가상&amp;브랜드", msg)

    def test_보관된_제품은_어제_제품에서_뺀다(self):
        y = datetime.combine(slack_reports.today_kst() - timedelta(days=1), datetime.min.time()) + timedelta(hours=3)
        _add(Product(company_id=CID, name="보관된상품", brand="가상브랜드", category="기타", status="archived", created_at=y))
        r = slack_reports.send_product_daily(self.db, CID)
        self.assertEqual(r["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
