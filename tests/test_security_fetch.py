"""SSRF 방지(safe_fetch)와 AI 링크 분석 주소의 로그인 요구."""
from tests import _env  # noqa: F401
from tests._env import client_for, make_user

import unittest

import httpx

from app.services import safe_fetch
from app.services.safe_fetch import UnsafeURL, address_problem, safe_get

PUBLIC_IP = "http://93.184.216.34"   # 공인 IP (실제 통신은 가짜 transport 로만)


class AddressProblemTests(unittest.TestCase):
    def test_blocks_internal_and_bad_schemes(self):
        for url in ("http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/", "http://10.0.0.5/",
                    "http://192.168.0.1/", "http://172.16.0.1/", "http://[::1]/", "http://0.0.0.0/",
                    "http://[fd00::1]/", "file:///etc/passwd", "ftp://93.184.216.34/", "gopher://x/",
                    "http:///nohost"):
            self.assertIsNotNone(address_problem(url), url)

    def test_allows_public_ip(self):
        self.assertIsNone(address_problem(PUBLIC_IP + "/page"))


class SafeGetTests(unittest.TestCase):
    def test_redirect_to_metadata_is_blocked(self):
        def handler(req):
            if req.url.host == "93.184.216.34":
                return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
            raise AssertionError("내부 주소로 요청이 나가면 안 됨")
        with self.assertRaises(UnsafeURL):
            safe_get(PUBLIC_IP + "/r", transport=httpx.MockTransport(handler))

    def test_body_size_limited_and_ok_page(self):
        big = b"a" * 50_000
        r = safe_get(PUBLIC_IP + "/p", max_bytes=1000,
                     transport=httpx.MockTransport(lambda req: httpx.Response(200, content=big)))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.content), 1000)

    def test_fetch_page_refuses_internal(self):
        from app.ai.web_scraper import fetch_page
        self.assertIn("거부", fetch_page("http://169.254.169.254/latest/meta-data/"))


class AiProductFillAuthTests(unittest.TestCase):
    def test_requires_login(self):
        c = client_for()
        for path, data in (("/api/ai/product-fill", {"url": "http://169.254.169.254/"}),
                           ("/api/ai/product-text-fill", {"raw_text": "x"})):
            r = c.post(path, data=data)
            self.assertIn(r.status_code, (302, 303, 401, 403), path)

    def test_logged_in_internal_url_refused_without_network(self):
        """로그인해도 내부 주소는 실제로 요청이 나가지 않아야 한다 (코덱스: 응답 내용만 보던 허술한 시험 교체)."""
        srv, base, hits = _local_server(b"LOCAL_ONLY_MARKER", "text/html")
        try:
            c = client_for(make_user("admin", company_id=1))
            r = c.post("/api/ai/product-fill", data={"url": base + "/secret"})
            self.assertEqual(r.status_code, 200)
        finally:
            srv.shutdown()
        self.assertEqual(hits, [], "내부 주소로 요청이 나가면 안 됨")
        self.assertNotIn("LOCAL_ONLY_MARKER", r.text)


def _png_bytes():
    from io import BytesIO
    from PIL import Image
    b = BytesIO()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(b, format="PNG")
    return b.getvalue()


class SafeImageTests(unittest.TestCase):
    def test_only_real_images_pass(self):
        from app.services.safe_fetch import safe_get_image
        png = _png_bytes()
        ok = safe_get_image(PUBLIC_IP + "/a.png", transport=httpx.MockTransport(
            lambda req: httpx.Response(200, headers={"content-type": "image/png"}, content=png)))
        self.assertEqual(ok, (png, "png"))
        for ct, body in (("application/json", b'{"AccessKeyId":"x"}'), ("image/jpeg", b'{"AccessKeyId":"x"}'),
                         ("text/html", png)):
            got = safe_get_image(PUBLIC_IP + "/a", transport=httpx.MockTransport(
                lambda req, ct=ct, body=body: httpx.Response(200, headers={"content-type": ct}, content=body)))
            self.assertIsNone(got, ct)

    def test_image_downloaders_refuse_internal_addresses(self):
        """127.0.0.1 에 진짜 이미지를 주는 서버를 띄워도, 내려받기 함수들이 가져오지 않아야 한다."""
        import http.server
        import tempfile
        import threading
        from pathlib import Path
        from unittest import mock
        from app.api import ai_influencer
        from app.services import image_service, instagram
        png = _png_bytes()
        hits = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(png)

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        tmp = Path(tempfile.mkdtemp())
        try:
            with mock.patch.object(image_service, "CACHE_DIR", tmp), mock.patch.object(instagram, "UPLOAD_DIR", tmp):
                self.assertIsNone(ai_influencer._download_image(base + "/a.png"))
                self.assertIsNone(image_service.save_url_image(base + "/b.png", tmp))
                self.assertIsNone(image_service.cache_external_image(base + "/c.png"))
                self.assertEqual(instagram._download_and_save(base + "/d.png"), "")
        finally:
            srv.shutdown()
        self.assertEqual(hits, [], "내부 주소로 요청이 나가면 안 됨")



def _local_server(body: bytes, ctype: str):
    """127.0.0.1 에 잠깐 띄우는 시험 서버 — 요청이 오면 hits 에 경로를 남긴다."""
    import http.server
    import threading
    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}", hits


class DnsRebindingTests(unittest.TestCase):
    """검사 때는 공인 IP, 연결 때는 내부 IP 를 주는 DNS 를 흉내 — 검사한 IP 로만 연결해야 한다 (코덱스 재검토 #2)."""

    def test_connection_is_pinned_to_checked_ip(self):
        import socket
        from unittest import mock
        answers = iter(["93.184.216.34", "127.0.0.1", "127.0.0.1", "127.0.0.1"])

        def fake_getaddrinfo(host, *a, **k):
            if host == "rebind.invalid":
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (next(answers), 0))]
            raise socket.gaierror("no")

        seen = []

        def handler(req):
            seen.append((req.url.host, req.headers.get("host")))
            return httpx.Response(200, content=b"ok")

        with mock.patch.object(safe_fetch.socket, "getaddrinfo", fake_getaddrinfo):
            r = safe_get("http://rebind.invalid:8080/private", transport=httpx.MockTransport(handler))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(seen, [("93.184.216.34", "rebind.invalid:8080")],
                         "연결은 검사한 공인 IP 로, 도메인은 Host 헤더로만")


if __name__ == "__main__":
    unittest.main()
