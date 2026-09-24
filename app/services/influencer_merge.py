"""중복 인플루언서 합치기 (T9).

같은 인스타 아이디로 두 번 이상 등록된 인플루언서를 한 줄로 합친다. 운영 2026-09-24: 32묶음·66명.

규칙
  - 묶음: 회사 안 · 보관 안 된 것 · 아이디(복사 찌꺼기·@ 제거, 소문자)가 같은 것. reels 같은 예약어는 제외.
  - 남길 줄(keeper): 정산 > 캠페인 > 그 밖의 기록이 많은 줄 → 진짜 이름 → 팔로워 → 사진 → 먼저 만든 줄.
  - 합치기: keeper 의 **빈 칸만** 채운다 (이미 있는 값은 덮지 않는다). 기록(influencer_id 를 가진 모든 표)은 keeper 로 옮긴다.
  - 사라지는 줄은 지우지 않고 보관(is_archived) — 블랜드픽이 그 번호를 가리켜도 깨지지 않게 (PR-003).
  - 자동 합치기 제외: 계좌·사업자·연락처·시트 번호가 서로 다름(충돌) · 블랜드픽 연결(회원·포털·서류) 있음.
  - 되돌리기: 옮긴 행·바꾼 칸의 원래 값을 InfluencerMergeLog 에 남긴다.
"""
from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.models.influencer import Influencer
from app.models.influencer_merge_log import InfluencerMergeLog
from app.services.influencer_enrich import RESERVED_HANDLES, clean_handle

_VALID = re.compile(r"^[a-z0-9._]{1,30}$")
# 합치지 않고 남기는 칸
_SKIP = {"id", "company_id", "created_at", "updated_at", "is_archived", "enriched_at", "enrich_error",
         "name", "handle", "notes", "categories", "followers", "has_campaign_history"}
# 두 줄 값이 다르면 사람이 골라야 하는 칸 (돈·연락·시트 연결)
CONFLICT_FIELDS = ("bank_name", "account_number", "account_holder", "business_type",
                   "business_registration_number", "legal_name", "contact_phone", "contact_email", "sheet_code")
# 블랜드픽이 OS 인플루언서 표에 직접 추가한 칸 — 값이 있으면 블랜드픽과 연결된 사람 (PR-003)
# (bank_account·bank_holder·phone·tax_email 은 블랜드픽 쪽 돈·연락 칸 — OS 모델에 없어 채우거나 비교할 수 없으므로 값이 있으면 막는다)
BLENDPICK_LINK_COLS = ("user_id", "shop_managed", "portal_password", "bankbook_file", "id_card_file", "biz_cert_file",
                       "bank_account", "bank_holder", "phone", "tax_email")
_REF_WEIGHT = {"settlements": 100, "campaigns": 10}


def key_of(handle: str | None) -> str:
    k = clean_handle(handle).lower()
    return k if _VALID.match(k) and k not in RESERVED_HANDLES else ""


def _empty(v) -> bool:
    return v is None or v == "" or v == 0 or v == [] or v == {} or v == "false"


def _norm(field: str, v) -> str:
    s = str(v or "").strip()
    if field in ("contact_phone", "account_number", "business_registration_number"):
        return re.sub(r"\D", "", s)
    return s.lower().replace(" ", "")


def _q(db: Session, name: str) -> str:
    """표 이름을 DB 문법에 맞게 감싼다 (대문자·특수문자 표 이름 대비). 이름은 DB 에서 읽은 값뿐이다."""
    return db.get_bind().dialect.identifier_preparer.quote(name)


def _ref_tables_all(db: Session) -> tuple[list[str], list[str]]:
    """(id 가 있는 참조 표, id 가 없는 참조 표) — influencer_id 칸을 가진 표 전부를 DB 에서 직접 확인."""
    insp = inspect(db.get_bind())
    ok, no_id = [], []
    for t in insp.get_table_names():
        if t in ("influencers", InfluencerMergeLog.__tablename__):
            continue
        cols = {c["name"] for c in insp.get_columns(t)}
        if "influencer_id" in cols:
            (ok if "id" in cols else no_id).append(t)
    return sorted(ok), sorted(no_id)


