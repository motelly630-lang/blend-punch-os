"""
파이프라인 실행기

두 가지 모드:
  1. create_product_pipeline() — 이미지/엑셀/텍스트 → 브랜드+제품 생성 → 검토
  2. run_product_pipeline()    — 기존 제품 재검토 (평가 전용)
  3. run_brand_pipeline()      — 기존 브랜드 재검토
"""
import uuid
from sqlalchemy.orm import Session
from app.agents.input_processor import build_initial_context

_PASS_STATUS = {
    "staff":     "ai_draft",
    "assistant": "structured",
    "manager":   "reviewed",
    "lead":      "strategy_checked",
    "director":  "approved",
}


# ─────────────────────────────────────────────────────────────────────────────
# 신규 생성 파이프라인 (핵심)
# ─────────────────────────────────────────────────────────────────────────────

def create_product_pipeline(
    db: Session,
    company_id: int = 1,
    text: str = None,
    image_path: str = None,
    excel_path: str = None,
    product_id: str = None,   # 외부에서 지정 가능 (폴링용)
) -> dict:
    """
    이미지/엑셀/텍스트 입력 → 브랜드+제품 자동 생성 → 5단계 검토까지 완료.

    각 단계에서 실제 DB 작업(INSERT/UPDATE)을 수행한다.

    Returns:
        {
            "product_id": str,
            "final_status": str,
            "final_score": float|None,
            "steps": list,
            "rejected_at": str|None,
        }
    """
    from app.agents.product_creator import (
        CreatorStaff, CreatorAssistant, CreatorManager,
        CreatorLead, CreatorDirector,
    )

    # product_id 외부에서 받으면 그대로, 없으면 새로 생성
    if not product_id:
        product_id = str(uuid.uuid4())

    context = build_initial_context(
        text=text,
        image_path=image_path,
        excel_path=excel_path,
    )
    context["product_id"] = product_id
    # 텍스트를 최상위 레벨에 직접 노출 (Claude가 쉽게 읽도록)
    if text:
        context["input_text"] = text

    agents = [
        ("staff",     CreatorStaff()),
        ("assistant", CreatorAssistant()),
        ("manager",   CreatorManager()),
        ("lead",      CreatorLead()),
        ("director",  CreatorDirector()),
    ]

    return _run(
        db=db, agents=agents,
        target_id=product_id, target_name="신규 제품",
        company_id=company_id,
        context=context,   # ← 핵심: 빌드한 컨텍스트 전달
    )


# ─────────────────────────────────────────────────────────────────────────────
# 기존 제품/브랜드 재검토 파이프라인 (평가 전용)
# ─────────────────────────────────────────────────────────────────────────────

def run_product_pipeline(
    db: Session,
    product_id: str,
    product_name: str,
    company_id: int = 1,
    text: str = None,
    image_path: str = None,
    excel_path: str = None,
    existing_data: dict = None,
    start_from: str = "staff",
) -> dict:
    """기존 제품 재검토 (CreatorStaff가 UPDATE 모드로 동작)."""
    from app.agents.product_creator import (
        CreatorStaff, CreatorAssistant, CreatorManager,
        CreatorLead, CreatorDirector,
    )

    context = build_initial_context(
        text=text,
        image_path=image_path,
        excel_path=excel_path,
        existing_data=existing_data,
    )
    context["product_id"] = product_id

    agents = [
        ("staff",     CreatorStaff()),
        ("assistant", CreatorAssistant()),
        ("manager",   CreatorManager()),
        ("lead",      CreatorLead()),
        ("director",  CreatorDirector()),
    ]

    roles_order = ["staff", "assistant", "manager", "lead", "director"]
    start_idx = roles_order.index(start_from) if start_from in roles_order else 0
    agents = agents[start_idx:]

    return _run(
        db=db, agents=agents,
        target_id=product_id, target_name=product_name,
        company_id=company_id, context=context,
    )


