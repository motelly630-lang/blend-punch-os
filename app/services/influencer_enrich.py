"""인플루언서 인스타 프로필 일괄 보강 (팔로워·프로필사진).

배경: 인플루언서 약 1,260명 중 대부분이 아이디만 있고 팔로워·사진이 비어 있다 (사진 보유 111명, 2026-09-23).
셀러 매칭·제안서가 팔로워 수를 쓰기 때문에, 이게 비면 기능이 반쪽이 된다.

수집 방식 (DE-006):
  - **Meta 공식 Business Discovery** (`meta_instagram`, META_PAGE_TOKEN 이 있으면). 봇 로그인 없음.
  - Meta 설정이 없을 때만 예전 instagrapi 경로 (비공식 — 운영에서 쓴 적 없음).

천천히·안전하게:
  - 한 실행당 `limit` 명, 사람 사이 짧은 대기
  - Meta 가 알려주는 사용량(%)이 USAGE_STOP_PCT 에 닿으면 그 실행을 스스로 멈춘다 (한도 여유 확보)
  - 한도 초과·토큰 끊김·통신 오류는 **그 사람을 실패로 적지 않고** 실행을 멈춘다 → 다음 실행에서 다시 시도
  - 개인 계정·없는 아이디(notfound)만 실패로 적고 RETRY_AFTER_DAYS 동안 다시 건드리지 않는다
  - 사람이 올린 사진·입력한 이름은 덮지 않는다. 팔로워는 Meta 값으로 갱신한다.

수동 실행 (서버에서 처음 한 번 지켜보며):
  .venv/bin/python -m app.services.influencer_enrich --dry-run
  .venv/bin/python -m app.services.influencer_enrich --limit 20
"""
from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.influencer import Influencer

log = logging.getLogger(__name__)

DEFAULT_LIMIT = 10
# 사람 사이 대기(초). Meta 공식 API 라 짧아도 되지만, 한 시간 몰아치기를 피한다.
SLEEP_RANGE = (1.5, 3.0)
# 조회 불가(개인 계정 등)로 끝난 계정은 이 기간 동안 다시 건드리지 않는다
RETRY_AFTER_DAYS = 30
# Meta 사용량이 이 %에 닿으면 그 실행을 멈춘다 (한도 100% 에 닿기 전 여유)
USAGE_STOP_PCT = 50.0
# 예전 instagrapi 경로: 연속 실패가 이만큼이면 접는다 (계정 차단·세션 만료 신호)
ABORT_AFTER_CONSECUTIVE_FAILS = 5
# 인스타에서 복사할 때 딸려 온 꼬리 글자 (예: "uu._.home ·")
_HANDLE_TAIL = re.compile(r"[\s·•・|,]+$")
# 아이디가 아니라 인스타 주소의 일부인 말 — 릴스·게시물 주소에서 잘못 뽑힌 값 (운영 2026-09-24: reels 2, 인스타그램 1).
# 이걸 Meta 에 조회하면 'reels' 라는 남의 계정 정보가 여러 사람에게 들어갈 수 있다 → 조회하지 않는다.
RESERVED_HANDLES = {"reels", "reel", "p", "tv", "stories", "explore", "accounts", "direct",
                    "instagram", "share", "s", "인스타그램", "www.instagram.com"}
_URL_ID = re.compile(r"instagram\.com/(?!(?:reels?|p|tv|stories|explore|accounts|direct|share|s)/)([A-Za-z0-9._]{1,30})")
# Meta 경로에서 실행을 멈추는 오류 — 그 사람 탓이 아니므로 기록하지 않고 다음 실행에서 다시 시도
_STOP_KINDS = {"rate", "token", "network"}


def pending_query(db: Session, company_id: int = 1):
    """대상: 인스타 · 아이디 있음 · (팔로워 비었거나 사진 비었음) · 최근 30일 안에 조회 불가로 끝나지 않은 것."""
    cutoff = datetime.utcnow() - timedelta(days=RETRY_AFTER_DAYS)
    return (db.query(Influencer)
              .filter(Influencer.company_id == company_id,
                      Influencer.is_archived.isnot(True),
                      Influencer.platform == "instagram",
                      Influencer.handle.isnot(None),
                      Influencer.handle != "",
                      or_(Influencer.followers == 0, Influencer.followers.is_(None),
                          Influencer.profile_image.is_(None), Influencer.profile_image == ""),
                      or_(Influencer.enriched_at.is_(None),
                          Influencer.enriched_at < cutoff))
              .order_by(Influencer.enriched_at.asc().nullsfirst(),
                        Influencer.created_at.asc()))


