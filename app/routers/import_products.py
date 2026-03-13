"""
Excel / CSV product import router.
Routes:
  POST /products/import/upload   — parse file, return preview partial (htmx)
  POST /products/import/confirm  — save confirmed rows (with optional AI enrichment)
"""
import io
import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Product
from app.auth.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/products/import")
templates = Jinja2Templates(directory="app/templates")

# ── Column name → Product field mapping ───────────────────────────────────────
COLUMN_MAP: dict[str, str] = {
    # Korean
    "제품명": "name", "상품명": "name",
    "브랜드": "brand",
    "카테고리": "category",
    "제품설명": "description", "설명": "description", "상품설명": "description",
    "소비자가": "consumer_price", "소비자가격": "consumer_price", "정가": "consumer_price",
    "최저가": "lowest_price",
    "공급가": "supplier_price", "원가": "supplier_price", "매입가": "supplier_price",
    "공구가": "groupbuy_price", "공동구매가": "groupbuy_price", "판매가": "groupbuy_price",
    "할인율": "discount_rate",
    "셀러커미션": "seller_commission_rate", "커미션율": "seller_commission_rate",
    "벤더마진": "vendor_commission_rate",
    "배송비": "shipping_cost",
    "상품링크": "product_link", "링크": "product_link", "제품링크": "product_link",
    # English
    "product_name": "name", "name": "name",
    "brand": "brand",
    "category": "category",
    "description": "description",
    "consumer_price": "consumer_price",
    "lowest_price": "lowest_price",
    "supplier_price": "supplier_price",
    "groupbuy_price": "groupbuy_price",
    "discount_rate": "discount_rate",
    "seller_commission_rate": "seller_commission_rate",
    "vendor_commission_rate": "vendor_commission_rate",
    "shipping_cost": "shipping_cost",
    "product_link": "product_link",
}

NUMERIC_FIELDS = {
    "consumer_price", "lowest_price", "supplier_price", "groupbuy_price",
    "shipping_cost",
}
PERCENT_FIELDS = {
    "discount_rate", "seller_commission_rate", "vendor_commission_rate",
}
ALL_PRODUCT_FIELDS = [
    ("name", "제품명"),
    ("brand", "브랜드"),
    ("category", "카테고리"),
    ("description", "설명"),
    ("consumer_price", "소비자가"),
    ("lowest_price", "최저가"),
    ("supplier_price", "공급가"),
    ("groupbuy_price", "공구가"),
    ("discount_rate", "할인율 (%)"),
    ("seller_commission_rate", "셀러 커미션율 (%)"),
    ("vendor_commission_rate", "벤더 마진율 (%)"),
    ("shipping_cost", "배송비"),
    ("product_link", "상품 링크"),
    ("__skip__", "— 가져오지 않음 —"),
]


