"""공구 알림 문장 만들기.

발송 통로(카카오톡·이메일·슬랙)와 **분리**해 둔다. 알림 내용을 계산하는 일과
그걸 어디로 보내는 일은 다른 문제이고, 통로는 나중에 바뀔 수 있기 때문이다.
여기서는 "무엇을 알려야 하는가"만 정하고, 문자열로 내보낸다.

    from app.services.campaign_alerts import build_digest, render_text
    d = build_digest(db)
    print(render_text(d))
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.campaign import Campaign

KST = timezone(timedelta(hours=9))

# 알림 대상 상태 — 끝난 공구(completed)·취소는 알릴 게 없다
LIVE_STATUS = ("planning", "negotiating", "contracted", "active")


def today_kst() -> date:
    return datetime.now(KST).date()


def _label(c: Campaign) -> str:
    """알림에 쓸 한 줄 이름. 공구명에 이미 '제품 × 셀러'가 들어있는 경우가 많다."""
    return (c.name or "(이름 없음)").strip()


def _days(d: date | None, base: date) -> int | None:
    return (d - base).days if d else None


def build_digest(db: Session, company_id: int = 1,
                 base: date | None = None) -> dict:
    """오늘 기준으로 알려야 할 공구를 분류한다.

    반환: {"date", "ending_today", "ending_tomorrow", "starting_today",
           "starting_tomorrow", "running", "no_end_date"}
    각 항목은 [{name, start, end, status, dday}] 리스트.
    """
    base = base or today_kst()
    rows = (db.query(Campaign)
              .filter(Campaign.company_id == company_id,
                      Campaign.is_archived.isnot(True),
                      Campaign.status.in_(LIVE_STATUS))
              .all())

    out: dict[str, list[dict]] = {
        "ending_today": [], "ending_tomorrow": [],
        "starting_today": [], "starting_tomorrow": [],
        "running": [], "no_end_date": [],
    }
    for c in rows:
        item = {
            "name": _label(c), "start": c.start_date, "end": c.end_date,
            "status": c.status, "revenue": c.actual_revenue or 0,
            "dday": _days(c.end_date, base),
        }
        d_start = _days(c.start_date, base)
        d_end = item["dday"]

        if d_start == 0:
            out["starting_today"].append(item)
        elif d_start == 1:
            out["starting_tomorrow"].append(item)

        if d_end == 0:
            out["ending_today"].append(item)
        elif d_end == 1:
            out["ending_tomorrow"].append(item)

        # 진행중 = 시작했고 아직 안 끝난 것 (시작·종료 알림과 중복될 수 있다)
        if d_start is not None and d_start <= 0 and (d_end is None or d_end >= 0):
            out["running"].append(item)
        if c.start_date and not c.end_date:
            out["no_end_date"].append(item)

    for k in out:
        out[k].sort(key=lambda x: (x["end"] or date.max, x["name"]))
    out["date"] = base
    return out


def has_anything(d: dict) -> bool:
    """알릴 게 있는가 (없으면 굳이 보내지 않는다)."""
    return any(d[k] for k in ("ending_today", "ending_tomorrow",
                              "starting_today", "starting_tomorrow"))


def _lines(items: list[dict], show_end: bool = True) -> list[str]:
    out = []
    for i in items:
        when = f" (~{i['end'].strftime('%m/%d')})" if show_end and i["end"] else ""
        out.append(f"· {i['name']}{when}")
    return out


def render_text(d: dict, include_running: bool = True) -> str:
    """카카오톡·이메일·슬랙에 그대로 넣을 수 있는 짧은 텍스트.

    휴대폰에서 읽는 걸 전제로 짧게 유지한다 — 카카오톡 '나에게 보내기'는
    본문이 길면 잘린다.
    """
    day = d["date"].strftime("%m월 %d일")
    parts = [f"[블렌드펀치] {day} 공구 알림"]

    if d["ending_today"]:
        parts.append("\n오늘 종료 " + f"{len(d['ending_today'])}건")
        parts += _lines(d["ending_today"], show_end=False)
    if d["ending_tomorrow"]:
        parts.append("\n내일 종료 " + f"{len(d['ending_tomorrow'])}건")
        parts += _lines(d["ending_tomorrow"], show_end=False)
    if d["starting_today"]:
        parts.append("\n오늘 시작 " + f"{len(d['starting_today'])}건")
        parts += _lines(d["starting_today"])
    if d["starting_tomorrow"]:
        parts.append("\n내일 시작 " + f"{len(d['starting_tomorrow'])}건")
        parts += _lines(d["starting_tomorrow"])

    if include_running and d["running"]:
        parts.append(f"\n진행중 총 {len(d['running'])}건")

    if len(parts) == 1:
        parts.append("\n오늘 시작·종료하는 공구가 없습니다.")

    if d["no_end_date"]:
        parts.append(f"\n※ 종료일 미입력 {len(d['no_end_date'])}건 "
                     "— OS에서 채워주세요")
    return "\n".join(parts)
