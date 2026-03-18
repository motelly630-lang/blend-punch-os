"""
AI Product Registration Assistant — Action JSON Protocol
모든 응답은 {reply, actions[]} 형식으로 강제된다.
단순 텍스트 응답 금지 — 반드시 액션 배열 포함.
"""
import json
import re
import asyncio
import base64
from fastapi import APIRouter, Form, UploadFile, File, Depends
from fastapi.responses import JSONResponse
from app.ai.client import ClaudeClient
from app.ai.web_scraper import fetch_page
from app.config import settings
from app.auth.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/ai")

# ─────────────────────────────────────────────────────────────────────────────
# Action Protocol System Prompt
# ─────────────────────────────────────────────────────────────────────────────
_SYSTEM = """너는 공동구매 플랫폼 'BLEND PUNCH'의 제품 등록 AI 오퍼레이터다.
사용자의 입력(텍스트/URL/이미지/엑셀)을 분석하고, 즉시 액션을 실행하여 폼 필드를 채운다.

[페르소나 규칙]
- "~할 수 있습니다" "~해드릴게요" 금지
- 반드시 완료형으로: "~를 완료했습니다. 좌측 폼을 확인하세요."
- 수정 요청은 "~를 수정했습니다."
- 불확실한 정보는 반드시 warning 액션 포함

[상품 타입]
A(수량형): 동일 상품 수량별 판매 (1팩/2팩/3팩, 1개월/3개월분)
B(옵션형): 색상·사이즈·용량 등 속성 차이 (S/M/L, 블랙/화이트, 200ml/400ml)
C(세트형): 구성품이 다른 세트 구분 (A세트=제품+파우치, B세트=제품+케이스)
D(혼합형): 단품+세트+사은품+추가상품 복합 구조

[반환 형식 — 반드시 준수]
유효한 JSON 오브젝트, 마크다운 코드블록 없이 순수 JSON만:
{
  "reply": "완료형 메시지 (예: '제품 정보 분석을 완료했습니다. 좌측 폼을 확인하세요.')",
  "actions": [
    액션 배열 (아래 타입 중 필요한 것 모두 포함)
  ],
  "confidence": 0.0~1.0
}

[액션 타입 — 정확히 이 형식만 허용]

1. 상품 타입 설정:
{"type": "set_product_type", "data": "A"}
data: "A"|"B"|"C"|"D"

2. 단일 필드 업데이트:
{"type": "set_field", "data": {"field": "name", "value": "제품명"}}
사용 가능한 field명: name / brand / category / description / internal_notes / source_url / positioning / group_buy_guideline
category는 반드시: 건강기능식품/스킨케어/뷰티·메이크업/헤어케어/바디케어/다이어트·슬리밍/식품·음료/생활용품/주방용품/가전제품/패션·의류/패션잡화/홈·인테리어/유아·육아/반려동물/스포츠·레저/전자기기/욕실용품/기타 중 하나

3. 가격 구조 업데이트:
{"type": "update_price", "data": {"consumer_price": 50000, "groupbuy_price": 35000, "discount_rate": 30, "lowest_price": 32000, "supplier_price": 20000, "seller_commission_rate": 15, "vendor_commission_rate": 10, "recommended_commission_rate": 15}}
- 포함하지 않을 필드는 생략 (null 사용 금지, 아예 키 제거)
- 숫자 필드에 단위 문자 금지 (순수 숫자만)
- rate 필드: 0~100 정수

4. 마케팅 정보 업데이트:
{"type": "update_marketing", "data": {"usp": "핵심 차별점 한 문장", "key_benefits": "혜택1\n혜택2\n혜택3", "content_angle": "콘텐츠 앵글", "positioning": "포지셔닝 전략"}}
- 포함하지 않을 키는 생략
- key_benefits: 줄바꿈(\\n)으로 구분된 단일 문자열

5. 배송·물류 업데이트:
{"type": "update_shipping", "data": {"shipping_type": "무료배송", "dispatch_days": "1~2일", "carrier": "CJ대한통운", "shipping_cost": 0}}
- shipping_type: "무료배송"|"유료배송"
- dispatch_days: "당일"|"1~2일"|"3~5일"|"주문제작"

6. 옵션/세트 생성:
{"type": "create_options", "data": [{"name": "A세트", "price": 45000, "notes": "메모", "components": [{"item_name": "품목명", "option": "옵션", "qty": 1}]}]}

7. 경고 (데이터 불확실 시 필수):
{"type": "warning", "data": {"message": "이미지가 불선명하여 가격 정보가 불확실합니다. 직접 확인이 필요합니다.", "fields": ["consumer_price", "groupbuy_price"]}}

[데이터 무결성 규칙]
- 단순 텍스트 응답 절대 금지 — actions 배열은 항상 하나 이상 포함
- confidence 0.7 미만이면 반드시 warning 액션 추가
- 이미지가 흐릿하거나 정보가 부족하면 warning 추가
- 숫자 필드는 순수 숫자만 (단위 문자, 콤마, 공백 금지)
- 할인율 자동 계산: consumer_price와 groupbuy_price가 있으면 discount_rate = round((consumer_price - groupbuy_price) / consumer_price * 100)"""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e != -1:
        try:
            return json.loads(text[s:e + 1])
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except Exception:
        return {}


