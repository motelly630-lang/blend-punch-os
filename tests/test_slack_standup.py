"""#출근보고 AI 직원 보고 (대표님 2026-09-26).

- 직원마다 이름·아이콘·카드(blocks)로 #출근보고 에 올린다
- 숫자는 DB 에서 센다 — 오늘 마감·3일 안 마감, 매출 미입력·작성중 정산, CS 기한 지남, 인플루언서 수집 0명 경고
- 고객 이름·연락처는 보고에 넣지 않는다
- DB 에서 온 글자(공구 이름 등)는 escape — 전원 호출·링크 위장 안 됨
- 하루 한 번만 (직원별), 한 직원이 실패해도 나머지는 올린다, 이벤트가 꺼져 있으면 안 나간다
"""
from tests import _env
from tests._env import SessionLocal, uid

import unittest
from datetime import datetime, timedelta
from unittest import mock

from app.config import settings
from app.models.campaign import Campaign
from app.models.cs import CSTicket
from app.models.influencer import Influencer
from app.models.settlement import Settlement
from app.services import slack_notify, slack_standup as su
from app.services.slack_reports import today_kst
from tests.test_slack_notify import _FakeClient

CID = 77          # 다른 테스트 데이터와 섞이지 않게 별도 회사


def _add(*rows):
    db = SessionLocal()
    db.add_all(rows); db.commit(); db.close()


def _report(key):
    db = SessionLocal()
    try:
        return su.BUILDERS[key](db, CID, today_kst())
    finally:
        db.close()


def _all_text(r) -> str:
    return " ".join([r["summary"], *r["lines"], *[f"{k} {v}" for k, v, _ in r["stats"]]])


def _stats(r) -> dict:
    return {k: v for k, v, _ in r["stats"]}


