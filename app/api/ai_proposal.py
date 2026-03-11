from fastapi import APIRouter, Form, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Product
from app.ai.proposal_generator import generate_proposal
from app.auth.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/ai")


@router.post("/proposal-draft", response_class=HTMLResponse)
def ai_proposal_draft(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    product_id: str = Form(""),
    custom_instructions: str = Form(""),
):
    product = db.query(Product).filter(Product.id == product_id).first() if product_id else None

    if not product:
        return HTMLResponse(
            '<div id="ai-draft-area" class="text-red-600 text-sm p-3 bg-red-50 rounded-lg border border-red-200">'
            "제품을 먼저 선택해 주세요.</div>"
        )

    public_url = f"/public/products/{product.id}" if product.status == "active" else (product.source_url or "")
    benefits = product.key_benefits or []

    result = generate_proposal(
        proposal_type="vendor",
        product_name=product.name,
        product_brand=product.brand,
        product_category=product.category,
        product_price=product.price or 0,
        product_usp=product.unique_selling_point or "",
        commission_rate=product.recommended_commission_rate or 0.15,
        custom_instructions=custom_instructions,
        product_content_angle=product.content_angle or "",
        product_key_benefits=benefits,
        public_product_url=public_url,
        internal_notes=getattr(product, "internal_notes", "") or "",
    )

    title = result.get("title", "")
    body = result.get("body", "")
    char_count = len(body)

    return HTMLResponse(f"""
<div id="ai-draft-area" class="bg-white rounded-xl border border-gray-100 shadow-sm p-6 space-y-4">
  <div class="flex items-center justify-between">
    <span class="text-sm font-semibold text-blue-700 flex items-center gap-1.5">
      <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
      </svg>
      AI 제안서 초안 생성 완료
    </span>
    <div class="flex items-center gap-3">
      <span class="text-xs text-gray-400">{char_count}자</span>
      <button type="button" onclick="copyDraft()"
        class="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1 border border-gray-200 px-2.5 py-1.5 rounded-lg transition-colors">
        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/>
        </svg>
        복사
      </button>
    </div>
  </div>
  <input type="hidden" name="ai_generated" value="true">
  <input type="hidden" name="proposal_type" value="vendor">
  <div>
    <label class="block text-sm font-medium text-gray-700 mb-1">제목</label>
    <input type="text" name="title" id="draft-title" value="{_esc(title)}"
      class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
  </div>
  <div>
    <label class="block text-sm font-medium text-gray-700 mb-1">본문</label>
    <textarea name="body" id="draft-body" rows="12"
      class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y">{_esc(body)}</textarea>
  </div>
</div>
<script>
function copyDraft() {{
  const body = document.getElementById('draft-body');
  if (!body) return;
  navigator.clipboard.writeText(body.value).then(() => {{
    const btn = document.querySelector('button[onclick="copyDraft()"]');
    if (btn) {{
      const orig = btn.innerHTML;
      btn.innerHTML = '복사됨 ✓';
      setTimeout(() => btn.innerHTML = orig, 2000);
    }}
  }});
}}
</script>
""")


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
