"""#출근보고 — AI 직원들이 각자 이름·아이콘으로 아침 보고를 올린다 (대표님 2026-09-26, 1단계).

| 직원 | 보고 내용 (전부 OS DB 에서 코드가 센다 — AI·비용 없음) | 자세히 |
|---|---|---|
| 🛒 공구 매니저 | 오늘 마감 · 3일 안 마감 · 오늘 시작 · 진행 중 · 종료일 지났는데 완료 안 된 것 | /campaigns |
| 💰 정산 매니저 | 매출 미입력 끝난 공구 · 작성중 정산서 · 지급 대기 · 지급 예정일 지남 | /campaigns/revenue |
| 💬 고객 관리 매니저 | 어제 새 문의 · 처리 중 · 처리 기한 지남 · 긴급 (**고객 이름·연락처는 넣지 않는다**) | /cs |
| 📸 인플루언서 매니저 | 밤새 채운 인원 · 조회 안 됨 · 남은 대기 · 수집 0명이면 경고 | /influencers |
| 📈 트렌드 분석가 | 오늘 준비할 시즌 3개 (오늘 트렌드 브리핑이 있을 때만) | /trends |

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
    ("trend", "트렌드 분석가", ":chart_with_upwards_trend:"),
]


def _base_url() -> str:
    from app.config import settings
    return (settings.app_base_url or "").rstrip("/")


def _won(v) -> str:
    return f"{int(round(v or 0)):,}원"


def _camp_label(c) -> str:
    prod = c.product.name if getattr(c, "product", None) else (c.product_name_manual or "")
    inf = c.influencer.name if getattr(c, "influencer", None) else ""
    return " · ".join(x for x in (prod or c.name, inf) if x)


# ── 직원별 보고 만들기 — {"summary", "stats": [(이름, 값)], "lines": [...], "path"} 또는 None(보고 없음) ──

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
    return {"summary": summary, "path": "/campaigns", "lines": lines,
            "stats": [("진행 중", f"{len(running)}건"), ("오늘 마감", f"{len(ending_today)}건"),
                      ("3일 안 마감", f"{len(ending_soon)}건"), ("오늘 시작", f"{len(starting)}건")]}


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
    return {"summary": summary, "path": "/campaigns/revenue?tab=ended" if missing else "/settlements", "lines": lines,
            "stats": [("매출 미입력", f"{missing}건"), ("작성중", f"{draft_n}건 · {_won(draft_s)}"),
                      ("지급 대기", f"{wait_n}건 · {_won(wait_s)}"), ("예정일 지남", f"{late_n}건")]}


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
    summary = f"어제 새 문의 {new}건, 처리 중 {open_n}건이에요." + (f" 기한 지난 게 {late}건 있어요." if late else "")
    return {"summary": summary, "path": "/cs", "lines": lines,
            "stats": [("새 문의 (24시간)", f"{new}건"), ("처리 중", f"{open_n}건"),
                      ("기한 지남", f"{late}건"), ("긴급", f"{urgent}건")]}


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
    return {"summary": summary, "path": "/influencers", "lines": lines,
            "stats": [("어젯밤 채움", f"{filled}명"), ("조회 안 됨", f"{failed}명"), ("남은 대기", f"{waiting:,}명")]}


def build_trend(db, cid: int, today: date) -> dict | None:
    from app.models.product import Product
    from app.models.trend_engine import TrendBriefing
    from app.services.slack_reports import _trend_candidates
    b = (db.query(TrendBriefing).filter(TrendBriefing.company_id == cid, TrendBriefing.report_date == today.isoformat())
         .order_by(TrendBriefing.created_at.desc()).first())
    if not b or not b.report_data:
        return None
    allowed = {pid for (pid,) in db.query(Product.id).filter(Product.company_id == cid).all()}
    cands = _trend_candidates(b.report_data, allowed)[:3]
    if not cands:
        return None
    lines = []
    for e in cands:
        prep = e.get("prep_delta")
        when = f"준비 D-{prep}" if prep and prep > 0 else "지금 준비 시기"
        prods = ", ".join(m["product_name"] for m in e["matched_products"][:3])
        lines.append(f"• {e['name']} ({when})" + (f" — {prods}" if prods else ""))
    return {"summary": f"지금 준비할 시즌 {len(cands)}개예요: " + ", ".join(e["name"] for e in cands) + ".",
            "path": "/trends", "lines": lines, "stats": []}


BUILDERS = {"groupbuy": build_groupbuy, "settlement": build_settlement, "cs": build_cs,
            "influencer": build_influencer, "trend": build_trend}


# ── 카드 모양 (Block Kit) ──────────────────────────────────────────────

def render(name: str, r: dict) -> tuple[str, list]:
    """→ (알림용 한 줄 text, blocks). DB 에서 온 글자는 전부 escape (전원 호출·링크 위장 방지)."""
    e = sn.escape
    text = f"{name}: {r['summary']}"
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": e(r["summary"])}}]
    if r.get("stats"):
        blocks.append({"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*{e(k)}*\n{e(v)}"} for k, v in r["stats"][:10]]})
    if r.get("lines"):
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": e("\n".join(r["lines"][:12]))[:2900]}})
    if r.get("path") and _base_url():
        blocks.append({"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"자세히 → {e(_base_url() + r['path'])}"}]})
    return text, blocks


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
                 "stats": [], "lines": [], "path": ""}
        if r is not None:
            out.append({"key": key, "name": name, "icon": icon, "report": r})
    return out


def send_all(db, company_id: int, force: bool = False, dedupe: bool = True) -> dict:
    """모든 직원 보고를 #출근보고 로. 반환 {"status", "reason", "results"} — 하나라도 실패면 failed."""
    from app.services.slack_reports import today_kst
    today = today_kst()
    results = {}
    for s in collect(db, company_id, today):
        text, blocks = render(s["name"], s["report"])
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
            for s in collect(db, a.company):
                text, blocks = render(s["name"], s["report"])
                print(f"\n=== {s['icon']} {s['name']} ===\n{text}")
                for b in blocks[1:]:
                    t = b.get("text", {}).get("text") or " | ".join(
                        f.get("text", "").replace("\n", " ") for f in b.get("fields") or b.get("elements") or [])
                    print("  " + t.replace("\n", "\n  "))
    finally:
        db.close()
