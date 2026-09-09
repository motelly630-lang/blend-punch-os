"""통합 운영 스프레드시트 연동 화면.

GET  /settings/sheets                 — 연동 상태 + 대상 선택 화면
POST /settings/sheets/preview         — 시트 → OS 미리보기 (DB 변경 없음)
POST /settings/sheets/apply           — 시트 → OS 반영
POST /settings/sheets/export-preview  — OS → 시트 미리보기 (시트 변경 없음)
POST /settings/sheets/export-apply    — OS → 시트 기록

양방향 모두 '미리보기 → 확인 → 반영' 2단계로 고정한다. 오타가 곧바로 운영
DB(또는 시트)에 반영되는 것을 막기 위함 — 마스터 데이터라 되돌리기가 어렵다.
"""
import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth.dependencies import require_super_admin
from app.auth.tenant import get_company_id
from app.config import settings
from app.database import get_db
from app.integrations import sheets_bridge, sheets_export, sheets_import
from app.services import sheet_autosync
from app.models.user import User

log = logging.getLogger(__name__)
router = APIRouter(prefix="/settings/sheets")
templates = Jinja2Templates(directory="app/templates")

# 화면에 보여줄 대상 목록. 일정·정산은 OS가 진실이라 내려받기만 된다.
TARGETS = [
    {"key": e, "label": sheets_bridge.ENTITIES[e]["label"],
     "tab": sheets_bridge.ENTITIES[e]["tab"],
     "import_ok": e in sheets_import.IMPORT_ORDER}
    for e in sheets_export.EXPORT_ORDER
]


def _page(request: Request, user: User, result: dict | None = None,
          entities: list[str] | None = None, export: dict | None = None,
          db: Session | None = None):
    logs = []
    if db is not None:
        try:
            logs = sheet_autosync.recent_logs(db, get_company_id(user))
        except Exception:
            log.warning("동기화 이력 조회 실패", exc_info=True)
    return templates.TemplateResponse("sheets/index.html", {
        "request": request,
        "active_page": "sheets",
        "current_user": user,
        "configured": sheets_bridge.is_configured(),
        "sheet_id": settings.integrated_sheet_id or "",
        "targets": TARGETS,
        "selected": entities or [t["key"] for t in TARGETS],
        "result": result,
        "export": export,
        "logs": logs,
        "autosync": settings.sheet_autosync,
        "autosync_minutes": settings.sheet_autosync_minutes,
    })


@router.get("")
def sheets_index(request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_super_admin)):
    return _page(request, user, db=db)


def _run(request: Request, user: User, db: Session,
         entities: list[str], dry_run: bool):
    import time
    picked = [e for e in entities if e in sheets_import._IMPORTERS] or None
    cid = get_company_id(user)
    started = time.monotonic()
    result = sheets_import.run(db, entities=picked, company_id=cid, dry_run=dry_run)
    if not dry_run:
        sheet_autosync._record(db, "import", "manual", result, started, cid)
    return _page(request, user, result=result, entities=picked, db=db)


@router.post("/preview")
def sheets_preview(
    request: Request,
    entities: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    return _run(request, user, db, entities, dry_run=True)


@router.post("/apply")
def sheets_apply(
    request: Request,
    entities: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    log.info("sheet import apply by %s: %s", user.username, entities)
    return _run(request, user, db, entities, dry_run=False)


# ── OS → 시트 (내려받기) ──────────────────────────────────────────────────────

def _run_export(request: Request, user: User, db: Session,
                entities: list[str], dry_run: bool):
    import time
    picked = [e for e in entities if e in sheets_export.ENTITY_MODELS] or None
    cid = get_company_id(user)
    started = time.monotonic()
    result = sheets_export.run(db, entities=picked, company_id=cid, dry_run=dry_run)
    if not dry_run:
        sheet_autosync._record(db, "export", "manual", result, started, cid)
    return _page(request, user, export=result, entities=picked, db=db)


@router.post("/export-preview")
def sheets_export_preview(
    request: Request,
    entities: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    return _run_export(request, user, db, entities, dry_run=True)


@router.post("/export-apply")
def sheets_export_apply(
    request: Request,
    entities: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    log.info("sheet export apply by %s: %s", user.username, entities)
    return _run_export(request, user, db, entities, dry_run=False)
