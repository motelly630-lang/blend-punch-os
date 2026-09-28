"""자동 채우기 1단계 — 판매 페이지에서 사진·가격·소개 후보 뽑기 + 제안 주소."""
from tests import _env  # noqa: F401
from tests._env import SessionLocal, client_for, make_user, uid

import unittest
from unittest import mock

import httpx

from app.models import Product
from app.services.page_suggest import extract

LD_PAGE = """<html><head><title>쇼핑몰 | 가상 크림</title>
<meta property="og:image" content="/img/og.jpg">
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Organization","name":"몰"},
 {"@type":"Product","name":"가상 수분크림 50ml","image":["https://cdn.example/p1.jpg"],
  "description":"  하루 종일   촉촉한 &amp; 가벼운 크림 ",
  "offers":{"@type":"Offer","price":"29000","priceCurrency":"KRW"}}]}</script></head><body></body></html>"""

OG_PAGE = """<html><head><meta property="og:title" content="가상 떡갈비">
<meta property="og:image" content="//cdn.example/tteok.png">
<meta property="product:price:amount" content="15,900원">
<meta name="description" content="아이 반찬으로 좋은 떡갈비"></head></html>"""


class ExtractTests(unittest.TestCase):
    def test_json_ld_product_first(self):
        got = extract(LD_PAGE, "https://shop.example/p/1")
        self.assertEqual((got["name"], got["image"], got["price"], got["description"]),
                         ("가상 수분크림 50ml", "https://cdn.example/p1.jpg", 29000, "하루 종일 촉촉한 & 가벼운 크림"))
        self.assertEqual(got["sources"]["price"], "구조화 정보")

    def test_og_fallback_and_protocol_relative_image(self):
        got = extract(OG_PAGE, "https://shop.example/p/2")
        self.assertEqual((got["name"], got["image"], got["price"], got["description"]),
                         ("가상 떡갈비", "https://cdn.example/tteok.png", 15900, "아이 반찬으로 좋은 떡갈비"))

    def test_relative_image_and_empty_page(self):
        got = extract('<meta property="og:image" content="/a.jpg">', "https://shop.example/x/y")
        self.assertEqual(got["image"], "https://shop.example/a.jpg")
        empty = extract("<html></html>", "https://shop.example/")
        self.assertFalse(any(empty[k] for k in ("name", "image", "price", "description")))

    def test_bad_values_ignored(self):
        got = extract('<meta property="og:image" content="javascript:alert(1)">'
                      '<meta property="product:price:amount" content="0">', "https://shop.example/")
        self.assertIsNone(got["image"])
        self.assertIsNone(got["price"])


class SuggestEndpointTests(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.p = Product(name=f"제안시험 {uid()}", brand="x", category="기타", company_id=1)
        self.db.add(self.p)
        self.db.commit()
        self.c1 = client_for(make_user("admin", company_id=1))

    def tearDown(self):
        self.db.close()

    def post(self, client, url):
        return client.post(f"/products/{self.p.id}/suggest", json={"source_url": url}).json()

    def test_returns_suggestions_without_saving(self):
        fake = httpx.Response(200, text=LD_PAGE, request=httpx.Request("GET", "https://93.184.216.34/"))
        with mock.patch("app.services.safe_fetch.safe_get", return_value=fake):
            d = self.post(self.c1, "https://shop.example/p/1")
        self.assertTrue(d["ok"])
        self.assertEqual(d["suggestions"]["price"], 29000)
        self.db.expire_all()
        self.assertIsNone(self.db.get(Product, self.p.id).product_image, "제안만 — 저장하면 안 됨")

    def test_blocked_site_and_internal_address(self):
        blocked = httpx.Response(403, text="no", request=httpx.Request("GET", "https://93.184.216.34/"))
        with mock.patch("app.services.safe_fetch.safe_get", return_value=blocked):
            d = self.post(self.c1, "https://shop.example/p/1")
        self.assertFalse(d["ok"])
        self.assertIn("막았습니다", d["error"])
        d = self.post(self.c1, "http://169.254.169.254/latest/meta-data/")
        self.assertFalse(d["ok"])
        self.assertIn("열 수 없는 주소", d["error"])

    def test_other_company_cannot_use(self):
        c2 = client_for(make_user("admin", company_id=2))
        r = c2.post(f"/products/{self.p.id}/suggest", json={"source_url": "https://shop.example/"})
        self.assertEqual(r.status_code, 404)

    def test_accepted_suggestion_logged_as_autofill(self):
        from app.models import ProductFieldLog
        self.c1.patch(f"/products/{self.p.id}/field", json={"field": "consumer_price", "value": "29000",
                                                           "via": "autofill", "source_url": "https://shop.example/p/1"})
        self.db.expire_all()
        lg = self.db.query(ProductFieldLog).filter(ProductFieldLog.product_id == self.p.id).one()
        self.assertEqual((lg.field, lg.via, lg.source_url), ("consumer_price", "autofill", "https://shop.example/p/1"))



class SuggestBoxEscapingTests(unittest.TestCase):
    def test_js_escaper_handles_quotes(self):
        """제안 상자는 외부 페이지 글자를 HTML 속성에 넣는다 — 따옴표까지 바꾸는 esc 여야 한다
        (2026-09-28 자동 보안 검사 지적, 브라우저로 실행 재현 후 수정)."""
        from pathlib import Path
        html = Path("app/templates/products/list.html").read_text(encoding="utf-8")
        i = html.index("function esc(t)")
        body = html[i:i + 400]
        self.assertIn("&quot;", body)
        self.assertIn("&#39;", body)
        self.assertNotIn("textContent", body, "textContent→innerHTML 방식은 따옴표를 바꾸지 않는다")



class CopyButtonTests(unittest.TestCase):
    def test_install_page_has_bookmarklet(self):
        r = client_for(make_user("admin", company_id=1)).get("/products/copy-button")
        self.assertEqual(r.status_code, 200)
        self.assertIn("javascript:(function(){", r.text.replace("&#39;", "'"))
        self.assertIn("BPOS1:", r.text)

    def test_bookmarklet_is_valid_javascript(self):
        import shutil
        import subprocess
        import tempfile
        from app.routers.products import COPY_BUTTON_JS
        node = shutil.which("node")
        if not node:
            self.skipTest("node 없음")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(COPY_BUTTON_JS)
        self.assertEqual(subprocess.run([node, "--check", f.name]).returncode, 0)

    def test_copybtn_log_label(self):
        db = SessionLocal()
        p = Product(name=f"복사버튼 {uid()}", brand="x", category="기타", company_id=1)
        db.add(p)
        db.commit()
        c = client_for(make_user("admin", company_id=1))
        c.patch(f"/products/{p.id}/field", json={"field": "unique_selling_point", "value": f"복사소개 {uid()}",
                                               "via": "copybtn", "source_url": "https://smartstore.naver.com/x/products/1"})
        page = c.get("/products?view=fill&missing=image").text
        self.assertIn("복사 버튼</span>", page)
        db.close()


if __name__ == "__main__":
    unittest.main()
