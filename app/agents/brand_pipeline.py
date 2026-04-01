"""
브랜드 관리 파이프라인 — 5단계 에이전트

사원 → 대리 → 과장 → 팀장 → 이사
"""
from app.agents.base import BaseAgent


class BrandStaff(BaseAgent):
    """사원: 브랜드 기본 정보 입력 및 초안 작성."""
    role = "staff"
    target_type = "brand"
    system_prompt = """당신은 블랜드펀치 브랜드팀 신입 사원입니다.
주어진 데이터에서 브랜드의 기본 정보를 정확하게 수집하고 정리하는 것이 임무입니다.
감상이나 판단 없이 사실 기반으로만 정보를 수집하세요."""

    output_schema = """{
  "decision": "pass",
  "output": {
    "brand_name": "브랜드명",
    "category": "브랜드 카테고리",
    "origin": "브랜드 출신/국가",
    "founded_year": "설립연도 (모르면 null)",
    "logo_exists": true,
    "description_raw": "수집된 브랜드 설명",
    "contact_info": "담당자/연락처",
    "missing_fields": ["누락 항목"]
  }
}"""


class BrandAssistant(BaseAgent):
    """대리: 브랜드 소개 문구 정리, USP 구조화."""
    role = "assistant"
    target_type = "brand"
    system_prompt = """당신은 블랜드펀치 브랜드팀 대리입니다.
수집된 브랜드 정보를 셀러와 소비자에게 매력적으로 전달할 수 있도록 구조화하는 것이 임무입니다.
- 브랜드 핵심 소개 문구 (50자 이내 슬로건)
- USP(브랜드 차별점) 3가지 이내
- 주요 타겟 소비자
- 브랜드 톤앤매너
세련되고 설득력 있게 작성하세요."""

    output_schema = """{
  "decision": "pass",
  "output": {
    "brand_slogan": "브랜드 슬로건 (50자 이내)",
    "brand_description": "정리된 브랜드 소개 (150자 이내)",
    "usp": ["차별점1", "차별점2", "차별점3"],
    "target_consumer": "주요 소비자층",
    "tone_and_manner": "브랜드 톤앤매너 (예: 프리미엄, 친근함, 전문성)",
    "key_products": ["대표 제품군1", "대표 제품군2"]
  }
}"""


class BrandManager(BaseAgent):
    """과장: 브랜드 신뢰도/시장 적합성 검토."""
    role = "manager"
    target_type = "brand"
    system_prompt = """당신은 블랜드펀치 브랜드팀 과장입니다.
이 브랜드가 공구 시장에서 실제로 통할 수 있는지 냉정하게 검토하는 것이 임무입니다.
다음을 평가하세요:
- 브랜드 신뢰도 (소비자 인지도, 온라인 평판)
- 공구/SNS 커머스 시장 적합성
- 경쟁 브랜드 대비 포지셔닝
- 잠재 리스크 (품질 이슈, CS, 가품 논란 등)
근거 있는 판단을 내리고, 부적합하면 반려하세요."""

    output_schema = """{
  "decision": "pass 또는 reject",
  "reject_reason": "반려 시에만 작성",
  "output": {
    "brand_credibility": "높음/보통/낮음",
    "credibility_reason": "신뢰도 근거",
    "market_fit": "적합/부적합/조건부",
    "market_fit_reason": "시장 적합성 근거",
    "competitive_position": "경쟁 브랜드 대비 포지셔닝",
    "risks": ["리스크1", "리스크2"],
    "review_notes": "검토 의견"
  }
}"""


class BrandLead(BaseAgent):
    """팀장: 협업 가치와 셀러 적합성 판단."""
    role = "lead"
    target_type = "brand"
    system_prompt = """당신은 블랜드펀치 브랜드팀 팀장입니다.
이 브랜드와의 협업이 블랜드펀치 비즈니스에 실질적인 가치를 줄 수 있는지 전략적으로 판단합니다.
다음을 평가하세요:
- 셀러 생태계와의 적합성 (어떤 셀러들이 이 브랜드 제품을 팔 수 있나?)
- 블랜드펀치 포트폴리오 내 시너지
- 장기 파트너십 가능성
- 독점/선점 가능성
- 예상 매출 기여도
가치가 낮으면 반려하세요."""

    output_schema = """{
  "decision": "pass 또는 reject",
  "reject_reason": "반려 시에만 작성",
  "output": {
    "collaboration_value": "높음/보통/낮음",
    "collaboration_reason": "협업 가치 근거",
    "seller_fit_types": ["적합한 셀러 타입1", "셀러 타입2"],
    "portfolio_synergy": "포트폴리오 시너지 설명",
    "exclusivity_potential": "독점/선점 가능성",
    "revenue_potential": "예상 매출 기여도 (예: 월 500만원 이상)",
    "strategy_notes": "전략 의견"
  }
}"""


class BrandDirector(BaseAgent):
    """이사: 최종 등록 승인."""
    role = "director"
    target_type = "brand"
    system_prompt = """당신은 블랜드펀치의 이사입니다.
사원부터 팀장까지의 검토 결과를 종합해 이 브랜드의 최종 등록 여부를 결정합니다.
판단 기준:
1. 브랜드 신뢰도와 시장 적합성
2. 셀러 생태계 기여도
3. 장기 파트너십 가능성
4. 리스크 대비 기회
5. 전략적 포트폴리오 가치

0~100점 우선순위 점수를 부여하고:
- 80점 이상: 즉시 승인
- 60~79점: 조건부 승인 (조건 명시)
- 60점 미만: 반려"""

    output_schema = """{
  "decision": "pass 또는 reject",
  "reject_reason": "반려 시에만 작성",
  "priority_score": 85,
  "output": {
    "final_verdict": "승인 / 조건부 승인 / 반려",
    "conditions": "조건부 승인 시 조건 (없으면 null)",
    "priority_score": 85,
    "score_breakdown": {
      "brand_credibility": 20,
      "market_fit": 20,
      "seller_ecosystem": 20,
      "partnership_potential": 20,
      "strategic_value": 20
    },
    "executive_summary": "3줄 이내 최종 의견",
    "next_action": "다음 액션 (예: 전속 계약 논의, 시범 제품 1종 공구 진행 등)"
  }
}"""
