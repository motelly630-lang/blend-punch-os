"""템플릿 폼 주소 (IM-012): 폼·htmx 가 보내는 주소가 실제 서버 주소다.

- 코드로 읽은 서버 주소 목록이 실제 앱 주소와 같다 (검사기가 믿을 만한지)
- 모든 템플릿의 action / hx-* 주소가 분기별로 실제 주소와 맞는다
"""
from tests import _env  # noqa: F401  (app 보다 먼저)

import importlib.util
import unittest
from pathlib import Path

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
AUTO_DOCS = {"/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc"}


def _checker():
    spec = importlib.util.spec_from_file_location("check_form_urls", ROOT / ".claude/lib/check_form_urls.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TemplateFormUrlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _checker()
        cls.routes = cls.mod.collect_routes(ROOT)

    def test_코드로_읽은_주소목록이_실제_앱과_같다(self):
        real = {(m, r.path) for r in app.routes for m in (getattr(r, "methods", None) or [])
                if m != "HEAD" and r.path not in AUTO_DOCS}
        self.assertEqual(real - set(self.routes), set(), "검사기가 놓친 서버 주소")
        self.assertEqual(set(self.routes) - real, set(), "검사기가 지어낸 서버 주소")

    def test_모든_템플릿의_폼주소가_실제_주소다(self):
        bad = []
        for f in sorted((ROOT / "app/templates").rglob("*.html")):
            for ln, attr, url, v in self.mod.check_text(f.read_text(encoding="utf-8"), self.routes):
                bad.append(f"{f.relative_to(ROOT)}:{ln} {attr} → {v}")
        self.assertEqual(bad, [])

    def test_슬래시_빠진_주소는_잡는다(self):
        bad = '<form action="/influencers{% if i %}/{{ i.id }}/edit{% else %}new{% endif %}">'
        got = [v for *_, v in self.mod.check_text(bad, self.routes)]
        self.assertEqual(got, ["/influencersnew"])


if __name__ == "__main__":
    unittest.main()
