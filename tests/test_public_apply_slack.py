"""공개 카탈로그 공구 신청 — 제품 상세 신청 · 서버 검사 · 반복 신청 제한 · Slack 02-공동구매-운영 알림.
(코덱스 검토 2026-09-29 반영: 도배 방지, all 로는 안 켜짐, 서버 길이·연락 방식 검사, 신청자 글자는 plain_text)"""
from tests import _env  # noqa: F401
from tests._env import SessionLocal, client_for, make_user, seed_companies, uid

import unittest
from html.parser import HTMLParser
from unittest import mock

from app.config import settings
from app.models import Product
from app.models.group_buy_application import GroupBuyApplication
from app.routers import public
from app.services import slack_notify as sn


def _pub(db, **kw):
    base = dict(name=f"신청시험 {uid()}", brand=f"신청브랜드{uid()}", category="기타", company_id=1,
                status="active", visibility_status="active")
    base.update(kw)
    p = Product(**base)
    db.add(p)
    db.commit()
    return p


def form(**kw):
    base = {"applicant_name": "김가상", "contact_type": "카카오", "contact_value": f"kim{uid()}",
            "channel_handle": "@kim_mom", "followers": "5만", "message": "다음 달 초 진행 희망"}
    base.update(kw)
    return base


class Base(unittest.TestCase):
    def setUp(self):
        seed_companies()
        self.db = SessionLocal()
        public._apply_hits.clear()
        public._here_times.clear()
        self._events = mock.patch.object(settings, "slack_events", "public_apply")
        self._events.start()

    def tearDown(self):
        self._events.stop()
        self.db.close()

    def apply(self, p, spy=None, **kw):
        data = form(**kw)
        data.setdefault("product_id", p.id)
        data.setdefault("product_name", "화면조작이름")
        return client_for().post("/public/apply", data=data)

    def count(self, p):
        self.db.expire_all()
        return self.db.query(GroupBuyApplication).filter(GroupBuyApplication.product_id == p.id).count()


class ApplyFlowTests(Base):
    def test_detail_page_has_apply_button_and_form(self):
        p = _pub(self.db)
        html = client_for().get(f"/public/products/product/{p.id}").text
        self.assertIn("공구 신청하기", html)
        self.assertIn('name="return_to" value="detail"', html)

    def test_apply_saves_server_values_and_notifies(self):
        p = _pub(self.db)
        with mock.patch.object(sn, "post", wraps=sn.post) as post:
            r = self.apply(p, return_to="detail", contact_value="kim1234")
        self.assertEqual(r.headers["location"], f"/public/products/product/{p.id}?applied=1")
        a = self.db.query(GroupBuyApplication).filter(GroupBuyApplication.product_id == p.id).one()
        self.assertEqual((a.company_id, a.product_name, a.brand, a.contact_value), (1, p.name, p.brand, "kim1234"))
        args, kw = post.call_args
        self.assertEqual((args[0], args[1], args[3], kw["dedupe_key"]), ("public_apply", "groupbuy", 1, f"public_apply:{a.id}"))
        mrk = kw["blocks"][1]["text"]
        self.assertEqual(mrk["type"], "mrkdwn")
        self.assertIn("<!here>", mrk["text"])
        joined = " ".join(f["text"] for f in kw["blocks"][2]["fields"])
        self.assertTrue(all(f["type"] == "plain_text" for f in kw["blocks"][2]["fields"]))
        for piece in (p.name, "김가상", "카카오", "kim1234", "@kim_mom", "5만"):
            self.assertIn(piece, joined)
        self.assertEqual(kw["blocks"][3]["text"]["type"], "plain_text")

    def test_applicant_text_only_in_plain_text(self):
        p = _pub(self.db)
        evil = "<!channel> *ADMIN* `x` _i_ <https://evil.invalid|OS 로그인>"
        with mock.patch.object(sn, "post", wraps=sn.post) as post:
            self.apply(p, applicant_name="<!channel>긴급", message=evil)
        blocks = post.call_args.kwargs["blocks"]
        mrkdwn_texts = [b["text"]["text"] for b in blocks if b.get("text", {}).get("type") == "mrkdwn"]
        mrkdwn_texts += [e["text"] for b in blocks if b["type"] == "context" for e in b["elements"]]
        for t in mrkdwn_texts:
            self.assertNotIn("ADMIN", t)
            self.assertNotIn("channel", t)
            self.assertNotIn("evil", t)

    def test_non_public_product_not_linked(self):
        hidden = _pub(self.db, visibility_status="hidden")
        name = f"숨김 {uid()}"
        self.apply(hidden, product_name=name, brand="b")
        a = self.db.query(GroupBuyApplication).filter(GroupBuyApplication.product_name == name).first()
        self.assertIsNotNone(a)
        self.assertIsNone(a.product_id)

    def test_slack_failure_does_not_block_application(self):
        p = _pub(self.db)
        with mock.patch.object(sn, "post", side_effect=RuntimeError("slack down")):
            r = self.apply(p, return_to="detail")
        self.assertIn("applied=1", r.headers["location"])
        self.assertEqual(self.count(p), 1)