def ref_tables(db: Session) -> list[str]:
    return _ref_tables_all(db)[0]


def _ref_counts(db: Session, tables: list[str], ids: list[str]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {i: {} for i in ids}
    if not ids:
        return out
    for t in tables:
        rows = db.execute(text(f"SELECT influencer_id, COUNT(*) FROM {_q(db, t)} WHERE influencer_id IN :ids GROUP BY influencer_id")
                          .bindparams(_ids_param()), {"ids": ids}).fetchall()
        for iid, n in rows:
            out.setdefault(iid, {})[t] = n
    return out


def _ids_param():
    from sqlalchemy import bindparam
    return bindparam("ids", expanding=True)


def _blendpick_linked(db: Session, ids: list[str]) -> set[str]:
    insp = inspect(db.get_bind())
    cols = [c for c in BLENDPICK_LINK_COLS if c in {x["name"] for x in insp.get_columns("influencers")}]
    if not cols or not ids:
        return set()
    cond = " OR ".join(f"({c} IS NOT NULL AND CAST({c} AS VARCHAR) NOT IN ('', 'false', '0'))" for c in cols)
    rows = db.execute(text(f"SELECT id FROM influencers WHERE id IN :ids AND ({cond})").bindparams(_ids_param()),
                      {"ids": ids}).fetchall()
    return {r[0] for r in rows}


def _score(inf: Influencer, refs: dict[str, int]) -> tuple:
    rec = sum(n * _REF_WEIGHT.get(t, 1) for t, n in refs.items())
    real_name = key_of(inf.name) != key_of(inf.handle)
    return (rec, real_name, (inf.followers or 0) > 0, bool((inf.profile_image or "").strip()),
            -(inf.created_at.timestamp() if inf.created_at else 0))


def conflicts(keeper: Influencer, other: Influencer) -> list[str]:
    out = []
    for f in CONFLICT_FIELDS:
        a, b = getattr(keeper, f, None), getattr(other, f, None)
        if not _empty(a) and not _empty(b) and _norm(f, a) != _norm(f, b):
            out.append(f)
    return out


def group_blocks(db: Session, members: list[Influencer]) -> list[str]:
    """이 묶음을 자동으로 합치면 안 되는 이유 목록 (비었으면 합쳐도 된다).

    충돌은 **모든 쌍**을 본다 — 남길 줄이 비어 있고 나머지 둘의 계좌가 다르면 한쪽이 조용히 묻히기 때문.
    """
    out = []
    for i, a in enumerate(members):
        for b in members[i + 1:]:
            c = conflicts(a, b)
            if c:
                out.append(f"{a.name} ↔ {b.name}: 값이 서로 다름 — {', '.join(c)}")
    st = {m.status for m in members}
    if "blacklist" in st and len(st) > 1:
        out.append("블랙리스트인 줄과 아닌 줄이 섞여 있음 — 직접 확인 필요")
    ids = [m.id for m in members]
    if _blendpick_linked(db, ids):
        out.append("블랜드픽과 연결된 사람(회원·서류·계좌 칸)이 있음 — 개발자 확인 필요")
    _, no_id = _ref_tables_all(db)
    for t in no_id:
        n = db.execute(text(f"SELECT COUNT(*) FROM {_q(db, t)} WHERE influencer_id IN :ids").bindparams(_ids_param()),
                       {"ids": ids}).scalar()
        if n:
            out.append(f"{t} 표에 기록이 있는데 옮길 수 없음(id 칸 없음) — 개발자 확인 필요")
    return out


def find_groups(db: Session, company_id: int) -> list[dict]:
    rows = (db.query(Influencer)
              .filter(Influencer.company_id == company_id, Influencer.is_archived.isnot(True))
              .all())
    by_key: dict[str, list[Influencer]] = {}
    for r in rows:
        k = key_of(r.handle)
        if k:
            by_key.setdefault(k, []).append(r)
    dup = {k: v for k, v in by_key.items() if len(v) > 1}
    ids = [i.id for v in dup.values() for i in v]
    tables = ref_tables(db)
    refs = _ref_counts(db, tables, ids)
    linked = _blendpick_linked(db, ids)
    groups = []
    for k, members in sorted(dup.items()):
        members = sorted(members, key=lambda m: _score(m, refs.get(m.id, {})), reverse=True)
        keeper = members[0]
        blocked = group_blocks(db, members)
        groups.append({
            "key": k, "keeper_id": keeper.id, "blocked": blocked,
            "members": [{"inf": m, "refs": refs.get(m.id, {}), "blendpick": m.id in linked} for m in members],
        })
    return groups


def _set(inf: Influencer, field: str, value, log: dict) -> None:
    """값을 바꾸고 [바꾸기 전, 바꾼 뒤] 를 남긴다 (같은 칸을 두 번 바꾸면 처음 값은 유지)."""
    before = log[field][0] if field in log else getattr(inf, field)
    setattr(inf, field, value)
    log[field] = [before, value]


def merge_group(db: Session, company_id: int, keeper_id: str, member_ids: list[str], by: str = "") -> list[InfluencerMergeLog]:
    """keeper 로 나머지를 합친다. 조건이 안 맞으면 ValueError (아무것도 바꾸지 않음)."""
    ids = list(dict.fromkeys([keeper_id] + list(member_ids)))
    rows = (db.query(Influencer)
              .filter(Influencer.company_id == company_id, Influencer.id.in_(ids),
                      Influencer.is_archived.isnot(True))
              .all())
    by_id = {r.id: r for r in rows}
    if len(by_id) != len(ids) or len(ids) < 2:
        raise ValueError("합칠 인플루언서를 찾지 못했어요 (다른 회사이거나 이미 보관됨)")
    keeper = by_id[keeper_id]
    k = key_of(keeper.handle)
    if not k or any(key_of(r.handle) != k for r in rows):
        raise ValueError("아이디가 같은 인플루언서끼리만 합칠 수 있어요")
    blocks = group_blocks(db, [by_id[i] for i in ids])
    if blocks:
        raise ValueError(" / ".join(blocks))
    others = [by_id[i] for i in ids if i != keeper_id]

    tables = ref_tables(db)
    cols = [c.name for c in Influencer.__table__.columns]
    logs = []
    for o in others:
        keeper_before, merged_before, moved = {}, {}, {}   # 칸 → [합치기 전 값, 합친 뒤 값]
        # 1) keeper 빈 칸 채우기
        for f in cols:
            if f in _SKIP:
                continue
            if _empty(getattr(keeper, f)) and not _empty(getattr(o, f)):
                _set(keeper, f, getattr(o, f), keeper_before)
        if key_of(keeper.name) == key_of(keeper.handle) and key_of(o.name) != key_of(o.handle) and (o.name or "").strip():
            _set(keeper, "name", o.name, keeper_before)            # 아이디만 적힌 이름 → 진짜 이름
        if (o.followers or 0) > (keeper.followers or 0):
            _set(keeper, "followers", o.followers, keeper_before)
        cats = list(dict.fromkeys((keeper.categories or []) + (o.categories or [])))
        if cats != (keeper.categories or []):
            _set(keeper, "categories", cats, keeper_before)
        if o.has_campaign_history == "true" and keeper.has_campaign_history != "true":
            _set(keeper, "has_campaign_history", "true", keeper_before)
        if (o.notes or "").strip() and (o.notes or "").strip() not in (keeper.notes or ""):
            _set(keeper, "notes", ((keeper.notes or "").rstrip() + "\n" + o.notes.strip()).strip(), keeper_before)

        # 2) 기록 옮기기
        for t in tables:
            qt = _q(db, t)
            rid = [r[0] for r in db.execute(text(f"SELECT id FROM {qt} WHERE influencer_id = :m"), {"m": o.id}).fetchall()]
            if rid:
                db.execute(text(f"UPDATE {qt} SET influencer_id = :k WHERE influencer_id = :m"), {"k": keeper.id, "m": o.id})
                moved[t] = rid

        # 3) 보관 — 시트 번호는 keeper 로 옮겼으므로 비운다 (시트 동기화가 보관된 줄을 되살리지 않게)
        _set(o, "is_archived", True, merged_before)
        if o.sheet_code and keeper.sheet_code == o.sheet_code:
            _set(o, "sheet_code", None, merged_before)
        stamp = datetime.utcnow().strftime("%Y-%m-%d")
        _set(o, "notes", ((o.notes or "").rstrip() + f"\n[병합 {stamp}] → {keeper.name} ({keeper.id})").strip(), merged_before)

        # 기록마다 시각을 따로 찍는다 — 되돌리기가 "나중 합치기부터" 순서를 가릴 수 있게
        log = InfluencerMergeLog(company_id=company_id, keeper_id=keeper.id, merged_id=o.id, moved=moved,
                                 keeper_before=keeper_before, merged_before=merged_before, merged_by=by or None,
                                 created_at=datetime.utcnow())
        db.add(log)
        logs.append(log)
    db.commit()
    return logs


def undo(db: Session, company_id: int, log_id: str) -> InfluencerMergeLog:
    """합치기 1건을 되돌린다. 옮긴 행을 원래 사람에게 돌려놓고, 바꾼 칸을 원래 값으로."""
    log = db.query(InfluencerMergeLog).filter(InfluencerMergeLog.id == log_id,
                                              InfluencerMergeLog.company_id == company_id).first()
    if not log or log.undone_at:
        raise ValueError("되돌릴 합치기 기록이 없어요 (이미 되돌렸거나 다른 회사)")
    keeper = db.query(Influencer).filter(Influencer.id == log.keeper_id, Influencer.company_id == company_id).first()
    merged = db.query(Influencer).filter(Influencer.id == log.merged_id, Influencer.company_id == company_id).first()
    if not keeper or not merged:
        raise ValueError("합쳤던 인플루언서를 찾지 못했어요")
    if keeper.is_archived:
        raise ValueError("남긴 줄이 그 뒤 다른 줄로 다시 합쳐졌어요 — 나중 합치기부터 되돌려 주세요")
    later = (db.query(InfluencerMergeLog)
               .filter(InfluencerMergeLog.company_id == company_id, InfluencerMergeLog.keeper_id == log.keeper_id,
                       InfluencerMergeLog.undone_at.is_(None), InfluencerMergeLog.created_at > log.created_at)
               .count())
    if later:
        raise ValueError("같은 사람에게 그 뒤에 합친 기록이 있어요 — 최근 것부터 차례로 되돌려 주세요")
    for t, rids in (log.moved or {}).items():
        if not rids:
            continue
        res = db.execute(text(f"UPDATE {_q(db, t)} SET influencer_id = :m WHERE id IN :ids AND influencer_id = :k")
                         .bindparams(_ids_param()), {"m": merged.id, "k": keeper.id, "ids": rids})
        if res.rowcount != len(rids):
            db.rollback()
            raise ValueError(f"{t} 기록이 그 뒤에 바뀌어 전부 되돌릴 수 없어요 ({res.rowcount}/{len(rids)}) — 아무것도 바꾸지 않았어요")
    skipped = []
    for obj, changes in ((keeper, log.keeper_before or {}), (merged, log.merged_before or {})):
        for f, (before, after) in changes.items():
            if getattr(obj, f) == after:
                setattr(obj, f, before)
            else:
                skipped.append(f)          # 합친 뒤 사람이 고친 값 — 덮지 않는다
    log.undone_at = datetime.utcnow()
    db.commit()
    log.skipped = skipped
    return log
