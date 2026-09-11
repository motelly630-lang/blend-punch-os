#!/usr/bin/env python3
r"""blend-punch-os 프로젝트 메모리 공유 라이브러리.

`.claude/memory/` (커밋 대상, 팀 공유 지식) 와 `.claude/state/` (gitignore, 머신 로컬)
를 다루는 최소 기능만 담는다. 훅과 스킬이 공통으로 쓴다.

설계 원칙:
  - **stdlib 만 쓴다.** 훅은 WSL 의 /usr/bin/python3 로 돌고 외부 패키지를 가정할 수 없다
    (WSL 에 jq/sqlite3/rg 도 없다). 프론트매터도 직접 파싱한다.
  - **실패해도 작업을 막지 않는다.** 호출자(훅)는 항상 exit 0 해야 한다.
  - **원자적으로 쓴다.** 같은 디렉터리에 임시파일 → os.replace. 중단 시 반쪽 파일이 남지 않는다.

정규화 규칙 확인:  python3 .claude/lib/osmem.py --selftest
"""
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# 이 파일은 .claude/lib/ 에 있다 → parents[2] 가 프로젝트 루트
PROJECT = Path(__file__).resolve().parents[2]
MEM = PROJECT / ".claude" / "memory"
STATE_DIR = PROJECT / ".claude" / "state"
INDEX = MEM / "INDEX.md"
STATE = MEM / "state.json"

# type → (디렉터리, ID 접두)
TYPES = {
    "project": ("project", "PR"),
    "decision": ("decisions", "DE"),
    "preference": ("preferences", "PF"),
    "workflow": ("workflows", "WF"),
    "issue": ("issues", "IS"),
    "regression": ("regression", "RG"),
}

INDEX_MAX_LINES = 120  # SessionStart 주입 상한. 넘으면 잘라내고 알린다


# ── 훅 공통 ────────────────────────────────────────────────────────────────

def emit(payload):
    """훅 출력 규약 — stdout 에 JSON 한 줄. 기존 훅과 동일."""
    print(json.dumps(payload, ensure_ascii=False))


def hook_json():
    """훅 stdin 을 파싱한다. 실패하면 None (호출자가 '해당 없음' 과 구분해 보고)."""
    try:
        raw = sys.stdin.read()
    except Exception:
        return None
    if not raw or not raw.strip():
        return None
    try:
        return json.loads(raw.lstrip("\ufeff"))
    except Exception:
        return None


def to_posix(p):
    """훅이 준 파일 경로를 WSL POSIX 경로로 바꾼다. 못 바꾸면 마커를 돌려준다.

    os-build-css.sh / os-router-parity.py 에 복붙돼 있던 것을 여기로 모았다.
    동작을 바꾸면 두 훅이 함께 깨지므로 --selftest 로 확인한 뒤 바꾼다.
    """
    if not p:
        return "__EMPTY__"
    q = p.replace("\\", "/")
    m = re.match(r"^//wsl(?:\$|\.localhost)/[^/]+(/.*)$", q, re.I)
    if m:
        return m.group(1)
    if re.match(r"^[A-Za-z]:/", q):
        return "__NOT_IN_WSL__"      # Windows 드라이브 파일 — 이 프로젝트가 아니다
    if q.startswith("//"):
        return "__UNKNOWN_UNC__"     # 형태를 못 알아본 UNC — 알려야 한다
    return q


def rel(p):
    """프로젝트 루트 기준 상대경로 문자열. 밖이면 절대경로 그대로."""
    try:
        return str(Path(p).resolve().relative_to(PROJECT)).replace("\\", "/")
    except Exception:
        return str(p)


def now_iso():
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def today():
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


# ── 원자적 쓰기 ────────────────────────────────────────────────────────────

def write_atomic(path, text):
    """같은 디렉터리 임시파일에 쓰고 os.replace. 개행은 LF 로 고정한다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".osmem-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def append_line(path, text):
    """JSONL 저널용 append. 디렉터리가 없으면 만든다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(text.rstrip("\n") + "\n")


# ── 프론트매터 (직접 파싱 — 평평한 스칼라 + 리스트만 지원) ──────────────────

