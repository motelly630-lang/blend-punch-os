"""공개 카탈로그 공구 신청 — 제품 상세 신청 버튼 · 저장 · Slack 02-공동구매-운영 알림."""
from tests import _env  # noqa: F401
from tests._env import SessionLocal, client_for, seed_companies, uid

import unittest
from unittest import mock

from app.models import Product
from app.models.group_buy_application import GroupBuyApplication
from app.routers import public


def _pub(db, **kw):
    base = dict(name=f"신청시험 {uid()}", brand=f"신청브랜드{uid()}", category="기타", company_id=1,
                status="active", visibility_status="active")
    base.update(kw)
    p = Product(**base)
    db.add(p)
    db.commit()
    return p


FORM = {"applicant_name": "김가상", "contact_type": "카카오", "contact_value": "kim1234",
        "channel_handle": "@kim_mom", "followers": "5만", "message": "다음 달 초 진행 희망"}


class ApplyTests(unittest.TestCase):
    def setUp(self):
        seed_companies()
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_detail_page_has_apply_button_and_form(self):
        p = _pub(self.db)
        html = client_for().get(f"/public/products/product/{p.id}").text
        self.assertIn("공구 신청하기", html)
        self.assertIn('action="/public/apply"', html)
        self.assertIn('name="return_to" value="detail"', html)

    def test_apply_from_detail_saves_and_notifies_slack(self):
        p = _pub(self.db)
        with mock.patch("app.services.slack_notify.post") as post:
            r = client_for().post("/public/apply", data={**FORM, "product_id": p.id, "product_name": "화면조작이름",
                                                         "brand": "x", "return_to": "detail"})
        self.assertEqual(r.headers["location"], f"/public/products/product/{p.id}?applied=1")
        a = self.db.query(GroupBuyApplication).filter(GroupBuyApplication.product_id == p.id).one()
        self.assertEqual((a.company_id, a.product_name, a.brand, a.applicant_name, a.contact_value),
                         (1, p.name, p.brand, "김가상", "kim1234"))
        post.assert_called_once()
        args, kw = post.call_args
        self.assertEqual((args[0], args[1], args[3]), ("public_apply", "groupbuy", 1))
        self.assertEqual(kw["dedupe_key"], f"public_apply:{a.id}")
        body = kw["blocks"][1]["text"]["text"]
        self.assertTrue(body.startswith("<!here> "), "놓치지 않게 @here")
        for piece in (p.name, "김가상", "카카오", "kim1234", "@kim_mom", "5만", "다음 달 초 진행 희망"):
            self.assertIn(piece, body)
        self.assertIn("/applications", kw["blocks"][2]["elements"][0]["text"])

    def test_applicant_text_cannot_ping_or_spoof_links(self):
        p = _pub(self.db)
        evil = {**FORM, "applicant_name": "<!channel> 긴급", "message": "<https://evil.example|OS 로그인>"}
        with mock.patch("app.services.slack_notify.post") as post:
            client_for().post("/public/apply", data={**evil, "product_id": p.id, "product_name": "x"})
        body = post.call_args.kwargs["blocks"][1]["text"]["text"]
        self.assertEqual(body.count("<!"), 1, "@here 는 우리가 넣은 하나뿐")
        self.assertIn("&lt;!channel&gt;", body)
        self.assertIn("&lt;https://evil.example|OS 로그인&gt;", body)

    def test_non_public_product_not_linked(self):
        hidden = _pub(self.db, visibility_status="hidden")
        with mock.patch("app.services.slack_notify.post"):
            client_for().post("/public/apply", data={**FORM, "product_id": hidden.id, "product_name": "숨김",
                                                     "brand": "b"})
        a = self.db.query(GroupBuyApplication).filter(GroupBuyApplication.product_name == "숨김").first()
        self.assertIsNotNone(a)
        self.assertIsNone(a.product_id, "공개 제품이 아니면 연결하지 않음")

    def test_slack_failure_does_not_block_application(self):
        p = _pub(self.db)
        with mock.patch("app.services.slack_notify.post", side_effect=RuntimeError("slack down")):
            r = client_for().post("/public/apply", data={**FORM, "product_id": p.id, "product_name": "x",
                                                         "return_to": "detail"})
        self.assertIn("applied=1", r.headers["location"])
        self.assertEqual(self.db.query(GroupBuyApplication).filter(GroupBuyApplication.product_id == p.id).count(), 1)

    def test_event_is_off_unless_enabled(self):
        from app.services import slack_notify as sn
        with mock.patch.object(sn, "_api") as api:
            res = sn.post(public.APPLY_SLACK_EVENT, "groupbuy", "x", 1)
        self.assertEqual(res["status"], "off")
        api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
