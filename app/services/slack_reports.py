"""Slack 정기 리포트 — 03 셀러·브랜드 / 05 마케팅 / 01 공지 채널, 그리고 아침 보고 AI 우선순위.

| 이벤트 키 | 채널 | 언제 | 내용 |
|---|---|---|---|
| brand_created | 03 | 10분 스캔 | [신규브랜드] 새 브랜드 (5건 초과면 요약) |
| product_daily | 03 | 매일 09:30 | 어제 등록된 제품 (입력 미완성 표시). 없으면 안 보냄 |
| trend_digest | 05 | 매일 09:10 | [레퍼런스] 준비할 시즌 3개 + 맞는 우리 제품 (AI 선택, 실패 시 규칙) |
| weekly_summary | 01 | 월요일 09:00 | 지난주 오픈·마감, 이번 주 예정 |
| campaign_digest_ai | 02 | 아침 보고에 덧붙임 | 오늘 먼저 할 3가지 (AI) |

원칙: **숫자·이름은 코드가 DB 에서 뽑고, AI 는 그 안에서 고르고 이유만 쓴다.** AI 가 실패하면
AI 부분만 빠지고 리포트는 나간다. 정산은 대표님 재검토 전까지 AI 판단에서 제외한다.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.services import slack_notify as sn

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")

EV_BRAND = "brand_created"
EV_PRODUCT_DAILY = "product_daily"
EV_TREND = "trend_digest"
EV_WEEKLY = "weekly_summary"
EV_DIGEST_AI = "campaign_digest_ai"


def today_kst() -> date:
    return datetime.now(KST).date()


def _ai():
    """중앙 Claude 클라이언트 (키가 없으면 None)."""
    try:
        from app.ai.client import ClaudeClient
        c = ClaudeClient()
        if not c.available:
            return None
        # 알림용이라 오래 기다리지 않는다 — API 가 멈춰도 아침 보고가 늦지 않게 (기본 10분 × 재시도)
        c.client = c.client.with_options(timeout=30.0, max_retries=1)
        return c
    except Exception as e:
        logger.warning("AI 클라이언트 준비 실패: %s", e)
        return None


def _names(items: list, limit: int = 5, attr: str = "name") -> list[str]:
    out = [f"· {getattr(i, attr) if not isinstance(i, dict) else i[attr]}" for i in items[:limit]]
    if len(items) > limit:
        out.append(f"· 외 {len(items) - limit}건")
    return out


# ── 03: 새 브랜드 (10분 스캔) ──────────────────────────────────────────

def scan_brands(db, company_id: int) -> dict:
    from app.models.brand import Brand
    from app.services.campaign_slack import NEW_WINDOW, notify_new
    out = {"brand_created": 0, "brand_batched": 0, "failed": 0}
    if not sn.is_enabled(EV_BRAND):
        return out
    # Brand.created_at 은 서버 로컬 시각(datetime.now)으로 저장된다 — 서버 시간대와 무관하게
    # 잡히도록 두 기준 중 이른 쪽부터 본다. 넓어진 창은 중복 방지 기록이 걸러준다.
    since = min(datetime.now(), datetime.utcnow()) - NEW_WINDOW
    brands = db.query(Brand).filter(
        Brand.company_id == company_id, Brand.created_at >= since,
        (Brand.is_archived == False) | (Brand.is_archived.is_(None)),  # noqa: E712
    ).all()
    notify_new(brands, company_id=company_id, event=EV_BRAND, channel="seller", key_prefix="brand_created",
               header="[신규브랜드] 새 브랜드", line=lambda b: b.name,
               single=lambda b: f"[신규브랜드] *{b.name}* 등록됐어요",
               out=out, count_key="brand_created", batch_key="brand_batched")
    return out


# ── 03: 어제 등록된 제품 (매일) ─────────────────────────────────────────

def send_product_daily(db, company_id: int) -> dict:
    from app.models.product import Product
    day = today_kst() - timedelta(days=1)
    # Product.created_at 은 UTC — KST 하루를 UTC 구간으로 바꿔 조회
    start = datetime.combine(day, datetime.min.time()) - timedelta(hours=9)
    end = start + timedelta(days=1)
    items = db.query(Product).filter(
        Product.company_id == company_id, Product.created_at >= start, Product.created_at < end,
        (Product.status != "archived") | (Product.status.is_(None)),
    ).order_by(Product.created_at).all()
    if not items:
        return {"sent": False, "status": "skipped", "reason": "어제 등록 제품 없음"}
    incomplete = sum(1 for p in items if not p.is_complete)
    lines = [f"*[BP OS] {day.strftime('%m/%d')} 등록 제품 {len(items)}건*"]
    lines += [f"· {p.brand} — {p.name}{' (초안)' if p.status == 'draft' else ''}"
              f"{'  ⚠️ 입력 미완성' if not p.is_complete else ''}" for p in items[:10]]
    if len(items) > 10:
        lines.append(f"· 외 {len(items) - 10}건")
    if incomplete:
        lines.append(f"\n⚠️ 입력 미완성 {incomplete}건 — OS 제품 화면에서 채워주세요")
    return sn.post(EV_PRODUCT_DAILY, "seller", "\n".join(lines), company_id=company_id,
                   dedupe_key=f"product_daily:{day}")


# ── 05: 트렌드 (매일, AI) ───────────────────────────────────────────────

TREND_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "why": {"type": "string"},
                    "products": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["key", "why", "products"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}

TREND_SYSTEM = (
    "너는 인플루언서 공동구매 회사 블랜드펀치의 마케팅 담당이다. 다가오는 시즌 이벤트 목록과 "
    "각 이벤트에 맞는 우리 제품 후보가 주어진다. 지금 공구·콘텐츠를 준비하면 가장 효과가 클 이벤트 "
    "3개를 골라라. 준비 시작일이 가깝고, 맞는 제품이 있는 것을 우선한다.\n"
    "규칙: key 는 주어진 key 그대로. products 는 그 이벤트의 후보 제품명 중에서만 최대 3개 그대로 옮긴다. "
    "why 는 한국어 한 문장(40자 이내)으로, 숫자나 사실을 새로 지어내지 않는다."
)


def _trend_candidates(report: list[dict], allowed_ids: set[str] | None = None) -> list[dict]:
    """준비 기간이 지나지 않았고 맞는 제품이 있는 이벤트, 준비 임박 순.

    allowed_ids 가 있으면 그 회사 제품만 남긴다 (트렌드 매칭이 회사 구분 없이 제품을 모으므로 — RG-002).
    """
    cands = []
    for e in report or []:
        if not isinstance(e, dict):
            continue
        prods = [m for m in (e.get("matched_products") or []) if isinstance(m, dict) and m.get("product_name")
                 and (allowed_ids is None or m.get("product_id") in allowed_ids)]
        if prods and (e.get("peak_delta") or 0) >= 0:
            cands.append({**e, "matched_products": prods})
    cands.sort(key=lambda e: (max(e.get("prep_delta") or 0, 0), -(e.get("trend_score") or 0)))
    return cands[:10]


def _pick_trends_ai(cands: list[dict]) -> list[dict] | None:
    client = _ai()
    if client is None:
        return None
    facts = []
    for e in cands:
        prods = ", ".join(m["product_name"] for m in e["matched_products"][:6])
        facts.append(f"- key={e['key']} | {e['name']} | 준비까지 {e.get('prep_delta')}일 · 피크까지 "
                     f"{e.get('peak_delta')}일 | 설명: {e.get('description', '')[:80]} | 후보 제품: {prods}")
    try:
        res = client.complete_json(TREND_SYSTEM, "\n".join(facts), max_tokens=2000, schema=TREND_SCHEMA)
        items = res.get("items") if isinstance(res, dict) else None
        if not isinstance(items, list):
            return None
        by_key = {e["key"]: e for e in cands}
        picked, seen = [], set()
        for it in items:
            if not isinstance(it, dict):
                continue
            e = by_key.get(it.get("key"))
            if not e or e["key"] in seen:
                continue   # 없는 이벤트를 지어냈거나 중복 — 버린다
            seen.add(e["key"])
            allowed = {m["product_name"] for m in e["matched_products"]}
            prods = [p for p in (it.get("products") or []) if isinstance(p, str) and p in allowed][:3]
            picked.append({"event": e, "why": str(it.get("why") or "")[:80], "products": prods})
            if len(picked) == 3:
                break
    except Exception as ex:   # 호출·형식 어느 쪽이 깨져도 규칙으로 대체
        logger.warning("트렌드 AI 실패: %s", ex)
        return None
    if not picked:
        return None
    for e in cands:   # 3개가 안 되면 준비 임박 순으로 채운다
        if len(picked) >= 3:
            break
        if e["key"] not in {p["event"]["key"] for p in picked}:
            picked.append({"event": e, "why": "", "products": [m["product_name"] for m in e["matched_products"][:3]]})
    return picked


def send_trend_digest(db, company_id: int) -> dict:
    from app.models.trend_engine import TrendBriefing
    today = today_kst()
    b = db.query(TrendBriefing).filter(
        TrendBriefing.company_id == company_id, TrendBriefing.report_date == today.isoformat(),
    ).order_by(TrendBriefing.created_at.desc()).first()
    if not b or not b.report_data:
        return {"sent": False, "status": "skipped", "reason": "오늘 트렌드 브리핑 없음"}
    from app.models.product import Product
    allowed = {pid for (pid,) in db.query(Product.id).filter(Product.company_id == company_id).all()}
    cands = _trend_candidates(b.report_data, allowed)
    if not cands:
        return {"sent": False, "status": "skipped", "reason": "제품이 맞는 시즌 없음"}
    picked = _pick_trends_ai(cands) if sn.is_enabled(EV_TREND) else None
    by_ai = picked is not None
    if not picked:   # AI 없거나 실패 — 규칙으로 상위 3개
        picked = [{"event": e, "why": "", "products": [m["product_name"] for m in e["matched_products"][:3]]}
                  for e in cands[:3]]
    lines = [f"[레퍼런스] *[BP OS] 트렌드 — 지금 준비할 시즌 {len(picked)}개*"
             + ("  _(AI 선택)_" if by_ai else "")]
    for n, p in enumerate(picked, 1):
        e = p["event"]
        prep = e.get("prep_delta")
        when = f"준비 D-{prep}" if prep and prep > 0 else "지금 준비 시기"
        lines.append(f"\n{n}. *{e['name']}* ({when} · 피크 {str(e.get('peak_date', ''))[5:].replace('-', '/')})")
        if p["why"]:
            lines.append(f"   {p['why']}")
        if p["products"]:
            lines.append(f"   추천 제품: {', '.join(p['products'])}")
    return sn.post(EV_TREND, "marketing", "\n".join(lines), company_id=company_id,
                   dedupe_key=f"trend_digest:{today}")


# ── 01: 주간 요약 (월요일) ──────────────────────────────────────────────

def send_weekly_summary(db, company_id: int) -> dict:
    from app.models.campaign import Campaign
    today = today_kst()
    this_mon = today - timedelta(days=today.weekday())
    last_mon, last_sun, this_sun = this_mon - timedelta(days=7), this_mon - timedelta(days=1), this_mon + timedelta(days=6)
    q = db.query(Campaign).filter(Campaign.company_id == company_id,
                                  (Campaign.is_archived == False) | (Campaign.is_archived.is_(None)),  # noqa: E712
                                  (Campaign.status != "cancelled") | (Campaign.status.is_(None)))
    started = q.filter(Campaign.start_date >= last_mon, Campaign.start_date <= last_sun).all()
    ended = q.filter(Campaign.end_date >= last_mon, Campaign.end_date <= last_sun).all()
    will_start = q.filter(Campaign.start_date >= this_mon, Campaign.start_date <= this_sun).all()
    will_end = q.filter(Campaign.end_date >= this_mon, Campaign.end_date <= this_sun).all()
    f = lambda d: d.strftime("%m/%d")
    lines = [f"*[BP OS] 주간 공구 요약* ({f(this_mon)} 주)",
             f"\n*지난주* ({f(last_mon)}~{f(last_sun)}) — 오픈 {len(started)}건 · 마감 {len(ended)}건"]
    if started:
        lines += ["오픈"] + _names(started)
    if ended:
        lines += ["마감"] + _names(ended)
    lines.append(f"\n*이번 주* — 오픈 예정 {len(will_start)}건 · 마감 예정 {len(will_end)}건")
    if will_start:
        lines += ["오픈 예정"] + _names(will_start)
    if will_end:
        lines += ["마감 예정"] + _names(will_end)
    return sn.post(EV_WEEKLY, "notice", "\n".join(lines), company_id=company_id,
                   dedupe_key=f"weekly_summary:{this_mon}")


# ── 02: 아침 보고 AI 우선순위 ───────────────────────────────────────────

PRIORITY_SCHEMA = {
    "type": "object",
    "properties": {"ids": {"type": "array", "items": {"type": "string"}}},
    "required": ["ids"],
    "additionalProperties": False,
}

PRIORITY_SYSTEM = (
    "너는 인플루언서 공동구매 회사의 운영 매니저다. 오늘 할 수 있는 일 후보 목록(id: 설명)이 주어진다. "
    "담당자가 오늘 가장 먼저 해야 할 일을 최대 3개 골라 중요한 순서대로 id 만 돌려줘라. "
    "오늘 마감·오픈처럼 시간이 급한 것, 승인 대기처럼 다른 일을 막고 있는 것을 우선한다. "
    "목록에 없는 id 는 쓰지 않는다."
)

# 후보 종류 → (행동 문장, 이유). 문장은 코드가 쓴다 — AI 는 고르기만 (숫자·이름 지어내기 방지)
_ACTIONS = {
    "ending_today": ("오늘 마감 '{name}' 마무리 확인", "오늘 끝나는 공구"),
    "starting_today": ("오늘 오픈 '{name}' 오픈 확인", "오늘 시작하는 공구"),
    "ending_tomorrow": ("내일 마감 '{name}' 마감 안내 준비", "내일 끝나는 공구"),
    "starting_tomorrow": ("내일 오픈 '{name}' 오픈 준비", "내일 시작하는 공구"),
    "to_active": ("진행 전환 {n}건 승인", "승인해야 상태가 바뀌어요"),
    "to_completed": ("완료 전환 {n}건 승인", "승인해야 상태가 바뀌어요"),
    "archive": ("보관 {n}건 정리", "목록이 깔끔해져요"),
    "needs_review": ("일정 지난 기획·협의 {n}건 상태 확인", "일정은 지났는데 상태가 그대로예요"),
    "no_end_date": ("종료일 미입력 {n}건 채우기", "종료일이 없으면 마감 알림이 안 가요"),
}


def priority_candidates(d: dict) -> list[dict]:
    """아침 보고 데이터 → 후보 행동 [{id, todo, why}]. 정산(no_settlement)은 대표님 재검토 전까지 제외."""
    out = []
    for kind in ("ending_today", "starting_today", "ending_tomorrow", "starting_tomorrow"):
        for n, item in enumerate((d.get(kind) or [])[:5]):
            todo, why = _ACTIONS[kind]
            out.append({"id": f"{kind}:{n}", "todo": todo.format(name=item.get("name", "")), "why": why})
    p = d.get("pending") or {}
    for kind in ("to_active", "to_completed", "archive", "needs_review"):
        if p.get(kind):
            todo, why = _ACTIONS[kind]
            out.append({"id": kind, "todo": todo.format(n=p[kind]), "why": why})
    if d.get("no_end_date"):
        todo, why = _ACTIONS["no_end_date"]
        out.append({"id": "no_end_date", "todo": todo.format(n=len(d["no_end_date"])), "why": why})
    return out


def ai_priorities(d: dict) -> list[dict] | None:
    """오늘 먼저 할 일 최대 3개. 후보가 3개 이하면 AI 없이 그대로, 알릴 게 없으면 None."""
    if not sn.is_enabled(EV_DIGEST_AI):
        return None
    cands = priority_candidates(d)
    if not cands:
        return None
    if len(cands) <= 3:
        return cands
    client = _ai()
    if client is None:
        return None
    by_id = {c["id"]: c for c in cands}
    try:
        res = client.complete_json(PRIORITY_SYSTEM, "\n".join(f"{c['id']}: {c['todo']}" for c in cands),
                                   max_tokens=500, schema=PRIORITY_SCHEMA)
        ids = res.get("ids") if isinstance(res, dict) else None
        if not isinstance(ids, list):
            return None
        picked = []
        for i in ids:
            if isinstance(i, str) and i in by_id and by_id[i] not in picked:
                picked.append(by_id[i])
            if len(picked) == 3:
                break
        return picked or None
    except Exception as ex:
        logger.warning("아침 우선순위 AI 실패: %s", ex)
        return None


def render_priorities(items: list[dict]) -> str:
    lines = ["\n*오늘 먼저 할 일* _(순서는 AI 제안 — 판단은 담당자)_"]
    lines += [f"{n}. {i['todo']} — {i['why']}" for n, i in enumerate(items, 1)]
    return "\n".join(lines)
