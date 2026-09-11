#!/usr/bin/env python3
r"""PostToolUse(Write|Edit) 훅 — 이번 세션에서 무엇을 건드렸는지 기계적으로만 기록한다.

**영구 메모리를 쓰지 않는다.** LLM 판단도, 승인도 없다. 그냥 {시각, 도구, 경로} 한 줄을
`.claude/state/journal-<session>.jsonl` 에 덧붙일 뿐이다. 이 저널은 머신 로컬이고
gitignore 대상이며, 나중에 `/os-mem save` 가 "이번에 뭘 했더라" 를 복원하는 재료로 쓴다.

이 분리가 설계의 핵심이다 — 훅은 사실만 모으고, 무엇을 영구 기억할지는 사람이 정한다.

절대 작업을 막지 않는다: 어떤 예외가 나도 exit 0, 출력도 내지 않는다(조용한 성공).
저널 기록 실패는 작업 실패가 아니다.

확인:  python3 .claude/hooks/os-mem-journal.py --selftest
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import osmem  # noqa: E402

# 저널에 남기지 않을 경로 — 메모리 시스템 자신이 만드는 잡음을 거른다
SKIP_PREFIXES = (".claude/state/", ".claude/memory/state.json")


def journal_path(session_id):
    sid = (session_id or "unknown")[:40]
    return osmem.STATE_DIR / ("journal-%s.jsonl" % sid)


def extract(d):
    """(tool, posix_path) — 대상이 아니면 (None, None)."""
    tool = d.get("tool_name") or ""
    if tool not in ("Write", "Edit", "NotebookEdit"):
        return None, None
    ti = d.get("tool_input") or {}
    tr = d.get("tool_response") or {}
    raw = ti.get("file_path") or tr.get("filePath") or ""
    p = osmem.to_posix(raw)
    if p.startswith("__"):          # __EMPTY__ / __NOT_IN_WSL__ / __UNKNOWN_UNC__
        return None, None
    return tool, p


def record(d):
    tool, p = extract(d)
    if not tool:
        return None
    rel = osmem.rel(p)
    if rel.startswith(SKIP_PREFIXES):
        return None
    entry = {
        "ts": osmem.now_iso(),
        "tool": tool,
        "path": rel,
        "prompt_id": d.get("prompt_id"),
    }
    osmem.append_line(journal_path(d.get("session_id")), json.dumps(entry, ensure_ascii=False))
    return entry


def main():
    try:
        d = osmem.hook_json()
        if d:
            record(d)
    except Exception:
        pass        # 저널 실패가 작업을 막아서는 안 된다
    # 출력 없음 — 매 수정마다 메시지를 띄우면 그게 더 방해다


def selftest():
    samples = [
        {"tool_name": "Edit", "session_id": "selftest",
         "tool_input": {"file_path": r"\\wsl$\Ubuntu\home\blendpunch\blend-punch-os\app\routers\cs.py"}},
        {"tool_name": "Write", "session_id": "selftest",
         "tool_input": {"file_path": "/home/blendpunch/blend-punch-os/app/main.py"}},
        {"tool_name": "Edit", "session_id": "selftest",
         "tool_input": {"file_path": r"C:\Users\Mypc\x.txt"}},          # 프로젝트 밖 → 무시
        {"tool_name": "Read", "session_id": "selftest",
         "tool_input": {"file_path": "/home/blendpunch/blend-punch-os/app/main.py"}},  # 대상 아님
        {"tool_name": "Write", "session_id": "selftest",
         "tool_input": {"file_path": "/home/blendpunch/blend-punch-os/.claude/state/x"}},  # 자기 잡음
    ]
    jp = journal_path("selftest")
    if jp.exists():
        jp.unlink()
    for s in samples:
        r = record(s)
        print("  %-8s %-56s -> %s" % (
            s["tool_name"], s["tool_input"]["file_path"][:56],
            r["path"] if r else "기록 안 함"))
    print("\n저널 파일: %s" % osmem.rel(jp))
    if jp.exists():
        for ln in jp.read_text(encoding="utf-8").strip().split("\n"):
            print("  " + ln)
        jp.unlink()
        print("(셀프테스트 저널 삭제함)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    main()
