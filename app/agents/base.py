"""
BaseAgent — 모든 직급 에이전트의 공통 기반.

각 에이전트는 두 가지 역할을 가진다:
  1. think()  — Claude API 호출 → JSON 분석 결과 반환
  2. db_action() — 분석 결과를 바탕으로 DB에 실제 작업 수행 (서브클래스에서 override)

run() = think() + db_action() 순서로 실행

비용 최적화:
  - staff/assistant: Haiku (빠르고 저렴)
  - manager/lead: Sonnet (논리 분석)
  - director: risk_level이 HIGH일 때만 Opus, 평소엔 Sonnet

Retry/Fallback:
  - API 실패 시 최대 3회 재시도
  - 3회 모두 실패 시 하위 모델로 Fallback
"""
import json
import time
import uuid
from sqlalchemy.orm import Session

import anthropic
from app.config import settings
from app.models.agent_log import AgentLog

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

ROLE_MODELS = {
    "staff":     "claude-haiku-4-5-20251001",
    "assistant": "claude-haiku-4-5-20251001",
    "manager":   "claude-sonnet-4-6",
    "lead":      "claude-sonnet-4-6",
    "director":  "claude-sonnet-4-6",   # 기본값 Sonnet; HIGH risk 시 Opus로 승격
}

# 모델 폴백 체인: 실패 시 하위 모델로 내려간다
FALLBACK_MODELS = {
    "claude-opus-4-6":          "claude-sonnet-4-6",
    "claude-sonnet-4-6":        "claude-haiku-4-5-20251001",
    "claude-haiku-4-5-20251001": None,   # 더 이상 내려갈 수 없음
}

ROLE_LABELS = {
    "staff":     "사원",
    "assistant": "대리",
    "manager":   "과장",
    "lead":      "팀장",
    "director":  "이사",
}

MAX_RETRIES = 3


class BaseAgent:
    role: str = ""
    target_type: str = ""
    system_prompt: str = ""
    output_schema: str = ""

    def _select_model(self, context: dict) -> str:
        """
        이사 역할: lead의 risk_level이 HIGH이면 Opus, 그 외엔 Sonnet.
        나머지 역할: ROLE_MODELS 기본값 사용.
        """
        base_model = ROLE_MODELS[self.role]
        if self.role == "director":
            lead_risk = context.get("lead_result", {}).get("risk_level", "LOW")
            if lead_risk == "HIGH":
                return "claude-opus-4-6"
        return base_model

    def run(
        self,
        db: Session,
        target_id: str,
        target_name: str,
        context: dict,
        company_id: int = 1,
    ) -> dict:
        """
        think() → db_action() 순서로 실행.

        Returns:
            {
                "role", "role_label",
                "decision": "pass"|"reject",
                "score": float,           ← 0.0~1.0
                "confidence": float,      ← 0.0~1.0
                "risk_level": "LOW"|"HIGH",
                "reject_reason": str|None,
                "output": dict,
                "priority_score": float|None,
                "db_result": dict|None,
            }
        """
        model = self._select_model(context)
        user_message = self._build_user_message(context)

        start = time.monotonic()
        error_msg = None
        tokens = 0
        result = None

        # ── 1. Think — Retry/Fallback 포함 ───────────────────────────────────
        current_model = model
        last_error = None

        while current_model:
            success = False
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    resp = _client.messages.create(
                        model=current_model,
                        max_tokens=2048,
                        system=self.system_prompt,
                        messages=[{"role": "user", "content": user_message}],
                    )
                    response_text = resp.content[0].text
                    tokens = resp.usage.input_tokens + resp.usage.output_tokens
                    result = self._parse_response(response_text)
                    model = current_model   # 실제 사용된 모델 기록
                    success = True
                    break
                except anthropic.RateLimitError as e:
                    last_error = str(e)
                    time.sleep(2 ** attempt)   # exponential backoff
                except Exception as e:
                    last_error = str(e)
                    break  # 재시도 불필요한 에러는 바로 폴백

            if success:
                break

            # 폴백 시도
            next_model = FALLBACK_MODELS.get(current_model)
            if next_model:
                current_model = next_model
            else:
                break   # 더 내려갈 모델 없음

        if result is None:
            error_msg = f"모든 재시도 실패: {last_error}"
            result = {
                "decision": "reject",
                "score": 0.0,
                "confidence": 0.0,
                "risk_level": "HIGH",
                "reject_reason": f"에이전트 오류: {error_msg}",
                "output": {},
            }

        elapsed_ms = int((time.monotonic() - start) * 1000)

        # ── 2. Act (DB 작업) — pass일 때만 ───────────────────────────────────
        db_result = None
        if result.get("decision") == "pass":
            try:
                db_result = self.db_action(
                    db=db,
                    target_id=target_id,
                    output=result.get("output", {}),
                    context=context,
                    company_id=company_id,
                )
            except Exception as e:
                error_msg = f"DB 작업 오류: {e}"
                result["decision"] = "reject"
                result["reject_reason"] = error_msg

        # ── 3. 로그 기록 ──────────────────────────────────────────────────────
        log = AgentLog(
            id=str(uuid.uuid4()),
            company_id=company_id,
            target_type=self.target_type,
            target_id=target_id,
            target_name=target_name,
            role=self.role,
            input_summary=json.dumps(context, ensure_ascii=False)[:2000],
            output=json.dumps(result.get("output", {}), ensure_ascii=False),
            decision=result.get("decision", "reject"),
            reject_reason=result.get("reject_reason"),
            priority_score=result.get("priority_score"),
            score=result.get("score"),
            confidence=result.get("confidence"),
            risk_level=result.get("risk_level"),
            model_used=model,
            tokens_used=tokens,
            elapsed_ms=elapsed_ms,
            status="error" if error_msg else "success",
            error_msg=error_msg,
        )
        db.add(log)
        db.commit()

        result["role"] = self.role
        result["role_label"] = ROLE_LABELS[self.role]
        result["db_result"] = db_result
        return result

    def db_action(
        self,
        db: Session,
        target_id: str,
        output: dict,
        context: dict,
        company_id: int,
    ) -> dict | None:
        """DB 작업 수행. 서브클래스에서 override. 기본: 아무것도 안 함."""
        return None

    def _build_user_message(self, context: dict) -> str:
        return (
            f"## 현재까지 수집된 정보\n\n"
            f"```json\n{json.dumps(context, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## 요청\n\n"
            f"위 정보를 바탕으로 {ROLE_LABELS[self.role]}으로서 분석을 수행하고, "
            f"반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요.\n\n"
            f"출력 형식:\n{self.output_schema}"
        )

    def _parse_response(self, text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            import re
            m = re.search(r'\{.*\}', text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group())
                except Exception:
                    pass
            return {
                "decision": "reject",
                "score": 0.0,
                "confidence": 0.0,
                "risk_level": "HIGH",
                "reject_reason": f"응답 파싱 실패: {text[:200]}",
                "output": {},
            }