class BuildTest(unittest.TestCase):
    def test_공구_매니저_오늘_마감과_3일_안_마감(self):
        t = today_kst()
        a, b = "오늘끝" + uid(), "모레끝" + uid()
        _add(Campaign(name=a, company_id=CID, start_date=t - timedelta(3), end_date=t, status="active"),
             Campaign(name=b, company_id=CID, start_date=t - timedelta(1), end_date=t + timedelta(2), status="active"),
             Campaign(name="취소" + uid(), company_id=CID, start_date=t, end_date=t, status="cancelled"))
        r = _report("groupbuy")
        stats = _stats(r)
        self.assertGreaterEqual(int(stats["오늘 마감"][:-1]), 1)
        text = _all_text(r)
        self.assertIn(a, text)
        self.assertIn("D-2 — " + b, text)
        self.assertNotIn("취소", text)

    def test_정산_매니저_매출_미입력과_작성중(self):
        t = today_kst()
        _add(Campaign(name="매출없음" + uid(), company_id=CID, start_date=t - timedelta(9), end_date=t - timedelta(2),
                      status="active"),
             Settlement(company_id=CID, status="pending", final_payment=87909),
             Settlement(company_id=CID, status="confirmed", final_payment=100000, due_date=t - timedelta(1)))
        stats = _stats(_report("settlement"))
        self.assertNotEqual(stats["매출 미입력"], "0건")
        self.assertIn("87,909원", stats["작성중"])
        self.assertNotEqual(stats["예정일 지남"], "0건")

    def test_고객_관리는_숫자만_고객_정보는_안_넣는다(self):
        _add(CSTicket(company_id=CID, cs_number="CS-T-" + uid(), status="received", customer_name="홍길동가상",
                      customer_phone="010-0000-1111", due_at=datetime.utcnow() - timedelta(hours=3), is_urgent=True))
        r = _report("cs")
        text = _all_text(r)
        self.assertNotIn("홍길동가상", text)
        self.assertNotIn("010-0000-1111", text)
        self.assertNotEqual(_stats(r)["기한 지남"], "0건")
        self.assertIn(("기한 지난 문의", "/cs?tab=overdue"), r["links"])

    def test_인플루언서_수집_0명이면_경고(self):
        _add(Influencer(name="대기" + uid(), platform="instagram", handle="gasang" + uid(), company_id=CID))
        with mock.patch.object(settings, "influencer_enrich", True):
            r = _report("influencer")
        self.assertTrue(any("한 명도 못 채웠어요" in l for l in r["lines"]), r)

    def test_브랜드·제품_정리는_목록_화면과_같은_기준(self):
        from app.models.brand import Brand
        from app.models.product import Product
        cid = 70 + int(uid()[:4], 16) % 5
        _add(Brand(name="빈브랜드" + uid(), company_id=cid),
             Brand(name="로고브랜드" + uid(), company_id=cid, logo="/static/x.png"),
             Brand(name="보관브랜드" + uid(), company_id=cid, is_archived=True),
             Product(name="미완성" + uid(), brand="가상", category="식품", company_id=cid, is_complete=False),
             Product(name="완성" + uid(), brand="가상", category="식품", company_id=cid, is_complete=True),
             Product(name="보관" + uid(), brand="가상", category="식품", company_id=cid, is_complete=False, is_archived=True))
        db = SessionLocal()
        try:
            r = su.build_catalog(db, cid, today_kst())
        finally:
            db.close()
        s = _stats(r)
        self.assertEqual((s["정보 필요 브랜드"], s["미완성 제품"], s["어제 새 미완성"]), ("1곳", "1개", "1개"))
        self.assertIn(("정보 필요 브랜드", "/brands?need=1"), r["links"])

    def test_경영_분석가는_종료일_기준_이번달_지난달_매출(self):
        t = today_kst()
        if t.day == 1:
            self.skipTest("매달 1일은 '이번 달 끝난 공구' 가 아직 없다")
        cid = 80 + int(uid()[:4], 16) % 5
        last = t.replace(day=1) - timedelta(days=3)
        _add(Campaign(name="이번달" + uid(), company_id=cid, end_date=t - timedelta(1), actual_revenue=100000),
             Campaign(name="이번달미입력" + uid(), company_id=cid, end_date=t - timedelta(1)),
             Campaign(name="취소" + uid(), company_id=cid, end_date=t - timedelta(1), status="cancelled", actual_revenue=999),
             Campaign(name="지난달" + uid(), company_id=cid, end_date=last, actual_revenue=50000),
             Settlement(company_id=cid, status="paid", final_payment=30000, paid_at=datetime.utcnow()))
        db = SessionLocal()
        try:
            r = su.build_biz(db, cid, t)
        finally:
            db.close()
        s = _stats(r)
        self.assertEqual((s["이번 달 매출"], s["지난달 매출"], s["이번 달 매출 입력"], s["이번 달 지급한 정산"]),
                         ("100,000원", "50,000원", "1/2건", "30,000원"))
        self.assertTrue(any("2건 중 매출이 입력된 건 1건" in l for l in r["lines"]))

    def test_이름에_섞인_제어문자는_무력화(self):
        text, blocks = su.render("공구 매니저", {"summary": "<!channel> 요약", "stats": [("<!here>", "1건", 1)],
                                                "lines": ["<https://evil|클릭>"], "links": [("목록", "/campaigns")]})
        blob = str(blocks)
        self.assertNotIn("<!channel>", blob)
        self.assertNotIn("<!here>", blob)
        self.assertNotIn("<https://evil", blob)

    def test_어제보다_변화와_바로가기(self):
        r = {"summary": "요약", "lines": ["할 일"], "links": [("매출 넣기", "/campaigns/revenue?tab=ended")],
             "stats": [su._s("매출 미입력", 92), su._s("어젯밤 채움", 148, "명", delta=False)]}
        _, blocks = su.render("정산 매니저", r, prev={"매출 미입력": 97, "어젯밤 채움": 1})
        fields = [f["text"] for f in blocks[1]["fields"]]
        self.assertIn("어제보다 -5", fields[0])
        self.assertNotIn("어제보다", fields[1])                     # 비교 안 하는 칸
        self.assertIn("/campaigns/revenue?tab=ended|매출 넣기>", blocks[-1]["elements"][0]["text"])

    def test_할_일_없는_날은_한_줄(self):
        _, blocks = su.render("고객 관리 매니저", {"summary": "없어요 ✅", "lines": [], "links": [("CS 목록", "/cs")],
                                                  "stats": [su._s("처리 중", 0)]})
        self.assertEqual([b["type"] for b in blocks], ["section", "context"])

    def test_오늘_숫자는_하루_한_번만_저장하고_다음날_비교(self):
        from app.models.standup_snapshot import StandupSnapshot
        t, cid = today_kst(), 60 + int(uid()[:4], 16) % 9
        db = SessionLocal()
        try:
            su.save_today(db, cid, t - timedelta(1), "settlement", {"stats": [su._s("매출 미입력", 10)]})
            su.save_today(db, cid, t - timedelta(1), "settlement", {"stats": [su._s("매출 미입력", 99)]})
            self.assertEqual(db.query(StandupSnapshot).filter_by(company_id=cid).count(), 1)
            self.assertEqual(su.load_prev(db, cid, t), {"settlement": {"매출 미입력": 10}})
        finally:
            db.close()


