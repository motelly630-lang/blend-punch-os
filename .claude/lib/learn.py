#!/usr/bin/env python3
r"""학습 반영(os-learn) 보조 도구 — 기계적으로 확인할 수 있는 것만 한다.

판단(무엇을 배웠나, 어디에 넣나)은 모델이 `/os-learn` 스킬 절차로 한다. 이 파일은
  pending   반영 기록이 없는 지난 세션 찾기 (SessionStart 훅이 한 줄로 알린다)
  lint      스킬·메모리·원장의 낡음·충돌·누락 점검
  metrics   git 기록으로 작업 사례의 객관 지표(커밋 수·fix 커밋 수·소요시간) 계산
만 한다. 대화 내용은 읽지 않는다 — 읽을 수 있는 것은 저널·git·파일뿐이다.

사용:
  python3 .claude/lib/learn.py pending
  python3 .claude/lib/learn.py lint
  python3 .claude/lib/learn.py metrics --since "2026-09-24 08:00" [--until ...] -- <경로...>
  python3 .claude/lib/learn.py --selftest
python3 stdlib 만 쓴다.
"""
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import osmem  # noqa: E402

LEARN = osmem.MEM / "learning"
LEDGER = LEARN / "LEDGER.md"
PROJECT_SKILLS = osmem.PROJECT / ".claude" / "skills"
GLOBAL_SKILLS = Path.home() / ".claude" / "skills"
PENDING_DAYS = 14

_ENTRY = re.compile(r"^### (IM-\d+) · (\d{4}-\d{2}-\d{2}) · (\w+)", re.M)
_STATUSES = {"proposed", "applied", "rejected", "reverted", "deferred"}


# ── 원장 ───────────────────────────────────────────────────────────────────────

def ledger_text():
    return LEDGER.read_text(encoding="utf-8") if LEDGER.is_file() else ""


def parse_ledger(text=None):
    """[{id, date, status, body}] — `### IM-001 · 2026-09-24 · applied` 헤더 단위."""
    text = ledger_text() if text is None else text
    heads = list(_ENTRY.finditer(text))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[m.end():end]
        body = body.split("\n## ", 1)[0]            # 다음 섹션 앞에서 자른다
        out.append({"id": m.group(1), "date": m.group(2), "status": m.group(3), "body": body})
    return out


def next_im_id(text=None):
    nums = [int(e["id"][3:]) for e in parse_ledger(text)]
    return "IM-%03d" % (max(nums) + 1 if nums else 1)


# ── pending ────────────────────────────────────────────────────────────────────

def pending(current_sid=None, state_dir=None, ledger=None, days=PENDING_DAYS):
    """반영 기록(원장에 세션 앞 8자리)이 없는 최근 세션의 저널 → [(sid8, 파일수, 날짜)]."""
    state_dir = Path(state_dir) if state_dir else osmem.STATE_DIR
    ledger = ledger_text() if ledger is None else ledger
    cutoff = time.time() - days * 86400
    out = []
    for j in sorted(state_dir.glob("journal-*.jsonl")):
        sid = j.stem[len("journal-"):]
        if current_sid and sid == current_sid:
            continue
        if j.stat().st_mtime < cutoff or sid[:8] in ledger:
            continue
        paths = set(re.findall(r'"path":\s*"([^"]+)"', j.read_text(encoding="utf-8", errors="replace")))
        if paths:
            out.append((sid[:8], len(paths), time.strftime("%Y-%m-%d", time.localtime(j.stat().st_mtime))))
    return out


# ── lint ───────────────────────────────────────────────────────────────────────

def _frontmatter(text):
    if not text.startswith("---"):
        return ""
    parts = text.split("---", 2)
    return parts[1] if len(parts) > 2 else ""


def _field(fm, key):
    m = re.search(r"^\s*%s:\s*(.+)$" % re.escape(key), fm, re.M)
    return m.group(1).strip().strip('"') if m else ""


def _triggers(desc):
    """description 속 트리거 표현: 큰따옴표 인용구 + '트리거 - a, b' 목록."""
    words = set(re.findall(r'"([^"]{2,30})"', desc))
    m = re.search(r"트리거\s*-\s*(.+)$", desc)
    if m:
        words |= {w.strip(" .") for w in m.group(1).split(",") if len(w.strip(" .")) >= 2}
    return words


def skill_files():
    out = []
    for root, scope in ((PROJECT_SKILLS, "project"), (GLOBAL_SKILLS, "global")):
        if root.is_dir():
            out += [(p, scope) for p in sorted(root.glob("*/SKILL.md"))]
    return out


