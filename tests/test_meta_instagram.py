"""Meta 인스타 조회(DE-006): 정상 조회, 개인 계정·토큰 만료·한도 안내, 오류 속 토큰 가림, 사진 저장 검사,
URL 가져오기 화면 연결 (이름은 비우고 표시 이름은 참고용, 실패하면 아이디만)."""
from tests import _env
from tests._env import client_for, make_user

import unittest
from pathlib import Path
from unittest import mock

from app.config import settings
from app.services import meta_instagram as m

FAKE = "EAAfaketoken" + "x" * 30


class _Resp:
    def __init__(self, data=None, status=200, headers=None, content=b""):
        self._d, self.status_code, self.headers, self.content = data, status, headers or {}, content

    def json(self):
        return self._d

    def iter_bytes(self):
        for i in range(0, len(self.content), 1024 * 1024):
            yield self.content[i:i + 1024 * 1024]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Client:
    """httpx.Client 대역 — Graph API 응답 / 이미지 응답을 흉내낸다."""
    graph = {}
    image = _Resp(headers={"content-type": "image/jpeg"}, content=b"\xff\xd8fakejpeg")
    calls = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None, headers=None):
        _Client.calls.append((url, params, headers))
        return _Resp(_Client.graph)

    def stream(self, method, url):
        _Client.calls.append((url, None, None))
        return _Client.image


OK = {"business_discovery": {"username": "gasang_seller", "name": "가상 소개 문구 계정", "biography": "소개",
                             "profile_picture_url": "https://scontent-icn2-1.cdninstagram.com/v/p.jpg", "followers_count": 12345,
                             "media_count": 67}}


class MetaBase(unittest.TestCase):
    def setUp(self):
        self._saved = (settings.meta_page_token, settings.meta_ig_user_id)
        settings.meta_page_token, settings.meta_ig_user_id = FAKE, "17840000000000000"
        _Client.graph, _Client.calls = OK, []
        _Client.image = _Resp(headers={"content-type": "image/jpeg"}, content=b"\xff\xd8fakejpeg")
        self._p = mock.patch.object(m.httpx, "Client", _Client)
        self._p.start()
        self.saved_files = []

    def tearDown(self):
        self._p.stop()
        settings.meta_page_token, settings.meta_ig_user_id = self._saved
        for f in self.saved_files:
            Path("." + f).unlink(missing_ok=True)


class FetchTests(MetaBase):
    def test_정상_조회(self):
        p = m.fetch_profile("@gasang_seller")
        self.assertEqual((p["handle"], p["followers"], p["media_count"]), ("gasang_seller", 12345, 67))
        self.assertEqual(p["display_name"], "가상 소개 문구 계정")
        url, params, headers = _Client.calls[0]
        self.assertIn("business_discovery.username(gasang_seller)", params["fields"])
        # 토큰은 주소(쿼리)가 아니라 헤더로 — 주소는 로그에 남는다 (리뷰 지적)
        self.assertNotIn("access_token", params); self.assertNotIn(FAKE, url)
        self.assertEqual(headers["Authorization"], f"Bearer {FAKE}")

    def test_개인_계정이면_알기_쉽게_안내(self):
        _Client.graph = {"error": {"code": 110, "error_subcode": 2207013, "message": "Invalid user id"}}
        with self.assertRaises(m.MetaError) as cm:
            m.fetch_profile("private_person")
        self.assertIn("개인 계정", str(cm.exception))

    def test_토큰_만료_안내(self):
        _Client.graph = {"error": {"code": 190, "message": "Error validating access token"}}
        with self.assertRaises(m.MetaError) as cm:
            m.fetch_profile("gasang_seller")
        self.assertIn("토큰", str(cm.exception))

    def test_호출_한도_안내(self):
        _Client.graph = {"error": {"code": 4, "message": "Application request limit reached"}}
        with self.assertRaises(m.MetaError) as cm:
            m.fetch_profile("gasang_seller")
        self.assertIn("한도", str(cm.exception))

    def test_오류_메시지_속_토큰은_가린다(self):
        _Client.graph = {"error": {"code": 999, "message": f"Malformed access token {FAKE}"}}
        with self.assertRaises(m.MetaError) as cm:
            m.fetch_profile("gasang_seller")
        self.assertNotIn(FAKE, str(cm.exception))
        self.assertIn("가림", str(cm.exception))

    def test_아이디_형식이_아니면_호출하지_않는다(self):
        with self.assertRaises(m.MetaError):
            m.fetch_profile("a b<script>")
        self.assertEqual(_Client.calls, [])

    def test_설정이_없으면_안내(self):
        settings.meta_page_token = ""
        self.assertFalse(m.available())
        with self.assertRaises(m.MetaError):
            m.fetch_profile("gasang_seller")


