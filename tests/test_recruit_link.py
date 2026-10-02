"""모집 링크 — 제품별 공유 미리보기(og) · ?ref= 유입 경로 저장·표시 · 내부 '모집 링크 복사' 버튼."""
from tests import _env  # noqa: F401
from tests._env import SessionLocal, client_for, make_user, seed_companies, uid

import html as htmlmod
import re
from urllib.parse import quote
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

    def saved_latest(self, pid):
        self.db.expire_all()
        return (self.db.query(GroupBuyApplication).filter(GroupBuyApplication.product_id == pid)
                .order_by(GroupBuyApplication.created_at.desc()).first())

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

    def test_abs_image_url(self):
        base = settings.app_base_url.rstrip("/")
        self.assertEqual(public._abs_url("/uploads/a.jpg"), base + "/uploads/a.jpg")
        self.assertEqual(public._abs_url("HTTPS://cdn.x/a.jpg"), "HTTPS://cdn.x/a.jpg")
        self.assertEqual(public._abs_url("//cdn.x/a.jpg"), "https://cdn.x/a.jpg")
        self.assertEqual(public._abs_url("uploads/a.jpg"), base + "/uploads/a.jpg")
        self.assertEqual(public._abs_url("https://cdn.x:8443/a.jpg"), "https://cdn.x:8443/a.jpg")
        self.assertEqual(public._abs_url("https://[::1]/a.jpg"), "https://[::1]/a.jpg")
        for bad in (None, "", "  ", "data:image/png;base64,AAAA", "javascript:alert(1)", "https://", "//",
                    "https://cdn.x:bad/a", "https://cdn.x:99999/a", "https://exa\\mple.com/a",
                    "///cdn.x/a.jpg", "https://cdn.x/a\nb.jpg", "https://cdn.x/a b.jpg", "ftp://cdn.x/a.jpg",
                    "http://[bad/a.jpg"):
            self.assertIsNone(public._abs_url(bad), bad)


class UserCodeTests(unittest.TestCase):
    """코덱스 재검토 A·B — 직원 코드는 계정 고유번호 전체. 겹치지 않고, 개명·다른 계정 삭제에도 안 바뀐다."""

    def mk(self, name, uid_hex, company_id=1, role="staff", raw_id=None):
        from app.models.user import User
        db = SessionLocal()
        h = uid_hex
        u = User(id=raw_id or f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}", username=name, hashed_password="x",
                 role=role, company_id=company_id)
        db.add(u)
        db.commit()
        db.refresh(u)
        db.expunge(u)
        db.close()
        return u

    def test_codes_unique_even_with_same_prefix_and_lookalike_names(self):
        import uuid as _u
        pre = _u.uuid4().hex[:6]
        users = [self.mk(f"foo{pre}", pre + "a" * 26), self.mk(f"f.oo{pre}", pre + "b" * 26),
                 self.mk(f"김혁{pre}", pre + "c" * 26), self.mk(f"u_{pre}", pre + "d" * 26)]
        codes = [public.recruit_user_code(u) for u in users]
        self.assertEqual(len(set(codes)), 4, codes)
        for c in codes:
            for ch in public.RECRUIT_CHANNELS:
                self.assertIsNotNone(public.clean_ref(f"{c}-{ch}"), c)

    def test_code_survives_rename_and_other_deletion(self):
        import uuid as _u
        from app.models.user import User
        a = self.mk(f"foo{uid()}", _u.uuid4().hex)
        b = self.mk(f"f.oo{uid()}", _u.uuid4().hex)
        before = public.recruit_user_code(b)
        db = SessionLocal()
        db.query(User).filter(User.id == a.id).delete()
        db.query(User).filter(User.id == b.id).update({"username": f"renamed{uid()}"})
        db.commit()
        b2 = db.query(User).filter(User.id == b.id).one()
        self.assertEqual(public.recruit_user_code(b2), before)
        db.close()

    def test_non_standard_ids_get_no_code(self):
        """코덱스 3차 B — 표준 UUID 가 아니면 링크를 만들지 않는다 (겹침·40자 초과·이름 조회 실패 방지)."""
        from types import SimpleNamespace as NS
        good = "12345678-1234-4234-8234-123456789abc"
        self.assertEqual(public.recruit_user_code(NS(id=good)), good.replace("-", ""))
        for bad in ("old-admin", "oldadmin", "A" * 36, "김직원", good.upper(), good.replace("-", ""),
                    "{" + good + "}", "urn:uuid:" + good, "", None):
            self.assertIsNone(public.recruit_user_code(NS(id=bad)), bad)

    def test_non_standard_account_sees_disabled_notice(self):
        seed_companies()
        u = self.mk(f"odd{uid()}", "0" * 32, company_id=1, role="admin", raw_id=f"odd-{uid()}")
        db = SessionLocal()
        pid = _pub(db).id
        db.close()
        page = client_for(u).get(f"/products/{pid}").text
        self.assertIn("모집 링크 사용 불가", page)
        self.assertNotIn("data-recruit-link", page)

    def test_labels_show_name_and_channel_only_for_own_company(self):
        import uuid as _u
        seed_companies()
        me = self.mk(f"hyeok{uid()}", _u.uuid4().hex, company_id=1)
        other = self.mk(f"other{uid()}", _u.uuid4().hex, company_id=2)
        g_admin = self.mk(f"gadmin{uid()}", _u.uuid4().hex, company_id=None, role="admin")
        g_partner = self.mk(f"gpartner{uid()}", _u.uuid4().hex, company_id=None, role="partner")
        g_staff = self.mk(f"gstaff{uid()}", _u.uuid4().hex, company_id=None, role="staff")
        my_partner = self.mk(f"mypartner{uid()}", _u.uuid4().hex, company_id=1, role="partner")
        code = lambda u: f"{public.recruit_user_code(u)}-insta"
        mine, theirs = f"{public.recruit_user_code(me)}-kakao", code(other)
        db = SessionLocal()
        labels = public.ref_labels(db, [mine, theirs, "hand-made", None, code(g_admin), code(g_partner),
                                        code(g_staff), code(my_partner)], 1)
        db.close()
        self.assertEqual(labels[mine], f"{me.username} · 카카오톡")
        self.assertEqual(labels[theirs], theirs, "다른 회사 직원 이름은 안 보여줌")
        self.assertEqual(labels[code(g_admin)], f"{g_admin.username} · 인스타 DM", "전체 관리자는 표시")
        for u in (g_partner, g_staff, my_partner):
            self.assertEqual(labels[code(u)], code(u), f"{u.username}: 회사 없는 비관리자·협력사는 이름 숨김")
        self.assertEqual(labels["hand-made"], "hand-made")