def _err_response(reply: str) -> dict:
    return {
        "reply": reply,
        "actions": [{"type": "warning", "data": {"message": reply, "fields": []}}],
        "confidence": 0.0,
    }


_VALID_ACTION_TYPES = {
    "set_product_type", "set_field", "update_price",
    "update_marketing", "update_shipping", "create_options", "warning",
}

_VALID_SET_FIELD_NAMES = {
    "name", "brand", "category", "description", "internal_notes",
    "source_url", "positioning", "group_buy_guideline",
}

_VALID_PRICE_KEYS = {
    "consumer_price", "groupbuy_price", "discount_rate", "lowest_price",
    "supplier_price", "seller_commission_rate", "vendor_commission_rate",
    "recommended_commission_rate",
}

_VALID_MARKETING_KEYS = {"usp", "key_benefits", "content_angle", "positioning"}

_VALID_SHIPPING_KEYS = {"shipping_type", "shipping_cost", "carrier", "dispatch_days"}


def _validate_actions(actions: list) -> list[dict]:
    """Clean and validate actions array. Strips invalid types/keys."""
    if not isinstance(actions, list):
        return []

    cleaned = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        t = action.get("type")
        data = action.get("data")

        if t not in _VALID_ACTION_TYPES:
            continue

        if t == "set_product_type":
            if data not in ("A", "B", "C", "D"):
                continue

        elif t == "set_field":
            if not isinstance(data, dict):
                continue
            field = data.get("field")
            if field not in _VALID_SET_FIELD_NAMES:
                continue
            value = data.get("value")
            if value is None:
                continue

        elif t == "update_price":
            if not isinstance(data, dict):
                continue
            # Keep only valid keys, coerce to numbers
            clean_data = {}
            for k in _VALID_PRICE_KEYS:
                v = data.get(k)
                if v is not None:
                    try:
                        v = float(str(v).replace(",", "").replace("원", "").replace("%", "").strip())
                        clean_data[k] = int(v) if k != "discount_rate" else round(v)
                    except (ValueError, TypeError):
                        pass
            if not clean_data:
                continue
            # Auto-calculate discount_rate if missing
            cp = clean_data.get("consumer_price")
            gp = clean_data.get("groupbuy_price")
            if cp and gp and cp > 0 and "discount_rate" not in clean_data:
                clean_data["discount_rate"] = round((cp - gp) / cp * 100)
            action = {"type": "update_price", "data": clean_data}

        elif t == "update_marketing":
            if not isinstance(data, dict):
                continue
            clean_data = {k: v for k, v in data.items() if k in _VALID_MARKETING_KEYS and v}
            if not clean_data:
                continue
            # Normalize key_benefits to newline-separated string
            if "key_benefits" in clean_data:
                kb = clean_data["key_benefits"]
                if isinstance(kb, list):
                    clean_data["key_benefits"] = "\n".join(str(b) for b in kb)
            action = {"type": "update_marketing", "data": clean_data}

        elif t == "update_shipping":
            if not isinstance(data, dict):
                continue
            clean_data = {k: v for k, v in data.items() if k in _VALID_SHIPPING_KEYS and v is not None}
            if not clean_data:
                continue
            action = {"type": "update_shipping", "data": clean_data}

        elif t == "create_options":
            if not isinstance(data, list):
                continue
            clean_opts = []
            for opt in data:
                if isinstance(opt, dict):
                    clean_opts.append({
                        "name": str(opt.get("name", "")),
                        "price": int(float(str(opt.get("price", 0)).replace(",", "") or 0)),
                        "notes": str(opt.get("notes", "")),
                        "components": [
                            {"item_name": str(c.get("item_name", "")),
                             "option": str(c.get("option", "")),
                             "qty": int(c.get("qty", 1))}
                            for c in (opt.get("components") or []) if isinstance(c, dict)
                        ],
                    })
            if not clean_opts:
                continue
            action = {"type": "create_options", "data": clean_opts}

        elif t == "warning":
            if not isinstance(data, dict):
                action = {"type": "warning", "data": {"message": str(data), "fields": []}}
            else:
                action = {"type": "warning", "data": {
                    "message": str(data.get("message", "데이터를 확인해주세요.")),
                    "fields": data.get("fields") if isinstance(data.get("fields"), list) else [],
                }}

        cleaned.append(action)
    return cleaned