class SendTest(unittest.TestCase):
    def setUp(self):
        _env.seed_companies()
        self._saved = {k: getattr(settings, k) for k in ("alert_mock", "slack_bot_token", "slack_channels", "slack_events")}
        settings.alert_mock = False
        settings.slack_bot_token = "xoxb-test-only"
        settings.slack_channels = "standup=C0STANDUP01"
        settings.slack_events = "staff_standup"
        _FakeClient.calls, _FakeClient.post_result, _FakeClient.post_status = [], {"ok": True}, 200
        self._p = mock.patch.object(slack_notify.httpx, "Client", _FakeClient)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        for k, v in self._saved.items():
            setattr(settings, k, v)

    def _posts(self):
        return [p for m, p, _ in _FakeClient.calls if m == "chat.postMessage"]

    def test_직원별_이름_아이콘_카드로_한_번만(self):
        cid = 900 + int(uid()[:4], 16) % 90          # 날짜별 중복 키가 다른 테스트 실행과 겹치지 않게
        db = SessionLocal()
        try:
            first = su.send_all(db, cid)
            second = su.send_all(db, cid)
        finally:
            db.close()
        posts = self._posts()
        self.assertEqual(first["status"], "sent", first)
        self.assertGreaterEqual(len(posts), 4)                      # 트렌드는 브리핑이 있을 때만
        self.assertEqual({p["channel"] for p in posts}, {"C0STANDUP01"})
        names = [p["username"] for p in posts]
        self.assertIn("공구 매니저", names)
        self.assertIn("정산 매니저", names)
        self.assertTrue(all(p.get("icon_emoji") and p.get("blocks") for p in posts))
        first_block = [p["blocks"][0]["text"]["text"] for p in posts if p["username"] == "정산 매니저"][0]
        self.assertIn("*정산 매니저*", first_block)               # 권한 없어도 누구 보고인지 보이게
        self.assertEqual(second["status"], "skipped")               # 오늘 이미 보냄 → 전부 duplicate
        self.assertEqual(len(self._posts()), len(posts))

    def test_한_직원이_실패해도_나머지는_올린다(self):
        cid = 900 + int(uid()[:4], 16) % 90
        def boom(*a, **kw):
            raise RuntimeError("가상 오류")
        db = SessionLocal()
        try:
            with mock.patch.dict(su.BUILDERS, {"cs": boom}):
                r = su.send_all(db, cid, dedupe=False)
        finally:
            db.close()
        cs_post = [p for p in self._posts() if p["username"] == "고객 관리 매니저"]
        self.assertEqual(len(cs_post), 1)
        self.assertIn("만들지 못했어요", cs_post[0]["text"])
        self.assertIn("공구 매니저", [p["username"] for p in self._posts()])
        self.assertEqual(r["status"], "sent")

    def test_이벤트가_꺼져_있으면_안_나간다(self):
        settings.slack_events = "trend_digest"
        db = SessionLocal()
        try:
            r = su.send_all(db, CID, dedupe=False)
        finally:
            db.close()
        self.assertEqual(self._posts(), [])
        self.assertEqual(r["status"], "skipped")


class EnrichAlertTest(unittest.TestCase):
    def test_토큰_끊기면_DM_사용량_정지는_조용히(self):
        from app import scheduler
        base = {"updated": 0, "failed": 0, "remaining": 900}
        for err, expect in (("Meta 토큰이 만료됐거나 끊겼어요", 1), ("Meta 사용량 50% — 멈춥니다", 0)):
            with mock.patch("app.services.influencer_enrich.enrich_batch", return_value={**base, "error": err}), \
                    mock.patch.object(scheduler, "_admin_alert") as alert:
                scheduler._influencer_enrich_job()
            self.assertEqual(alert.call_count, expect, err)


if __name__ == "__main__":
    unittest.main()