_SCALAR = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$")
_ITEM = re.compile(r"^\s*-\s+(.*)$")


def _unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def parse_frontmatter(text):
    """(meta, body). 프론트매터가 없으면 ({}, 원문).

    지원하는 형태만 다룬다 — 이 저장소의 스키마가 평평하기 때문이다:
        key: 값
        key: [a, b, c]
        key:
          - a
          - b
    """
    if not text.startswith("---"):
        return {}, text
    lines = text.split("\n")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    meta, key = {}, None
    for raw in lines[1:end]:
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        item = _ITEM.match(raw)
        if item and key:
            meta.setdefault(key, [])
            if isinstance(meta[key], list):
                meta[key].append(_unquote(item.group(1)))
            continue
        m = _SCALAR.match(raw)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val == "":
            meta[key] = []          # 다음 줄들이 - item 이면 리스트, 아니면 빈 값
        elif val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            meta[key] = [_unquote(x) for x in inner.split(",") if x.strip()] if inner else []
        else:
            meta[key] = _unquote(val)
    return meta, "\n".join(lines[end + 1:]).lstrip("\n")


def dump_frontmatter(meta):
    """meta 를 프론트매터 블록 문자열로. 키 순서를 고정해 diff 를 안정시킨다."""
    order = ["id", "type", "title", "status", "supersedes", "superseded_by",
             "tags", "paths", "updated"]
    keys = [k for k in order if k in meta] + [k for k in meta if k not in order]
    out = ["---"]
    for k in keys:
        v = meta[k]
        if isinstance(v, list):
            out.append("%s: [%s]" % (k, ", ".join(str(x) for x in v)))
        else:
            out.append("%s: %s" % (k, "" if v is None else v))
    out.append("---")
    return "\n".join(out)


def read_doc(path):
    """(meta, body). meta['_path'] 에 상대경로를 넣어준다."""
    p = Path(path)
    meta, body = parse_frontmatter(p.read_text(encoding="utf-8"))
    meta["_path"] = rel(p)
    return meta, body


def write_doc(path, meta, body):
    meta = {k: v for k, v in meta.items() if not k.startswith("_")}
    meta["updated"] = today()
    write_atomic(path, dump_frontmatter(meta) + "\n\n" + body.strip() + "\n")


def list_docs(types=None, status="active"):
    """메모리 문서 목록. status=None 이면 전부."""
    out = []
    wanted = set(types) if types else set(TYPES)
    for t in sorted(wanted):
        d = MEM / TYPES[t][0]
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.md")):
            try:
                meta, _ = read_doc(p)
            except Exception:
                continue
            if status and meta.get("status", "active") != status:
                continue
            meta.setdefault("type", t)
            out.append(meta)
    return out


def next_id(type_):
    """해당 type 의 다음 ID. 기존 최대값 +1 (status 무관, 번호 재사용 금지)."""
    if type_ not in TYPES:
        raise ValueError("unknown type: %s" % type_)
    sub, prefix = TYPES[type_]
    d = MEM / sub
    mx = 0
    if d.is_dir():
        for p in d.glob("*.md"):
            m = re.match(r"^%s-(\d+)" % prefix, p.name)
            if m:
                mx = max(mx, int(m.group(1)))
    return "%s-%03d" % (prefix, mx + 1)


def doc_path(type_, id_, slug):
    sub = TYPES[type_][0]
    slug = re.sub(r"[^a-z0-9가-힣]+", "-", slug.lower()).strip("-")[:48]
    return MEM / sub / ("%s-%s.md" % (id_, slug))


# ── state.json ─────────────────────────────────────────────────────────────

def default_state():
    return {
        "schema": 1,
        "project": "blend-punch-os",
        "state": "idle",            # idle | active | blocked
        "current_task": None,
        "tasks": [],                # [{id, title, status: todo|doing|done}]
        "last_checkpoint": None,    # {id, at, git}
        "memory": {"dirty": False, "updated": None},
        "session": {"id": None, "started": None, "last_seen": None},
    }


def load_state():
    try:
        st = json.loads(STATE.read_text(encoding="utf-8"))
        if isinstance(st, dict):
            base = default_state()
            base.update(st)
            return base
    except Exception:
        pass
    return default_state()