def _build_messages(history: list, user_content: str) -> list:
    msgs = []
    for h in history[-8:]:
        if h.get("role") in ("user", "assistant"):
            msgs.append({"role": h["role"], "content": h["content"]})
    msgs.append({"role": "user", "content": user_content})
    return msgs


async def _call_claude(messages: list, system: str) -> dict:
    claude = ClaudeClient()
    response = await asyncio.to_thread(
        lambda: claude.client.messages.create(
            model=claude.model,
            max_tokens=4096,
            system=system + "\n\n[CRITICAL] 반드시 유효한 JSON 오브젝트만 출력. 배열 금지. 마크다운 없이 순수 JSON만. actions 배열 반드시 포함.",
            messages=messages,
        )
    )
    return _extract_json(response.content[0].text)


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI Function (Tool) Definitions
# ─────────────────────────────────────────────────────────────────────────────
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_sets",
            "description": (
                "상품 분석 결과에 따라 최적의 세트 구성을 화면에 직접 생성한다. "
                "반드시 A(체험/입문), B(주력/표준), C(대량/프리미엄) 3개 세트를 포함해야 한다. "
                "이 함수를 호출하면 사용자의 화면에 세트 UI가 즉시 렌더링된다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reply": {
                        "type": "string",
                        "description": "세트 구성 설명 및 전략 요약 메시지"
                    },
                    "sets": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "세트 명칭 (예: A세트 - 입문자용 체험팩)"},
                                "price": {"type": "number", "description": "전략적 할인가 (숫자만, 단위 없음)"},
                                "notes": {"type": "string", "description": "세트 전략/설명 메모"},
                                "components": {
                                    "type": "array",
                                    "description": "구성품 리스트",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "item_name": {"type": "string", "description": "품목명"},
                                            "option": {"type": "string", "description": "옵션/사양"},
                                            "qty": {"type": "integer", "description": "수량"}
                                        },
                                        "required": ["item_name", "qty"]
                                    }
                                }
                            },
                            "required": ["name", "price", "components"]
                        }
                    }
                },
                "required": ["sets", "reply"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "시장 조사, 경쟁사 세트 구성/가격 분석, 소비자 트렌드 파악을 위해 웹 검색을 수행한다. "
                "모르는 정보는 추측하지 말고 반드시 이 도구로 먼저 검색하라."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "검색 쿼리 (한국어 가능)"}
                },
                "required": ["query"]
            }
        }
    }
]

