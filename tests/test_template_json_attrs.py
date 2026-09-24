"""템플릿 JSON 속성 (RG-006): tojson 을 큰따옴표 속성에 넣어도 화면이 깨지지 않는다.

- 템플릿 전체에 이스케이프 없는 `tojson` 속성이 0건
- 제품 수정·제품 상세·쇼핑몰 화면에서 따옴표가 든 값이 있어도 Alpine 속성이 끝까지 온전하다
"""
from tests import _env  # noqa: F401  (app 보다 먼저)
from tests._env import SessionLocal, client_for, make_user, uid

import importlib.util
import unittest
from html.parser import HTMLParser
from pathlib import Path

from app.models.product import Product
from app.models.sales_page import SalesPage

ROOT = Path(__file__).resolve().parents[1]


def _checker():
    spec = importlib.util.spec_from_file_location("check_tojson_attr", ROOT / ".claude/lib/check_tojson_attr.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _xdata(html_text):
    """HTML 규칙대로 파싱한 x-data 속성값 목록 (브라우저가 보는 값)."""
    out = []

    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            out.extend(v for k, v in attrs if k == "x-data" and v)

    P().feed(html_text)
    return out


def _mk_product(**kw):
    db = SessionLocal()
    try:
        p = Product(name=f"가상상품{uid()}", brand="가상브랜드", category="뷰티", company_id=1, **kw)
        db.add(p)
        db.commit()
        return p.id
    finally:
        db.close()


class TemplateJsonAttrTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = client_for(make_user("admin", company_id=1))

    def test_템플릿에_이스케이프없는_tojson_속성이_없다(self):
        mod = _checker()
        bad = [f"{p.relative_to(ROOT)}:{ln}"
               for p in sorted((ROOT / "app/templates").rglob("*.html"))
               for ln in mod.check_text(p.read_text(encoding="utf-8"))]
        self.assertEqual(bad, [], "RG-006 위반 — `| tojson | forceescape` 로 바꾸세요")

    def test_제품수정_화면의_productPage_속성이_끝까지_온전하다(self):
        pid = _mk_product(categories=["뷰티", "푸드"], set_options=[{"name": '1+1 "특가"', "price": 1000}])
        r = self.c.get(f"/products/{pid}/edit")
        self.assertEqual(r.status_code, 200)
        xs = [x for x in _xdata(r.text) if x.startswith("productPage(")]
        self.assertEqual(len(xs), 1)
        self.assertTrue(xs[0].rstrip().endswith(")"), xs[0][:80])

    def test_제품상세_메모에_따옴표가_있어도_속성이_온전하다(self):
        pid = _mk_product(notes='메모 "따옴표" 포함')
        r = self.c.get(f"/products/{pid}")
        self.assertEqual(r.status_code, 200)
        xs = [x for x in _xdata(r.text) if "editing: false" in x]
        self.assertEqual(len(xs), 1)
        self.assertIn("saved: false }", xs[0])

    def test_쇼핑몰_화면의_shopPage_속성이_끝까지_온전하다(self):
        pid = _mk_product()
        slug = f"t{uid()}"
        db = SessionLocal()
        try:
            db.add(SalesPage(slug=slug, product_id=pid, price=10000, status="active", is_published=True,
                             options=[{"name": '빨강 "L"', "price": 0, "stock": 5}],
                             addon_products=[{"name": "가상추가", "price": 1000, "max_qty": 1}]))
            db.commit()
        finally:
            db.close()
        r = client_for().get(f"/shop/{slug}")
        self.assertEqual(r.status_code, 200)
        xs = [x for x in _xdata(r.text) if x.lstrip().startswith("shopPage(")]
        self.assertEqual(len(xs), 1)
        self.assertTrue(xs[0].rstrip().endswith(")"), xs[0][:80])


if __name__ == "__main__":
    unittest.main()
