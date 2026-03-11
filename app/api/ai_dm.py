from fastapi import APIRouter, Form, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.proposal import Proposal
from app.ai.dm_generator import generate_dm
from app.auth.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/ai")

_DM_LABELS = {
    "dm_first":    "DM 첫 연락",
    "dm_followup": "DM 팔로업",
    "dm_confirm":  "DM 협업 확정",
}


@router.post("/dm", response_class=HTMLResponse)
def ai_dm(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    dm_type: str = Form("dm_first"),
    product_id: str = Form(""),
    product_name: str = Form(""),
    product_brand: str = Form(""),
    product_category: str = Form(""),
    product_usp: str = Form(""),
    influencer_name: str = Form(""),
    influencer_platform: str = Form(""),
    custom_instructions: str = Form(""),
    save: str = Form("false"),
):
    if not product_name:
        return HTMLResponse(
            '<div id="output-panel" class="p-4 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">'
            "제품 정보를 먼저 입력해 주세요.</div>"
        )

    result = generate_dm(
        dm_type=dm_type,
        product_name=product_name,
        product_brand=product_brand,
        product_category=product_category,
        product_usp=product_usp,
        influencer_name=influencer_name,
        influencer_platform=influencer_platform,
        custom_instructions=custom_instructions,
    )

    title = result.get("title", "")
    body = result.get("body", "")
    label = _DM_LABELS.get(dm_type, "DM")

    if save == "true":
        proposal = Proposal(
            product_id=product_id or None,
            proposal_type=dm_type,
            title=title or None,
            body=body,
            ai_generated=True,
        )
        db.add(proposal)
        db.commit()
        db.refresh(proposal)
        return HTMLResponse(f"""
<div id="output-panel" class="p-5 bg-green-50 border border-green-200 rounded-xl text-sm text-green-800">
  <div class="flex items-center gap-2 font-semibold mb-2">
    <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
      <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
    </svg>
    저장 완료
  </div>
  <p>제안서 목록에서 확인하세요: <a href="/proposals/{proposal.id}" class="underline font-medium">바로 가기 →</a></p>
</div>
""")

    body_esc = _esc(body)
    return HTMLResponse(f"""
<div id="output-panel" class="space-y-4">
  <div class="flex items-center justify-between">
    <div>
      <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">{label}</span>
      <span class="ml-2 font-semibold text-gray-800">{_esc(title)}</span>
    </div>
    <div class="flex gap-2">
      <button type="button" onclick="copyOutput('output-body')"
        class="px-3 py-1.5 text-xs font-medium border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors">
        복사
      </button>
      <button type="button"
        hx-post="/api/ai/dm"
        hx-target="#output-panel"
        hx-swap="outerHTML"
        hx-include="#ctx-product-id,#ctx-product-name,#ctx-product-brand,#ctx-product-category,#ctx-product-usp,#ctx-influencer-name,#ctx-influencer-platform"
        hx-vals='{{"dm_type": "{dm_type}", "save": "true"}}'
        class="px-3 py-1.5 text-xs font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
        저장
      </button>
    </div>
  </div>
  <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
    <textarea id="output-body" rows="6" readonly
      class="w-full text-sm text-gray-800 bg-transparent resize-none focus:outline-none">{body_esc}</textarea>
    <div class="mt-2 text-right text-xs text-gray-400">{len(body)}자</div>
  </div>
</div>
""")


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
