from pathlib import Path
from app.ai.client import ClaudeClient

_PROMPTS = Path(__file__).parent.parent / "prompts"

_PROMPT_FILE_MAP = {
    "dm_first": "dm_first_contact.md",
    "dm_followup": "dm_followup.md",
    "dm_confirm": "dm_confirmation.md",
}


def generate_dm(
    dm_type: str,
    product_name: str,
    product_brand: str = "",
    product_category: str = "",
    product_usp: str = "",
    influencer_name: str = "",
    influencer_platform: str = "",
    custom_instructions: str = "",
) -> dict:
    claude = ClaudeClient()
    if not claude.available:
        return _mock_dm(dm_type, product_name, product_brand, influencer_name)

    prompt_file_name = _PROMPT_FILE_MAP.get(dm_type, "dm_first_contact.md")
    prompt = (_PROMPTS / prompt_file_name).read_text(encoding="utf-8")
    system = prompt.split("## User")[0].replace("## System\n", "").strip()
    user_template = prompt.split("## User Template\n", 1)[1]

    user = (
        user_template
        .replace("{product_name}", product_name)
        .replace("{product_brand}", product_brand or "미입력")
        .replace("{product_category}", product_category or "미입력")
        .replace("{product_usp}", product_usp or "없음")
        .replace("{influencer_name}", influencer_name or "셀러")
        .replace("{influencer_platform}", influencer_platform or "SNS")
        .replace("{custom_instructions}", custom_instructions or "없음")
    )

    try:
        return claude.complete_json(system, user)
    except Exception:
        return _mock_dm(dm_type, product_name, product_brand, influencer_name)


def _mock_dm(dm_type: str, product_name: str, product_brand: str,
             influencer_name: str) -> dict:
    name = influencer_name or "셀러"
    brand = product_brand or "저희"
    if dm_type == "dm_first":
        return {
            "title": f"DM 첫 연락 — {name}",
            "body": (
                f"안녕하세요 {name}님 😊 "
                f"{brand}의 [{product_name}] 공동구매 관련해서 연락드렸어요. "
                f"채널과 잘 맞을 것 같아서요! 혹시 관심 있으시면 편하게 답장 주세요 🙏"
            ),
        }
    elif dm_type == "dm_followup":
        return {
            "title": f"DM 팔로업 — {name}",
            "body": (
                f"안녕하세요 {name}님, 며칠 전에 [{product_name}] 공구 관련 DM 드렸는데요. "
                f"바쁘셨을 것 같아서요 😊 추가 혜택도 준비되어 있으니 관심 있으시면 언제든지!"
            ),
        }
    else:
        return {
            "title": f"협업 확정 감사 — {name}",
            "body": (
                f"감사합니다 {name}님! 협업 확정 너무 기쁘네요 🎉 "
                f"[{product_name}] 공구가 성공적으로 진행될 수 있도록 최대한 지원 드리겠습니다. "
                f"계약 관련 내용은 별도로 안내 드릴게요!"
            ),
        }
