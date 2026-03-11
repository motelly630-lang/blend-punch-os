from pathlib import Path
from app.ai.client import ClaudeClient

_PROMPTS = Path(__file__).parent.parent / "prompts"

_PROMPT_MAP = {
    "email":           "proposal_email.md",
    "kakao":           "proposal_kakao.md",
    "vendor":          "proposal_vendor.md",
    "seller_outreach": "seller_outreach.md",
    "inf_summary":     "inf_summary.md",
    "memo":            "memo.md",
}


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
    product_content_angle: str = "",
    product_key_benefits: list | None = None,
    public_product_url: str = "",
    internal_notes: str = "",
) -> dict:
    claude = ClaudeClient()
    if not claude.available:
        return _mock_proposal(proposal_type, product_name, product_brand, influencer_name, commission_rate)

    prompt_file_name = _PROMPT_MAP.get(proposal_type, "proposal_email.md")
    prompt = (_PROMPTS / prompt_file_name).read_text(encoding="utf-8")
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
        .replace("{product_content_angle}", product_content_angle or "")
        .replace("{product_key_benefits}", ", ".join(product_key_benefits or []))
        .replace("{public_product_url}", public_product_url or "없음")
        .replace("{internal_notes}", internal_notes or "없음")
    )

    try:
        return claude.complete_json(system, user)
    except Exception:
        return _mock_proposal(proposal_type, product_name, product_brand, influencer_name, commission_rate)


def _mock_proposal(proposal_type: str, product_name: str, product_brand: str,
                   influencer_name: str, commission_rate: float) -> dict:
    commission_pct = f"{commission_rate * 100:.0f}%"
    name = influencer_name or "셀러"
    if proposal_type == "vendor":
        body = (
            f"안녕하세요!\n\n"
            f"BLEND PUNCH에서 [{product_brand}] {product_name} 공동구매 협업을 제안 드립니다.\n\n"
            f"■ 제품 소개\n{product_name}은 {product_brand}의 대표 제품으로, "
            f"공동구매 채널에서 높은 전환율을 기대할 수 있습니다.\n\n"
            f"■ 핵심 셀링포인트\n경쟁 대비 차별화된 가격과 품질로 팔로워 만족도가 높습니다.\n\n"
            f"■ 협업 조건\n- 커미션: {commission_pct}\n"
            f"- 전용 할인가 및 마케팅 소재 지원\n"
            f"- 정산 월 1회 (익월 15일)\n\n"
            f"관심 있으시면 편하게 DM 주세요 🙏\n\n"
            f"BLEND PUNCH 드림"
        )
        return {"title": f"[{product_brand}] {product_name} 공동구매 제안", "body": body}
    elif proposal_type == "kakao":
        body = (
            f"안녕하세요 {name}님 😊\n"
            f"저희 {product_brand}의 [{product_name}] 공동구매 제안 드립니다.\n\n"
            f"✅ 커미션: {commission_pct}\n"
            f"✅ 전용 할인가 제공\n"
            f"✅ 마케팅 소재 지원 (사진·영상)\n\n"
            f"관심 있으시면 답장 주세요 🙏"
        )
        return {"title": f"{product_name} 공동구매 제안", "body": body}
    elif proposal_type == "seller_outreach":
        body = (
            f"📢 [{product_brand}] {product_name} 셀러 모집 안내\n\n"
            f"안녕하세요! BLEND PUNCH에서 {product_brand}의 [{product_name}] 공동구매를 함께 진행할 셀러를 모집합니다.\n\n"
            f"✅ 커미션: {commission_pct}\n"
            f"✅ 전용 할인가 제공\n"
            f"✅ 마케팅 소재 (사진/영상) 일체 제공\n"
            f"✅ 공구 세팅 및 운영 지원\n\n"
            f"관심 있는 셀러분들은 DM 또는 링크로 신청해 주세요 🙏\n"
            f"선착순 모집이므로 서둘러 주세요!"
        )
        return {"title": f"[셀러 모집] {product_brand} {product_name} 공동구매", "body": body}
    elif proposal_type == "inf_summary":
        body = (
            f"【인플루언서 요약 리포트】\n\n"
            f"대상: {name}\n"
            f"연결 제품: {product_name} ({product_brand})\n\n"
            f"■ 채널 적합도: 검토 필요\n"
            f"■ 추천 콘텐츠 형식: 피드 + 스토리\n"
            f"■ 예상 공구 성과: 보통 ~ 양호\n"
            f"■ 종합 의견: 추가 채널 분석 후 확정 권장\n\n"
            f"※ AI 미사용 모드 — 실제 분석은 AI 연결 후 진행하세요."
        )
        return {"title": f"인플루언서 요약 — {name}", "body": body}
    elif proposal_type == "memo":
        body = (
            f"【내부 메모】\n\n"
            f"제품: {product_name} ({product_brand})\n"
            f"셀러: {name}\n\n"
            f"■ 진행 상황: 초기 접촉 단계\n"
            f"■ 액션 아이템: 조건 협의 후 계약 진행\n"
            f"■ 특이사항: 없음\n\n"
            f"※ AI 미사용 모드 — 실제 내용은 수동 입력하세요."
        )
        return {"title": f"내부 메모 — {product_name}", "body": body}
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
