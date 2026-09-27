"""옵시디언 트렌드 받은편지함 → OS 트렌드 (맥북에서 실행, 대표님 2026-09-27 ② 결정).

젠스파크 GenCode 가 `05_Marketing/Trend_Inbox/*.md` (양식 Template_Trend_Batch) 에 주간 트렌드 표를 쓰면,
이 스크립트가 status: 수집됨 인 노트의 표를 읽어 OS `POST /trends/api/ingest` 로 보낸다.
토큰(CLAW_API_TOKEN)은 맥북 .env 에서 앱 설정으로만 읽고, 화면·노트에 적지 않는다 — 젠스파크에 토큰을 주지 않기 위한 길.

- 기본은 미리보기(보내지 않음). `--send` 일 때만 보낸다.
- 다 보내면 노트 맨 위 status 를 'OS등록' 으로, uploaded_at·uploaded_count 를 적는다 (다음 실행 때 다시 안 보냄).
- 하나라도 실패하면 status 를 그대로 둬서 다음에 다시 시도한다 (같은 주 같은 이름은 OS 가 덮어써서 중복 안 됨).
- season 은 수집 주(예: 2026-W40) — OS 는 이름+season 이 같으면 덮어쓰므로, 주마다 새로 기록돼 '최근 30일 트렌드' 에 잡힌다.

사용:  uv run python scripts/trend_inbox_upload.py            # 미리보기
       uv run python scripts/trend_inbox_upload.py --send     # 운영 OS 로 보내기
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

INBOX = Path.home() / "Documents" / "Obsidian Vault" / "05_Marketing" / "Trend_Inbox"
COLUMNS = ["트렌드", "분류", "점수", "출처", "출처 주소", "한 줄 요약", "태그"]
_FM = re.compile(r"^---\n(.*?)\n---\n", re.S)


def front_matter(text: str) -> dict:
    m = _FM.match(text)
    out = {}
    for line in (m.group(1).splitlines() if m else []):
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def set_front(text: str, **kv) -> str:
    """맨 위 설정 칸을 바꾸거나 추가한다 (본문은 그대로)."""
    m = _FM.match(text)
    if not m:
        return text
    lines = m.group(1).splitlines()
    for k, v in kv.items():
        for i, line in enumerate(lines):
            if line.split(":", 1)[0].strip() == k:
                lines[i] = f"{k}: {v}"
                break
        else:
            lines.append(f"{k}: {v}")
    return "---\n" + "\n".join(lines) + "\n---\n" + text[m.end():]


def parse_rows(text: str) -> list[dict]:
    """'| 트렌드 | 분류 | ...' 표를 찾아 줄마다 dict. 빈 줄·구분선·트렌드 칸이 빈 줄은 건너뛴다."""
    body = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    rows, header = [], None
    for line in body.splitlines():
        s = line.strip()
        if not (s.startswith("|") and s.endswith("|")):
            header = None if header and not s else header
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if header is None:
            if cells and cells[0] == "트렌드":
                header = cells
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        row = dict(zip(header, cells))
        if row.get("트렌드"):
            rows.append(row)
    return rows


def to_payload(row: dict, season: str) -> dict | None:
    """표 한 줄 → OS ingest 형식. 점수가 숫자가 아니면 5, 범위는 0~10 으로 자른다."""
    name = row.get("트렌드", "").strip()
    if not name:
        return None
    try:
        score = float(re.sub(r"[^0-9.]", "", row.get("점수", "")) or 5)
    except ValueError:
        score = 5.0
    url = row.get("출처 주소", "").strip()
    tags = [t.strip() for t in re.split(r"[,，]", row.get("태그", "")) if t.strip()]
    return {"name": name[:300], "category": (row.get("분류") or "기타").strip()[:50],
            "score": max(0.0, min(10.0, score)), "source": (row.get("출처") or "").strip()[:50] or None,
            "source_url": url if url.startswith("http") else None,
            "summary": (row.get("한 줄 요약") or "").strip() or None, "tags": tags or None, "season": season}


def season_of(collected_at: str, fallback: date) -> str:
    try:
        d = date.fromisoformat(collected_at[:10])
    except ValueError:
        d = fallback
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def main() -> int:
    ap = argparse.ArgumentParser(description="옵시디언 트렌드 받은편지함 → OS")
    ap.add_argument("--send", action="store_true", help="운영 OS 로 보내기 (없으면 미리보기)")
    ap.add_argument("--inbox", default=str(INBOX))
    a = ap.parse_args()
    inbox = Path(a.inbox)
    if not inbox.is_dir():
        print(f"받은편지함 폴더가 없어요: {inbox}")
        return 1
    notes = sorted(p for p in inbox.glob("*.md") if front_matter(p.read_text(encoding="utf-8")).get("status") == "수집됨")
    if not notes:
        print("보낼 노트가 없어요 (status: 수집됨 인 노트 없음)")
        return 0

    token = base = ""
    if a.send:
        from app.config import settings
        token, base = settings.claw_api_token, (settings.app_base_url or "").rstrip("/")
        if not token:
            print("맥북 .env 에 CLAW_API_TOKEN 이 없어요 — 서버와 같은 값을 넣어야 보낼 수 있어요 (값은 화면에 적지 않기)")
            return 1
    import httpx
    total_fail = 0
    for p in notes:
        text = p.read_text(encoding="utf-8")
        fm = front_matter(text)
        season = season_of(fm.get("collected_at", ""), date.today())
        payloads = [x for x in (to_payload(r, season) for r in parse_rows(text)) if x]
        print(f"\n## {p.name} — {len(payloads)}개 · {season}")
        for x in payloads:
            print(f"  · [{x['category']}] {x['name']} ({x['score']:g}점, {x['source'] or '출처 없음'})")
        if not a.send or not payloads:
            continue
        ok = fail = 0
        with httpx.Client(timeout=20) as c:
            for x in payloads:
                try:
                    r = c.post(f"{base}/trends/api/ingest", json=x, headers={"Authorization": f"Bearer {token}"})
                    if r.status_code in (200, 201):
                        ok += 1
                    else:
                        fail += 1
                        print(f"  ✗ {x['name']}: HTTP {r.status_code} {r.text[:120]}")
                except httpx.HTTPError as e:
                    fail += 1
                    print(f"  ✗ {x['name']}: {type(e).__name__}")
        total_fail += fail
        if fail == 0:
            p.write_text(set_front(text, status="OS등록", uploaded_at=date.today().isoformat(),
                                   uploaded_count=str(ok)), encoding="utf-8")
            print(f"  → OS 에 {ok}개 보냄, 노트 상태를 'OS등록' 으로 바꿈")
        else:
            print(f"  → {ok}개 성공 · {fail}개 실패 — 노트 상태는 그대로 (다음에 다시 시도)")
    if not a.send:
        print("\n(미리보기예요. 보내려면 --send)")
    return 1 if total_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
