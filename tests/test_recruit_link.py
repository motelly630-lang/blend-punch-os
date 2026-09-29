"""모집 링크 — 제품별 공유 미리보기(og) · ?ref= 유입 경로 저장·표시 · 내부 '모집 링크 복사' 버튼."""
from tests import _env  # noqa: F401
from tests._env import SessionLocal, client_for, make_user, seed_companies, uid

import html as htmlmod
import re
import unittest
from unittest import mock

from app.config import settings
from app.models import Product
from app.models.group_buy_application import GroupBuyApplication
from app.routers import public
from app.services import slack_notify as sn


def _pub(db, **kw):
    base = dict(name=f"모집시험 {uid()}", brand=f"모집브랜드{uid()}", category="기타", company_id=1,
                status="active", visibility_status="active")
    base.update(kw)
    p = Product(**base)
    db.add(p)
    db.commit()
    return p


def _form(pid, **kw):
    d = {"applicant_name": "김가상", "contact_type": "카카오", "contact_value": f"k{uid()}", "product_id": pid,
         "product_name": "x", "return_to": "detail"}
    d.update(kw)
    return d


def meta(page, prop):
    m = re.search(rf'<meta property="{prop}" content="([^"]*)"', page)
    return htmlmod.unescape(m.group(1)) if m else None


class Base(unittest.TestCase):
    def setUp(self):
        seed_companies()
        self.db = SessionLocal()
        public._apply_hits.clear()
        public._here_times.clear()

    def tearDown(self):
        self.db.close()

    def saved(self, pid):
        self.db.expire_all()
        return self.db.query(GroupBuyApplication).filter(GroupBuyApplication.product_id == pid).one()


class CleanRefTests(unittest.TestCase):
    def test_accepts_and_normalizes(self):
        self.assertEqual(public.clean_ref(" Hyeok-Insta "), "hyeok-insta")
        self.assertEqual(public.clean_ref("kim_01-kakao"), "kim_01-kakao")

    def test_rejects_bad(self):
        for v in (None, "", "-x", "a" * 41, "<script>", "한글-insta", "a b", "x/y"):
            self.assertIsNone(public.clean_ref(v), v)

    def test_user_code(self):
        self.assertEqual(public.recruit_user_code("Hyeok"), "hyeok")
        self.assertEqual(public.recruit_user_code("김 혁"), "staff")
        self.assertEqual(public.recruit_user_code("a.b@c"), "abc")
        self.assertIsNotNone(public.clean_ref(public.recruit_user_code("x" * 80) + "-insta"))


class OgTagTests(Base):
    def test_product_specific_preview(self):
        p = _pub(self.db, groupbuy_price=19900, seller_commission_rate=0.2, unique_selling_point="촉촉한 보습",
                 product_image="/uploads/products/a.jpg")
        page = client_for().get(f"/public/products/product/{p.id}").text
        self.assertIn(p.name, meta(page, "og:title"))
        self.assertIn("19,900원", meta(page, "og:title"))
        self.assertIn("20%", meta(page, "og:title"))
        self.assertEqual(meta(page, "og:description"), "촉촉한 보습")
        self.assertEqual(meta(page, "og:image"), settings.app_base_url.rstrip("/") + "/uploads/products/a.jpg")
        self.assertTrue(meta(page, "og:url").endswith(f"/public/products/product/{p.id}"))
        self.assertEqual(page.count('property="og:title"'), 1, "기본 og 와 겹치면 안 됨")

    def test_no_image_uses_default(self):
        p = _pub(self.db)
        page = client_for().get(f"/public/products/product/{p.id}").text
        self.assertTrue(meta(page, "og:image").endswith("/static/og-image.png"))
        self.assertTrue(meta(page, "og:image").startswith("http"))


