import json
from pathlib import Path
from app.ai.client import ClaudeClient

_PROMPTS = Path(__file__).parent.parent / "prompts"


def generate_playbook(
    product_name: str,
    product_brand: str = "",
    product_category: str = "",
    product_price: float = 0,
    product_usp: str = "",
    content_angle: str = "",
    key_benefits: list | None = None,
    public_product_url: str = "",
) -> dict:
    claude = ClaudeClient()
    if not claude.available:
        return _mock_playbook(product_name, product_brand)

    prompt_file = _PROMPTS / "playbook.md"
    prompt = prompt_file.read_text(encoding="utf-8")
    system = prompt.split("## User")[0].replace("## System\n", "").strip()
    user_template = prompt.split("## User Template\n", 1)[1]

    benefits_str = ", ".join(key_benefits) if key_benefits else ""

    user = (
        user_template
        .replace("{product_name}", product_name)
        .replace("{product_brand}", product_brand or "미입력")
        .replace("{product_category}", product_category or "미입력")
        .replace("{product_price}", f"{int(product_price):,}" if product_price else "미입력")
        .replace("{product_usp}", product_usp or "미입력")
        .replace("{content_angle}", content_angle or "없음")
        .replace("{key_benefits}", benefits_str or "없음")
        .replace("{public_product_url}", public_product_url or "없음")
    )

    try:
        return claude.complete_json(system, user)
    except Exception:
        return _mock_playbook(product_name, product_brand)


def _mock_playbook(product_name: str, product_brand: str = "") -> dict:
    brand = product_brand or "브랜드"
    return {
        "pre_launch": (
            f"D-7: '{product_name}' 공구 예고 스토리 업로드. "
            "「곧 오픈 예정 👀」 문구와 제품 티저 이미지 1장. "
            "D-3: 관심 있는 팔로워 DM 수집 (「댓글 남겨주세요」). "
            "D-1: 「내일 오픈!」 카운트다운 스토리."
        ),
        "demand_build": (
            "한정 수량 강조 (예: 「선착순 50세트」). "
            "사전 관심자에게 알림 신청 받기. "
            "스토리 폴 활용 — 「이 제품 써보셨나요?」로 관심도 확인."
        ),
        "launch_day": (
            "오전 10시 피드 포스팅 + 스토리 링크 연결. "
            "오후 2시 스토리 업데이트 (현재 수량 현황). "
            "저녁 8시 마감 전 마지막 알림 스토리."
        ),
        "closing": (
            "마감 1시간 전: 「곧 마감됩니다 ⏰」 스토리. "
            "마감 30분 전: 남은 수량 공개 + 「지금 아니면 기회 없어요」. "
            "마감 직전: 감사 메시지 예약."
        ),
        "hooks": [
            f"이거 한 번만 써봐도 {product_name} 없이 못 살아요",
            f"왜 이제 알았지? {brand} {product_name} 솔직 리뷰",
            f"공구가 이렇게 쉬웠나? {product_name} 완전 정복",
            f"팔로워들이 먼저 물어봤어요 — {product_name} 드디어 공구!",
            f"써보고 반했어요 ✨ {product_name} 공동구매 오픈",
        ],
        "content_angles": [
            "Before/After 비교 콘텐츠",
            "일상 속 자연스러운 사용 장면",
            "솔직 후기 + 단점도 언급하는 진정성 리뷰",
        ],
        "posting_guide": (
            "최적 시간대: 오전 7~9시(출근길), 오후 12~1시(점심), 저녁 8~10시(귀가 후). "
            "공구 기간 중 최소 하루 1스토리 + 피드 1회."
        ),
        "story_flow": (
            "1컷: 제품 언박싱/첫인상 (기대감) → "
            "2컷: 사용 장면 클로즈업 → "
            "3컷: 효과/결과 Before-After → "
            "4컷: 가격 + 링크 공유 (CTA)"
        ),
        "reel_flow": (
            "0~3초: 강렬한 오프닝 훅 (\"이거 알아요?\") → "
            "3~20초: 제품 핵심 기능 시연 → "
            "20~25초: 결과/혜택 강조 → "
            "25~30초: CTA (\"링크 클릭 / DM 주세요\")"
        ),
    }


def playbook_to_text(data: dict) -> str:
    """Convert playbook JSON dict to flat copy-ready text."""
    lines = []
    label_map = {
        "pre_launch": "【론칭 전 예열 전략】",
        "demand_build": "【수요 집결 전략】",
        "launch_day": "【오픈 당일 플랜】",
        "closing": "【마감 푸시 전략】",
        "posting_guide": "【포스팅 가이드】",
        "story_flow": "【스토리 흐름】",
        "reel_flow": "【릴스 구성】",
    }
    for key, label in label_map.items():
        if key in data:
            lines.append(label)
            lines.append(str(data[key]))
            lines.append("")

    if "hooks" in data and data["hooks"]:
        lines.append("【후킹 문구】")
        for h in data["hooks"]:
            lines.append(f"• {h}")
        lines.append("")

    if "content_angles" in data and data["content_angles"]:
        lines.append("【콘텐츠 앵글】")
        for a in data["content_angles"]:
            lines.append(f"• {a}")
        lines.append("")

    return "\n".join(lines).strip()
