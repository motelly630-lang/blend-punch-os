"""공구 알림 문장 미리보기 (발송 안 함).

    .venv/bin/python scripts/campaign_digest.py            # 오늘 기준
    .venv/bin/python scripts/campaign_digest.py 2026-08-20 # 특정 날짜 기준

통로(카카오톡·이메일)를 붙이기 전에 '무슨 내용이 갈지' 확인하는 용도.
"""
from __future__ import annotations

import sys
from datetime import date

sys.path.insert(0, ".")

from app.database import SessionLocal
from app.services.campaign_alerts import build_digest, has_anything, render_text


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    base = date.fromisoformat(args[0]) if args else None

    db = SessionLocal()
    try:
        d = build_digest(db, base=base)
    finally:
        db.close()

    print("─" * 46)
    print(render_text(d))
    print("─" * 46)
    print(f"보낼 만한 내용 있음: {'예' if has_anything(d) else '아니오 (발송 생략)'}")
    for k, label in [("ending_today", "오늘 종료"), ("ending_tomorrow", "내일 종료"),
                     ("starting_today", "오늘 시작"), ("starting_tomorrow", "내일 시작"),
                     ("running", "진행중"), ("no_end_date", "종료일 없음")]:
        print(f"  {label}: {len(d[k])}")

    # --send 를 붙이면 실제 웹훅으로 보낸다 (ALERT_MOCK=false 여야 실발송)
    if "--send" in sys.argv:
        from app.services.webhook_notify import send_webhook
        r = send_webhook(render_text(d))
        print(f"\n발송: {'성공' if r['sent'] else '안 됨'} — {r['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