def pending_count(db: Session, company_id: int = 1) -> int:
    return pending_query(db, company_id).count()


def _apply(inf: Influencer, handle: str, followers: int, image_path: str) -> list[str]:
    """받은 값을 반영하고 바뀐 항목 이름 목록을 돌려준다."""
    changed = []
    if followers > 0 and (inf.followers or 0) != followers:
        inf.followers = followers
        changed.append(f"팔로워 {followers:,}")
    # 프로필 사진은 비어 있을 때만 채운다 (사람이 올린 걸 덮지 않는다)
    if image_path and not (inf.profile_image or "").strip():
        inf.profile_image = image_path
        changed.append("프로필사진")
    if not (inf.profile_url or "").strip():
        inf.profile_url = f"https://www.instagram.com/{handle}/"
        changed.append("프로필주소")
    return changed


def clean_handle(raw: str) -> str:
    """'@uu._.home ·' → 'uu._.home'. 앞의 @·공백, 뒤의 / · 공백 같은 복사 찌꺼기를 뗀다."""
    h = (raw or "").strip().lstrip("@").strip()
    return _HANDLE_TAIL.sub("", h).rstrip("/").strip()


def lookup_handle(inf: Influencer) -> str:
    """조회에 쓸 아이디. 저장된 아이디가 예약어(reels 등)면 프로필 주소 속 아이디, 그것도 없으면 ''."""
    h = clean_handle(inf.handle)
    if h.lower() not in RESERVED_HANDLES:
        return h
    m = _URL_ID.search(inf.profile_url or "")
    return m.group(1) if m and m.group(1).lower() not in RESERVED_HANDLES else ""


def _enrich_meta(db: Session, targets: list, rep: dict, sleep: bool) -> None:
    from app.services import meta_instagram as mi

    for idx, inf in enumerate(targets):
        handle = lookup_handle(inf)
        now = datetime.utcnow()
        try:
            if not handle:
                raise mi.MetaError("아이디가 잘못 저장돼 있어요 (예: reels) — 편집 화면에서 올바른 인스타 아이디를 넣어주세요",
                                   "notfound")
            prof = mi.fetch_profile(handle)
        except mi.MetaError as e:
            if e.kind in _STOP_KINDS:
                rep.update(ok=False, aborted=True, error=f"{e} — 이번 실행은 여기서 멈추고 다음 실행에서 이어갑니다.")
                rep["rows"].append({"name": inf.name, "handle": handle, "action": "중단", "detail": str(e)})
                break
            inf.enriched_at, inf.enrich_error = now, str(e)[:190]
            rep["failed"] += 1
            rep["rows"].append({"name": inf.name, "handle": handle, "action": "실패", "detail": str(e)})
        else:
            need_img = not (inf.profile_image or "").strip()
            img = mi.save_profile_image(prof["profile_picture_url"]) if need_img and prof["profile_picture_url"] else ""
            changed = _apply(inf, handle, prof["followers"], img)
            if prof.get("handle") and inf.handle != prof["handle"]:
                inf.handle = prof["handle"]            # 복사 찌꺼기·@ 를 뗀 인스타 공식 아이디로 정리
                changed.append("아이디 정리")
            inf.enriched_at, inf.enrich_error = now, None
            rep["updated"] += 1
            rep["rows"].append({"name": inf.name, "handle": handle, "action": "수집",
                                "detail": ", ".join(changed) or "변경 없음"})
        db.commit()   # 한 명씩 확정 — 중간에 끊겨도 앞의 결과는 남는다

        usage = mi.last_usage_pct
        rep["usage_pct"] = usage
        if usage is not None and usage >= USAGE_STOP_PCT:
            rep.update(aborted=True, error=f"Meta 사용량 {usage:.0f}% — 한도 여유를 남기려고 이번 실행을 멈춥니다.")
            break
        if sleep and idx < len(targets) - 1:
            time.sleep(random.uniform(*SLEEP_RANGE))


