"""
Decision Engine — 에이전트 결과를 받아 다음 액션을 결정한다.

규칙:
  - decision == "reject"  → 파이프라인 중단, rejected 상태
  - decision == "pass" AND score >= threshold  → Auto-Pass (자동 진행)
  - decision == "pass" AND score < threshold   → Human-Review 대기열에 넣고 중단
  - score 필드가 없으면 1.0 으로 취급 (하위 호환)

역할별 임계값 (THRESHOLDS):
  staff/assistant: 0.70 — 데이터 수집 단계, 관대하게
  manager/lead:    0.80 — 논리 검증
  director:        0.90 — 최종 결재, 엄격하게
"""
import json
import uuid
from datetime import datetime
from sqlalchemy.orm import Session

# 역할별 Auto-Pass 임계값
THRESHOLDS = {
    "staff":     0.70,   # 수집 단계 — 관대하게
    "assistant": 0.70,   # 구조화 단계
    "manager":   0.80,   # 수익성 검증
    "lead":      0.80,   # 전략 검토
    "director":  0.70,   # 최종 결재 — score=priority_score/100, 70점=0.70이 승인 기준
}
AUTO_PASS_THRESHOLD = 0.90   # 하위 호환용


class DecisionResult:
    """Decision Engine 판정 결과."""
    def __init__(self, action: str, reason: str = ""):
        self.action = action   # "continue" | "human_review" | "reject"
        self.reason = reason

    @property
    def should_continue(self) -> bool:
        return self.action == "continue"

    @property
    def needs_human_review(self) -> bool:
        return self.action == "human_review"

    @property
    def is_rejected(self) -> bool:
        return self.action == "reject"


def evaluate(agent_result: dict, role_key: str) -> DecisionResult:
    """
    에이전트 결과를 평가하여 다음 액션을 반환한다.

    Args:
        agent_result: BaseAgent.run() 반환 dict
        role_key: "staff" | "assistant" | "manager" | "lead" | "director"
    """
    decision = agent_result.get("decision", "reject")
    score = float(agent_result.get("score", 1.0))  # score 없으면 1.0 (하위 호환)
    threshold = THRESHOLDS.get(role_key, AUTO_PASS_THRESHOLD)

    if decision != "pass":
        return DecisionResult(
            "reject",
            agent_result.get("reject_reason", "에이전트가 반려 결정")
        )

    # Staff는 항상 자동 통과 (수집 단계)
    if role_key == "staff":
        return DecisionResult("continue", "사원 단계 — 자동 통과")

    if score >= threshold:
        return DecisionResult("continue", f"score={score:.2f} ≥ {threshold} → Auto-Pass")

    # score 부족 → 휴먼 리뷰 필요
    return DecisionResult(
        "human_review",
        f"score={score:.2f} < {threshold} → 관리자 검토 필요"
    )


def add_to_review_queue(
    db: Session,
    target_type: str,
    target_id: str,
    target_name: str,
    role_key: str,
    agent_result: dict,
    context: dict,
    company_id: int,
) -> str:
    """
    Human-Review 대기열에 항목을 추가한다.
    Returns: queue item id
    """
    from app.models.human_review_queue import HumanReviewQueue

    item = HumanReviewQueue(
        id=str(uuid.uuid4()),
        company_id=company_id,
        target_type=target_type,
        target_id=target_id,
        target_name=target_name,
        stopped_at_role=role_key,
        score=float(agent_result.get("score", 0.0)),
        confidence=float(agent_result.get("confidence", 0.0)),
        context_snapshot=json.dumps(context, ensure_ascii=False)[:10000],
        status="pending",
    )
    db.add(item)
    db.commit()
    return item.id


def trigger_approved_actions(
    db: Session,
    product_id: str,
    director_result: dict,
    context: dict,
    company_id: int,
) -> dict:
    """
    이사 승인 시 자동 실행:
      1. Campaign 레코드 자동 생성 (status=planning)
      2. Proposal 초안 자동 생성 (type=DM, AI-generated)

    Returns: {"campaign_id": str, "proposal_id": str}
    """
    from app.models.campaign import Campaign
    from app.models.proposal import Proposal
    from app.models.product import Product
    from app.models.trigger_log import TriggerLog
    import datetime as dt

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return {}

    output = director_result.get("output", {})
    triggered = {}

    # ── 1. 캠페인 자동 생성 ────────────────────────────────────────────────────
    try:
        campaign_id = str(uuid.uuid4())
        today = dt.date.today()
        campaign = Campaign(
            id=campaign_id,
            company_id=company_id,
            name=f"[AI] {product.name} 공구",
            product_id=product_id,
            status="planning",
            start_date=today,
            end_date=today + dt.timedelta(days=30),
            commission_rate=product.seller_commission_rate or 0.2,
            seller_commission_rate=product.seller_commission_rate or 0.2,
            vendor_commission_rate=product.vendor_commission_rate or 0.1,
            unit_price=product.groupbuy_price or product.consumer_price or 0,
            notes=f"AI 파이프라인 자동 생성\n{output.get('next_action', '')}",
        )
        db.add(campaign)
        db.flush()
        triggered["campaign_id"] = campaign_id

        db.add(TriggerLog(
            id=str(uuid.uuid4()),
            company_id=company_id,
            source_type="product", source_id=product_id,
            trigger_type="campaign_created", target_id=campaign_id,
            status="success", result={"campaign_name": campaign.name},
        ))
    except Exception as e:
        db.add(TriggerLog(
            id=str(uuid.uuid4()),
            company_id=company_id,
            source_type="product", source_id=product_id,
            trigger_type="campaign_created",
            status="error", error_msg=str(e),
        ))

    # ── 2. 제안서 초안 자동 생성 ──────────────────────────────────────────────
    try:
        lead_out = context.get("lead_result", {})
        guideline = lead_out.get("group_buy_guideline", "")
        summary = output.get("executive_summary", "")
        next_action = output.get("next_action", "")

        proposal_body = (
            f"안녕하세요! 블렌드펀치입니다.\n\n"
            f"이번에 새로운 제품 **{product.name}**의 공구를 제안드립니다.\n\n"
            f"📦 제품 정보\n"
            f"- 브랜드: {product.brand or '-'}\n"
            f"- 소비자가: {int(product.consumer_price or 0):,}원\n"
            f"- 공구가: {int(product.groupbuy_price or product.consumer_price or 0):,}원\n\n"
            f"💡 셀러 가이드\n{guideline}\n\n"
            f"📋 제품 요약\n{summary}\n\n"
            f"🚀 다음 단계\n{next_action}\n\n"
            f"관심 있으시면 언제든 연락 주세요!"
        )

        proposal_id = str(uuid.uuid4())
        proposal = Proposal(
            id=proposal_id,
            company_id=company_id,
            product_id=product_id,
            campaign_id=triggered.get("campaign_id"),
            proposal_type="DM",
            title=f"[AI초안] {product.name} 공구 제안",
            body=proposal_body,
            ai_generated=True,
        )
        db.add(proposal)
        db.flush()
        triggered["proposal_id"] = proposal_id

        db.add(TriggerLog(
            id=str(uuid.uuid4()),
            company_id=company_id,
            source_type="product", source_id=product_id,
            trigger_type="proposal_created", target_id=proposal_id,
            status="success", result={"proposal_title": proposal.title},
        ))
    except Exception as e:
        db.add(TriggerLog(
            id=str(uuid.uuid4()),
            company_id=company_id,
            source_type="product", source_id=product_id,
            trigger_type="proposal_created",
            status="error", error_msg=str(e),
        ))

    db.commit()
    return triggered
