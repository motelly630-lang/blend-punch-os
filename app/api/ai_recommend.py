"""
Seller Recommendation Engine
POST /api/ai/recommend-sellers  — scoring + AI reasoner
POST /api/automation/save-note  — save output to automation_notes
POST /api/automation/add-to-campaign — save recommendation to campaign
"""
from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.influencer import Influencer
from app.models.automation import AutomationNote, CampaignRecommendation
from app.models.campaign import Campaign
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.ai.client import ClaudeClient

router = APIRouter()


# ── Scoring ────────────────────────────────────────────────────────────────────

def _score_influencer(inf: Influencer, category: str, usp: str,
                      max_gmv: float, max_eng: float) -> float:
    """
    Weights: category/tag match 40% | past_gmv 30% | engagement_rate 20% | campaign_history 10%
    Returns 0–100.
    """
    score = 0.0

    # 1. Category / tag match (40 pts)
    cat_lower = (category or "").lower()
    inf_cats = inf.categories if isinstance(inf.categories, list) else []
    inf_cats_lower = [c.lower() for c in inf_cats]
    if cat_lower and any(cat_lower in c or c in cat_lower for c in inf_cats_lower):
        score += 40.0
    elif cat_lower and any(
        word in " ".join(inf_cats_lower)
        for word in cat_lower.split()
    ):
        score += 20.0

    # 2. past_gmv normalized (30 pts)
    gmv = inf.past_gmv or 0.0
    if max_gmv > 0:
        score += (gmv / max_gmv) * 30.0

    # 3. engagement_rate normalized (20 pts)
    eng = inf.engagement_rate or 0.0
    if max_eng > 0:
        score += (eng / max_eng) * 20.0

    # 4. Campaign history (10 pts)
    if inf.has_campaign_history == "true":
        score += 10.0

    return round(score, 1)


def _ai_reason(inf: Influencer, product_name: str, usp: str, score: float) -> str:
    try:
        client = ClaudeClient()
        if not client.available:
            raise ValueError("no key")
        cats = ", ".join(inf.categories) if isinstance(inf.categories, list) else (inf.categories or "")
        prompt = (
            f"제품: {product_name} / USP: {usp}\n"
            f"인플루언서: {inf.name} / 카테고리: {cats} / "
            f"팔로워: {inf.followers:,} / 과거GMV: {inf.past_gmv or 0:,}원 / "
            f"추천점수: {score}\n"
            f"위 정보를 바탕으로 이 인플루언서를 추천하는 이유를 2~3문장으로 작성하라. "
            f"구체적인 수치와 카테고리 적합성을 언급하라."
        )
        return client.complete("너는 인플루언서 마케팅 전문가다.", prompt, max_tokens=300)
    except Exception:
        return "카테고리 일치도와 과거 성과 기준으로 추천된 셀러입니다."


# ── Recommend Endpoint ─────────────────────────────────────────────────────────

