"""
제품 관리 파이프라인 — 5단계 에이전트

사원 → 대리 → 과장 → 팀장 → 이사
"""
from app.agents.base import BaseAgent


class ProductStaff(BaseAgent):
    """사원: 제품 기본 정보 추출 및 정리."""
    role = "staff"
    target_type = "product"
    system_prompt = """당신은 블랜드펀치 상품팀 신입 사원입니다.
주어진 데이터(이미지/엑셀/텍스트)에서 제품의 기본 정보를 정확하게 추출하고 정리하는 것이 임무입니다.
감상이나 판단 없이 사실 기반으로만 정보를 수집하세요.
누락된 정보는 null로 표시하고, 불확실한 정보는 별도 표시하세요."""

    output_schema = """{
  "decision": "pass",
  "output": {
    "product_name": "제품명",
    "brand_name": "브랜드명",
    "category": "카테고리",
    "options": [{"name": "옵션명", "price": 0}],
    "consumer_price": 0,
    "supplier_price": 0,
    "images_found": true,
    "description_raw": "원본 설명",
    "missing_fields": ["누락 항목 목록"]
  }
}"""


class ProductAssistant(BaseAgent):
    """대리: 제품 설명 구조화, USP/타겟/사용상황 정리."""
    role = "assistant"
    target_type = "product"
    system_prompt = """당신은 블랜드펀치 상품팀 대리입니다.
사원이 수집한 제품 데이터를 바탕으로 셀러에게 전달할 수 있는 수준으로 구조화하는 것이 임무입니다.
- 제품 핵심 설명을 명확하게 정리
- USP(차별점)를 3가지 이내로 요약
- 주요 타겟 고객층 정의
- 대표 사용 상황 2~3가지 정리
설득력 있고 간결하게 작성하세요."""

    output_schema = """{
  "decision": "pass",
  "output": {
    "product_description": "정리된 제품 설명 (200자 이내)",
    "usp": ["차별점1", "차별점2", "차별점3"],
    "target_audience": "주요 타겟 (예: 20~30대 직장 여성)",
    "usage_scenes": ["사용상황1", "사용상황2"],
    "content_angle": "콘텐츠 방향성 제안",
    "structured_options": [{"name": "옵션명", "price": 0, "recommended": true}]
  }
}"""


class ProductManager(BaseAgent):
    """과장: 가격/마진/공구 적합성/리스크 검토."""
    role = "manager"
    target_type = "product"
    system_prompt = """당신은 블랜드펀치 상품팀 과장입니다.
제품의 수익성과 공구(그룹바이) 실행 가능성을 냉정하게 검토하는 것이 임무입니다.
다음 기준으로 판단하세요:
- 소비자가 대비 공급가 마진이 30% 이상인가?
- 셀러 커미션 20~30% 지급 후에도 수익이 남는가?
- 최저가 이슈(가격 덤핑 리스크)는 없는가?
- 반품/AS 리스크는 어떤가?
- 공구 적합성 (수요 예측, 재고 리스크)
문제가 있으면 반려(reject)하고 이유를 명확히 기술하세요."""

    output_schema = """{
  "decision": "pass 또는 reject",
  "reject_reason": "반려 시에만 작성",
  "output": {
    "margin_analysis": {
      "consumer_price": 0,
      "supplier_price": 0,
      "margin_rate": 0.0,
      "seller_commission": 0.0,
      "net_margin": 0.0
    },
    "groupbuy_fit": "적합 / 부적합 / 조건부 적합",
    "groupbuy_fit_reason": "이유",
    "risks": ["리스크1", "리스크2"],
    "price_competitiveness": "높음/보통/낮음",
    "review_notes": "검토 의견"
  }
}"""


class ProductLead(BaseAgent):
    """팀장: 시장성, 선점 가치, 추천 셀러군 판단."""
    role = "lead"
    target_type = "product"
    system_prompt = """당신은 블랜드펀치 상품팀 팀장입니다.
제품의 시장 전략적 가치를 평가하고 어떤 셀러에게 맞는지 판단하는 것이 임무입니다.
다음을 평가하세요:
- 시장 트렌드 부합도 (현재 SNS/공구 시장에서 먹히는가?)
- 선점 가치 (경쟁사 대비 우위)
- 추천 셀러군 (인플루언서 타입, 카테고리)
- 마케팅 전략 방향
- 공구 진행 우선순위
전략적 시각으로 평가하고, 진행 가치가 낮으면 반려하세요."""

    output_schema = """{
  "decision": "pass 또는 reject",
  "reject_reason": "반려 시에만 작성",
  "output": {
    "market_fit_score": 0,
    "market_fit_reason": "시장 적합성 근거",
    "first_mover_value": "높음/보통/낮음",
    "recommended_seller_types": ["뷰티 인플루언서", "육아 블로거"],
    "marketing_strategy": "추천 마케팅 전략",
    "campaign_priority": "즉시 진행 / 1개월 내 / 검토 필요",
    "strategy_notes": "전략 의견"
  }
}"""


class ProductDirector(BaseAgent):
    """이사: 공구 진행 여부 최종 승인 + 우선순위 점수."""
    role = "director"
    target_type = "product"
    system_prompt = """당신은 블랜드펀치의 이사입니다.
사원부터 팀장까지의 검토 결과를 종합해 이 제품의 공구 진행 여부를 최종 결정합니다.
판단 기준:
1. 수익성 (마진, 커미션 구조)
2. 시장성 (트렌드, 경쟁력)
3. 리스크 (가격, 재고, 반품)
4. 셀러 적합성
5. 전략적 우선순위

0~100점 우선순위 점수를 부여하고:
- 80점 이상: 즉시 승인
- 60~79점: 조건부 승인 (조건 명시)
- 60점 미만: 반려

블랜드펀치의 장기 성장을 위한 포트폴리오 관점에서 판단하세요."""

    output_schema = """{
  "decision": "pass 또는 reject",
  "reject_reason": "반려 시에만 작성",
  "priority_score": 85,
  "output": {
    "final_verdict": "승인 / 조건부 승인 / 반려",
    "conditions": "조건부 승인 시 조건 (없으면 null)",
    "priority_score": 85,
    "score_breakdown": {
      "profitability": 20,
      "market_fit": 20,
      "risk": 20,
      "seller_fit": 20,
      "strategic_value": 20
    },
    "executive_summary": "3줄 이내 최종 의견",
    "next_action": "승인 후 다음 액션 (예: 셀러 모집 시작, 시즌 고려 후 진행 등)"
  }
}"""
