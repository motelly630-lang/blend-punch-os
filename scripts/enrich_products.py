"""enrich_products.py — 이미 등록된 제품의 서술형 필드를 AI로 일괄 생성.

## 왜 필요한가

제품 등록 자체는 거의 끝나 있다(카테고리·브랜드·이미지·가격 90~100% 채워짐).
비어 있는 건 서술형 필드뿐이다 — 사용장면 100%, 공구안내 71%, 셀링포인트 41%, 설명 40%.

그런데 이걸 채워주는 경로가 없었다:
  - `app/agents/product_pipeline.py` (기존 제품 재검토) → db_action 이 없어 **평가만** 하고 필드를 쓰지 않는다
  - `app/agents/product_creator.py` (CreatorAssistant/CreatorLead) → 필드를 쓰지만
    **신규 생성 경로**(텍스트·이미지·엑셀 → 제품 생성)에만 연결돼 있다
이 스크립트가 그 사이를 잇는다. 기존 제품에 Creator 단계를 적용한다.

## 채워지는 필드

CreatorAssistant → description, unique_selling_point, target_audience, usage_scenes,
                   content_angle, key_benefits
CreatorLead      → categories, recommended_inf_categories, group_buy_guideline, positioning

## 사용법

    # 1) 대상만 확인 (API 호출 없음, 비용 0)
    uv run python scripts/enrich_products.py --limit 10

    # 2) 실제 실행 — 실행 전 값을 backups/enrich_*.json 에 자동 저장
    uv run python scripts/enrich_products.py --limit 10 --apply

    # 3) 모델을 바꿔 품질 비교 (기본은 코드의 ROLE_MODELS)
    uv run python scripts/enrich_products.py --limit 3 --apply --model claude-opus-5

    # 4) 되돌리기
    uv run python scripts/enrich_products.py --restore backups/enrich_20260909_120000.json

## 주의

- 기본 대상 DB 는 `.env` 의 DATABASE_URL — 로컬은 `blendpunch`, 운영은 `blendpunch_dev`.
  **운영에 돌리기 전에 반드시 로컬에서 품질을 먼저 확인할 것.**
- Creator 단계는 캠페인·제안서를 만들지 않는다(그건 5단계 파이프라인의 Director 자동 트리거).
  이 스크립트는 제품 필드만 건드린다.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import or_

from app.database import SessionLocal
from app.models import Product

# CreatorAssistant/Lead 가 채우는 필드 = 이 스크립트가 건드리는 필드 전체
ASSISTANT_FIELDS = [
    "description", "unique_selling_point", "target_audience",
    "usage_scenes", "content_angle", "key_benefits",
]
LEAD_FIELDS = [
    "categories", "recommended_inf_categories", "group_buy_guideline", "positioning",
]
TOUCHED_FIELDS = ASSISTANT_FIELDS + LEAD_FIELDS + ["review_status"]

# 채워졌는지 판정할 때 "비었다"로 볼 값
def _empty(v):
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, (list, dict)) and not v)


def _select(db, limit, ids, company_id):
    q = db.query(Product).filter(
        Product.company_id == company_id,
        Product.status == "active",
        Product.is_archived.isnot(True),
    )
    if ids:
        return q.filter(Product.id.in_(ids)).all()
    # 서술 필드가 하나라도 비어 있고, 이미지가 있는 제품 우선
    # (이미지 없는 제품은 문구를 채워도 카탈로그에서 볼품이 없다)
    q = q.filter(
        Product.product_image.isnot(None),
        Product.product_image != "",
        # 가격이 없는 제품은 대리 단계에서 "필수 정보 부재"로 반려된다 — API 비용만 나가므로 제외.
        # 이 제품들은 문구 생성 전에 가격 데이터가 먼저 채워져야 한다.
        or_(Product.consumer_price > 0, Product.groupbuy_price > 0),
        or_(
            Product.description.is_(None), Product.description == "",
            Product.usage_scenes.is_(None), Product.usage_scenes == "",
            Product.group_buy_guideline.is_(None), Product.group_buy_guideline == "",
            Product.unique_selling_point.is_(None), Product.unique_selling_point == "",
        ),
    )
    return q.order_by(Product.created_at.desc()).limit(limit).all()


# 생성 문구가 지켜야 할 규칙. 에이전트 system_prompt 는 신규생성 경로와 공유되므로
# 건드리지 않고, 컨텍스트로 전달한다(_build_user_message 가 컨텍스트를 그대로 넘긴다).
WRITING_RULES = [
    "가격·금액·할인율을 문구에 절대 넣지 마라. 가격은 수시로 바뀌므로 문구가 거짓이 된다.",
    "제공된 정보에 없는 스펙(용량, 소재, 인증, 원산지, 연령대 등)을 지어내지 마라.",
    "'최고', '1위', '유일' 같은 검증 불가한 최상급 표현을 쓰지 마라.",
    "description 은 제품이 무엇이고 누구에게 왜 좋은지를 담백하게. 과장된 감탄사로 시작하지 마라.",
    "usage_scenes 는 실제 사용 장면 2~3개를 줄바꿈으로 구분해 쓰라.",
]


def _context(p):
    """에이전트에 넘길 컨텍스트 — 기존에 있는 정보만 담는다(없는 걸 지어내지 않게)."""
    return {
        "작성_규칙": WRITING_RULES,
        "product_id": p.id,
        "name": p.name,
        "brand": p.brand,
        "category": p.category,
        "categories": p.categories,
        "consumer_price": p.consumer_price,
        "groupbuy_price": p.groupbuy_price,
        "discount_rate": p.discount_rate,
        "shipping_type": p.shipping_type,
        "ship_origin": p.ship_origin,
        "existing_description": p.description,
        "existing_usp": p.unique_selling_point,
        "existing_target_audience": p.target_audience,
        "set_options": p.set_options,
        "source_url": p.source_url,
        "product_link": p.product_link,
    }


def _snapshot(p):
    return {f: getattr(p, f, None) for f in TOUCHED_FIELDS}


def _fmt(v, width=70):
    if _empty(v):
        return "(비어있음)"
    s = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v)
    s = s.replace("\n", " ⏎ ")
    return s if len(s) <= width else s[:width] + "…"


def cmd_restore(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    db = SessionLocal()
    n = 0
    try:
        for pid, before in data["snapshots"].items():
            p = db.query(Product).filter(Product.id == pid).first()
            if not p:
                print(f"  ! 제품 없음: {pid}")
                continue
            for f, v in before.items():
                setattr(p, f, v)
            n += 1
        db.commit()
        print(f"✅ {n}건 복원 완료 ({path})")
    finally:
        db.close()


def main():
    ap = argparse.ArgumentParser(description="기존 제품의 서술형 필드를 AI로 채운다")
    ap.add_argument("--limit", type=int, default=10, help="대상 제품 수 (기본 10)")
    ap.add_argument("--ids", default="", help="특정 제품 id 쉼표구분 (지정 시 --limit 무시)")
    ap.add_argument("--company-id", type=int, default=1)
    ap.add_argument("--apply", action="store_true", help="실제 실행 (없으면 대상만 표시, API 호출 없음)")
    ap.add_argument("--model", default="", help="모든 단계에 강제할 모델 ID (예: claude-opus-5)")
    ap.add_argument("--stage", default="both", choices=["assistant", "lead", "both"])
    ap.add_argument("--restore", default="", help="스냅샷 JSON 으로 되돌리기")
    args = ap.parse_args()

    if args.restore:
        cmd_restore(args.restore)
        return

    ids = [s.strip() for s in args.ids.split(",") if s.strip()]
    db = SessionLocal()
    try:
        targets = _select(db, args.limit, ids, args.company_id)
        if not targets:
            print("대상 제품이 없습니다.")
            return

        print(f"대상 {len(targets)}건 (company_id={args.company_id})")
        for p in targets:
            missing = [f for f in ASSISTANT_FIELDS + LEAD_FIELDS if _empty(getattr(p, f, None))]
            print(f"  - {p.name[:38]:40} [{p.brand}] 빈 필드 {len(missing)}개: {', '.join(missing[:5])}")

        if not args.apply:
            print("\n실행하려면 --apply 를 붙이세요. (지금은 API 호출·DB 변경 없음)")
            return

        # 모델 강제 — 품질 비교용
        from app.agents import base as agent_base
        if args.model:
            for role in list(agent_base.ROLE_MODELS):
                agent_base.ROLE_MODELS[role] = args.model
            print(f"\n모델 강제: {args.model}")
        else:
            print(f"\n모델: {agent_base.ROLE_MODELS}")

        from app.agents.product_creator import CreatorAssistant, CreatorLead
        stages = []
        if args.stage in ("assistant", "both"):
            stages.append(("대리(콘텐츠)", CreatorAssistant()))
        if args.stage in ("lead", "both"):
            stages.append(("차장(전략)", CreatorLead()))

        # 실행 전 값 저장 — 되돌릴 수 있어야 한다
        snap_path = Path("backups") / f"enrich_{datetime.now():%Y%m%d_%H%M%S}.json"
        snap_path.parent.mkdir(exist_ok=True)
        snapshots = {p.id: _snapshot(p) for p in targets}
        snap_path.write_text(
            json.dumps({"created_at": datetime.now().isoformat(), "snapshots": snapshots},
                       ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"실행 전 스냅샷: {snap_path}\n")

        ok = fail = rejected = 0
        for i, p in enumerate(targets, 1):
            print(f"[{i}/{len(targets)}] {p.name[:50]}")
            context = _context(p)
            halted = None
            for label, agent in stages:
                try:
                    res = agent.run(db, p.id, p.name, context, company_id=p.company_id)
                    dec = res.get("decision")
                    print(f"    {label}: {dec} score={res.get('score')} "
                          f"risk={res.get('risk_level')}")
                    # 반려는 체인을 멈춘다. 계속 돌리면 다음 단계가 "정보 부족"으로 반려된
                    # 데이터 위에 전략 필드를 써버린다(Decision Engine 의미와도 어긋남).
                    if dec == "reject":
                        print(f"      반려사유: {res.get('reject_reason')}")
                        halted = "reject"
                        break
                    # 다음 단계가 앞 단계 결과를 볼 수 있게 컨텍스트 누적
                    context[f"{agent.role}_result"] = res.get("output")
                except Exception as e:
                    print(f"    {label}: ✗ 실패 — {type(e).__name__}: {e}")
                    halted = "error"
                    break

            # ── 기존 값 보존 ──────────────────────────────────────────────────
            # 에이전트 db_action 은 `output.get(x) or product.x` 라서 output 에 값이 있으면
            # 기존 값을 덮어쓴다. 이 스크립트의 목적은 "빈 칸 채우기"이므로, 원래 값이
            # 있던 필드는 되돌린다. (실제 사고: categories 가 ["육아"] → ["맥포머스",
            # "자석블록", ...] 로 바뀌어 소비자 대분류가 SEO 키워드로 오염됐다)
            db.refresh(p)
            restored = []
            for f in ASSISTANT_FIELDS + LEAD_FIELDS:
                before = snapshots[p.id][f]
                if not _empty(before) and getattr(p, f, None) != before:
                    setattr(p, f, before)
                    restored.append(f)
            if restored:
                db.commit()
                db.refresh(p)
                print(f"    기존값 보존: {', '.join(restored)}")

            if halted == "reject":
                rejected += 1
            elif halted == "error":
                fail += 1
            else:
                ok += 1

            after = _snapshot(p)
            for f in ASSISTANT_FIELDS + LEAD_FIELDS:
                b, a = snapshots[p.id][f], after[f]
                if b != a:
                    print(f"      {f}: {_fmt(b, 30)} → {_fmt(a)}")
            print()

        print(f"완료 — 성공 {ok}건 / 반려 {rejected}건 / 실패 {fail}건")
        print(f"되돌리기: uv run python scripts/enrich_products.py --restore {snap_path}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
