"""인플루언서 인스타 프로필 자동 수집 (팔로워·프로필사진).

배경: 인플루언서 1,247명 중 1,117명이 핸들은 있는데 팔로워가 비어 있다.
셀러 매칭·제안서가 팔로워 수를 쓰기 때문에, 이게 비면 기능이 반쪽이 된다.

⚠️ instagrapi 는 비공식 방식이다. 한 번에 많이 긁으면 계정이 막힌다.
   - 한 실행당 기본 50명, 계정마다 랜덤 대기
   - 하루 1회 스케줄 → 1,117명이면 약 3주에 걸쳐 천천히 채워진다
   - 반드시 **전용(서브) 계정**을 쓸 것. 본인 계정이 막히면 업무가 마비된다
   - 성공·실패 모두 `enriched_at` 에 남겨서 같은 계정을 무한 재시도하지 않는다
"""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.influencer import Influencer

log = logging.getLogger(__name__)

# 신규 수집 계정 워밍업 기간용 보수적 기본값. 계정이 1~2주 버티는 걸 확인한 뒤
# .env 의 INFLUENCER_ENRICH_LIMIT 로 단계적으로 올린다 (10 → 20 → 50).
DEFAULT_LIMIT = 10
# 계정 사이 대기(초). 짧으면 차단 위험, 길면 진도가 안 난다.
SLEEP_RANGE = (4.0, 9.0)
# 한 번 시도한 계정은 이 기간 동안 다시 건드리지 않는다
RETRY_AFTER_DAYS = 30
# 연속 실패가 이만큼 나오면 그 실행을 접는다 (계정 차단·세션 만료 신호)
ABORT_AFTER_CONSECUTIVE_FAILS = 5


def pending_query(db: Session, company_id: int = 1):
    """수집 대상: 인스타 · 핸들 있음 · 팔로워 비어 있음 · 최근에 시도 안 한 것."""
    cutoff = datetime.utcnow() - timedelta(days=RETRY_AFTER_DAYS)
    return (db.query(Influencer)
              .filter(Influencer.company_id == company_id,
                      Influencer.is_archived.isnot(True),
                      Influencer.platform == "instagram",
                      Influencer.handle.isnot(None),
                      Influencer.handle != "",
                      or_(Influencer.followers == 0, Influencer.followers.is_(None)),
                      or_(Influencer.enriched_at.is_(None),
                          Influencer.enriched_at < cutoff))
              .order_by(Influencer.enriched_at.asc().nullsfirst(),
                        Influencer.created_at.asc()))


def pending_count(db: Session, company_id: int = 1) -> int:
    return pending_query(db, company_id).count()


def enrich_batch(db: Session, company_id: int = 1, limit: int = DEFAULT_LIMIT,
                 dry_run: bool = False, sleep: bool = True) -> dict:
    """대상 몇 명을 골라 프로필을 채운다.

    dry_run=True 면 누구를 어떤 순서로 긁을지만 알려주고 인스타에 접속하지 않는다.
    """
    targets = pending_query(db, company_id).limit(limit).all()
    rep = {
        "ok": True, "picked": len(targets), "updated": 0, "failed": 0,
        "remaining": 0, "rows": [], "error": None, "aborted": False,
    }
    if dry_run:
        rep["rows"] = [{"name": i.name, "handle": i.handle, "action": "예정"}
                       for i in targets]
        rep["remaining"] = max(0, pending_count(db, company_id) - len(targets))
        return rep

    if not targets:
        return rep

    try:
        from app.services.instagram import fetch_instagram_profile
    except Exception as e:                       # instagrapi 미설치 등
        rep.update(ok=False, error=f"인스타 모듈을 불러올 수 없습니다: {e}")
        return rep

    consecutive_fails = 0
    for idx, inf in enumerate(targets):
        handle = (inf.handle or "").lstrip("@").strip()
        now = datetime.utcnow()
        try:
            data = fetch_instagram_profile(handle)
            followers = int(data.get("followers") or 0)

            changed = []
            if followers > 0 and (inf.followers or 0) != followers:
                inf.followers = followers
                changed.append(f"팔로워 {followers:,}")
            # 프로필 사진은 비어 있을 때만 채운다 (사람이 올린 걸 덮지 않는다)
            img = data.get("profile_image_path")
            if img and not (inf.profile_image or "").strip():
                inf.profile_image = img
                changed.append("프로필사진")
            if not (inf.profile_url or "").strip():
                inf.profile_url = f"https://www.instagram.com/{handle}/"
                changed.append("프로필주소")

            inf.enriched_at = now
            inf.enrich_error = None
            rep["updated"] += 1
            consecutive_fails = 0
            rep["rows"].append({"name": inf.name, "handle": handle,
                                "action": "수집", "detail": ", ".join(changed) or "변경 없음"})
        except Exception as e:
            msg = str(e)[:190]
            inf.enriched_at = now          # 실패도 기록 — 무한 재시도 방지
            inf.enrich_error = msg
            rep["failed"] += 1
            consecutive_fails += 1
            rep["rows"].append({"name": inf.name, "handle": handle,
                                "action": "실패", "detail": msg})
            log.warning("인플루언서 수집 실패 %s: %s", handle, msg)

        db.commit()   # 한 명씩 확정 — 중간에 끊겨도 앞의 결과는 남는다

        if consecutive_fails >= ABORT_AFTER_CONSECUTIVE_FAILS:
            rep.update(aborted=True, ok=False,
                       error=(f"연속 {consecutive_fails}건 실패로 중단했습니다. "
                              "인스타 계정이 막혔거나 세션이 만료됐을 수 있습니다."))
            break

        if sleep and idx < len(targets) - 1:
            time.sleep(random.uniform(*SLEEP_RANGE))

    rep["remaining"] = pending_count(db, company_id)
    return rep
