import json
from fastapi import APIRouter, Form, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Product
from app.models.playbook import Playbook
from app.ai.playbook_generator import generate_playbook, playbook_to_text
from app.auth.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/ai")


@router.post("/playbook", response_class=HTMLResponse)
def ai_playbook(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    product_id: str = Form(""),
    product_name: str = Form(""),
    product_brand: str = Form(""),
    product_category: str = Form(""),
    product_price: str = Form("0"),
    product_usp: str = Form(""),
    content_angle: str = Form(""),
    key_benefits: str = Form(""),
    public_product_url: str = Form(""),
    save: str = Form("false"),
):
    # DB lookup if product_id provided
    product = None
    if product_id:
        product = db.query(Product).filter(Product.id == product_id).first()

    if product:
        p_name = product.name
        p_brand = product.brand or ""
        p_category = product.category or ""
        p_price = float(product.price or 0)
        p_usp = product.unique_selling_point or ""
        p_angle = product.content_angle or ""
        p_benefits = product.key_benefits or []
        if product.status == "active":
            p_url = public_product_url or f"/public/products/{product.id}"
        else:
            p_url = public_product_url or ""
    else:
        p_name = product_name
        p_brand = product_brand
        p_category = product_category
        p_price = float(product_price) if product_price else 0
        p_usp = product_usp
        p_angle = content_angle
        p_benefits = [b.strip() for b in key_benefits.split(",") if b.strip()] if key_benefits else []
        p_url = public_product_url

    if not p_name:
        return HTMLResponse(
            '<div id="output-panel" class="p-4 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">'
            "제품명을 입력하거나 제품을 선택해 주세요.</div>"
        )

    data = generate_playbook(
        product_name=p_name,
        product_brand=p_brand,
        product_category=p_category,
        product_price=p_price,
        product_usp=p_usp,
        content_angle=p_angle,
        key_benefits=p_benefits,
        public_product_url=p_url,
    )
    flat_text = playbook_to_text(data)

    if save == "true":
        pb = Playbook(
            product_id=product_id or None,
            product_name=p_name,
            product_brand=p_brand,
            product_usp=p_usp,
            content_angle=p_angle,
            body_json=data,
            body=flat_text,
            ai_generated=True,
        )
        db.add(pb)
        db.commit()
        db.refresh(pb)
        return HTMLResponse(f"""
<div id="output-panel" class="p-5 bg-green-50 border border-green-200 rounded-xl text-sm text-green-800">
  <div class="flex items-center gap-2 font-semibold mb-2">
    <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
      <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
    </svg>
    플레이북 저장 완료
  </div>
  <p class="text-green-700">{_esc(p_name)} 플레이북이 저장되었습니다.</p>
</div>
""")

    # Preview mode — render 9 section cards
    sections = [
        ("pre_launch",     "론칭 전 예열"),
        ("demand_build",   "수요 집결"),
        ("launch_day",     "오픈 당일"),
        ("closing",        "마감 푸시"),
        ("hooks",          "후킹 문구"),
        ("content_angles", "콘텐츠 앵글"),
        ("posting_guide",  "포스팅 가이드"),
        ("story_flow",     "스토리 흐름"),
        ("reel_flow",      "릴스 구성"),
    ]

    cards_html = ""
    for key, label in sections:
        val = data.get(key, "")
        if isinstance(val, list):
            content = "".join(f"<li class='ml-4 list-disc'>{_esc(str(v))}</li>" for v in val)
            content = f"<ul class='space-y-1 text-gray-700'>{content}</ul>"
        else:
            content = f"<p class='text-gray-700 whitespace-pre-wrap'>{_esc(str(val))}</p>"
        cards_html += f"""
<div class="bg-white rounded-lg border border-gray-100 p-4 shadow-sm">
  <div class="text-xs font-semibold text-blue-600 uppercase tracking-wide mb-2">{label}</div>
  {content}
</div>"""

    data_json = _esc(json.dumps(data, ensure_ascii=False))
    flat_esc = _esc(flat_text)

    return HTMLResponse(f"""
<div id="output-panel" class="space-y-4">
  <div class="flex items-center justify-between">
    <div>
      <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-700">플레이북</span>
      <span class="ml-2 font-semibold text-gray-800">{_esc(p_name)}</span>
    </div>
    <div class="flex gap-2">
      <button type="button" onclick="copyOutput('output-body')"
        class="px-3 py-1.5 text-xs font-medium border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors">
        전체 복사
      </button>
      <button type="button"
        hx-post="/api/ai/playbook"
        hx-target="#output-panel"
        hx-swap="outerHTML"
        hx-include="#ctx-product-id,#ctx-product-name,#ctx-product-brand,#ctx-product-category,#ctx-product-price,#ctx-product-usp,#ctx-content-angle,#ctx-key-benefits,#ctx-public-url"
        hx-vals='{{"save": "true"}}'
        class="px-3 py-1.5 text-xs font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
        저장
      </button>
    </div>
  </div>
  <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
    {cards_html}
  </div>
  <div id="output-body" class="hidden">{flat_esc}</div>
</div>
""")


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
