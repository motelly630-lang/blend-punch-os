from pathlib import Path
from app.ai.client import ClaudeClient
from app.ai.web_scraper import fetch_page

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "product_url_fill.md"


_TEXT_SYSTEM = """너는 제품 정보 추출 전문가다.
사용자가 붙여넣은 비정형 텍스트(카톡 대화, PDF 복사본, 메모 등)에서 제품 데이터를 추출한다.

반환 JSON 스키마:
{
  "name": "제품명",
  "brand": "브랜드명",
  "category": "카테고리 (식품/뷰티/건강/주방/리빙/다이어트/육아/반려동물 중 하나)",
  "consumer_price": 소비자가(숫자, 원 단위),
  "groupbuy_price": 공구가(숫자, 원 단위),
  "discount_rate": 할인율(0~100 정수, consumer_price와 groupbuy_price로 계산 가능하면 계산),
  "seller_commission_rate": 셀러커미션율(0~100 정수),
  "description": "제품 설명 요약",
  "key_benefits": ["혜택1", "혜택2"],
  "unique_selling_point": "핵심 차별점 한 문장",
  "content_angle": "콘텐츠 앵글 제안"
}
값을 알 수 없으면 null로 둔다. 숫자 필드에 단위 문자 금지."""


def analyze_product_text(raw_text: str) -> dict:
    claude = ClaudeClient()
    result = claude.complete_json(_TEXT_SYSTEM, f"다음 텍스트에서 제품 정보를 추출하라:\n\n{raw_text}")
    # Server-side: calculate discount_rate if missing but both prices available
    cp = result.get("consumer_price")
    gp = result.get("groupbuy_price")
    if cp and gp and cp > 0 and result.get("discount_rate") is None:
        result["discount_rate"] = round((cp - gp) / cp * 100)
    return result


def analyze_product_url(url: str) -> dict:
    page_content = fetch_page(url)
    prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    system = prompt.split("## User")[0].replace("## System\n", "").strip()
    user = (
        prompt.split("## User Template\n", 1)[1]
        .replace("{url}", url)
        .replace("{page_content}", page_content)
    )
    claude = ClaudeClient()
    return claude.complete_json(system, user)
