"""
제품 생성 파이프라인 — 5단계 에이전트 (실행형)

기존 product_pipeline.py가 "평가"라면,
이 파일은 실제 DB에 데이터를 생성/수정하는 "업무 수행" 파이프라인이다.

사원:  데이터 추출 → Brand 생성 + Product INSERT
대리:  구조화     → Product UPDATE (설명/USP/타겟)
과장:  가격 검토  → Product UPDATE (가격/마진/리스크)
팀장:  전략 수립  → Product UPDATE (콘텐츠 방향/셀러군)
이사:  최종 승인  → Product UPDATE (status=active, priority_score)
"""
import uuid
from sqlalchemy.orm import Session
from app.agents.base import BaseAgent


# ─────────────────────────────────────────────────────────────────────────────
# 사원: 데이터 추출 + Brand/Product DB INSERT
# ─────────────────────────────────────────────────────────────────────────────
class CreatorStaff(BaseAgent):
    role = "staff"
    target_type = "product"
    system_prompt = """당신은 블랜드펀치 상품팀 사원입니다.
주어진 데이터(이미지/엑셀/텍스트)에서 제품 등록에 필요한 기본 정보를 추출하는 것이 임무입니다.
- 정확한 사실만 추출하세요. 없는 정보는 null로 표시하세요.
- 가격은 숫자만, 단위 제외
- 브랜드명이 없으면 "미분류"로 설정"""

    output_schema = """{
  "decision": "pass",
  "score": 1.0,
  "confidence": 0.95,
  "risk_level": "LOW",
  "output": {
    "product_name": "제품명 (input_text에서 추출, 필수)",
    "brand_name": "브랜드명 (없으면 '미분류')",
    "category": "카테고리 (예: 주방용품, 뷰티, 식품, 가전)",
    "consumer_price": 39000,
    "supplier_price": 15000,
    "options": [],
    "description_raw": "input_text의 특징/설명 그대로",
    "image_info": "이미지에서 추출한 정보 (이미지 없으면 null)",
    "missing_fields": []
  }
}

중요: decision은 반드시 "pass"만 사용하세요. 사원은 수집만 하며 거절하지 않습니다."""

    def _build_user_message(self, context: dict) -> str:
        """입력 데이터를 직접 노출해서 Claude가 쉽게 읽도록."""
        input_text = context.get("input_text", "")
        image_data = context.get("inputs", {}).get("image", {}).get("data", {})
        excel_data = context.get("inputs", {}).get("excel", {}).get("data", {})

        parts = []
        if input_text:
            parts.append(f"[텍스트 입력]\n{input_text}")
        if image_data:
            import json as _json
            parts.append(f"[이미지 추출 정보]\n{_json.dumps(image_data, ensure_ascii=False)}")
        if excel_data:
            import json as _json
            parts.append(f"[엑셀 데이터]\n{_json.dumps(excel_data, ensure_ascii=False)}")

        raw = "\n\n".join(parts) if parts else "데이터 없음"

        return (
            f"## 제품 원본 데이터\n\n{raw}\n\n"
            f"## 지시\n위 데이터를 분석해 아래 JSON 형식으로만 응답하세요. "
            f"다른 텍스트 없이 JSON만 출력하세요.\n\n{self.output_schema}"
        )

    def _parse_response(self, text: str) -> dict:
        """사원은 항상 pass — decision 강제 보정."""
        result = super()._parse_response(text)
        result["decision"] = "pass"   # 사원은 거절 없음
        return result

    def db_action(self, db: Session, target_id: str, output: dict,
                  context: dict, company_id: int) -> dict:
        """
        1. 브랜드 없으면 자동 생성
        2. 제품 INSERT (review_status=ai_draft)
        target_id는 이 단계에서 실제 product.id가 된다.
        """
        from app.models.brand import Brand
        from app.models.product import Product

        brand_name = output.get("brand_name") or "미분류"

        # 브랜드 조회 or 생성
        brand = (
            db.query(Brand)
            .filter(Brand.name == brand_name, Brand.company_id == company_id)
            .first()
        )
        brand_created = False
        if not brand:
            brand = Brand(
                id=str(uuid.uuid4()),
                name=brand_name,
                company_id=company_id,
                description=f"AI가 자동 생성한 브랜드 ({brand_name})",
            )
            db.add(brand)
            db.flush()
            brand_created = True

        # 제품 조회 (이미 있으면 update, 없으면 insert)
        product = db.query(Product).filter(Product.id == target_id).first()
        if product:
            # 기존 제품 업데이트
            product.name = output.get("product_name") or product.name
            product.brand = brand_name
            product.category = output.get("category") or product.category or "기타"
            if output.get("consumer_price"):
                product.consumer_price = float(output["consumer_price"])
            if output.get("supplier_price"):
                product.supplier_price = float(output["supplier_price"])
            product.review_status = "ai_draft"
        else:
            # 새 제품 생성 (target_id를 그대로 사용)
            product = Product(
                id=target_id,
                company_id=company_id,
                name=output.get("product_name") or "신규 제품",
                brand=brand_name,
                category=output.get("category") or "기타",
                consumer_price=float(output.get("consumer_price") or 0),
                supplier_price=float(output.get("supplier_price") or 0),
                status="draft",
                review_status="ai_draft",
            )
            db.add(product)

        db.commit()
        return {
            "brand_created": brand_created,
            "brand_name": brand_name,
            "product_id": target_id,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 대리: 구조화 + Product UPDATE (설명/USP/타겟/사용상황)
# ─────────────────────────────────────────────────────────────────────────────
class CreatorAssistant(BaseAgent):
    role = "assistant"
    target_type = "product"
    system_prompt = """당신은 블랜드펀치 상품팀 대리입니다.
사원이 추출한 제품 데이터를 셀러와 소비자에게 매력적으로 전달할 수 있도록 구조화하는 것이 임무입니다.
- 제품 설명: 200자 이내, 핵심 가치 중심
- USP: 실제 차별점 3가지 (과장 금지)
- 타겟: 구체적인 소비자군 (나이/성별/라이프스타일)
- 사용상황: 실제 사용 장면 2~3가지"""

    output_schema = """{
  "decision": "pass 또는 reject",
  "score": 0.85,
  "confidence": 0.90,
  "risk_level": "LOW",
  "reject_reason": "반려 시에만 작성",
  "output": {
    "description": "정리된 제품 설명 (200자 이내)",
    "unique_selling_point": "핵심 USP 한 줄 요약",
    "usp_list": ["차별점1", "차별점2", "차별점3"],
    "target_audience": "주요 타겟 (예: 30대 요리 좋아하는 주부)",
    "usage_scenes": "대표 사용 상황 (줄바꿈으로 구분)",
    "content_angle": "콘텐츠 제작 방향성",
    "key_benefits": ["혜택1", "혜택2", "혜택3"]
  }
}

score 기준: 설명 완성도(0~0.4) + 타겟 명확성(0~0.3) + USP 차별성(0~0.3)"""

    def db_action(self, db: Session, target_id: str, output: dict,
                  context: dict, company_id: int) -> dict:
        from app.models.product import Product
        product = db.query(Product).filter(Product.id == target_id).first()
        if not product:
            return {}

        product.description        = output.get("description") or product.description
        product.unique_selling_point = output.get("unique_selling_point") or product.unique_selling_point
        product.target_audience    = output.get("target_audience") or product.target_audience
        product.usage_scenes       = output.get("usage_scenes") or product.usage_scenes
        product.content_angle      = output.get("content_angle") or product.content_angle
        if output.get("key_benefits"):
            product.key_benefits   = output["key_benefits"]
        product.review_status      = "structured"
        db.commit()
        return {"updated_fields": ["description", "usp", "target", "usage_scenes"]}


# ─────────────────────────────────────────────────────────────────────────────
# 과장: 가격/마진 검토 + Product UPDATE (가격 구조 보완)
# ─────────────────────────────────────────────────────────────────────────────
class CreatorManager(BaseAgent):
    role = "manager"
    target_type = "product"
    system_prompt = """당신은 블랜드펀치 상품팀 과장입니다.
제품의 수익 구조를 분석하고 공구 진행 가능 여부를 판단하는 것이 임무입니다.
판단 기준:
- 소비자가 대비 공급가 마진 30% 이상 → pass
- 셀러 커미션 20% 지급 후 순마진 10% 이상 → pass
- 최저가 이슈나 AS 리스크가 심각하면 → reject
groupbuy_price가 없으면 소비자가의 85%로 추천하세요."""

    output_schema = """{
  "decision": "pass 또는 reject",
  "score": 0.85,
  "confidence": 0.90,
  "risk_level": "LOW 또는 HIGH",
  "reject_reason": "반려 시에만 작성",
  "output": {
    "consumer_price": 0,
    "supplier_price": 0,
    "groupbuy_price": 0,
    "lowest_price": 0,
    "seller_commission_rate": 0.2,
    "vendor_commission_rate": 0.1,
    "margin_rate": 0.35,
    "net_margin_rate": 0.15,
    "groupbuy_fit": "적합 / 조건부 적합 / 부적합",
    "risks": ["리스크1", "리스크2"],
    "price_note": "가격 관련 특이사항"
  }
}

score 기준: 마진율(0~0.4) + 가격경쟁력(0~0.3) + 리스크(0~0.3)
risk_level: 마진 10% 미만이거나 심각한 AS 리스크 → HIGH, 그 외 → LOW"""

    def db_action(self, db: Session, target_id: str, output: dict,
                  context: dict, company_id: int) -> dict:
        from app.models.product import Product
        product = db.query(Product).filter(Product.id == target_id).first()
        if not product:
            return {}

        if output.get("consumer_price"):
            product.consumer_price = float(output["consumer_price"])
        if output.get("supplier_price"):
            product.supplier_price = float(output["supplier_price"])
        if output.get("groupbuy_price"):
            product.groupbuy_price = float(output["groupbuy_price"])
        if output.get("lowest_price"):
            product.lowest_price = float(output["lowest_price"])
        if output.get("seller_commission_rate"):
            product.seller_commission_rate = float(output["seller_commission_rate"])
        if output.get("vendor_commission_rate"):
            product.vendor_commission_rate = float(output["vendor_commission_rate"])

        product.review_status = "reviewed"
        db.commit()
        return {"updated_fields": ["pricing", "commission_rates"]}


# ─────────────────────────────────────────────────────────────────────────────
# 팀장: 전략 수립 + Product UPDATE (카테고리/공구 가이드/추천 셀러군)
# ─────────────────────────────────────────────────────────────────────────────
class CreatorLead(BaseAgent):
    role = "lead"
    target_type = "product"
    system_prompt = """당신은 블랜드펀치 상품팀 팀장입니다.
제품의 시장 전략을 수립하고 어떤 셀러에게 맞는지 판단하는 것이 임무입니다.
- 추천 카테고리 태그: 소비자가 검색할 키워드 3~5개
- 공구 가이드: 셀러에게 전달할 공구 진행 안내문 (간결하게)
- 추천 셀러 카테고리: 인스타그램/유튜브/블로그 중 어떤 타입이 잘 팔지
전략적 가치가 낮으면 reject하세요."""

    output_schema = """{
  "decision": "pass 또는 reject",
  "score": 0.85,
  "confidence": 0.88,
  "risk_level": "LOW 또는 HIGH",
  "reject_reason": "반려 시에만 작성",
  "output": {
    "categories": ["카테고리태그1", "태그2", "태그3"],
    "recommended_inf_categories": ["뷰티유튜버", "라이프스타일블로거"],
    "group_buy_guideline": "셀러용 공구 진행 가이드 (2~3줄)",
    "positioning": "시장 포지셔닝 전략",
    "campaign_priority": "즉시 진행 / 1개월 내 / 장기 검토",
    "strategy_note": "전략 메모"
  }
}

score 기준: 시장 매력도(0~0.4) + 인플루언서 매칭 가능성(0~0.3) + 전략 명확성(0~0.3)
risk_level: 시장 포화 심각 or 타겟 모호 → HIGH"""

    def db_action(self, db: Session, target_id: str, output: dict,
                  context: dict, company_id: int) -> dict:
        from app.models.product import Product
        product = db.query(Product).filter(Product.id == target_id).first()
        if not product:
            return {}

        if output.get("categories"):
            product.categories = output["categories"]
        if output.get("recommended_inf_categories"):
            product.recommended_inf_categories = output["recommended_inf_categories"]
        if output.get("group_buy_guideline"):
            product.group_buy_guideline = output["group_buy_guideline"]
        if output.get("positioning"):
            product.positioning = output["positioning"]

        product.review_status = "strategy_checked"
        db.commit()
        return {"updated_fields": ["categories", "inf_categories", "guideline", "positioning"]}


# ─────────────────────────────────────────────────────────────────────────────
# 이사: 최종 승인 + Product UPDATE (status=active, priority_score)
# ─────────────────────────────────────────────────────────────────────────────
class CreatorDirector(BaseAgent):
    role = "director"
    target_type = "product"
    system_prompt = """당신은 블랜드펀치의 이사입니다.
사원부터 팀장까지의 작업 결과를 종합해 이 제품의 공구 진행 여부를 최종 결정합니다.
판단 기준: 수익성(30점) + 시장성(30점) + 리스크(20점) + 전략적 가치(20점) = 100점
- 70점 이상: 승인 (status=active)
- 50~69점: 조건부 승인 (status=draft, 조건 명시)
- 49점 이하: 반려

'과거 성공 패턴(memory_insights)' 섹션이 있다면 반드시 참고해서 인플루언서 추천과 전략을 보강하세요.
블랜드펀치 포트폴리오 관점에서 냉정하게 판단하세요."""

    output_schema = """{
  "decision": "pass 또는 reject",
  "score": 0.88,
  "confidence": 0.92,
  "risk_level": "LOW 또는 HIGH",
  "priority_score": 85,
  "reject_reason": "반려 시에만 작성",
  "output": {
    "final_verdict": "승인 / 조건부 승인 / 반려",
    "product_status": "active 또는 draft",
    "priority_score": 85,
    "conditions": "조건부 승인 조건 (없으면 null)",
    "executive_summary": "3줄 이내 최종 의견",
    "next_action": "다음 액션 (예: 즉시 셀러 모집 시작)",
    "memory_applied": "참고한 과거 성공 패턴 요약 (없으면 null)"
  }
}

score = priority_score / 100  (예: priority_score 85 → score 0.85)"""

    def _build_user_message(self, context: dict) -> str:
        """메모리 인사이트를 컨텍스트에 포함시킨다."""
        import json as _json
        from app.agents.memory_service import query_insights
        # context에 db 없으므로 memory는 runner가 사전 주입
        # (runner.py에서 context["memory_insights"]를 미리 넣어준다)
        return super()._build_user_message(context)

    def db_action(self, db: Session, target_id: str, output: dict,
                  context: dict, company_id: int) -> dict:
        from app.models.product import Product
        from app.agents.decision_engine import trigger_approved_actions
        from app.agents.memory_service import save_success

        product = db.query(Product).filter(Product.id == target_id).first()
        if not product:
            return {}

        product.status         = output.get("product_status") or "draft"
        product.review_status  = "approved"
        product.priority_score = float(output.get("priority_score") or 0)

        # 데이터 완성도 체크
        required = ["name", "brand", "category", "description",
                    "consumer_price", "target_audience"]
        missing = [f for f in required if not getattr(product, f, None)]
        product.is_complete    = len(missing) == 0
        product.missing_fields = missing or None
        db.commit()

        # ── Auto-Trigger: 캠페인 + 제안서 자동 생성 ──────────────────────────
        triggered = trigger_approved_actions(
            db=db,
            product_id=target_id,
            director_result={"output": output},
            context=context,
            company_id=company_id,
        )

        # ── Memory 저장: 성공 패턴 기록 ──────────────────────────────────────
        try:
            save_success(
                db=db,
                company_id=company_id,
                product_id=target_id,
                product_name=product.name,
                brand_name=product.brand or "",
                category=product.category or "",
                director_output=output,
                lead_output=context.get("lead_result", {}),
                manager_output=context.get("manager_result", {}),
            )
        except Exception:
            pass  # 메모리 저장 실패가 파이프라인을 막으면 안 됨

        return {
            "product_status": product.status,
            "priority_score": product.priority_score,
            "is_complete": product.is_complete,
            "triggered": triggered,
        }
