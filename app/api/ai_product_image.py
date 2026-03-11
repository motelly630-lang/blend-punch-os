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

        data = claude.complete_vision_json(system, user_text, image_bytes, media_type)
    except Exception as e:
        return HTMLResponse(
            f'<div id="ai-fill-result" class="text-red-600 text-sm p-3 bg-red-50 rounded-lg border border-red-200">'
            f"이미지 분석 실패: {_esc(str(e))}</div>"
        )

    return HTMLResponse(f"""
<div id="ai-fill-result" class="space-y-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
  <div class="flex items-center gap-2 text-blue-700 text-sm font-medium">
    <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
      <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
    </svg>
    이미지 분석 완료 — 아래 버튼을 눌러 폼에 반영하세요
  </div>
  <button type="button" onclick="applyAiImageFill({repr(data)})"
    class="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700">
    폼에 적용하기
  </button>
</div>
<script>
function applyAiImageFill(data) {{
  const fields = {{
    'name': data.name || '',
    'brand': data.brand || '',
    'price': data.price || '',
    'description': data.description || '',
    'target_audience': data.target_audience || '',
    'unique_selling_point': data.unique_selling_point || '',
    'content_angle': data.content_angle || '',
  }};
  for (const [key, value] of Object.entries(fields)) {{
    const el = document.querySelector('[name="' + key + '"]');
    if (el) el.value = value;
  }}
  const benefitsEl = document.querySelector('[name="key_benefits_raw"]');
  if (benefitsEl && data.key_benefits) {{
    benefitsEl.value = Array.isArray(data.key_benefits) ? data.key_benefits.join('\\n') : data.key_benefits;
  }}
  const catEl = document.querySelector('[name="category"]');
  if (catEl && data.category) {{
    for (let opt of catEl.options) {{
      if (opt.value === data.category || opt.text === data.category) {{
        opt.selected = true; break;
      }}
    }}
  }}
  const demandEl = document.querySelector('[name="estimated_demand"]');
  if (demandEl && data.estimated_demand) {{
    for (let opt of demandEl.options) {{
      if (opt.value === data.estimated_demand) {{ opt.selected = true; break; }}
    }}
  }}
  const commEl = document.querySelector('[name="recommended_commission_rate"]');
  if (commEl && data.recommended_commission_rate) {{
    commEl.value = (parseFloat(data.recommended_commission_rate) * 100).toFixed(0);
  }}
  document.getElementById('ai-fill-result').innerHTML =
    '<p class="text-green-700 text-sm font-medium">✓ 폼에 적용되었습니다. 내용을 검토 후 저장하세요.</p>';
}}
</script>
""")


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