_SYSTEM_TOOLS_ADDON = """
[추가 지침: Function Calling & 외부 지식 활용]
- 세트/옵션 구성 요청 시: 반드시 create_sets 함수를 호출하라. 텍스트로만 답하는 것은 금지.
- 시장 데이터가 불확실하면: web_search 도구로 경쟁사 가격·구성을 먼저 조사한 뒤 create_sets를 호출하라.
- 세트 설계 기준: A(체험/소량/낮은 가격) → B(주력/표준/중간) → C(대량/프리미엄/높은 가격)
- create_sets 호출 시 reply 필드에 전략 요약을 반드시 포함하라.
"""


async def _do_web_search(query: str) -> str:
    """DuckDuckGo HTML 검색으로 상위 결과 텍스트 반환."""
    import urllib.parse
    search_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    try:
        raw = await asyncio.to_thread(fetch_page, search_url, 3000)
        return raw[:2500] if raw else "검색 결과 없음"
    except Exception as ex:
        return f"검색 실패: {ex}"


async def _call_openai_agentic(messages: list, system: str) -> dict:
    """
    OpenAI Function Calling 에이전트 루프.
    - web_search 호출 → 결과 주입 → 재호출 (최대 3회)
    - create_sets 호출 → create_options 액션으로 변환해서 반환
    - 일반 JSON 응답 → 기존 방식 그대로
    """
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    full_msgs = [
        {"role": "system", "content": system + _SYSTEM_TOOLS_ADDON}
    ] + messages

    for _loop in range(4):  # 최대 4번 (web_search 최대 3회 + 최종 응답 1회)
        response = await client.chat.completions.create(
            model="gpt-4o",
            max_tokens=4096,
            tools=_TOOLS,
            tool_choice="auto",
            messages=full_msgs,
        )
        choice = response.choices[0]
        msg = choice.message

        # ── 툴 호출이 있을 경우 ────────────────────────────────────────────
        if msg.tool_calls:
            # assistant 메시지 기록
            full_msgs.append({"role": "assistant", "content": msg.content, "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]})

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments)
                except Exception:
                    fn_args = {}

                if fn_name == "web_search":
                    query = fn_args.get("query", "")
                    search_result = await _do_web_search(query)
                    full_msgs.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": search_result,
                    })
                    # 루프 계속 → AI가 검색 결과 보고 create_sets 호출

                elif fn_name == "create_sets":
                    sets_data = fn_args.get("sets", [])
                    reply_text = fn_args.get("reply", "세트 구성을 완료했습니다. 좌측 폼을 확인하세요.")
                    # create_options 액션 형식으로 변환
                    clean_sets = []
                    for s in sets_data:
                        clean_sets.append({
                            "name": str(s.get("name", "")),
                            "price": int(float(str(s.get("price", 0)).replace(",", "") or 0)),
                            "notes": str(s.get("notes", "")),
                            "components": [
                                {
                                    "item_name": str(c.get("item_name", "")),
                                    "option": str(c.get("option", "")),
                                    "qty": int(c.get("qty", 1)),
                                }
                                for c in (s.get("components") or []) if isinstance(c, dict)
                            ],
                        })
                    return {
                        "reply": reply_text,
                        "actions": [{"type": "create_options", "data": clean_sets}],
                        "confidence": 0.95,
                    }

        else:
            # ── 일반 텍스트/JSON 응답 ────────────────────────────────────
            content = msg.content or ""
            result = _extract_json(content)
            if result:
                return result
            # JSON 파싱 실패 시 reply만 담아서 반환
            return {
                "reply": content or "분석을 완료했습니다.",
                "actions": [],
                "confidence": 1.0,
            }

    return {"reply": "처리 중 오류가 발생했습니다. 다시 시도해주세요.", "actions": [], "confidence": 0.0}


