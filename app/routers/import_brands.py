"""
Excel / CSV brand import router.
Routes:
  POST /brands/import/upload   — parse file, return preview partial
  POST /brands/import/confirm  — save confirmed rows
"""
import io
import uuid
import logging

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.brand import Brand
from app.auth.dependencies import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/brands/import")
templates = Jinja2Templates(directory="app/templates")

COLUMN_MAP = {
    "브랜드명": "name", "브랜드": "name", "상호명": "name", "name": "name",
    "설명": "description", "브랜드설명": "description", "소개": "description",
    "description": "description",
}


def _parse_file(file_bytes: bytes, filename: str) -> list[dict]:
    """Excel 또는 CSV 파싱 → [{name, description}, ...] 반환."""
    fname = filename.lower()
    if fname.endswith(".csv"):
        import csv
        text = file_bytes.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        raw_rows = list(reader)
    else:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(h).strip() if h else "" for h in rows[0]]
        raw_rows = [dict(zip(headers, row)) for row in rows[1:]]

    results = []
    for raw in raw_rows:
        row: dict = {}
        for col_raw, val in raw.items():
            col = str(col_raw).strip() if col_raw else ""
            field = COLUMN_MAP.get(col)
            if field and val is not None:
                row[field] = str(val).strip()
        name = row.get("name", "").strip()
        if not name:
            continue
        results.append({
            "name": name,
            "description": row.get("description", ""),
        })
    return results


@router.post("/upload", response_class=HTMLResponse)
async def import_upload(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        content = await file.read()
        rows = _parse_file(content, file.filename or "")
    except Exception as e:
        return HTMLResponse(f'<p class="text-red-500 text-sm p-4">파일 파싱 오류: {e}</p>')

    if not rows:
        return HTMLResponse('<p class="text-gray-400 text-sm p-4">파싱된 데이터가 없습니다. 헤더를 확인하세요.</p>')

    # 이미 존재하는 브랜드 이름
    existing_names = {b.name for b in db.query(Brand.name).all()}

    return templates.TemplateResponse(
        "brands/import_preview.html",
        {"request": request, "rows": rows, "existing_names": existing_names,
         "total": len(rows)},
    )


@router.post("/confirm")
async def import_confirm(
    rows_json: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import json
    try:
        rows = json.loads(rows_json)
    except Exception:
        return RedirectResponse("/brands?msg=데이터+오류", status_code=302)

    existing_names = {b.name for b in db.query(Brand.name).all()}
    added = 0
    skipped = 0
    for row in rows:
        name = (row.get("name") or "").strip()
        if not name or name in existing_names:
            skipped += 1
            continue
        db.add(Brand(
            id=str(uuid.uuid4()),
            name=name,
            description=row.get("description") or None,
        ))
        existing_names.add(name)
        added += 1

    db.commit()
    return RedirectResponse(f"/brands?msg={added}개+브랜드+등록+완료+({skipped}개+중복+건너뜀)", status_code=302)
