"""옵시디언 트렌드 받은편지함 업로더 (scripts/trend_inbox_upload.py) — 표 읽기·변환·상태 바꾸기."""
import importlib.util
import unittest
from datetime import date
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "trend_inbox_upload", Path(__file__).resolve().parents[1] / "scripts" / "trend_inbox_upload.py")
tu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tu)

NOTE = """---
type: trend-batch
status: 수집됨
collected_by: Genspark
collected_at: 2026-09-28
---

# 주간 트렌드 2026-09-28

## 트렌드
| 트렌드 | 분류 | 점수 | 출처 | 출처 주소 | 한 줄 요약 | 태그 |
|---|---|---|---|---|---|---|
| 무선 미니 가습기 공구 증가 | 가전 | 8.5 | instagram | https://example.com/a | 인플루언서 공구 3건 | 가습기, 겨울가전 |
| 보온 도시락 | 주방 | 높음 | blog | 확인 필요 | 가을 소풍 | |
|  |  |  |  |  |  |  |

<!-- | 트렌드 | 이 줄은 주석이라 무시 | -->
"""


class InboxTest(unittest.TestCase):
    def test_표를_읽고_빈_줄·주석은_건너뛴다(self):
        rows = tu.parse_rows(NOTE)
        self.assertEqual([r["트렌드"] for r in rows], ["무선 미니 가습기 공구 증가", "보온 도시락"])

    def test_OS_형식으로_바꾼다(self):
        rows = tu.parse_rows(NOTE)
        season = tu.season_of("2026-09-28", date.today())
        a, b = (tu.to_payload(r, season) for r in rows)
        self.assertEqual(season, "2026-W40")
        self.assertEqual((a["score"], a["source_url"], a["tags"]), (8.5, "https://example.com/a", ["가습기", "겨울가전"]))
        self.assertEqual((b["score"], b["source_url"], b["tags"]), (5.0, None, None))   # '높음'→기본 5, '확인 필요'→주소 없음

    def test_보낸_뒤_상태만_바꾸고_본문은_그대로(self):
        out = tu.set_front(NOTE, status="OS등록", uploaded_count="2")
        fm = tu.front_matter(out)
        self.assertEqual((fm["status"], fm["uploaded_count"], fm["collected_at"]), ("OS등록", "2", "2026-09-28"))
        self.assertEqual(out.split("---\n", 2)[2], NOTE.split("---\n", 2)[2])


class IngestTest(unittest.TestCase):
    def test_업로더_형식이_OS_입구를_통과하고_출근보고에_잡힌다(self):
        from tests import _env  # noqa: F401
        from tests._env import SessionLocal
        from fastapi.testclient import TestClient
        from app.config import settings
        from app.main import app
        from app.services import slack_standup as su
        saved, settings.claw_api_token = settings.claw_api_token, "test-only-token"
        try:
            c = TestClient(app)
            row = tu.parse_rows(NOTE)[0]
            x = tu.to_payload(row, "2026-W40")
            self.assertEqual(c.post("/trends/api/ingest", json=x).status_code, 401)            # 토큰 없으면 막힘
            r = c.post("/trends/api/ingest", json=x, headers={"Authorization": "Bearer test-only-token"})
            self.assertIn(r.status_code, (200, 201), r.text)
            db = SessionLocal()
            try:
                items, _ = su.recent_trends(db, 1, limit=50)
            finally:
                db.close()
            self.assertIn(x["name"], [i.title for i in items])
        finally:
            settings.claw_api_token = saved


if __name__ == "__main__":
    unittest.main()
