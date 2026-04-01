"""
Agent Memory Service — 성공 패턴 저장 & 조회.

이사(Director) 에이전트가:
  1. 새 제품 검토 시 → query_insights() 로 과거 성공 패턴 조회
  2. 승인 후 캠페인 종료 시 → save_success() 로 패턴 저장
"""
import json
import uuid
from sqlalchemy.orm import Session


def save_success(
    db: Session,
    company_id: int,
    product_id: str,
    product_name: str,
    brand_name: str,
    category: str,
    director_output: dict,
    lead_output: dict,
    manager_output: dict,
) -> None:
    """
    이사 승인 시 성공 패턴을 agent_memory에 저장한다.
    """
    from app.models.agent_memory import AgentMemory

    memory = AgentMemory(
        id=str(uuid.uuid4()),
        company_id=company_id,
        product_id=product_id,
        product_name=product_name,
        brand_name=brand_name,
        category=category,
        influencer_categories=lead_output.get("recommended_inf_categories"),
        priority_score=float(director_output.get("priority_score") or 0),
        margin_rate=float(manager_output.get("margin_rate") or 0),
        commission_rate=float(manager_output.get("seller_commission_rate") or 0),
        lesson_learned=director_output.get("executive_summary"),
    )
    db.add(memory)
    db.commit()


def query_insights(db: Session, company_id: int, limit: int = 5) -> dict:
    """
    과거 고점수 성공 패턴을 조회해서 이사가 참고할 인사이트를 반환한다.

    Returns:
        {
            "top_influencer_categories": ["요리유튜버", ...],
            "avg_margin_rate": 0.35,
            "avg_commission_rate": 0.20,
            "successful_categories": ["주방용품", ...],
            "sample_lessons": ["...", "..."],
        }
    """
    from app.models.agent_memory import AgentMemory

    records = (
        db.query(AgentMemory)
        .filter(
            AgentMemory.company_id == company_id,
            AgentMemory.priority_score >= 70,
        )
        .order_by(AgentMemory.priority_score.desc())
        .limit(limit)
        .all()
    )

    if not records:
        return {}

    # 인플루언서 카테고리 집계
    cat_counts: dict = {}
    for r in records:
        for cat in (r.influencer_categories or []):
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
    top_cats = sorted(cat_counts, key=cat_counts.get, reverse=True)[:5]

    # 평균 지표
    margins = [r.margin_rate for r in records if r.margin_rate]
    commissions = [r.commission_rate for r in records if r.commission_rate]
    avg_margin = sum(margins) / len(margins) if margins else None
    avg_commission = sum(commissions) / len(commissions) if commissions else None

    success_categories = list({r.category for r in records if r.category})
    lessons = [r.lesson_learned for r in records if r.lesson_learned][:3]

    return {
        "top_influencer_categories": top_cats,
        "avg_margin_rate": round(avg_margin, 3) if avg_margin else None,
        "avg_commission_rate": round(avg_commission, 3) if avg_commission else None,
        "successful_categories": success_categories,
        "sample_lessons": lessons,
        "data_points": len(records),
    }
