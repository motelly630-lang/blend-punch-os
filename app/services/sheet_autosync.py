"""통합시트 자동 동기화 (스케줄러가 주기적으로 호출).

한 번 실행 = 시트→OS 반영 → OS→시트 기록. **순서대로 한 번에** 처리한다.
두 방향을 따로 돌리면 서로 밟을 수 있고 Sheets API 호출도 두 배가 된다.

안전장치
  1) 시트→OS 는 먼저 미리보기로 규모를 재고, 변경이 임계치를 넘으면 **중단**한다.
     시트에서 실수로 열을 밀거나 정렬을 흐트리면 수백 행이 한꺼번에 바뀔 수 있고,
     자동 실행은 사람이 안 보고 있기 때문이다. 그럴 땐 버튼으로 직접 확인해야 한다.
  2) OS→시트 는 막지 않는다. 시트는 되돌리기 쉽고 운영 DB를 건드리지 않는다.
  3) 모든 실행을 `sheet_sync_logs` 에 남긴다 — 조용한 실패를 만들지 않기 위함.
"""
from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session

from app.integrations import sheets_export, sheets_import
from app.models.sheet_sync_log import SheetSyncLog

log = logging.getLogger(__name__)

# 자동 실행에서 한 번에 허용할 '시트→OS' 변경 건수. 넘으면 사람이 확인해야 한다.
MAX_AUTO_IMPORT_CHANGES = 200


def _record(db: Session, direction: str, trigger: str, result: dict,
            started: float, company_id: int = 1) -> SheetSyncLog:
    """실행 결과를 로그 행으로 남긴다 (커밋까지)."""
    totals = result.get("totals") or {}
    row = SheetSyncLog(
        company_id=company_id,
        direction=direction,
        trigger=trigger,
        ok=bool(result.get("ok")),
        created=totals.get("created", 0) or totals.get("appended", 0) or 0,
        updated=totals.get("updated", 0) or 0,
        unchanged=totals.get("unchanged", 0) or 0,
        failed=totals.get("failed", 0) or 0,
        skipped=totals.get("skipped", 0) or 0,
        error=(result.get("error") or "")[:2000] or None,
        detail=[{
            "entity": r.get("entity"), "label": r.get("label"),
            "created": r.get("created", r.get("appended", 0)),
            "updated": r.get("updated", 0),
            "failed": r.get("failed", 0),
            "error": r.get("error"),
            "notes": (r.get("notes") or [])[:5],
        } for r in (result.get("reports") or [])] or None,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    db.add(row)
    db.commit()
    return row


def _import_step(db: Session, company_id: int, trigger: str) -> dict:
    """시트→OS. 미리보기로 규모를 확인한 뒤 반영."""
    started = time.monotonic()
    preview = sheets_import.run(db, company_id=company_id, dry_run=True)
    if not preview.get("ok"):
        _record(db, "import", trigger, preview, started, company_id)
        return preview

    t = preview.get("totals") or {}
    changes = (t.get("created", 0) or 0) + (t.get("updated", 0) or 0)
    if changes > MAX_AUTO_IMPORT_CHANGES:
        blocked = {
            "ok": False,
            "error": (f"변경 {changes}건이 자동 반영 한도({MAX_AUTO_IMPORT_CHANGES}건)를 "
                      f"넘어 중단했습니다. 시트를 확인하고 '미리보기 → 이대로 반영'으로 "
                      f"직접 진행하세요."),
            "totals": t,
            "reports": preview.get("reports"),
        }
        log.warning("sheet autosync import blocked: %s changes", changes)
        _record(db, "import", trigger, blocked, started, company_id)
        return blocked

    if changes == 0:
        # 바뀐 게 없으면 다시 읽지 않는다 (Sheets 호출 절약)
        _record(db, "import", trigger, preview, started, company_id)
        return preview

    result = sheets_import.run(db, company_id=company_id, dry_run=False)
    _record(db, "import", trigger, result, started, company_id)
    return result


def _export_step(db: Session, company_id: int, trigger: str) -> dict:
    started = time.monotonic()
    result = sheets_export.run(db, company_id=company_id, dry_run=False)
    _record(db, "export", trigger, result, started, company_id)
    return result


def run_once(db: Session, company_id: int = 1, trigger: str = "auto") -> dict:
    """시트→OS → OS→시트 순으로 한 번 동기화. 로그 2행이 남는다."""
    imported = _import_step(db, company_id, trigger)
    # 시트→OS 가 막혔거나 깨졌으면 내려받기도 하지 않는다.
    # 어긋난 상태 위에 덮어쓰면 원인을 못 찾게 된다.
    if not imported.get("ok"):
        return {"ok": False, "import": imported, "export": None}
    exported = _export_step(db, company_id, trigger)
    return {"ok": bool(exported.get("ok")), "import": imported, "export": exported}


def recent_logs(db: Session, company_id: int = 1, limit: int = 12) -> list[SheetSyncLog]:
    return (db.query(SheetSyncLog)
              .filter(SheetSyncLog.company_id == company_id)
              .order_by(SheetSyncLog.created_at.desc())
              .limit(limit).all())
