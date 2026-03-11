from fastapi import APIRouter, Form, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Product, Influencer
from app.ai.proposal_generator import generate_proposal

router = APIRouter(prefix="/api/ai")


@router.post("/proposal-draft", response_class=HTMLResponse)
def ai_proposal_draft(
    db: Session = Depends(get_db),
    product_id: str = Form(""),
    influencer_id: str = Form(""),
    proposal_type: str = Form("email"),
    custom_instructions: str = Form(""),
):
    product = db.query(Product).filter(Product.id == product_id).first() if product_id else None
    influencer = db.query(Influencer).filter(Influencer.id == influencer_id).first() if influencer_id else None

    if not product:
        return HTMLResponse(
            '<div id="ai-draft-area" class="text-red-600 text-sm p-3 bg-red-50 rounded-lg border border-red-200">'
            "제품을 먼저 선택해 주세요.</div>"
        )

    result = generate_proposal(
        proposal_type=proposal_type,
        product_name=product.name,
        product_brand=product.brand,
        product_category=product.category,
        product_price=product.price,
        product_usp=product.unique_selling_point or "",
        influencer_name=influencer.name if influencer else "",
        influencer_platform=influencer.platform if influencer else "",
        influencer_followers=influencer.followers if influencer else 0,
        influencer_categories=influencer.categories if influencer else [],
        commission_rate=product.recommended_commission_rate or 0.15,
        custom_instructions=custom_instructions,
    )

    title = result.get("title", "")
    body = result.get("body", "")
    char_count = len(body)
    type_label = "이메일" if proposal_type == "email" else "카카오톡"

    return HTMLResponse(f"""
<div id="ai-draft-area" class="bg-white rounded-xl border border-gray-100 shadow-sm p-6 space-y-4">
  <div class="flex items-center justify-between">
    <span class="text-sm font-semibold text-blue-700 flex items-center gap-1.5">
      <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
      </svg>
      {type_label} 초안 생성 완료
    </span>
    <span class="text-xs text-gray-400">{char_count}자</span>
  </div>
  <input type="hidden" name="ai_generated" value="true">
  <div>
    <label class="block text-sm font-medium text-gray-700 mb-1">제목</label>
    <input type="text" name="title" value="{_esc(title)}"
      class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
  </div>
  <div>
    <label class="block text-sm font-medium text-gray-700 mb-1">본문</label>
    <textarea name="body" rows="10"
      class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y">{_esc(body)}</textarea>
  </div>
</div>
""")


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