class OgTagTests(Base):
    def test_product_specific_preview(self):
        p = _pub(self.db, groupbuy_price=19900, seller_commission_rate=0.2, unique_selling_point="촉촉한 보습",
                 product_image="/uploads/products/a.jpg")
        page = client_for().get(f"/public/products/product/{p.id}").text
        self.assertIn(p.name, meta(page, "og:title"))
        self.assertIn("19,900원", meta(page, "og:title"))
        self.assertNotIn("20%", meta(page, "og:title"), "공유 미리보기에 커미션 노출 금지")
        self.assertNotIn("커미션", meta(page, "og:title"))
        self.assertEqual(meta(page, "og:description"), "촉촉한 보습")
        self.assertEqual(meta(page, "og:image"), settings.app_base_url.rstrip("/") + "/uploads/products/a.jpg")
        self.assertTrue(meta(page, "og:url").endswith(f"/public/products/product/{p.id}"))
        self.assertEqual(page.count('property="og:title"'), 1, "기본 og 와 겹치면 안 됨")

    def test_og_escapes_product_text(self):
        p = _pub(self.db, name='x" onload="alert(1)', unique_selling_point="<img src=x onerror=alert(1)>",
                 product_image="data:image/png;base64,AAAA")
        page = client_for().get(f"/public/products/product/{p.id}").text
        self.assertNotIn('onload="alert', page)
        self.assertNotIn("<img src=x", page)
        self.assertEqual(meta(page, "og:image"), settings.app_base_url.rstrip("/") + "/static/og-image.png")

    def test_no_image_uses_default(self):
        p = _pub(self.db)
        page = client_for().get(f"/public/products/product/{p.id}").text
        self.assertEqual(meta(page, "og:image"), settings.app_base_url.rstrip("/") + "/static/og-image.png")