class ImageTests(MetaBase):
    def test_사진을_저장한다(self):
        path = m.save_profile_image("https://scontent-icn2-1.cdninstagram.com/v/p.jpg")
        self.saved_files.append(path)
        self.assertTrue(path.startswith("/static/uploads/influencers/") and path.endswith(".jpg"))
        self.assertTrue(Path("." + path).exists())

    def test_이미지가_아니면_저장하지_않는다(self):
        _Client.image = _Resp(headers={"content-type": "text/html"}, content=b"<html>")
        self.assertEqual(m.save_profile_image("https://scontent-icn2-1.cdninstagram.com/v/p.jpg"), "")

    def test_너무_큰_파일은_저장하지_않는다(self):
        _Client.image = _Resp(headers={"content-type": "image/jpeg"}, content=b"x" * (m.MAX_IMAGE_BYTES + 1))
        self.assertEqual(m.save_profile_image("https://scontent-icn2-1.cdninstagram.com/v/p.jpg"), "")

    def test_인스타_페북_서버_주소가_아니면_받지_않는다(self):
        for bad in ("http://scontent.cdninstagram.com/p.jpg", "https://evil.example/p.jpg",
                    "https://cdninstagram.com.evil.example/p.jpg", "https://169.254.169.254/latest"):
            self.assertEqual(m.save_profile_image(bad), "", bad)
        self.assertEqual(_Client.calls, [])

    def test_요청_주소_로그가_꺼져_있다(self):
        import logging
        import app.main  # noqa: F401  (로그 설정 적용)
        self.assertGreaterEqual(logging.getLogger("httpx").getEffectiveLevel(), logging.WARNING)


class UrlFillTests(MetaBase):
    @classmethod
    def setUpClass(cls):
        cls.c = client_for(make_user("admin", company_id=1))

    def test_URL로_아이디_팔로워_사진을_채우고_이름은_비운다(self):
        r = self.c.post("/api/ai/influencer-url-fill", data={"url": "https://www.instagram.com/gasang_seller/"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("@gasang_seller", r.text); self.assertIn("팔로워 12,345", r.text); self.assertIn("사진 ✓", r.text)
        self.assertIn("참고용", r.text)                       # 표시 이름은 참고로만
        self.assertIn("&quot;name&quot;: &quot;&quot;", r.text)   # 폼에 넣을 이름은 비어 있음
        import re
        m_path = re.search(r"/static/uploads/influencers/[0-9a-f]+\.jpg", r.text)
        self.assertIsNotNone(m_path); self.saved_files.append(m_path.group(0))

    def test_게시물_주소면_프로필_주소를_달라고_안내(self):
        r = self.c.post("/api/ai/influencer-url-fill", data={"url": "https://www.instagram.com/p/ABC123/"})
        self.assertIn("프로필 주소", r.text)
        self.assertEqual(_Client.calls, [])

    def test_조회_실패면_이유와_함께_아이디만(self):
        _Client.graph = {"error": {"code": 110, "error_subcode": 2207013, "message": "x"}}
        r = self.c.post("/api/ai/influencer-url-fill", data={"url": "https://instagram.com/private_person"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("개인 계정", r.text); self.assertIn("아이디만 입력되었습니다", r.text)
        self.assertIn("@private_person", r.text)


if __name__ == "__main__":
    unittest.main()