class AbuseTests(Base):
    def test_same_contact_same_product_not_repeated(self):
        p = _pub(self.db)
        with mock.patch.object(sn, "post", wraps=sn.post) as post:
            for _ in range(25):
                r = self.apply(p, contact_value="same-person", return_to="detail")
        self.assertEqual(self.count(p), 1, "같은 신청 반복은 1건만")
        self.assertEqual(post.call_count, 1, "알림도 1번만")
        self.assertIn("dup=1", r.headers["location"])

    def test_ip_rate_limit(self):
        p = _pub(self.db)
        with mock.patch.object(sn, "post"):
            codes = [self.apply(p, contact_value=f"c{i}{uid()}", return_to="detail").headers["location"] for i in range(8)]
        self.assertEqual(self.count(p), public.APPLY_IP_LIMIT)
        self.assertIn("apply_error", codes[-1])

    def test_here_only_for_first_few(self):
        blocks_seen = []
        with mock.patch.object(sn, "post", wraps=sn.post) as post:
            for i in range(public.HERE_LIMIT + 2):
                public._apply_hits.clear()
                p = _pub(self.db)
                self.apply(p)
                blocks_seen.append(post.call_args.kwargs["blocks"][1]["text"]["text"])
        with_here = sum("<!here>" in t for t in blocks_seen)
        self.assertEqual(with_here, public.HERE_LIMIT, "처음 몇 건만 @here")
        self.assertNotIn("<!here>", blocks_seen[-1])


class ValidationTests(Base):
    def test_bad_inputs_rejected_before_save_and_notify(self):
        p = _pub(self.db)
        cases = ({"applicant_name": "가" * 101}, {"contact_type": "텔레그램"}, {"applicant_name": "   "},
                 {"contact_value": ""}, {"message": "m" * 2001}, {"followers": "9" * 51})
        with mock.patch.object(sn, "post") as post:
            for c in cases:
                r = self.apply(p, return_to="detail", **c)
                self.assertIn("apply_error", r.headers["location"], c)
        self.assertEqual(self.count(p), 0)
        post.assert_not_called()


class EventToggleTests(unittest.TestCase):
    def run_with(self, events):
        with mock.patch.object(settings, "slack_events", events), mock.patch.object(sn, "post") as post:
            public.notify_application_slack("x", 1, {"product_name": "p", "applicant_name": "a",
                                                     "contact_type": "카카오", "contact_value": "v"})
        return post.called

    def test_only_explicit_opt_in(self):
        self.assertFalse(self.run_with(""))
        self.assertFalse(self.run_with("campaign_open"))
        self.assertFalse(self.run_with("all"), "all 로는 켜지지 않아야 함")
        self.assertTrue(self.run_with("campaign_open,public_apply"))


