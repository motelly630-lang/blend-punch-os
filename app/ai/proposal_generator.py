from pathlib import Path
from app.ai.client import ClaudeClient

_PROMPTS = Path(__file__).parent.parent / "prompts"


def generate_proposal(
    proposal_type: str,
    product_name: str,
    product_brand: str,
    product_category: str,
    product_price: float,
    product_usp: str,
    influencer_name: str = "",
    influencer_platform: str = "",
    influencer_followers: int = 0,
    influencer_categories: list | None = None,
    commission_rate: float = 0.15,
    custom_instructions: str = "",
) -> dict:
    claude = ClaudeClient()
    if not claude.available:
        return _mock_proposal(proposal_type, product_name, product_brand, influencer_name, commission_rate)

    prompt_file = _PROMPTS / (
        "proposal_email.md" if proposal_type == "email" else "proposal_kakao.md"
    )
    prompt = prompt_file.read_text(encoding="utf-8")
    system = prompt.split("## User")[0].replace("## System\n", "").strip()
    user_template = prompt.split("## User Template\n", 1)[1]

    categories_str = ", ".join(influencer_categories) if influencer_categories else "미분류"
    commission_pct = f"{commission_rate * 100:.0f}%"

    user = (
        user_template
        .replace("{product_name}", product_name)
        .replace("{product_brand}", product_brand)
        .replace("{product_category}", product_category)
        .replace("{product_price}", f"{int(product_price):,}")
        .replace("{product_usp}", product_usp or "")
        .replace("{influencer_name}", influencer_name or "셀러")
        .replace("{influencer_platform}", influencer_platform or "SNS")
        .replace("{influencer_followers}", f"{influencer_followers:,}" if influencer_followers else "미정")
        .replace("{influencer_categories}", categories_str)
        .replace("{commission_rate}", commission_pct)
        .replace("{custom_instructions}", custom_instructions or "없음")
    )

    try:
        return claude.complete_json(system, user)
    except Exception:
        return _mock_proposal(proposal_type, product_name, product_brand, influencer_name, commission_rate)


def _mock_proposal(proposal_type: str, product_name: str, product_brand: str,
                   influencer_name: str, commission_rate: float) -> dict:
    commission_pct = f"{commission_rate * 100:.0f}%"
    name = influencer_name or "셀러"
    if proposal_type == "kakao":
        body = (
            f"안녕하세요 {name}님 😊\n"
            f"저희 {product_brand}의 [{product_name}] 공동구매 제안 드립니다.\n\n"
            f"✅ 커미션: {commission_pct}\n"
            f"✅ 전용 할인가 제공\n"
            f"✅ 마케팅 소재 지원 (사진·영상)\n\n"
            f"관심 있으시면 답장 주세요 🙏"
        )
        return {"title": f"{product_name} 공동구매 제안", "body": body}
    else:
        body = (
            f"안녕하세요 {name}님,\n\n"
            f"{product_brand}에서 [{product_name}] 공동구매 협업을 제안 드립니다.\n\n"
            f"■ 제품: {product_name} ({product_brand})\n"
            f"■ 커미션: 판매금액의 {commission_pct}\n"
            f"■ 전용 할인 쿠폰 및 마케팅 소재 제공\n"
            f"■ 정산 주기: 월 1회 (익월 15일)\n\n"
            f"관심 있으시다면 편하신 시간에 연락 주시면 자세히 안내 드리겠습니다.\n\n"
            f"감사합니다.\n{product_brand} 운영팀"
        )
        return {"title": f"[{product_brand}] {product_name} 공동구매 셀러 제안", "body": body}
