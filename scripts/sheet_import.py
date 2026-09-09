"""통합 운영 스프레드시트 → OS 임포트 (CLI).

    .venv/bin/python scripts/sheet_import.py                    # 미리보기 (전체)
    .venv/bin/python scripts/sheet_import.py --apply            # 실제 반영
    .venv/bin/python scripts/sheet_import.py brands products    # 대상 지정

웹 화면(/sheets)과 같은 로직을 쓴다 — 여기서 되면 화면에서도 된다.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.database import SessionLocal
from app.integrations import sheets_import

ACTION_LABEL = {"created": "신규", "updated": "수정", "unchanged": "변화없음", "failed": "오류"}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    dry_run = "--apply" not in sys.argv
    entities = args or None

    db = SessionLocal()
    try:
        result = sheets_import.run(db, entities=entities, dry_run=dry_run)
    finally:
        db.close()

    if not result.get("ok") and "reports" not in result:
        print(f"!! {result.get('error')}")
        return 1

    print("=" * 72)
    print("미리보기 (DB 변경 없음)" if dry_run else "실제 반영")
    print("=" * 72)

    for rep in result.get("reports", []):
        head = (f"[{rep['label']}] {rep['tab']} — "
                f"신규 {rep['created']} · 수정 {rep['updated']} · "
                f"변화없음 {rep['unchanged']} · 오류 {rep['failed']} · "
                f"빈행 {rep['skipped']}")
        print("\n" + head)
        if rep.get("error"):
            print(f"  !! {rep['error']}")
        for r in rep["rows"]:
            if r["action"] == "unchanged":
                continue
            mark = ACTION_LABEL.get(r["action"], r["action"])
            print(f"  {mark:5} {r['code']:16} {r['name']}")
            if r.get("error"):
                print(f"        !! {r['error']}")
            for c in r.get("changes", [])[:6]:
                print(f"        · {c}")
            if r.get("missing"):
                print(f"        (미입력: {', '.join(r['missing'])})")
        for n in rep.get("notes", []):
            print(f"  * {n}")
        if rep.get("unmapped"):
            print(f"  시트에만 있는 필드: {', '.join(rep['unmapped'])}")

    t = result.get("totals", {})
    print("\n" + "-" * 72)
    print(f"합계 — 신규 {t.get('created', 0)} · 수정 {t.get('updated', 0)} · "
          f"변화없음 {t.get('unchanged', 0)} · 오류 {t.get('failed', 0)} · "
          f"빈행 {t.get('skipped', 0)}")
    if dry_run:
        print("반영하려면: --apply")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
