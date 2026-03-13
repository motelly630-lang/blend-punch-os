import asyncio
from fastapi import APIRouter, UploadFile, File, Depends
from fastapi.responses import HTMLResponse
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.ai.client import ClaudeClient
from pathlib import Path

router = APIRouter(prefix="/api/ai")

_PROMPTS = Path(__file__).parent.parent / "prompts"


@router.post("/product-image-fill", response_class=HTMLResponse)
async def ai_product_image_fill(
    image: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    claude = ClaudeClient()
    if not claude.available:
        return HTMLResponse(
            '<div id="ai-fill-result" class="p-4 bg-yellow-50 border border-yellow-200 rounded-lg text-sm text-yellow-800">'
            "AI 미사용 모드 — API 키를 설정하면 이미지 분석을 사용할 수 있습니다.</div>"
        )

    try:
        image_bytes = await image.read()
        media_type = image.content_type or "image/jpeg"

        prompt_file = _PROMPTS / "product_image_fill.md"
        prompt = prompt_file.read_text(encoding="utf-8")
        system = prompt.split("## User")[0].replace("## System\n", "").strip()
        user_text = prompt.split("## User Template\n", 1)[1].strip()

        data = await asyncio.to_thread(
            lambda: claude.complete_vision_json(system, user_text, image_bytes, media_type)
        )
    except Exception as e:
        return HTMLResponse(
            f'<div id="ai-fill-result" class="text-red-600 text-sm p-3 bg-red-50 rounded-lg border border-red-200">'
            f"이미지 분석 실패: {_esc(str(e))}</div>"
        )

    # Build a preview of extracted fields for display
    preview_lines = []
    if data.get("name"): preview_lines.append(f"<b>제품명:</b> {_esc(str(data['name']))}")
    if data.get("brand"): preview_lines.append(f"<b>브랜드:</b> {_esc(str(data['brand']))}")
    if data.get("category"): preview_lines.append(f"<b>카테고리:</b> {_esc(str(data['category']))}")
    if data.get("price"): preview_lines.append(f"<b>가격:</b> {_esc(str(data['price']))}")
    preview_html = " &nbsp;·&nbsp; ".join(preview_lines) if preview_lines else "분석 완료"

    import json as _json
    data_json = _esc(_json.dumps(data, ensure_ascii=False))

    return HTMLResponse(f"""
<div id="ai-fill-result" class="space-y-3 p-4 bg-blue-50 border border-blue-200 rounded-lg">
  <div class="flex items-start gap-2">
    <svg class="w-4 h-4 text-blue-600 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
      <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
    </svg>
    <div>
      <div class="text-sm font-semibold text-blue-800 mb-0.5">이미지 분석 완료</div>
      <div class="text-xs text-blue-600">{preview_html}</div>
    </div>
  </div>
  <button type="button" onclick="applyAiImageFill(JSON.parse(this.dataset.d))" data-d="{data_json}"
    class="w-full px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors">
    폼에 적용하기
  </button>
</div>
<script>
function applyAiImageFill(data) {{
  // Text fields — use name selector to match current form
  const setByName = (name, val) => {{
    if (!val && val !== 0) return;
    const el = document.querySelector('[name="' + name + '"]');
    if (el) el.value = val;
  }};
  setByName('name', data.name);
  setByName('brand', data.brand);
  setByName('description', data.description);
  setByName('unique_selling_point', data.unique_selling_point);
  setByName('content_angle', data.content_angle);

  // Price → fill both legacy price and consumer_price
  if (data.price) {{
    setByName('price', data.price);
    setByName('consumer_price', data.price);
  }}

  // Key benefits (newline-separated textarea)
  if (data.key_benefits) {{
    const val = Array.isArray(data.key_benefits) ? data.key_benefits.join('\\n') : data.key_benefits;
    setByName('key_benefits_raw', val);
  }}

  // Category select
  if (data.category) {{
    const sel = document.querySelector('select[name="category"]');
    if (sel) for (let o of sel.options) {{
      if (o.value === data.category || o.text === data.category) {{ o.selected = true; break; }}
    }}
  }}

  // Recommended commission rate (API returns 0-1, form expects 0-100)
  if (data.recommended_commission_rate) {{
    const v = parseFloat(data.recommended_commission_rate);
    setByName('recommended_commission_rate', v <= 1 ? Math.round(v * 100) : Math.round(v));
    setByName('seller_commission_rate', v <= 1 ? Math.round(v * 100) : Math.round(v));
  }}

  document.getElementById('ai-fill-result').innerHTML =
    '<div class="flex items-center gap-2 text-green-700 text-sm font-medium">' +
    '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/></svg>' +
    '폼에 적용되었습니다 — 내용 검토 후 저장하세요</div>';
}}
</script>
""")


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