def lint(today=None):
    """[(level, message)] — level: error | warn | info."""
    today = today or date.today().isoformat()
    found = []

    # 1) 스킬 프론트매터 · 재검토 기한 · 트리거 겹침
    owners = {}
    for p, scope in skill_files():
        fm = _frontmatter(p.read_text(encoding="utf-8"))
        name, desc = _field(fm, "name"), _field(fm, "description")
        tag = "%s:%s" % (scope, p.parent.name)
        if not name or not desc:
            found.append(("error", "%s — name/description 없음" % tag))
            continue
        ra = _field(fm, "review_after")
        if ra and ra < today:
            found.append(("warn", "%s — 재검토 기한(review_after %s) 지남" % (tag, ra)))
        for w in _triggers(desc):
            owners.setdefault(w, set()).add(tag)
    for w, tags in sorted(owners.items()):
        if len(tags) > 1:
            found.append(("info", "트리거 '%s' 가 여러 스킬에 있음: %s" % (w, ", ".join(sorted(tags)))))

    # 2) 메모리 문서 ↔ INDEX
    index = osmem.INDEX.read_text(encoding="utf-8") if osmem.INDEX.is_file() else ""
    if index.count("\n") + 1 > osmem.INDEX_MAX_LINES:
        found.append(("error", "INDEX.md 가 %d줄 상한을 넘음" % osmem.INDEX_MAX_LINES))
    for meta in osmem.list_docs(status=None):
        did, st = meta.get("id", ""), meta.get("status", "active")
        listed = re.search(r"^\|\s*%s\s*\|" % re.escape(did), index, re.M) is not None
        if st == "active" and not listed:
            found.append(("error", "%s (active) 가 INDEX 표에 없음" % did))
        if st == "superseded" and listed:
            found.append(("warn", "%s (superseded) 가 아직 INDEX 표에 있음" % did))

    # 3) 원장: 상태값 · applied 항목의 변경 파일 존재
    for e in parse_ledger():
        if e["status"] not in _STATUSES:
            found.append(("error", "%s 상태값 '%s' 는 허용 목록(%s)에 없음"
                          % (e["id"], e["status"], "/".join(sorted(_STATUSES)))))
        if e["status"] != "applied":
            continue
        m = re.search(r"^- 변경:(.*)$", e["body"], re.M)
        for path in re.findall(r"`([^`]+)`", m.group(1) if m else ""):
            if "/" not in path or " " in path:
                continue
            p = Path(path).expanduser()
            p = p if p.is_absolute() else osmem.PROJECT / p
            if not p.exists():
                found.append(("error", "%s 변경 파일이 없음: %s" % (e["id"], path)))
    return found


# ── metrics ────────────────────────────────────────────────────────────────────

def metrics(since, until=None, paths=()):
    """git 기록 기반 객관 지표. 대화 속 지적 횟수는 여기서 셀 수 없다(원장에 사람이 적는다)."""
    cmd = ["git", "log", "--format=%h|%ci|%s", "--since", since]
    if until:
        cmd += ["--until", until]
    cmd += ["--"] + list(paths)
    rows = subprocess.run(cmd, cwd=osmem.PROJECT, capture_output=True, text=True).stdout.strip()
    commits = [r.split("|", 2) for r in rows.splitlines() if r]
    commits.reverse()                               # 오래된 것부터
    fixes = [c for c in commits if c[2].startswith(("fix", "hotfix"))]
    span = "%s → %s" % (commits[0][1], commits[-1][1]) if commits else "—"
    return {"commits": len(commits), "fix_commits": len(fixes), "span": span,
            "list": ["%s %s %s" % (c[0], c[1][11:16], c[2][:70]) for c in commits]}


# ── CLI ────────────────────────────────────────────────────────────────────────

def selftest():
    import tempfile
    sample = ("# 원장\n\n## 항목\n\n### IM-001 · 2026-09-24 · applied\n- 세션: abcd1234\n"
              "- 변경: `CLAUDE.md`\n\n### IM-002 · 2026-09-24 · proposed\n- 변경: 없음\n\n## 검토 기록\n")
    es = parse_ledger(sample)
    assert [e["id"] for e in es] == ["IM-001", "IM-002"], es
    assert es[1]["status"] == "proposed" and "검토 기록" not in es[1]["body"]
    assert next_im_id(sample) == "IM-003" and next_im_id("") == "IM-001"
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "journal-abcd1234ffff.jsonl").write_text('{"path": "a.py"}\n', encoding="utf-8")
        (Path(d) / "journal-99998888eeee.jsonl").write_text('{"path": "b.py"}\n{"path": "c.py"}\n', encoding="utf-8")
        (Path(d) / "journal-77776666dddd.jsonl").write_text("", encoding="utf-8")
        got = pending(state_dir=d, ledger=sample)
        assert [(s, n) for s, n, _ in got] == [("99998888", 2)], got
        assert pending(current_sid="99998888eeee", state_dir=d, ledger=sample) == []
    assert "배포" in _triggers('설명 "배포해" 등. 트리거 - 배포, 서버')
    print("selftest ok")
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--selftest":
        return selftest()
    if argv[0] == "pending":
        rows = pending()
        for sid, n, d in rows:
            print("%s  세션 %s  수정 파일 %d개 — 반영 기록 없음" % (d, sid, n))
        if not rows:
            print("반영 대기 없음")
        return 0
    if argv[0] == "lint":
        found = lint()
        for level, msg in found:
            print("[%s] %s" % (level, msg))
        n = {k: sum(1 for lv, _ in found if lv == k) for k in ("error", "warn", "info")}
        print("error %(error)d · warn %(warn)d · info %(info)d" % n)
        return 1 if n["error"] else 0
    if argv[0] == "metrics":
        args, paths = argv[1:], []
        if "--" in args:
            i = args.index("--")
            args, paths = args[:i], args[i + 1:]
        opts = dict(zip(args[::2], args[1::2]))
        if "--since" not in opts:
            print("--since 가 필요하다")
            return 2
        m = metrics(opts["--since"], opts.get("--until"), paths)
        print("커밋 %d · fix 커밋 %d · 기간 %s" % (m["commits"], m["fix_commits"], m["span"]))
        for row in m["list"]:
            print("  " + row)
        return 0
    print("알 수 없는 명령: %s" % argv[0])
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
