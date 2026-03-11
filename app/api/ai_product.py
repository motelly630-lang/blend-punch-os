from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse
from app.ai.product_analyzer import analyze_product_url

router = APIRouter(prefix="/api/ai")


@router.post("/product-fill", response_class=HTMLResponse)
def ai_product_fill(url: str = Form(...)):
    try:
        data = analyze_product_url(url)
    except Exception as e:
        return HTMLResponse(
            f'<div class="text-red-600 text-sm p-3 bg-red-50 rounded-lg border border-red-200">'
            f"AI 분석 실패: {e}</div>"
        )

    key_benefits = data.get("key_benefits", [])
    benefits_text = "\n".join(key_benefits) if isinstance(key_benefits, list) else str(key_benefits)
    commission_pct = float(data.get("recommended_commission_rate", 0.15)) * 100
    demand = data.get("estimated_demand", "medium")

    return HTMLResponse(f"""
<div id="ai-fill-result" class="space-y-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
  <div class="flex items-center gap-2 text-blue-700 text-sm font-medium">
    <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
      <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
    </svg>
    AI 분석 완료 — 아래 버튼을 눌러 폼에 반영하세요
  </div>
  <button type="button" onclick="applyAiFill({repr(data)})"
    class="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700">
    폼에 적용하기
  </button>
</div>
<script>
function applyAiFill(data) {{
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
  // key_benefits (textarea)
  const benefitsEl = document.querySelector('[name="key_benefits_raw"]');
  if (benefitsEl && data.key_benefits) {{
    benefitsEl.value = Array.isArray(data.key_benefits) ? data.key_benefits.join('\\n') : data.key_benefits;
  }}
  // category select
  const catEl = document.querySelector('[name="category"]');
  if (catEl && data.category) {{
    for (let opt of catEl.options) {{
      if (opt.value === data.category || opt.text === data.category) {{
        opt.selected = true; break;
      }}
    }}
  }}
  // estimated_demand
  const demandEl = document.querySelector('[name="estimated_demand"]');
  if (demandEl && data.estimated_demand) {{
    for (let opt of demandEl.options) {{
      if (opt.value === data.estimated_demand) {{ opt.selected = true; break; }}
    }}
  }}
  // commission rate
  const commEl = document.querySelector('[name="recommended_commission_rate"]');
  if (commEl && data.recommended_commission_rate) {{
    commEl.value = (parseFloat(data.recommended_commission_rate) * 100).toFixed(0);
  }}
  document.getElementById('ai-fill-result').innerHTML =
    '<p class="text-green-700 text-sm font-medium">✓ 폼에 적용되었습니다. 내용을 검토 후 저장하세요.</p>';
}}
</script>
""")
