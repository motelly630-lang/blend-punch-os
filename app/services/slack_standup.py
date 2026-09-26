"""#출근보고 — AI 직원들이 각자 이름·아이콘으로 아침 보고를 올린다 (대표님 2026-09-26, 1단계).

2026-09-26 고도화 A: 칸마다 '어제보다 ±N'(standup_snapshots), 목록 바로가기(필터 주소), 할 일 없는 날은 한 줄.

| 직원 | 보고 내용 (전부 OS DB 에서 코드가 센다 — AI·비용 없음) | 자세히 |
|---|---|---|
| 🛒 공구 매니저 | 오늘 마감 · 3일 안 마감 · 오늘 시작 · 진행 중 · 종료일 지났는데 완료 안 된 것 | /campaigns |
| 💰 정산 매니저 | 매출 미입력 끝난 공구 · 작성중 정산서 · 지급 대기 · 지급 예정일 지남 | /campaigns/revenue |
| 💬 고객 관리 매니저 | 어제 새 문의 · 처리 중 · 처리 기한 지남 · 긴급 (**고객 이름·연락처는 넣지 않는다**) | /cs |
| 📸 인플루언서 매니저 | 밤새 채운 인원 · 조회 안 됨 · 남은 대기 · 수집 0명이면 경고 | /influencers |
| 📦 브랜드·제품 정리 담당 | 정보 필요 브랜드(설명·로고 없음) · 미완성 제품 · 어제 새로 생긴 미완성 | /brands?need=1 · /products?completeness=incomplete |
| 📊 경영 분석가 | 이번 달·지난달 공구 매출(종료일 기준, 입력된 것만) · 매출 입력률 · 이번 달 지급한 정산 | /campaigns/revenue |
| 📈 트렌드 분석가 | 준비할 시즌(✅우리 강점 분류) · 우리한테 먹히는 분류(최근 6개월 매출) · 앵콜 후보 · 최근 30일 수집 트렌드 | /trends |

이벤트 키 `staff_standup`, 채널 키 `standup` (`SLACK_CHANNELS` 에 standup=<채널 ID>). 매일 09:15 (트렌드 브리핑 09:00 뒤).
직원마다 따로 올리고 하루 한 번만 (`standup:<직원>:<날짜>`). 한 직원이 실패해도 나머지는 올린다.
수동: `python -m app.services.slack_standup --preview` (보내지 않고 내용만) · `--send` (지금 보내기, 중복 방지 없음)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from app.services import slack_notify as sn

logger = logging.getLogger(__name__)

EVENT = "staff_standup"
CHANNEL = "standup"

STAFF = [
    # key, 보이는 이름, 아이콘
    ("groupbuy", "공구 매니저", ":shopping_trolley:"),
    ("settlement", "정산 매니저", ":moneybag:"),
    ("cs", "고객 관리 매니저", ":speech_balloon:"),
    ("influencer", "인플루언서 매니저", ":camera_with_flash:"),
    ("catalog", "브랜드·제품 정리 담당", ":package:"),
    ("biz", "경영 분석가", ":bar_chart:"),
    ("trend", "트렌드 분석가", ":chart_with_upwards_trend:"),
]


def _base_url() -> str:
    from app.config import settings
    return (settings.app_base_url or "").rstrip("/")


def _won(v) -> str:
    return f"{int(round(v or 0)):,}원"


def _s(label: str, n: int, unit: str = "건", extra: str = "", delta: bool = True) -> tuple:
    """숫자 칸 하나 → (이름, 보이는 글자, 숫자 또는 None). 숫자가 있으면 다음 날 '어제보다' 비교에 쓴다."""
    return (label, f"{n:,}{unit}" + (f" · {extra}" if extra else ""), n if delta else None)


def _camp_label(c) -> str:
    prod = c.product.name if getattr(c, "product", None) else (c.product_name_manual or "")
    inf = c.influencer.name if getattr(c, "influencer", None) else ""
    return " · ".join(x for x in (prod or c.name, inf) if x)


# ── 직원별 보고 만들기 — {"summary", "stats": [_s(...)], "lines": [...], "links": [(이름, 주소)]} 또는 None ──

def build_groupbuy(db, cid: int, today: date) -> dict:
    from sqlalchemy.orm import joinedload
    from app.models.campaign import Campaign
    cs = (db.query(Campaign).options(joinedload(Campaign.product), joinedload(Campaign.influencer))
          .filter(Campaign.company_id == cid,
                  (Campaign.is_archived == False) | (Campaign.is_archived.is_(None)),  # noqa: E712
                  (Campaign.status != "cancelled") | (Campaign.status.is_(None))).all())
    open_ = [c for c in cs if c.status != "completed"]
    ending_today = [c for c in open_ if c.end_date == today]
    ending_soon = sorted([c for c in open_ if c.end_date and today < c.end_date <= today + timedelta(days=3)],
                         key=lambda c: c.end_date)
    starting = [c for c in open_ if c.start_date == today]
    running = [c for c in open_ if c.start_date and c.start_date <= today and (not c.end_date or c.end_date >= today)]
    overdue = [c for c in open_ if c.end_date and c.end_date < today]
    lines = [f"🔴 오늘 마감 — {_camp_label(c)}" for c in ending_today[:5]]
    lines += [f"🟠 D-{(c.end_date - today).days} — {_camp_label(c)}" for c in ending_soon[:5]]
    lines += [f"🟢 오늘 시작 — {_camp_label(c)}" for c in starting[:5]]
    if overdue:
        lines.append(f"⚪ 종료일이 지났는데 완료 처리 안 된 공구 {len(overdue)}건 — 매출 넣으면서 완료로 바꿀 수 있어요")
    if ending_today or ending_soon or starting:
        summary = f"오늘 마감 {len(ending_today)}건, 3일 안 마감 {len(ending_soon)}건, 오늘 시작 {len(starting)}건이에요."
    else:
        summary = f"오늘 마감·시작하는 공구는 없어요. 진행 중 {len(running)}건이에요."
    links = [("캠페인 목록", "/campaigns")]
    if overdue:
        links.append(("매출 넣고 완료 처리", "/campaigns/revenue?tab=ended"))
    return {"summary": summary, "links": links, "lines": lines,
            "stats": [_s("진행 중", len(running)), _s("오늘 마감", len(ending_today)),
                      _s("3일 안 마감", len(ending_soon)), _s("오늘 시작", len(starting))]}


def build_settlement(db, cid: int, today: date) -> dict:
    from sqlalchemy import func
    from app.models.campaign import Campaign
    from app.models.settlement import Settlement
    missing = db.query(func.count(Campaign.id)).filter(
        Campaign.company_id == cid, (Campaign.status != "cancelled") | (Campaign.status.is_(None)),
        (Campaign.end_date < today) | (Campaign.status == "completed"),
        (Campaign.actual_revenue.is_(None)) | (Campaign.actual_revenue == 0)).scalar() or 0

    def agg(*conds):
        n, s = db.query(func.count(Settlement.id), func.coalesce(func.sum(Settlement.final_payment), 0)).filter(
            Settlement.company_id == cid, *conds).one()
        return n or 0, s or 0
    draft_n, draft_s = agg(Settlement.status == "pending")
    wait_n, wait_s = agg(Settlement.status == "confirmed")
    late_n, _ = agg(Settlement.status == "confirmed", Settlement.due_date.isnot(None), Settlement.due_date < today)
    lines = []
    if missing:
        lines.append(f"📝 매출이 비어 있는 끝난 공구 {missing}건 — 매출 입력 화면에서 한 번에 넣을 수 있어요")
    if draft_n:
        lines.append(f"🧾 작성중 정산서 {draft_n}건 — 확인하고 발행해 주세요")
    if late_n:
        lines.append(f"⏰ 지급 예정일이 지난 정산 {late_n}건")
    summary = (f"지급 대기 {wait_n}건({_won(wait_s)}), 작성중 {draft_n}건이에요."
               + (f" 매출 미입력 공구가 {missing}건 있어요." if missing else ""))
    links = []
    if missing:
        links.append(("매출 넣기", "/campaigns/revenue?tab=ended"))
    if draft_n:
        links.append(("작성중 정산서", "/settlements?tab=pending"))
    if wait_n:
        links.append(("지급 대기", "/settlements?tab=confirmed"))
    return {"summary": summary, "links": links or [("정산", "/settlements")], "lines": lines,
            "stats": [_s("매출 미입력", missing), _s("작성중", draft_n, extra=_won(draft_s)),
                      _s("지급 대기", wait_n, extra=_won(wait_s)), _s("예정일 지남", late_n)]}


def build_cs(db, cid: int, today: date) -> dict:
    from sqlalchemy import func
    from app.cs.constants import CS_STATUS_OPEN
    from app.models.cs import CSTicket
    now = datetime.utcnow()
    base = db.query(func.count(CSTicket.id)).filter(
        CSTicket.company_id == cid, (CSTicket.is_archived == False) | (CSTicket.is_archived.is_(None)))  # noqa: E712
    new = base.filter(CSTicket.received_at >= now - timedelta(hours=24)).scalar() or 0
    opened = base.filter(CSTicket.status.in_(CS_STATUS_OPEN))
    open_n = opened.scalar() or 0
    late = opened.filter(CSTicket.due_at.isnot(None), CSTicket.due_at < now).scalar() or 0
    urgent = opened.filter(CSTicket.is_urgent == True).scalar() or 0  # noqa: E712
    lines = []
    if late:
        lines.append(f"⏰ 처리 기한이 지난 문의 {late}건 — 먼저 봐 주세요")
    if urgent:
        lines.append(f"🚨 긴급 표시된 문의 {urgent}건")
    if not (new or open_n):
        summary = "새 문의도, 처리 중인 문의도 없어요 ✅"
    else:
        summary = f"어제 새 문의 {new}건, 처리 중 {open_n}건이에요." + (f" 기한 지난 게 {late}건 있어요." if late else "")
    links = ([("기한 지난 문의", "/cs?tab=overdue")] if late else []) + [("CS 목록", "/cs")]
    return {"summary": summary, "links": links, "lines": lines,
            "stats": [_s("새 문의 (24시간)", new), _s("처리 중", open_n), _s("기한 지남", late), _s("긴급", urgent)]}


def build_influencer(db, cid: int, today: date) -> dict:
    from sqlalchemy import func
    from app.config import settings
    from app.models.influencer import Influencer
    from app.services.influencer_enrich import pending_count
    since = datetime.utcnow() - timedelta(hours=20)       # 04:30 수집 ~ 09:15 보고 사이를 넉넉히
    base = db.query(func.count(Influencer.id)).filter(Influencer.company_id == cid, Influencer.enriched_at >= since)
    filled = base.filter(Influencer.enrich_error.is_(None)).scalar() or 0
    failed = base.filter(Influencer.enrich_error.isnot(None)).scalar() or 0
    waiting = pending_count(db, cid)
    lines = []
    if settings.influencer_enrich and waiting and not (filled or failed):
        lines.append("⚠️ 어젯밤 한 명도 못 채웠어요 — Meta 토큰이 끊겼거나 한도에 걸렸을 수 있어요 (서버 기록 확인 필요)")
    if failed:
        lines.append(f"🔍 자동 조회가 안 된 {failed}명은 '자동 조회 안 됨' 필터에 모였어요 — 직접 입력이 필요해요")
    if waiting:
        summary = f"어젯밤 {filled}명 채웠고, 남은 대기는 {waiting:,}명이에요."
    else:
        summary = f"어젯밤 {filled}명 채웠어요. 대기 중인 인플루언서는 없어요."
    links = []
    if failed:
        links.append(("자동 조회 안 됨 목록", "/influencers?data=failed"))
    if waiting:
        links.append(("아직 조회 전", "/influencers?data=empty"))
    return {"summary": summary, "links": links or [("인플루언서", "/influencers")], "lines": lines,
            "stats": [_s("어젯밤 채움", filled, "명", delta=False), _s("조회 안 됨", failed, "명", delta=False),
                      _s("남은 대기", waiting, "명")]}


def _man(v) -> str:
    """1,234,567원 → '123만원' (보고용 짧은 금액)."""
    v = int(round(v or 0))
    if v >= 100_000_000:
        eok, man = divmod(v // 10000, 10000)
        return f"{eok}억" + (f" {man:,}만원" if man else "원")
    return f"{v // 10000:,}만원" if v >= 10000 else f"{v:,}원"


def sales_strength(db, cid: int, today: date, days: int = 180) -> list[dict]:
    """최근 N일(종료일 기준) 매출이 입력된 공구를 제품 분류별로 — [{category, revenue, count, top}] 매출 순."""
    from collections import defaultdict
    from sqlalchemy.orm import joinedload
    from app.models.campaign import Campaign
    rows = (db.query(Campaign).options(joinedload(Campaign.product))
            .filter(Campaign.company_id == cid, (Campaign.status != "cancelled") | (Campaign.status.is_(None)),
                    Campaign.actual_revenue > 0, Campaign.end_date >= today - timedelta(days=days),
                    Campaign.end_date < today).all())
    agg = defaultdict(lambda: {"revenue": 0.0, "count": 0, "products": defaultdict(float)})
    for c in rows:
        cat = (c.product.category if c.product else None) or "미분류"
        name = (c.product.name if c.product else None) or c.product_name_manual or c.name
        a = agg[cat]
        a["revenue"] += c.actual_revenue or 0
        a["count"] += 1
        a["products"][name] += c.actual_revenue or 0
    out = [{"category": k, "revenue": v["revenue"], "count": v["count"],
            "top": max(v["products"], key=v["products"].get)} for k, v in agg.items()]
    return sorted(out, key=lambda x: -x["revenue"])


def encore_candidates(db, cid: int, today: date, limit: int = 3) -> list[dict]:
    """예전에 잘 팔렸는데(매출 입력된 공구) 지금 진행·예정 공구가 없고, 마지막 공구가 30일 넘게 지난 제품."""
    from collections import defaultdict
    from app.models.campaign import Campaign
    from app.models.product import Product
    rows = (db.query(Campaign.product_id, Campaign.actual_revenue, Campaign.end_date, Campaign.start_date, Campaign.status)
            .filter(Campaign.company_id == cid, Campaign.product_id.isnot(None),
                    (Campaign.status != "cancelled") | (Campaign.status.is_(None))).all())
    rev, cnt, last, busy = defaultdict(float), defaultdict(int), {}, set()
    for pid, r, end, start, status in rows:
        if (end and end >= today) or (start and start > today) or (not end and status in ("planning", "active")):
            busy.add(pid)
        if r:
            rev[pid] += r
            cnt[pid] += 1
            if end and (pid not in last or end > last[pid]):
                last[pid] = end
    picks = [pid for pid in sorted(rev, key=rev.get, reverse=True)
             if pid not in busy and pid in last and (today - last[pid]).days > 30][:limit]
    names = {p.id: p.name for p in db.query(Product.id, Product.name).filter(Product.company_id == cid,
                                                                             Product.id.in_(picks or [""]))}
    return [{"name": names.get(pid, "?"), "revenue": rev[pid], "count": cnt[pid], "last": last[pid]} for pid in picks]


def recent_trends(db, cid: int, days: int = 30, limit: int = 3) -> tuple[list, datetime | None]:
    """최근 N일 안에 모은 트렌드(젠스파크·인스타·뉴스 등) 점수 순 + 마지막 수집 시각. 오래된 건 보고에 쓰지 않는다
    (3~4월에 모은 여름 선풍기 트렌드가 9월 보고에 나오면 안 된다)."""
    from sqlalchemy import func
    from app.models.trend import TrendItem as T
    base = db.query(T).filter(T.company_id == cid)
    last = base.with_entities(func.max(T.created_at)).scalar()
    items = (base.filter(T.created_at >= datetime.utcnow() - timedelta(days=days))
             .order_by(T.final_score.desc().nullslast(), T.trend_score.desc().nullslast()).limit(limit).all())
    return items, last


def build_trend(db, cid: int, today: date) -> dict | None:
    """재료 4가지: 시즌 달력(언제) · 우리 판매 실적(무엇이 우리한테 먹히나) · 앵콜 후보 · 최근 수집 트렌드(무엇이 뜨나).
    네이버 데이터랩(얼마나 뜨나)은 키 연결 뒤에 붙인다."""
    from app.models.product import Product
    from app.models.trend_engine import TrendBriefing
    from app.services.slack_reports import _trend_candidates, strong_products
    from app.services.season_matrix import SEASON_MATRIX
    from app.services.trend_matcher import CATEGORY_GROUPS
    season_cats = {x["key"]: x.get("product_categories") or [] for x in SEASON_MATRIX}
    b = (db.query(TrendBriefing).filter(TrendBriefing.company_id == cid, TrendBriefing.report_date == today.isoformat())
         .order_by(TrendBriefing.created_at.desc()).first())
    cands = []
    if b and b.report_data:
        allowed = {pid for (pid,) in db.query(Product.id).filter(Product.company_id == cid).all()}
        cands = _trend_candidates(b.report_data, allowed)[:3]
    strength = sales_strength(db, cid, today)
    strong_cats = {s["category"] for s in strength[:3]}
    encore = encore_candidates(db, cid, today)
    fresh, last_collected = recent_trends(db, cid)
    if not (cands or strength or encore or fresh):
        return None

    lines = []
    if cands:
        lines.append("📅 준비할 시즌")
        for e in cands:
            prep = e.get("prep_delta")
            when = f"준비 D-{prep}" if prep and prep > 0 else "지금 준비 시기"
            # 저장된 브리핑엔 분류가 없어서 시즌표에서 찾는다
            cats = e.get("product_categories") or season_cats.get(e.get("key"), [])
            groups = set().union(*(CATEGORY_GROUPS.get(c, set()) for c in cats))
            mark = " ✅우리 강점 분류" if groups & strong_cats else ""
            prods = ", ".join(strong_products(e))
            lines.append(f"• {e['name']} ({when}){mark} — " + (prods or "딱 맞는 우리 제품 없음 → 소싱 후보"))
    if strength:
        lines.append("💪 우리한테 먹히는 분류 (최근 6개월, 매출 입력된 공구)")
        for s in strength[:3]:
            lines.append(f"• {s['category']} {_man(s['revenue'])} · {s['count']}건 · 대표 {s['top']}")
    if encore:
        lines.append("🔁 앵콜 후보 (예전에 잘 팔렸고 지금 공구 없음)")
        for x in encore:
            lines.append(f"• {x['name']} — {x['count']}번 {_man(x['revenue'])}, 마지막 {x['last'].month}/{x['last'].day}")
    if fresh:
        lines.append("🔥 최근 30일 모은 트렌드")
        for i in fresh:
            lines.append(f"• {i.title}" + (f" ({i.category})" if i.category else ""))
    else:
        when = f"{last_collected.month}/{last_collected.day}" if last_collected else "기록 없음"
        lines.append(f"🔥 최근 30일 새로 모은 트렌드 없음 (마지막 수집 {when}) — 젠스파크 주간 조사 연결이 필요해요")

    head = []
    if cands:
        head.append(f"준비할 시즌 {len(cands)}개")
    if strength:
        head.append(f"우리 강점은 {strength[0]['category']}")
    if encore:
        head.append(f"앵콜 후보 {len(encore)}개")
    return {"summary": ", ".join(head) + "예요." if head else "오늘 트렌드 보고예요.",
            "links": [("트렌드", "/trends"), ("시즌 브리핑", "/trends/briefings")], "lines": lines,
            "stats": [_s("준비할 시즌", len(cands), "개", delta=False), _s("앵콜 후보", len(encore), "개", delta=False),
                      _s("최근 30일 트렌드", len(fresh), "개", delta=False)]}


def build_catalog(db, cid: int, today: date) -> dict:
    """브랜드 목록 '정보 입력 필요'(설명·로고 둘 다 없음), 제품 목록 '미완성'(is_complete=False) 과 같은 기준."""
    from sqlalchemy import func
    from app.models.brand import Brand
    from app.models.product import Product
    need_brands = db.query(func.count(Brand.id)).filter(
        Brand.company_id == cid, (Brand.is_archived == False) | (Brand.is_archived.is_(None)),  # noqa: E712
        (Brand.description.is_(None)) | (func.trim(Brand.description) == ""),
        (Brand.logo.is_(None)) | (func.trim(Brand.logo) == "")).scalar() or 0
    prod = db.query(func.count(Product.id)).filter(
        Product.company_id == cid, (Product.is_archived == False) | (Product.is_archived.is_(None)),  # noqa: E712
        Product.is_complete == False)  # noqa: E712
    incomplete = prod.scalar() or 0
    new_incomplete = prod.filter(Product.created_at >= datetime.utcnow() - timedelta(hours=24)).scalar() or 0
    lines = []
    if new_incomplete:
        lines.append(f"🆕 어제 새로 생긴 미완성 제품 {new_incomplete}개 — 공구 한 번에 등록 등으로 만들어진 것, 정보를 채워 주세요")
    if need_brands:
        lines.append(f"🏷️ 설명·로고가 없는 브랜드 {need_brands}곳")
    if incomplete:
        lines.append(f"📦 정보가 덜 채워진 제품 {incomplete}개")
    summary = (f"정보가 필요한 브랜드 {need_brands}곳, 미완성 제품 {incomplete}개예요."
               if (need_brands or incomplete) else "브랜드·제품 정보가 모두 채워져 있어요 ✅")
    links = ([("정보 필요 브랜드", "/brands?need=1")] if need_brands else []) + \
            ([("미완성 제품", "/products?completeness=incomplete")] if incomplete else [])
    return {"summary": summary, "links": links or [("제품", "/products")], "lines": lines,
            "stats": [_s("정보 필요 브랜드", need_brands, "곳"), _s("미완성 제품", incomplete, "개"),
                      _s("어제 새 미완성", new_incomplete, "개", delta=False)]}


def _month_start(d: date) -> date:
    return d.replace(day=1)


def build_biz(db, cid: int, today: date) -> dict:
    """공구 매출은 **종료일이 속한 달** 기준, OS 에 입력된 매출만 센다 (미입력은 빠진다 — 그래서 입력률을 같이 보여준다).
    광고비는 Meta 광고 연결(D) 뒤에 붙인다."""
    from sqlalchemy import func
    from app.models.campaign import Campaign
    from app.models.settlement import Settlement
    this_m = _month_start(today)
    last_m = _month_start(this_m - timedelta(days=1))

    def month(start: date, end: date):
        q = db.query(Campaign).filter(
            Campaign.company_id == cid, (Campaign.status != "cancelled") | (Campaign.status.is_(None)),
            Campaign.end_date >= start, Campaign.end_date < end)
        rows = q.with_entities(Campaign.actual_revenue).all()
        rev = sum(r[0] or 0 for r in rows)
        return int(round(rev)), len(rows), sum(1 for r in rows if r[0])
    rev, ended, entered = month(this_m, today)                 # 이번 달 1일 ~ 어제 끝난 공구
    last_rev, last_ended, last_entered = month(last_m, this_m)
    # 지급 완료 시각은 UTC 로 저장 — KST 이번 달 1일 0시 = UTC 전날 15시
    paid_since = datetime.combine(this_m, datetime.min.time()) - timedelta(hours=9)
    paid = db.query(func.coalesce(func.sum(Settlement.final_payment), 0)).filter(
        Settlement.company_id == cid, Settlement.status == "paid", Settlement.paid_at >= paid_since).scalar() or 0
    lines = []
    if ended and entered < ended:
        lines.append(f"📝 이번 달 끝난 공구 {ended}건 중 매출이 입력된 건 {entered}건 — 나머지를 넣으면 매출이 더 커져요")
    if last_ended and last_entered < last_ended:
        lines.append(f"📝 지난달도 {last_ended - last_entered}건 매출이 비어 있어요")
    lines.append("📣 광고비·광고 대비 매출은 Meta 광고 연결 뒤에 보여드릴게요")
    summary = f"이번 달 공구 매출은 {_won(rev)}이에요 (끝난 공구 {ended}건 중 매출 입력 {entered}건 기준)."
    return {"summary": summary, "links": [("매출 넣기", "/campaigns/revenue?tab=ended"), ("정산", "/settlements")],
            "lines": lines,
            "stats": [_s("이번 달 매출", rev, "원"), _s("지난달 매출", last_rev, "원", delta=False),
                      ("이번 달 매출 입력", f"{entered}/{ended}건", None), _s("이번 달 지급한 정산", int(round(paid)), "원")]}


BUILDERS = {"groupbuy": build_groupbuy, "settlement": build_settlement, "cs": build_cs,
            "influencer": build_influencer, "catalog": build_catalog, "biz": build_biz, "trend": build_trend}


# ── 카드 모양 (Block Kit) ──────────────────────────────────────────────

def render(name: str, r: dict, icon: str = "", prev: dict | None = None) -> tuple[str, list]:
    """→ (알림용 한 줄 text, blocks). DB 에서 온 글자는 전부 escape (전원 호출·링크 위장 방지).

    - 첫 줄에 직원 이름·아이콘 (앱 권한이 없어 봇 이름으로 올라가도 누구 보고인지 보이게)
    - prev(어제 숫자)가 있으면 칸마다 '어제보다 ±N'
    - 할 일(lines)이 없는 조용한 날은 요약 한 줄 + 바로가기만
    - 바로가기는 우리 주소·고정 이름만 쓰므로 Slack 링크 문법 <주소|이름> 을 직접 만든다
    """
    e = sn.escape
    text = f"{name}: {r['summary']}"
    blocks = [{"type": "section", "text": {"type": "mrkdwn",
                                           "text": f"{icon} *{e(name)}*\n{e(r['summary'])}".strip()}}]
    if r.get("lines"):
        if r.get("stats"):
            fields = []
            for label, shown, n in r["stats"][:10]:
                d = (n - prev[label]) if (prev and n is not None and isinstance(prev.get(label), int)) else 0
                fields.append({"type": "mrkdwn", "text": f"*{e(label)}*\n{e(shown)}" + (f"  _(어제보다 {d:+,})_" if d else "")})
            blocks.append({"type": "section", "fields": fields})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": e("\n".join(r["lines"][:12]))[:2900]}})
    base = _base_url()
    if r.get("links") and base:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "바로가기 → " + "  ·  ".join(
            f"<{base}{path}|{e(label)}>" for label, path in r["links"][:5])}]})
    return text, blocks


def _snapshot_numbers(r: dict) -> dict:
    return {label: n for label, _, n in (r.get("stats") or []) if n is not None}


def load_prev(db, cid: int, today: date) -> dict:
    """어제 보고 숫자 {직원: {칸: 숫자}} — 어제 것이 없으면 비교하지 않는다(엉뚱한 날과 비교 방지)."""
    try:
        from app.models.standup_snapshot import StandupSnapshot as S
        rows = db.query(S).filter(S.company_id == cid, S.report_date == today - timedelta(days=1)).all()
        return {x.staff: x.numbers or {} for x in rows}
    except Exception as ex:
        logger.warning("출근보고 어제 숫자 읽기 실패: %s", ex)
        db.rollback()
        return {}


def save_today(db, cid: int, today: date, staff: str, r: dict) -> None:
    """오늘 숫자를 남긴다 — 하루·직원당 첫 번째 것만 (이미 있으면 그대로)."""
    from sqlalchemy.exc import IntegrityError
    from app.models.standup_snapshot import StandupSnapshot as S
    nums = _snapshot_numbers(r)
    if not nums:
        return
    try:
        if db.query(S.id).filter(S.company_id == cid, S.report_date == today, S.staff == staff).first():
            return
        db.add(S(company_id=cid, report_date=today, staff=staff, numbers=nums))
        db.commit()
    except IntegrityError:
        db.rollback()
    except Exception as ex:
        db.rollback()
        logger.warning("출근보고 숫자 저장 실패 (%s): %s", staff, ex)


def collect(db, cid: int, today: date | None = None) -> list[dict]:
    """직원별 보고를 만든다 (보내지 않음). 한 직원이 실패해도 나머지는 만든다."""
    from app.services.slack_reports import today_kst
    today = today or today_kst()
    out = []
    for key, name, icon in STAFF:
        try:
            r = BUILDERS[key](db, cid, today)
        except Exception as ex:
            logger.warning("출근보고 %s 만들기 실패: %s", key, ex)
            db.rollback()
            r = {"summary": f"오늘 보고를 만들지 못했어요 ({type(ex).__name__}) — 서버 기록 확인이 필요해요",
                 "stats": [], "lines": [], "links": []}
        if r is not None:
            out.append({"key": key, "name": name, "icon": icon, "report": r})
    return out


def send_all(db, company_id: int, force: bool = False, dedupe: bool = True) -> dict:
    """모든 직원 보고를 #출근보고 로. 반환 {"status", "reason", "results"} — 하나라도 실패면 failed."""
    from app.services.slack_reports import today_kst
    today = today_kst()
    results = {}
    prev = load_prev(db, company_id, today)
    for s in collect(db, company_id, today):
        text, blocks = render(s["name"], s["report"], s["icon"], prev.get(s["key"]))
        save_today(db, company_id, today, s["key"], s["report"])
        results[s["key"]] = sn.post(EVENT, CHANNEL, text, company_id=company_id, force=force,
                                    dedupe_key=f"standup:{s['key']}:{today}" if dedupe else None,
                                    blocks=blocks, username=s["name"], icon_emoji=s["icon"])
    failed = {k: r.get("reason") for k, r in results.items() if r.get("status") == "failed"}
    sent = sum(1 for r in results.values() if r.get("status") in ("sent", "mock"))
    return {"status": "failed" if failed else ("sent" if sent else "skipped"),
            "reason": "; ".join(f"{k}: {v}" for k, v in failed.items()) or f"{sent}명 보고",
            "results": results}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="#출근보고 미리보기·보내기")
    ap.add_argument("--send", action="store_true", help="지금 보내기 (이벤트 꺼져 있어도, 중복 방지 없이)")
    ap.add_argument("--preview", action="store_true", help="보내지 않고 내용만 (기본)")
    ap.add_argument("--company", type=int, default=1)
    a = ap.parse_args()
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        if a.send:
            r = send_all(db, a.company, force=True, dedupe=False)
            print(r["status"], "—", r["reason"])
        else:
            from app.services.slack_reports import today_kst
            prev = load_prev(db, a.company, today_kst())
            for s in collect(db, a.company):
                text, blocks = render(s["name"], s["report"], s["icon"], prev.get(s["key"]))
                print(f"\n=== {s['icon']} {s['name']} ===\n{text}")
                for b in blocks[1:]:
                    t = b.get("text", {}).get("text") or " | ".join(
                        f.get("text", "").replace("\n", " ") for f in b.get("fields") or b.get("elements") or [])
                    print("  " + t.replace("\n", "\n  "))
    finally:
        db.close()
