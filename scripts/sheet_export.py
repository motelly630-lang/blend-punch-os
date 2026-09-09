"""OS → 통합 운영 스프레드시트 내려받기 (CLI).

    .venv/bin/python scripts/sheet_export.py                   # 미리보기 (시트 무변경)
    .venv/bin/python scripts/sheet_export.py --apply           # 실제 기록
    .venv/bin/python scripts/sheet_export.py products sellers  # 대상 지정

⚠️ 운영 데이터는 EC2에 있다 — 실제 내려받기는 EC2에서 실행할 것.
   (로컬 DB로 --apply 하면 로컬 데이터가 시트에 섞인다)
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.database import SessionLocal
from app.integrations import sheets_export


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    dry_run = "--apply" not in sys.argv

    db = SessionLocal()
    try:
        result = sheets_export.run(db, entities=args or None, dry_run=dry_run)
    finally:
        db.close()

    if "reports" not in result:
        print(f"!! {result.get('error')}")
        return 1

    print("=" * 72)
    print("미리보기 (시트 변경 없음)" if dry_run else "시트에 기록")
    print("=" * 72)

    for rep in result["reports"]:
        print(f"\n[{rep['label']}] {rep['tab']} — "
              f"추가 {rep['appended']} · 수정 {rep['updated']} · "
              f"변화없음 {rep['unchanged']} · 코드발급 {rep['coded']}")
        if rep.get("error"):
            print(f"  !! {rep['error']}")
        for n in rep.get("notes", []):
            print(f"  * {n}")
        for f in rep.get("fixed", [])[:10]:
            print(f"  교정 {f}")
        if len(rep.get("fixed", [])) > 10:
            print(f"  교정 … 그 외 {len(rep['fixed']) - 10}건")
        if rep.get("write_ranges"):
            print(f"  쓰기 범위: {', '.join(rep['write_ranges'][:6])}"
                  + (" …" if len(rep["write_ranges"]) > 6 else ""))
        if rep.get("skipped_fields"):
            print(f"  OS에 대응 없어 안 쓰는 열: {', '.join(rep['skipped_fields'])}")

    t = result["totals"]
    print("\n" + "-" * 72)
    print(f"합계 — 추가 {t['appended']} · 수정 {t['updated']} · "
          f"변화없음 {t['unchanged']} · 코드발급 {t['coded']}")
    if dry_run:
        print("기록하려면: --apply")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
