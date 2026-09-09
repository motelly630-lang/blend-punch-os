import base64
import json
import logging
import re

import anthropic

from app.config import settings

log = logging.getLogger(__name__)

# Opus 4.7/4.8 reject sampling params (temperature/top_p/top_k) with a 400.
# Guard so the central client stays correct if claude_model is bumped to Opus.
_NO_SAMPLING_PREFIXES = ("claude-opus-4-7", "claude-opus-4-8")


class ClaudeClient:
    def __init__(self):
        # Use settings (reads from .env via pydantic-settings) — fixes "auth method" error
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model

    # ── internals ────────────────────────────────────────────────────────────

    def _supports_sampling(self) -> bool:
        return not self.model.startswith(_NO_SAMPLING_PREFIXES)

    def _system_blocks(self, system: str) -> list[dict]:
        """System prompt as a cacheable content block.

        Prompt caching is a prefix match — caching the (large, reused) system
        prompt cuts cost/latency on repeated calls (batch product imports,
        generating proposals for many influencers with the same system prompt).
        Sonnet 4.6 only caches prefixes >= 2048 tokens; shorter ones silently
        no-op (no error), so this is safe to apply universally.
        """
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    @staticmethod
    def _first_text(response) -> str:
        for block in response.content:
            if block.type == "text":
                return block.text
        return ""

    @staticmethod
    def _extract_json_object(text: str) -> dict:
        """Best-effort JSON-object extraction for the no-schema (legacy) path."""
        text = text.strip()
        text = re.sub(r"^```(?:json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

        # 1) JSON 오브젝트 {…} 추출 시도
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            try:
                result = json.loads(text[start : end + 1])
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        # 2) 전체 텍스트 파싱 — Claude가 배열로 반환한 경우 첫 번째 dict 꺼냄
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        return item
        except json.JSONDecodeError:
            pass

        return {}

    # ── public API ───────────────────────────────────────────────────────────

    def complete(self, system: str, user: str, max_tokens: int = 8192, temperature: float = 0.7) -> str:
        kwargs = dict(
            model=self.model,
            max_tokens=max_tokens,
            system=self._system_blocks(system),
            messages=[{"role": "user", "content": user}],
        )
        if self._supports_sampling():
            kwargs["temperature"] = temperature
        response = self.client.messages.create(**kwargs)
        return self._first_text(response)

    def complete_json(self, system: str, user: str, max_tokens: int = 8192, schema: dict | None = None) -> dict:
        """Return a JSON object from Claude.

        Pass ``schema`` (a JSON Schema with ``additionalProperties: false`` and all
        keys listed in ``required``) to use Structured Outputs — the API then
        *guarantees* a schema-valid response, so no fragile fence-stripping /
        brace-extraction is needed. Without a schema, falls back to robust
        best-effort text parsing (backward compatible with existing callers).
        """
        if schema is not None:
            kwargs = dict(
                model=self.model,
                max_tokens=max_tokens,
                system=self._system_blocks(system),
                messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
            if self._supports_sampling():
                kwargs["temperature"] = 0.3
            try:
                response = self.client.messages.create(**kwargs)
                if response.stop_reason == "refusal":
                    log.warning("complete_json: model refused (schema path)")
                    return {}
                # output_config guarantees the first text block is valid JSON
                return json.loads(self._first_text(response))
            except (json.JSONDecodeError, anthropic.APIError) as e:
                log.warning("complete_json schema path failed (%s); falling back to text path", type(e).__name__)
                # fall through to the legacy text path below

        json_system = (
            system
            + "\n\n반드시 유효한 JSON 오브젝트({...})만 출력하라. "
            "배열([...]) 형태 금지. 마크다운 코드 블록 없이 순수 JSON만 반환. "
            "모든 문자열 값은 간결하게 작성하라."
        )
        text = self.complete(json_system, user, max_tokens, temperature=0.3)
        return self._extract_json_object(text)

    def web_search_text(self, system: str, user: str, max_tokens: int = 3000, max_rounds: int = 4) -> str:
        """웹서치 서버툴로 정보를 수집해 최종 텍스트를 반환.

        server-side web_search 루프가 한도(기본 10회)에 도달하면 stop_reason=pause_turn
        이 되고, assistant 응답을 다시 보내 이어서 진행한다.
        """
        tools = [{"type": "web_search_20260209", "name": "web_search"}]
        messages = [{"role": "user", "content": user}]
        response = None
        for _ in range(max_rounds):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=self._system_blocks(system),
                messages=messages,
                tools=tools,
            )
            if response.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": response.content})
                continue
            break
        return "".join(b.text for b in (response.content if response else []) if b.type == "text")

    def complete_vision_json(self, system: str, user_text: str,
                             image_bytes: bytes, media_type: str = "image/jpeg",
                             max_tokens: int = 4096) -> dict:
        json_system = system + "\n\n반드시 유효한 JSON만 출력. 마크다운 코드 블록 없이 순수 JSON만."
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
        response = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, system=self._system_blocks(json_system),
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": user_text},
            ]}],
        )
        return self._extract_json_object(self._first_text(response))

    @property
    def available(self) -> bool:
        return bool(settings.anthropic_api_key)