def _enrich_legacy(db: Session, targets: list, rep: dict, sleep: bool) -> None:
    """예전 instagrapi 경로 — Meta 설정이 없을 때만. 비공식이라 계정 차단 위험이 있다."""
    try:
        from app.services.instagram import fetch_instagram_profile
    except Exception as e:                       # instagrapi 미설치 등
        rep.update(ok=False, error=f"인스타 모듈을 불러올 수 없습니다: {e}")
        return
    consecutive_fails = 0
    for idx, inf in enumerate(targets):
        handle = (inf.handle or "").lstrip("@").strip()
        now = datetime.utcnow()
        try:
            data = fetch_instagram_profile(handle)
            changed = _apply(inf, handle, int(data.get("followers") or 0), data.get("profile_image_path") or "")
            inf.enriched_at, inf.enrich_error = now, None
            rep["updated"] += 1
            consecutive_fails = 0
            rep["rows"].append({"name": inf.name, "handle": handle, "action": "수집",
                                "detail": ", ".join(changed) or "변경 없음"})
        except Exception as e:
            msg = str(e)[:190]
            inf.enriched_at, inf.enrich_error = now, msg   # 실패도 기록 — 무한 재시도 방지
            rep["failed"] += 1
            consecutive_fails += 1
            rep["rows"].append({"name": inf.name, "handle": handle, "action": "실패", "detail": msg})
            log.warning("인플루언서 수집 실패 %s: %s", handle, msg)
        db.commit()
        if consecutive_fails >= ABORT_AFTER_CONSECUTIVE_FAILS:
            rep.update(aborted=True, ok=False,
                       error=(f"연속 {consecutive_fails}건 실패로 중단했습니다. "
                              "인스타 계정이 막혔거나 세션이 만료됐을 수 있습니다."))
            break
        if sleep and idx < len(targets) - 1:
            time.sleep(random.uniform(4.0, 9.0))


def enrich_batch(db: Session, company_id: int = 1, limit: int = DEFAULT_LIMIT,
                 dry_run: bool = False, sleep: bool = True) -> dict:
    """대상 몇 명을 골라 프로필을 채운다.

    dry_run=True 면 누구를 어떤 순서로 조회할지만 알려주고 외부에 접속하지 않는다.
    """
    from app.services import meta_instagram as mi

    targets = pending_query(db, company_id).limit(limit).all()
    rep = {
        "ok": True, "picked": len(targets), "updated": 0, "failed": 0,
        "remaining": 0, "rows": [], "error": None, "aborted": False,
        "source": "meta" if mi.available() else "instagrapi", "usage_pct": None,
    }
    if dry_run:
        rep["rows"] = [{"name": i.name, "handle": i.handle, "action": "예정"} for i in targets]
        rep["remaining"] = max(0, pending_count(db, company_id) - len(targets))
        return rep
    if targets:
        (_enrich_meta if rep["source"] == "meta" else _enrich_legacy)(db, targets, rep, sleep)
    rep["remaining"] = pending_count(db, company_id)
    return rep


def _main(argv: list[str]) -> int:
    import argparse
    from app.database import SessionLocal

    ap = argparse.ArgumentParser(description="인플루언서 인스타 프로필 일괄 보강")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--company-id", type=int, default=1)
    a = ap.parse_args(argv)
    db = SessionLocal()
    try:
        rep = enrich_batch(db, company_id=a.company_id, limit=a.limit, dry_run=a.dry_run)
    finally:
        db.close()
    for r in rep["rows"]:
        print(f"  [{r['action']}] {r['name']} @{r['handle']}  {r.get('detail', '')}")
    print(f"방식 {rep['source']} · 대상 {rep['picked']} · 수집 {rep['updated']} · 실패 {rep['failed']} "
          f"· 남은 대기 {rep['remaining']} · 사용량 {rep['usage_pct']}%")
    if rep["error"]:
        print("멈춤:", rep["error"])
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv[1:]))
