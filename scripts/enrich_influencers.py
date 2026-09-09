"""인플루언서 인스타 프로필 수집 (CLI).

    .venv/bin/python scripts/enrich_influencers.py --dry-run        # 누구를 긁을지만
    .venv/bin/python scripts/enrich_influencers.py --limit 3        # 3명만 실제로 (첫 시험)
    .venv/bin/python scripts/enrich_influencers.py                 # 기본 50명

⚠️ 처음에는 반드시 --limit 3 정도로 시험할 것. 계정이 정상 동작하는지 확인 후 늘린다.
   .env 에 INSTAGRAM_USERNAME / INSTAGRAM_PASSWORD (전용 서브계정) 필요.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.database import SessionLocal
from app.services.influencer_enrich import DEFAULT_LIMIT, enrich_batch, pending_count


def _arg(name: str, default: int) -> int:
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return int(sys.argv[i + 1])
    return default


def main() -> int:
    dry = "--dry-run" in sys.argv
    limit = _arg("--limit", DEFAULT_LIMIT)

    db = SessionLocal()
    try:
        print(f"수집 대기: {pending_count(db):,}명")
        rep = enrich_batch(db, limit=limit, dry_run=dry)
    finally:
        db.close()

    print("=" * 60)
    print("미리보기 (인스타 접속 안 함)" if dry else "수집 실행")
    print("=" * 60)
    for r in rep["rows"]:
        mark = {"수집": "OK  ", "실패": "FAIL", "예정": "→   "}.get(r["action"], r["action"])
        print(f"  {mark} @{r['handle']:24} {r['name'][:20]:22} {r.get('detail', '')}")
    print("-" * 60)
    print(f"대상 {rep['picked']} · 수집 {rep['updated']} · 실패 {rep['failed']} "
          f"· 남은 대기 {rep['remaining']:,}")
    if rep.get("error"):
        print(f"!! {rep['error']}")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