async def _call_openai(messages: list, system: str) -> dict:
    """일반 JSON 응답 전용 (이미지/엑셀 분석용)."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    full_msgs = [{"role": "system", "content": system + "\n\n[CRITICAL] 반드시 유효한 JSON 오브젝트만 출력. 배열 금지. 마크다운 없이 순수 JSON만. actions 배열 반드시 포함."}] + messages
    response = await client.chat.completions.create(
        model="gpt-4o",
        max_tokens=4096,
        response_format={"type": "json_object"},
        messages=full_msgs,
    )
    return _extract_json(response.choices[0].message.content)


async def _call_openai_vision(image_b64: str, media_type: str, text: str, system: str) -> dict:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model="gpt-4o",
        max_tokens=4096,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system + "\n\n[CRITICAL] 반드시 유효한 JSON 오브젝트만 출력. actions 배열 반드시 포함."},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_b64}"}},
                {"type": "text", "text": text},
            ]},
        ],
    )
    return _extract_json(response.choices[0].message.content)


async def _call_ai(messages: list, system: str) -> dict:
    """OpenAI 에이전트 루프 우선, 없으면 Claude 폴백."""
    if settings.openai_api_key:
        return await _call_openai_agentic(messages, system)
    return await _call_claude(messages, system)


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/product-chat")
async def product_chat(
    message: str = Form(...),
    context_json: str = Form("{}"),
    history_json: str = Form("[]"),
    current_user: User = Depends(get_current_user),
):
    if not settings.anthropic_api_key:
        return JSONResponse(_err_response("AI 기능을 사용하려면 Anthropic API 키가 필요합니다."))

    try:
        history = json.loads(history_json) if history_json else []
        context = json.loads(context_json) if context_json else {}
    except Exception:
        history, context = [], {}

    # Auto-detect and scrape URL embedded in message
    url_match = re.search(r"https?://[^\s\)\"\']+", message)
    scraped = ""
    scraped_url = ""
    if url_match:
        scraped_url = url_match.group().rstrip(".,)")
        try:
            scraped = await asyncio.to_thread(fetch_page, scraped_url, 5000)
        except Exception:
            pass

    user_content = message
    if scraped and not scraped.startswith("페이지 로드 실패"):
        user_content += f"\n\n[URL 페이지 내용 (발췌)]\nURL: {scraped_url}\n{scraped}"
    if context:
        user_content += f"\n\n[현재 폼 상태 — 이 값들을 기반으로 수정]\n{json.dumps(context, ensure_ascii=False, indent=2)}"

    try:
        result = await _call_ai(_build_messages(history, user_content), _SYSTEM)
    except Exception as ex:
        return JSONResponse(_err_response(f"AI 분석 오류: {ex}"))

    if not isinstance(result, dict):
        return JSONResponse(_err_response("AI 응답을 파싱할 수 없습니다. 다시 시도해주세요."))

    actions = _validate_actions(result.get("actions", []))
    confidence = float(result.get("confidence", 1.0))

    # Force at least one action even if AI misbehaved — convert patches if present
    if not actions and result.get("patches"):
        actions = _patches_to_actions(result["patches"])

    # If still empty, add a warning
    if not actions:
        actions = [{"type": "warning", "data": {"message": "분석 결과를 추출하지 못했습니다. 다시 시도해주세요.", "fields": []}}]

    return JSONResponse({
        "reply": result.get("reply", "분석을 완료했습니다. 좌측 폼을 확인하세요."),
        "actions": actions,
        "confidence": round(confidence, 2),
        "product_type": _extract_product_type(actions),
        "type_reason": result.get("type_reason"),
    })


@router.post("/product-chat-image")
async def product_chat_image(
    image: UploadFile = File(...),
    context_json: str = Form("{}"),
    current_user: User = Depends(get_current_user),
):
    """Image upload → Claude Vision OCR → Action Protocol response."""
    if not settings.anthropic_api_key:
        return JSONResponse(_err_response("AI 기능을 사용하려면 Anthropic API 키가 필요합니다."))

    try:
        image_bytes = await image.read()
        media_type = image.content_type or "image/jpeg"
        image_size_kb = len(image_bytes) / 1024
    except Exception as ex:
        return JSONResponse(_err_response(f"이미지 읽기 실패: {ex}"))

    try:
        context = json.loads(context_json) if context_json else {}
    except Exception:
        context = {}

    _img_system = (
        _SYSTEM +
        "\n\n[이미지 OCR 모드] 이미지에서 텍스트·정보를 추출하여 actions 배열로 반환하라."
        " 이미지가 흐릿하거나 텍스트가 불분명하면 반드시 confidence를 낮게 설정하고 warning 액션을 포함하라."
        " 배경 이미지나 제품 사진인 경우 보이는 정보를 최대한 추출하라."
    )
    user_text = (
        "이 이미지에서 제품 정보를 OCR로 추출하고 actions 배열로 구성해서 폼에 반영해줘. "
        "텍스트나 가격표, 제품명, 옵션 등 모든 정보를 추출해라."
    )
    if context:
        user_text += f"\n\n[현재 폼 상태]\n{json.dumps(context, ensure_ascii=False)}"

    try:
        b64 = base64.standard_b64encode(image_bytes).decode()
        if settings.openai_api_key:
            result = await _call_openai_vision(b64, media_type, user_text, _img_system)
        else:
            claude = ClaudeClient()
            response_obj = await asyncio.to_thread(
                lambda: claude.client.messages.create(
                    model=claude.model,
                    max_tokens=4096,
                    system=_img_system + "\n\n반드시 JSON 오브젝트만 출력. actions 배열 포함.",
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                            {"type": "text", "text": user_text},
                        ],
                    }],
                )
            )
            result = _extract_json(response_obj.content[0].text)
    except Exception as ex:
        return JSONResponse(_err_response(f"이미지 분석 실패: {ex}"))

    if not isinstance(result, dict):
        return JSONResponse(_err_response("이미지 분석 결과를 파싱할 수 없습니다."))

    actions = _validate_actions(result.get("actions", []))
    confidence = float(result.get("confidence", 0.8))

    # Fallback: convert patches-style response to actions
    if not actions and result.get("patches"):
        actions = _patches_to_actions(result["patches"])

    # Low-confidence images get automatic warning
    if confidence < 0.7 and not any(a["type"] == "warning" for a in actions):
        actions.append({
            "type": "warning",
            "data": {
                "message": f"이미지 분석 신뢰도가 낮습니다({int(confidence*100)}%). 추출된 값을 직접 확인해주세요.",
                "fields": [],
            }
        })

    if not actions:
        actions = [{"type": "warning", "data": {"message": "이미지에서 제품 정보를 추출하지 못했습니다. 더 선명한 이미지를 업로드해주세요.", "fields": []}}]

    return JSONResponse({
        "reply": result.get("reply", f"이미지 OCR 분석을 완료했습니다. 좌측 폼을 확인하세요."),
        "actions": actions,
        "confidence": round(confidence, 2),
        "product_type": _extract_product_type(actions),
        "type_reason": result.get("type_reason"),
    })


@router.post("/product-chat-excel")
async def product_chat_excel(
    excel_file: UploadFile = File(...),
    context_json: str = Form("{}"),
    current_user: User = Depends(get_current_user),
):
    """Parse Excel/CSV → AI extracts product data → Action Protocol response."""
    if not settings.anthropic_api_key:
        return JSONResponse(_err_response("AI 기능을 사용하려면 Anthropic API 키가 필요합니다."))

    try:
        content = await excel_file.read()
        filename = excel_file.filename or ""

        if filename.lower().endswith(".csv"):
            text_data = content.decode("utf-8-sig", errors="replace")
            table_text = "\n".join(text_data.splitlines()[:25])
        else:
            try:
                import openpyxl
                from io import BytesIO
                wb = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=True)
                ws = wb.active
                rows = []
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i >= 25:
                        break
                    rows.append("\t".join(str(c) if c is not None else "" for c in row))
                table_text = "\n".join(rows)
            except ImportError:
                return JSONResponse(_err_response("openpyxl이 설치되지 않았습니다. 'uv pip install openpyxl' 실행 후 재시도해주세요."))
    except Exception as ex:
        return JSONResponse(_err_response(f"파일 읽기 실패: {ex}"))

    try:
        context = json.loads(context_json) if context_json else {}
    except Exception:
        context = {}

    user_content = (
        f"아래 엑셀 데이터에서 제품 정보를 추출하고 actions 배열로 구성해서 폼에 반영해줘:\n\n{table_text}"
    )
    if context:
        user_content += f"\n\n[현재 폼 상태]\n{json.dumps(context, ensure_ascii=False, indent=2)}"

    try:
        result = await _call_ai([{"role": "user", "content": user_content}], _SYSTEM)
    except Exception as ex:
        return JSONResponse(_err_response(f"엑셀 분석 오류: {ex}"))

    actions = _validate_actions(result.get("actions", []))
    if not actions and result.get("patches"):
        actions = _patches_to_actions(result["patches"])
    if not actions:
        actions = [{"type": "warning", "data": {"message": "엑셀에서 제품 정보를 추출하지 못했습니다. 열 구조를 확인해주세요.", "fields": []}}]

    return JSONResponse({
        "reply": result.get("reply", "엑셀 분석을 완료했습니다. 좌측 폼을 확인하세요."),
        "actions": actions,
        "confidence": float(result.get("confidence", 1.0)),
        "product_type": _extract_product_type(actions),
        "type_reason": result.get("type_reason"),
    })


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────
def _extract_product_type(actions: list) -> str | None:
    for a in actions:
        if a.get("type") == "set_product_type":
            return a.get("data")
    return None


def _patches_to_actions(patches: dict) -> list:
    """Convert old-style patches dict to actions array (backward compat)."""
    if not isinstance(patches, dict):
        return []
    actions = []

    # set_field targets
    for field in ("name", "brand", "category", "description", "internal_notes", "source_url", "positioning", "group_buy_guideline"):
        v = patches.get(field)
        if v is not None:
            actions.append({"type": "set_field", "data": {"field": field, "value": v}})

    # pricing
    price_data = {k: patches[k] for k in _VALID_PRICE_KEYS if patches.get(k) is not None}
    if price_data:
        actions.append({"type": "update_price", "data": price_data})

    # marketing
    mkt_map = {
        "unique_selling_point": "usp",
        "key_benefits": "key_benefits",
        "content_angle": "content_angle",
        "positioning": "positioning",
    }
    mkt_data = {}
    for src, dst in mkt_map.items():
        v = patches.get(src)
        if v is not None:
            kb = v if isinstance(v, str) else "\n".join(v) if isinstance(v, list) else str(v)
            mkt_data[dst] = kb
    if mkt_data:
        actions.append({"type": "update_marketing", "data": mkt_data})

    # shipping
    shipping_data = {}
    for k in ("shipping_type", "shipping_cost", "carrier", "dispatch_days"):
        v = patches.get(k)
        if v is not None:
            shipping_data[k] = v
    if shipping_data:
        actions.append({"type": "update_shipping", "data": shipping_data})

    # options
    opts = patches.get("set_options")
    if opts and isinstance(opts, list):
        actions.append({"type": "create_options", "data": opts})

    # product type
    pt = patches.get("product_type")
    if pt in ("A", "B", "C", "D"):
        actions.insert(0, {"type": "set_product_type", "data": pt})

    return actions