@router.post("/api/ai/recommend-sellers", response_class=HTMLResponse)
def recommend_sellers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    product_id: str = Form(""),
    product_name: str = Form(""),
    category: str = Form(""),
    usp: str = Form(""),
):
    influencers = (
        db.query(Influencer)
        .filter(Influencer.status == "active")
        .limit(500)
        .all()
    )
    if not influencers:
        return HTMLResponse('<div class="text-sm text-gray-400 p-4">등록된 인플루언서가 없습니다.</div>')

    max_gmv = max((i.past_gmv or 0) for i in influencers) or 1.0
    max_eng = max((i.engagement_rate or 0) for i in influencers) or 1.0

    scored = [
        (inf, _score_influencer(inf, category, usp, max_gmv, max_eng))
        for inf in influencers
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    top10 = scored[:10]

    # Build result rows with AI reasons
    rows_html = ""
    for inf, score in top10:
        reason = _ai_reason(inf, product_name or "제품", usp, score)
        cats = ", ".join(inf.categories) if isinstance(inf.categories, list) else (inf.categories or "-")
        score_color = "green" if score >= 60 else "amber" if score >= 30 else "gray"
        score_cls = {
            "green": "bg-green-100 text-green-700",
            "amber": "bg-amber-100 text-amber-700",
            "gray": "bg-gray-100 text-gray-500",
        }[score_color]

        rows_html += f"""
<div class="flex items-start gap-4 p-4 border border-gray-100 rounded-xl hover:border-indigo-200 transition-colors">
  <div class="flex-1 min-w-0">
    <div class="flex items-center gap-2 mb-1">
      <a href="/influencers/{inf.id}" class="font-semibold text-gray-900 hover:text-indigo-600 text-sm">{inf.name}</a>
      {"<span class='text-xs text-gray-400'>@" + inf.handle + "</span>" if inf.handle else ""}
      <span class="text-xs px-2 py-0.5 rounded-full font-bold {score_cls}">{score}점</span>
    </div>
    <div class="flex items-center gap-3 text-xs text-gray-500 mb-2">
      <span>팔로워 {inf.followers:,}</span>
      <span>GMV {int(inf.past_gmv or 0):,}원</span>
      {"<span>참여율 " + str(round(inf.engagement_rate or 0, 1)) + "%</span>" if inf.engagement_rate else ""}
      {"<span class='text-green-600 font-medium'>캠페인 경력 있음</span>" if inf.has_campaign_history == 'true' else ""}
    </div>
    <div class="text-xs text-gray-400 mb-2">{cats}</div>
    <div class="text-sm text-gray-700 leading-relaxed">{reason}</div>
  </div>
  <div class="flex flex-col gap-1.5 flex-shrink-0">
    <button onclick="navigator.clipboard.writeText(`{reason.replace('`', "'")}`).then(()=>alert('복사됨'))"
      class="text-xs px-2.5 py-1 border border-gray-200 rounded-lg text-gray-500 hover:bg-gray-50 whitespace-nowrap">복사</button>
    <form method="post" action="/api/automation/add-to-campaign" class="inline">
      <input type="hidden" name="influencer_id" value="{inf.id}">
      <input type="hidden" name="score" value="{score}">
      <input type="hidden" name="reason" value="{reason[:500]}">
      <input type="hidden" name="product_id" value="{product_id}">
      <select name="campaign_id" onchange="if(this.value)this.form.submit()"
        class="text-xs border border-indigo-200 rounded-lg px-2 py-1 bg-white cursor-pointer text-indigo-600">
        <option value="">캠페인 추가</option>
        {"".join(f'<option value="{c.id}">{c.name[:20]}</option>' for c in db.query(Campaign).filter(Campaign.status != "cancelled").order_by(Campaign.created_at.desc()).limit(30).all())}
      </select>
    </form>
  </div>
</div>"""

    save_content = "\n".join(
        f"{inf.name} ({score}점): {_ai_reason(inf, product_name or '제품', usp, score)}"
        for inf, score in top10[:3]
    )

    return HTMLResponse(f"""
<div id="output-panel" class="bg-white rounded-xl border border-gray-100 shadow-sm p-5 space-y-3">
  <div class="flex items-center justify-between mb-2">
    <h3 class="text-sm font-semibold text-gray-700">셀러 추천 결과 — {category or '전체'} / {product_name or '제품'}</h3>
    <div class="flex gap-2">
      <button onclick="navigator.clipboard.writeText(document.getElementById('recommend-text').innerText).then(()=>this.textContent='복사됨 ✓')"
        class="text-xs px-3 py-1.5 border border-gray-200 rounded-lg text-gray-500 hover:bg-gray-50">전체 복사</button>
      <button onclick="document.getElementById('save-note-modal').classList.remove('hidden')"
        class="text-xs px-3 py-1.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700">메모 저장</button>
    </div>
  </div>
  <div id="recommend-text" class="space-y-2">
    {rows_html}
  </div>
</div>

<!-- Save note modal -->
<div id="save-note-modal" class="hidden fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
  <div class="bg-white rounded-2xl shadow-xl w-full max-w-md p-6">
    <div class="flex items-center justify-between mb-4">
      <h3 class="font-semibold text-gray-800">메모로 저장</h3>
      <button onclick="document.getElementById('save-note-modal').classList.add('hidden')" class="text-gray-400">✕</button>
    </div>
    <form method="post" action="/api/automation/save-note" class="space-y-3">
      <input type="hidden" name="module" value="seller_recommend">
      <input type="hidden" name="product_id" value="{product_id}">
      <input type="hidden" name="product_name" value="{product_name}">
      <input type="hidden" name="content" value="{save_content.replace(chr(34), '&quot;')}">
      <div>
        <label class="block text-xs font-medium text-gray-600 mb-1">제목</label>
        <input type="text" name="title" value="셀러 추천 — {product_name or category}"
          class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500">
      </div>
      <div class="flex justify-end gap-3">
        <button type="button" onclick="document.getElementById('save-note-modal').classList.add('hidden')" class="text-sm text-gray-500">취소</button>
        <button type="submit" class="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700">저장</button>
      </div>
    </form>
  </div>
</div>
""")


# ── Save Note ──────────────────────────────────────────────────────────────────

@router.post("/api/automation/save-note")
def save_automation_note(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    module: str = Form(...),
    title: str = Form(""),
    content: str = Form(...),
    product_id: str = Form(""),
    product_name: str = Form(""),
):
    from fastapi.responses import RedirectResponse
    note = AutomationNote(
        module=module,
        title=title or None,
        content=content,
        product_id=product_id or None,
        product_name=product_name or None,
    )
    db.add(note)
    db.commit()
    return RedirectResponse("/automation?msg=메모가+저장되었습니다", status_code=302)


# ── Add to Campaign ────────────────────────────────────────────────────────────

@router.post("/api/automation/add-to-campaign")
def add_to_campaign(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    campaign_id: str = Form(...),
    influencer_id: str = Form(...),
    score: str = Form(""),
    reason: str = Form(""),
    product_id: str = Form(""),
):
    from fastapi.responses import RedirectResponse
    if not campaign_id:
        return RedirectResponse("/automation", status_code=302)
    rec = CampaignRecommendation(
        campaign_id=campaign_id,
        influencer_id=influencer_id,
        score=score or None,
        reason=reason or None,
    )
    db.add(rec)
    db.commit()
    return RedirectResponse(f"/campaigns/{campaign_id}?msg=인플루언서+추천+추가됨", status_code=302)