class RefFlowTests(Base):
    def test_query_ref_goes_into_form_and_cookie(self):
        p = _pub(self.db)
        c = client_for()
        r = c.get(f"/public/products/product/{p.id}?ref=Hyeok-Insta")
        self.assertIn('name="ref" value="hyeok-insta"', r.text)
        self.assertIn("bp_ref=hyeok-insta", r.headers.get("set-cookie", ""))
        ck = r.headers["set-cookie"].lower()
        for part in ("httponly", "secure", "samesite=lax", "max-age=2592000", "path=/"):
            self.assertIn(part, ck)

    def test_pages_not_shared_cached(self):
        """코덱스 검토 3 — 방문자별 ref 가 든 페이지를 중간 캐시가 남에게 주면 안 됨."""
        p = _pub(self.db)
        for url in ("/public/products?ref=a-insta", f"/public/products/product/{p.id}",
                    f"/public/products/brand/{p.brand}", "/public/products/product/없는제품",
                    f"/public/products/{p.id}", f"/public/brand/{p.brand}"):
            r = client_for().get(url)
            self.assertIn("no-store", r.headers.get("cache-control", ""), url)
            self.assertIn("private", r.headers.get("cache-control", ""), url)
            self.assertIn("Cookie", r.headers.get("vary", ""), url)

    def test_apply_redirects_not_cached(self):
        p = _pub(self.db)
        with mock.patch.object(sn, "post"):
            r = client_for().post("/public/apply", data=_form(p.id))
            bad = client_for().post("/public/apply", data=_form(p.id, applicant_name=""))
        for resp in (r, bad):
            self.assertIn(resp.status_code, (302, 303))
            self.assertIn("no-store", resp.headers.get("cache-control", ""))

    def test_old_address_keeps_ref(self):
        p = _pub(self.db)
        r = client_for().get(f"/public/products/{p.id}?ref=kim-insta")
        self.assertEqual(r.headers["location"], f"/public/products/product/{p.id}?ref=kim-insta")
        r = client_for().get(f"/public/products/{p.id}?ref=<bad>")
        self.assertEqual(r.headers["location"], f"/public/products/product/{p.id}")

    def test_old_brand_address_encodes_name(self):
        for name, enc in (("A?x=1", "A%3Fx%3D1"), ("A#B", "A%23B"), ("한 글&", "%ED%95%9C%20%EA%B8%80%26")):
            r = client_for().get(f"/public/brand/{quote(name, safe='')}?ref=kim-insta")
            self.assertEqual(r.headers["location"], f"/public/products/brand/{enc}?ref=kim-insta", name)

    def test_vary_merge(self):
        from starlette.responses import Response
        for before, after in (("Accept-Encoding", "Accept-Encoding, Cookie"), ("cookie", "cookie"), ("*", "*")):
            r = Response(headers={"Vary": before})
            self.assertEqual(public.no_store(r).headers["vary"], after)

    def test_label_failure_does_not_block_apply(self):
        p = _pub(self.db)
        with mock.patch.object(settings, "slack_events", "public_apply"), \
                mock.patch.object(public, "ref_labels", side_effect=RuntimeError("db hiccup")), \
                mock.patch.object(sn, "post", wraps=sn.post) as post:
            r = client_for().post("/public/apply", data=_form(p.id, ref="kim-insta"))
        self.assertIn("applied=1", r.headers["location"])
        joined = " ".join(f["text"] for f in post.call_args.kwargs["blocks"][2]["fields"])
        self.assertIn("유입: kim-insta", joined)

    def test_two_visitors_keep_their_own_ref(self):
        p = _pub(self.db)
        a, b = client_for(), client_for()
        a.cookies.set("bp_ref", "alice-insta")
        b.cookies.set("bp_ref", "bob-kakao")
        url = f"/public/products/product/{p.id}"
        self.assertIn('name="ref" value="alice-insta"', a.get(url).text)
        self.assertIn('name="ref" value="bob-kakao"', b.get(url).text)

    def test_new_link_overrides_old_cookie_bad_link_keeps_it(self):
        p = _pub(self.db)
        c = client_for()
        c.cookies.set("bp_ref", "old-insta")
        url = f"/public/products/product/{p.id}"
        r = c.get(url + "?ref=new-kakao")
        self.assertIn('value="new-kakao"', r.text)
        self.assertIn("bp_ref=new-kakao", r.headers["set-cookie"])
        c2 = client_for()
        c2.cookies.set("bp_ref", "old-insta")
        r = c2.get(url + "?ref=<bad>")
        self.assertIn('name="ref" value="old-insta"', r.text)
        self.assertNotIn("set-cookie", {k.lower() for k in r.headers.keys()})

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
        staff = make_user("staff", company_id=1)
        code = f"{public.recruit_user_code(staff)}-kakao"
        with mock.patch.object(settings, "slack_events", "public_apply"), \
                mock.patch.object(sn, "post", wraps=sn.post) as post2:
            client_for().post("/public/apply", data=_form(p.id, ref=code))
        joined = " ".join(f["text"] for f in post2.call_args.kwargs["blocks"][2]["fields"])
        self.assertIn(f"유입: {staff.username} · 카카오톡", joined)
        field = [f for f in post2.call_args.kwargs["blocks"][2]["fields"] if f["text"].startswith("유입")][0]
        self.assertEqual(field["type"], "plain_text")
        self.assertEqual(self.saved_latest(p.id).source_ref, code, "저장은 코드 그대로")
        field = [f for f in post.call_args_list[0].kwargs["blocks"][2]["fields"] if f["text"].startswith("유입")][0]
        self.assertEqual(field["type"], "plain_text")


