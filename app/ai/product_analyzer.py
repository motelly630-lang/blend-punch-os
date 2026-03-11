from pathlib import Path
from app.ai.client import ClaudeClient
from app.ai.web_scraper import fetch_page

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "product_url_fill.md"


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