def _parse_file(content: bytes, filename: str) -> tuple[list[str], list[list]]:
    """Return (headers, rows) from xlsx or csv bytes."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("xlsx", "xls"):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows = [[str(cell.value or "").strip() for cell in row] for row in ws.iter_rows()]
        wb.close()
    else:
        import csv
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text))
        rows = [[cell.strip() for cell in r] for r in reader]

    if not rows:
        return [], []
    headers = rows[0]
    data = [r for r in rows[1:] if any(c for c in r)]
    return headers, data


def _auto_map(headers: list[str]) -> dict[int, str]:
    """Return {col_index: field_name}. Unknown cols map to '__skip__'."""
    mapping = {}
    for i, h in enumerate(headers):
        key = h.strip().lower().replace(" ", "").replace("_", "")
        matched = None
        for alias, field in COLUMN_MAP.items():
            if alias.lower().replace(" ", "").replace("_", "") == key:
                matched = field
                break
        mapping[i] = matched or "__skip__"
    return mapping


def _convert_value(field: str, raw: str):
    raw = raw.strip()
    if not raw or raw.lower() in ("none", "null", "-", "n/a"):
        return None
    if field in NUMERIC_FIELDS:
        try:
            return float(raw.replace(",", ""))
        except ValueError:
            return None
    if field in PERCENT_FIELDS:
        try:
            v = float(raw.replace(",", "").replace("%", ""))
            return v / 100.0 if v > 1 else v  # accept both 30 and 0.30
        except ValueError:
            return None
    return raw or None


def _ai_enrich(name: str, brand: str, category: str, description: str) -> dict | None:
    """Call Claude to extract structured fields from product description."""
    try:
        from pathlib import Path
        from app.ai.client import ClaudeClient

        prompt_template = Path("app/prompts/product_import_fill.md").read_text()
        prompt = (
            prompt_template
            .replace("{{name}}", name)
            .replace("{{brand}}", brand)
            .replace("{{category}}", category)
            .replace("{{description}}", description[:2000])
        )
        # Split on ## User Template
        parts = prompt.split("## User Template")
        system = parts[0].replace("## System\n", "").strip()
        user = parts[1].strip() if len(parts) > 1 else description

        client = ClaudeClient()
        result = client.complete_json(system=system, user=user)
        return result
    except Exception:
        return None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/upload", response_class=HTMLResponse)
async def import_upload(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    try:
        headers, rows = _parse_file(content, file.filename or "file.xlsx")
    except Exception as e:
        return HTMLResponse(f'<p class="text-red-500 text-sm">파일 파싱 오류: {e}</p>')

    if not headers:
        return HTMLResponse('<p class="text-red-500 text-sm">파일이 비어 있습니다.</p>')

    mapping = _auto_map(headers)
    preview_rows = rows[:10]

    # Encode data for hidden field
    payload = json.dumps({
        "headers": headers,
        "rows": rows,
    })

    # Check if any column mapped to description (AI enrichment possible)
    has_description_col = any(v == "description" for v in mapping.values())

    return templates.TemplateResponse(
        "products/import_preview.html",
        {
            "request": request,
            "headers": headers,
            "preview_rows": preview_rows,
            "total_rows": len(rows),
            "mapping": mapping,
            "all_fields": ALL_PRODUCT_FIELDS,
            "payload": payload,
            "filename": file.filename,
            "has_description_col": has_description_col,
        },
    )


@router.post("/confirm")
async def import_confirm(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    payload_json: str = Form(...),
    mapping_json: str = Form(...),
    use_ai: str = Form(""),
):
    try:
        payload = json.loads(payload_json)
        mapping = json.loads(mapping_json)  # {str(col_idx): field_name}
    except Exception:
        return RedirectResponse("/products/import?err=데이터+오류", status_code=302)

    headers = payload.get("headers", [])
    rows = payload.get("rows", [])
    run_ai = use_ai == "1"

    saved = 0
    ai_enriched = 0
    skipped = 0
    errors: list[str] = []

    for row_idx, row in enumerate(rows):
        row_data: dict = {}
        for i, header in enumerate(headers):
            field = mapping.get(str(i), "__skip__")
            if field == "__skip__" or not field:
                continue
            val = row[i] if i < len(row) else ""
            converted = _convert_value(field, val)
            if converted is not None:
                row_data[field] = converted

        if not row_data.get("name"):
            skipped += 1
            continue  # skip rows without a product name

        # Optional AI enrichment from description
        ai_data = None
        if run_ai and row_data.get("description"):
            ai_data = _ai_enrich(
                name=row_data.get("name", ""),
                brand=row_data.get("brand", ""),
                category=row_data.get("category", ""),
                description=row_data["description"],
            )
            if ai_data:
                ai_enriched += 1

        product = Product(
            name=row_data.get("name", ""),
            brand=row_data.get("brand", ""),
            category=row_data.get("category", "기타"),
            description=row_data.get("description"),
            consumer_price=row_data.get("consumer_price", 0.0),
            lowest_price=row_data.get("lowest_price", 0.0),
            supplier_price=row_data.get("supplier_price", 0.0),
            groupbuy_price=row_data.get("groupbuy_price", 0.0),
            discount_rate=row_data.get("discount_rate", 0.0),
            seller_commission_rate=row_data.get("seller_commission_rate", 0.0),
            vendor_commission_rate=row_data.get("vendor_commission_rate", 0.0),
            shipping_cost=row_data.get("shipping_cost"),
            product_link=row_data.get("product_link"),
            status="draft",
            visibility_status="active",
            # AI-enriched fields
            key_benefits=ai_data.get("key_benefits") if ai_data else None,
            unique_selling_point=ai_data.get("unique_selling_point") if ai_data else None,
            target_audience=ai_data.get("target_audience") if ai_data else None,
            content_angle=ai_data.get("content_angle") if ai_data else None,
            ai_analysis_raw=json.dumps(ai_data, ensure_ascii=False) if ai_data else None,
        )
        db.add(product)
        saved += 1

        # Commit in batches of 50
        if saved % 50 == 0:
            db.flush()

    db.commit()

    msg_parts = [f"{saved}개+제품+등록"]
    if run_ai and ai_enriched:
        msg_parts.append(f"AI+분석+{ai_enriched}개")
    if skipped:
        msg_parts.append(f"{skipped}개+건너뜀")
    msg = "+·+".join(msg_parts)
    return RedirectResponse(f"/products?msg={msg}", status_code=302)