class _FormNesting(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth, self.nested, self.actions = 0, 0, []

    def handle_starttag(self, tag, attrs):
        if tag == "form":
            if self.depth:
                self.nested += 1
            self.depth += 1
            self.actions.append(dict(attrs).get("action"))

    def handle_endtag(self, tag):
        if tag == "form" and self.depth:
            self.depth -= 1


class ApplicationsAdminPageTests(unittest.TestCase):
    def test_forms_not_nested_and_rows_scoped(self):
        seed_companies()
        db = SessionLocal()
        a = GroupBuyApplication(company_id=1, product_name="관리시험", applicant_name="a", contact_type="카카오",
                                contact_value="v", message="m")
        db.add(a)
        db.commit()
        html = client_for(make_user("admin", company_id=1)).get("/applications").text
        parser = _FormNesting()
        parser.feed(html)
        self.assertEqual(parser.nested, 0, "form 안에 form 이 있으면 삭제 버튼이 엉뚱한 곳으로 감")
        self.assertIn(f"/applications/{a.id}/delete", parser.actions)
        self.assertIn(f'form="st-{a.id}-d"', html)
        self.assertIn('<tbody x-data="{ open: false }"', html)
        db.close()



class DuplicateKeyTests(Base):
    """코덱스 재검토 A — 다른 신청을 중복으로 오인하면 안 됨."""

    def test_same_name_different_product_is_new(self):
        name = f"동명제품 {uid()}"
        a = _pub(self.db, name=name, brand="브랜드A")
        b = _pub(self.db, name=name, brand="브랜드B")
        with mock.patch.object(sn, "post"):
            self.apply(a, contact_value="review-contact")
            r = self.apply(b, contact_value="review-contact", return_to="detail")
        self.assertNotIn("dup=1", r.headers["location"])
        self.assertEqual((self.count(a), self.count(b)), (1, 1))

    def test_same_value_different_contact_type_is_new(self):
        p = _pub(self.db)
        with mock.patch.object(sn, "post"):
            self.apply(p, contact_type="카카오", contact_value="review-contact")
            self.apply(p, contact_type="인스타", contact_value="review-contact")
        self.assertEqual(self.count(p), 2)

    def test_other_company_record_does_not_block(self):
        p = _pub(self.db)
        self.db.add(GroupBuyApplication(company_id=2, product_name=p.name, applicant_name="x", contact_type="카카오",
                                        contact_value="shared-contact"))
        self.db.commit()
        with mock.patch.object(sn, "post"):
            self.apply(p, contact_type="카카오", contact_value="shared-contact")
        self.assertEqual(self.count(p), 1)


class ConcurrencyTests(Base):
    """코덱스 재검토 B·C — 동시에 와도 같은 신청 1건, @here 는 상한까지만."""

    def test_concurrent_same_application_saved_once(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from sqlalchemy.orm import Query
        p = _pub(self.db)
        real_first = Query.first

        def slow_first(q, *a, **k):   # '중복 없음'을 확인한 뒤 저장까지의 틈을 넓힌다 (잠금이 없으면 모두 저장됨)
            r = real_first(q, *a, **k)
            if threading.current_thread() is not threading.main_thread():
                __import__("time").sleep(0.15)
            return r

        data = form(contact_value="concurrent-person")
        data.update(product_id=p.id, product_name="x")
        with mock.patch.object(sn, "post"), mock.patch.object(Query, "first", slow_first):
            with ThreadPoolExecutor(5) as ex:
                list(ex.map(lambda _: client_for().post("/public/apply", data=data), range(5)))
        self.assertEqual(self.count(p), 1)

    def test_concurrent_here_reservations_capped(self):
        from concurrent.futures import ThreadPoolExecutor
        cid = 424242
        with ThreadPoolExecutor(20) as ex:
            got = list(ex.map(lambda _: public._reserve_here(cid), range(20)))
        self.assertEqual(sum(got), public.HERE_LIMIT)

if __name__ == "__main__":
    unittest.main()