class RefFlowTests(Base):
    def test_query_ref_goes_into_form_and_cookie(self):
        p = _pub(self.db)
        c = client_for()
        r = c.get(f"/public/products/product/{p.id}?ref=Hyeok-Insta")
        self.assertIn('name="ref" value="hyeok-insta"', r.text)
        self.assertIn("bp_ref=hyeok-insta", r.headers.get("set-cookie", ""))
        self.assertIn("httponly", r.headers["set-cookie"].lower())

    def test_bad_ref_not_stored(self):
        p = _pub(self.db)
        r = client_for().get(f"/public/products/product/{p.id}?ref=<x>")
        self.assertNotIn("bp_ref", r.headers.get("set-cookie", ""))
        self.assertIn('name="ref" value=""', r.text)

    def test_apply_saves_form_ref(self):
        p = _pub(self.db)
        with mock.patch.object(sn, "post"):
            client_for().post("/public/apply", data=_form(p.id, ref="hyeok-kakao"))
        self.assertEqual(self.saved(p.id).source_ref, "hyeok-kakao")

    def test_apply_falls_back_to_cookie(self):
        """목록에서 링크로 들어와 다른 제품을 신청해도 처음 유입 경로가 남는다."""
        p = _pub(self.db)
        c = client_for()
        r = c.get("/public/products?ref=kim-dm")
        self.assertIn("bp_ref=kim-dm", r.headers.get("set-cookie", ""))
        c.cookies.set("bp_ref", "kim-dm")   # 운영은 https 라 브라우저가 돌려보냄 (시험 클라이언트는 http)
        with mock.patch.object(sn, "post"):
            c.post("/public/apply", data=_form(p.id))
        self.assertEqual(self.saved(p.id).source_ref, "kim-dm")

    def test_bad_form_ref_ignored(self):
        p = _pub(self.db)
        with mock.patch.object(sn, "post"):
            r = client_for().post("/public/apply", data=_form(p.id, ref="<!here> evil"))
        self.assertIn("applied=1", r.headers["location"])
        self.assertIsNone(self.saved(p.id).source_ref)

    def test_brand_modal_has_ref(self):
        p = _pub(self.db)
        page = client_for().get(f"/public/products/brand/{p.brand}?ref=lee-insta").text
        self.assertIn('name="ref" value="lee-insta"', page)

    def test_slack_shows_source(self):
        p = _pub(self.db)
        with mock.patch.object(settings, "slack_events", "public_apply"), \
                mock.patch.object(sn, "post", wraps=sn.post) as post:
            client_for().post("/public/apply", data=_form(p.id, ref="hyeok-insta"))
            client_for().post("/public/apply", data=_form(p.id))
        texts = [" ".join(f["text"] for f in c.kwargs["blocks"][2]["fields"]) for c in post.call_args_list]
        self.assertIn("유입: hyeok-insta", texts[0])
        self.assertIn("유입: 직접 방문", texts[1])


class AdminTests(Base):
    def test_applications_page_shows_source(self):
        a = GroupBuyApplication(company_id=1, product_name="유입표시", applicant_name="a", contact_type="카카오",
                                contact_value="v", source_ref=f"hyeok-{uid()}"[:40])
        self.db.add(a)
        self.db.commit()
        page = client_for(make_user("admin", company_id=1)).get("/applications").text
        self.assertGreaterEqual(page.count(f"유입 · {a.source_ref}"), 2, "휴대폰·PC 둘 다")

    def test_recruit_button_on_internal_detail(self):
        p = _pub(self.db)
        hidden = _pub(self.db, visibility_status="hidden")
        admin = client_for(make_user("admin", company_id=1))
        page = admin.get(f"/products/{p.id}").text
        self.assertIn("모집 링크 복사", page)
        self.assertIn(f'data-url="{settings.app_base_url.rstrip("/")}/public/products/product/{p.id}"', page)
        self.assertNotIn("공개 카탈로그에 안 보여요", page)
        self.assertIn("공개 카탈로그에 안 보여요", admin.get(f"/products/{hidden.id}").text)


if __name__ == "__main__":
    unittest.main()