def run_brand_pipeline(
    db: Session,
    brand_id: str,
    brand_name: str,
    company_id: int = 1,
    text: str = None,
    image_path: str = None,
    excel_path: str = None,
    existing_data: dict = None,
    start_from: str = "staff",
) -> dict:
    """브랜드 파이프라인 (기존 평가 에이전트 유지)."""
    from app.agents.brand_pipeline import (
        BrandStaff, BrandAssistant, BrandManager,
        BrandLead, BrandDirector,
    )
    from app.models.brand import Brand

    context = build_initial_context(
        text=text,
        image_path=image_path,
        excel_path=excel_path,
        existing_data=existing_data,
    )

    agents = [
        ("staff",     BrandStaff()),
        ("assistant", BrandAssistant()),
        ("manager",   BrandManager()),
        ("lead",      BrandLead()),
        ("director",  BrandDirector()),
    ]

    roles_order = ["staff", "assistant", "manager", "lead", "director"]
    start_idx = roles_order.index(start_from) if start_from in roles_order else 0
    agents = agents[start_idx:]

    result = _run(
        db=db, agents=agents,
        target_id=brand_id, target_name=brand_name,
        company_id=company_id, context=context,
    )

    # 브랜드 상태 업데이트
    brand = db.query(Brand).filter(Brand.id == brand_id).first()
    if brand:
        brand.review_status  = result["final_status"]
        brand.priority_score = result.get("final_score")
        db.commit()

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 공통 실행기
# ─────────────────────────────────────────────────────────────────────────────

def _run(
    db: Session,
    agents: list,
    target_id: str,
    target_name: str,
    company_id: int,
    context: dict = None,
) -> dict:
    from app.agents.decision_engine import evaluate, add_to_review_queue
    from app.agents.memory_service import query_insights

    if context is None:
        context = {}

    steps = []
    final_status = "draft"
    final_score = None
    rejected_at = None
    review_queue_id = None
    product_id = target_id

    for role_key, agent in agents:
        # 팀장 단계 전: 트렌드 시즌 인사이트 주입
        if role_key == "lead":
            try:
                from app.services.trend_matcher import get_upcoming_events
                upcoming = get_upcoming_events(window_days=60)
                if upcoming:
                    product_cat = context.get("staff_result", {}).get("category", "")
                    relevant = [e for e in upcoming[:5] if not product_cat
                                or any(kw in e.get("name", "") + e.get("category", "")
                                       for kw in [product_cat[:3]])]
                    if relevant:
                        context["trend_events"] = [
                            {"name": e["name"], "peak_date": str(e.get("peak_date", "")),
                             "lead_days": e.get("lead_days", 0)}
                            for e in relevant[:3]
                        ]
            except Exception:
                pass  # 트렌드 실패가 파이프라인을 막으면 안 됨

        # 이사 단계 전에 메모리 인사이트 주입
        if role_key == "director":
            insights = query_insights(db, company_id)
            if insights:
                context["memory_insights"] = insights

        result = agent.run(
            db=db,
            target_id=product_id,
            target_name=target_name,
            context=context,
            company_id=company_id,
        )

        # 사원 단계에서 product_name 업데이트
        if role_key == "staff" and result.get("output", {}).get("product_name"):
            target_name = result["output"]["product_name"]

        # 누적 컨텍스트 업데이트 — score/risk_level도 포함
        context[f"{role_key}_result"] = {
            **result.get("output", {}),
            "score": result.get("score"),
            "risk_level": result.get("risk_level"),
        }
        if result.get("db_result"):
            context[f"{role_key}_db"] = result["db_result"]

        steps.append(result)

        # ── Decision Engine ────────────────────────────────────────────────
        decision = evaluate(result, role_key)

        if decision.should_continue:
            final_status = _PASS_STATUS.get(role_key, final_status)
            if role_key == "director":
                final_score = result.get("priority_score")

        elif decision.needs_human_review:
            # score 부족 → 휴먼 리뷰 대기열에 추가하고 파이프라인 일시 정지
            review_queue_id = add_to_review_queue(
                db=db,
                target_type=agent.target_type,
                target_id=product_id,
                target_name=target_name,
                role_key=role_key,
                agent_result=result,
                context=context,
                company_id=company_id,
            )
            final_status = "pending_review"
            _update_review_status(db, product_id, "pending_review")
            break

        else:  # reject
            final_status = "rejected"
            rejected_at = role_key
            _update_review_status(db, product_id, "rejected")
            break

    return {
        "product_id": product_id,
        "final_status": final_status,
        "final_score": final_score,
        "steps": steps,
        "rejected_at": rejected_at,
        "review_queue_id": review_queue_id,
    }


def _update_review_status(db: Session, target_id: str, status: str):
    from app.models.product import Product
    product = db.query(Product).filter(Product.id == target_id).first()
    if product:
        product.review_status = status
        db.commit()
