import json
import re
import anthropic
from app.config import settings


class ClaudeClient:
    def __init__(self):
        # Use settings (reads from .env via pydantic-settings) — fixes "auth method" error
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model

    def complete(self, system: str, user: str, max_tokens: int = 8192, temperature: float = 0.7) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text

    def complete_json(self, system: str, user: str, max_tokens: int = 8192) -> dict:
        json_system = (
            system
            + "\n\n반드시 유효한 JSON만 출력하라. 마크다운 코드 블록 없이 순수 JSON만 반환. "
            "모든 문자열 값은 간결하게 작성하라."
        )
        text = self.complete(json_system, user, max_tokens, temperature=0.3)
        text = text.strip()
        text = re.sub(r"^```(?:json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        return json.loads(text)

    def complete_vision_json(self, system: str, user_text: str,
                             image_bytes: bytes, media_type: str = "image/jpeg",
                             max_tokens: int = 4096) -> dict:
        import base64
        json_system = system + "\n\n반드시 유효한 JSON만 출력. 마크다운 코드 블록 없이 순수 JSON만."
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
        response = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, system=json_system,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": user_text},
            ]}],
        )
        text = response.content[0].text.strip()
        text = re.sub(r"^```(?:json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e != -1:
            return json.loads(text[s:e+1])
        return json.loads(text)

    @property
    def available(self) -> bool:
        return bool(settings.anthropic_api_key)