class AdminTests(Base):
    def test_applications_page_shows_source(self):
        a = GroupBuyApplication(company_id=1, product_name="유입표시", applicant_name="a", contact_type="카카오",
                                contact_value="v", source_ref=f"hyeok-{uid()}"[:40])
        self.db.add(a)
        self.db.commit()
        page = client_for(make_user("admin", company_id=1)).get("/applications").text
        self.assertGreaterEqual(page.count(f"유입 · {a.source_ref}"), 2, "휴대폰·PC 둘 다")

    def test_applications_page_shows_staff_name(self):
        admin = make_user("admin", company_id=1)
        staff = make_user("staff", company_id=1)
        a = GroupBuyApplication(company_id=1, product_name="이름표시", applicant_name="a", contact_type="카카오",
                                contact_value="v", source_ref=f"{public.recruit_user_code(staff)}-insta")
        self.db.add(a)
        self.db.commit()
        page = client_for(admin).get("/applications").text
        self.assertGreaterEqual(page.count(f"유입 · {staff.username} · 인스타 DM"), 2)

    def test_recruit_button_on_internal_detail(self):
        p = _pub(self.db)
        hidden = _pub(self.db, visibility_status="hidden")
        admin_user = make_user("admin", company_id=1)
        admin = client_for(admin_user)
        page = admin.get(f"/products/{p.id}").text
        self.assertIn("모집 링크 복사", page)
        self.assertIn(f'data-url="{settings.app_base_url.rstrip("/")}/public/products/product/{p.id}"', page)
        self.assertIn('data-user="' + public.recruit_user_code(admin_user) + '"', page)
        self.assertNotIn("공개 카탈로그에 안 보여요", page)
        self.assertIn("공개 카탈로그에 안 보여요", admin.get(f"/products/{hidden.id}").text)


class ClipboardFallbackTests(unittest.TestCase):
    """코덱스 검토 1 — 복사 기능이 없거나 실패해도 링크를 직접 복사할 창이 뜬다 (node 로 실제 코드 실행)."""

    def test_copy_paths(self):
        import json, shutil, subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node 없음")
        seed_companies()
        db = SessionLocal()
        pid = _pub(db).id
        db.close()
        page = client_for(make_user("admin", company_id=1)).get(f"/products/{pid}").text
        xdata = htmlmod.unescape(re.search(r'<div x-data="(\{ open: false, ch:.*?\})"\s', page, re.S).group(1))
        js = """
const make = new Function('return (' + %s + ')');
const cases = {none: undefined, reject: {writeText: () => Promise.reject(new Error('no'))},
  sync: {writeText: () => { throw new Error('boom') }}, ok: {writeText: () => Promise.resolve()}};
(async () => { const out = {};
  for (const [k, cb] of Object.entries(cases)) {
    const prompts = []; Object.defineProperty(globalThis, 'navigator', {value: {clipboard: cb}, configurable: true, writable: true}); global.window = {prompt: (m, t) => prompts.push(t)};
    global.setTimeout = () => 0;
    const o = make(); o.$refs = {base: {dataset: {url: 'https://x/p/1', user: 'hy'}}}; o.ch = 'kakao';
    try { o.copy() } catch (e) { out[k] = 'throw'; continue }
    await new Promise(r => setImmediate(r));
    out[k] = {prompts, done: o.done};
  }
  console.log(JSON.stringify(out)); })();
""" % json.dumps(xdata)
        r = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        link = "https://x/p/1?ref=hy-kakao"
        for k in ("none", "reject", "sync"):
            self.assertEqual(out[k], {"prompts": [link], "done": False}, k)
        self.assertEqual(out["ok"], {"prompts": [], "done": True})


if __name__ == "__main__":
    unittest.main()