def save_state(st):
    write_atomic(STATE, json.dumps(st, ensure_ascii=False, indent=2) + "\n")


def progress(st):
    """(done, total, pct) — 체크리스트가 없으면 pct 는 None.

    **진행률을 추정하지 않는다.** tasks 가 비어 있으면 숫자를 만들지 않고 None 을 준다.
    """
    tasks = [t for t in (st.get("tasks") or []) if isinstance(t, dict)]
    total = len(tasks)
    if total == 0:
        return 0, 0, None
    done = sum(1 for t in tasks if t.get("status") == "done")
    return done, total, int(round(done * 100.0 / total))


# ── selftest ───────────────────────────────────────────────────────────────

def selftest():
    ok = True

    print("== to_posix ==")
    cases = [
        (r"\\wsl$\Ubuntu\home\blendpunch\blend-punch-os\app\routers\cs.py",
         "/home/blendpunch/blend-punch-os/app/routers/cs.py"),
        (r"\\wsl.localhost\Ubuntu\home\blendpunch\blend-punch-os\app\main.py",
         "/home/blendpunch/blend-punch-os/app/main.py"),
        ("/home/blendpunch/blend-punch-os/app/routers/cs.py",
         "/home/blendpunch/blend-punch-os/app/routers/cs.py"),
        (r"C:\Users\Mypc\AppData\Local\Temp\x.py", "__NOT_IN_WSL__"),
        (r"\\server\share\x.py", "__UNKNOWN_UNC__"),
        ("", "__EMPTY__"),
    ]
    for src, want in cases:
        got = to_posix(src)
        mark = "ok " if got == want else "FAIL"
        if got != want:
            ok = False
        print("  %s %-66s -> %s" % (mark, repr(src), got))

    print("== frontmatter 왕복 ==")
    sample = {
        "id": "DE-001", "type": "decision", "title": "테스트: 콜론도 들어간다",
        "status": "active", "tags": ["a", "b-c"], "paths": ["app/**"],
    }
    text = dump_frontmatter(sample) + "\n\n본문\n줄2\n"
    meta, body = parse_frontmatter(text)
    for k, v in sample.items():
        if meta.get(k) != v:
            ok = False
            print("  FAIL %s: %r != %r" % (k, meta.get(k), v))
    if body.strip() != "본문\n줄2":
        ok = False
        print("  FAIL body: %r" % body)
    print("  %s 스칼라/리스트/한글/콜론 보존" % ("ok " if ok else "FAIL"))

    print("== 블록 리스트 형태 ==")
    meta2, _ = parse_frontmatter("---\ntags:\n  - x\n  - y\nid: RG-009\n---\n본문\n")
    if meta2.get("tags") != ["x", "y"] or meta2.get("id") != "RG-009":
        ok = False
        print("  FAIL %r" % meta2)
    else:
        print("  ok  - item 형태 파싱")

    print("== progress (숫자 창작 금지) ==")
    if progress({"tasks": []}) != (0, 0, None):
        ok = False
        print("  FAIL 빈 체크리스트가 None 을 안 준다")
    else:
        print("  ok  빈 체크리스트 -> pct None")
    d, t, pct = progress({"tasks": [{"status": "done"}, {"status": "todo"},
                                    {"status": "done"}, {"status": "doing"}]})
    if (d, t, pct) != (2, 4, 50):
        ok = False
        print("  FAIL %r" % ((d, t, pct),))
    else:
        print("  ok  2/4 -> 50%")

    print("== 경로 ==")
    print("  PROJECT    = %s" % PROJECT)
    print("  MEM exists = %s" % MEM.is_dir())
    print("  INDEX      = %s (%s)" % (rel(INDEX), "있음" if INDEX.is_file() else "없음"))
    print("  STATE      = %s (%s)" % (rel(STATE), "있음" if STATE.is_file() else "없음"))
    counts = {}
    for t_ in TYPES:
        counts[t_] = len(list_docs([t_]))
    print("  문서 수(active) = %s" % counts)

    print("\n%s" % ("SELFTEST OK" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else 0)
