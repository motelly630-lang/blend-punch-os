#!/usr/bin/env python3
r"""SessionEnd / PreCompact 훅 — state.json 을 디스크에 확정한다.

⚠️ **SessionEnd 는 모든 훅을 합쳐 1.5초 예산이다.** 그래서 여기서는 LLM 호출도,
요약도, 무거운 탐색도 하지 않는다. 파일 몇 개 읽고 JSON 하나 쓰는 것이 전부다.

"세션 끝에 대화를 요약해 영구 저장" 은 이 지점에서 구조적으로 불가능하다.
그래서 추출은 세션 *중* 경계(`/os-mem save`)로 옮겼고, 여기서는
"이번 세션에 무엇을 건드렸는지"만 state 에 남겨 다음 세션이 이어받게 한다.

PreCompact 에도 같은 스크립트를 물린다 — 압축으로 맥락이 날아가기 전에 저장해 둔다.

확인:  python3 .claude/hooks/os-mem-flush.py --selftest
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import osmem  # noqa: E402

MAX_FILES_SHOWN = 12


def journal_summary(session_id):
    """(수정 파일 수, 최근 파일 목록). 저널이 없으면 (0, [])."""
    sid = (session_id or "unknown")[:40]
    jp = osmem.STATE_DIR / ("journal-%s.jsonl" % sid)
    if not jp.is_file():
        return 0, []
    paths = []
    try:
        for ln in jp.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            try:
                e = json.loads(ln)
            except Exception:
                continue
            p = e.get("path")
            if p and p not in paths:
                paths.append(p)
    except Exception:
        return 0, []
    return len(paths), paths[-MAX_FILES_SHOWN:]


def flush(d, reason):
    st = osmem.load_state()
    sid = (d or {}).get("session_id")
    sess = st.get("session") or {}
    if sid:
        sess["id"] = sid
    sess["last_seen"] = osmem.now_iso()
    sess["last_event"] = reason
    n, paths = journal_summary(sid)
    if n:
        sess["touched_files"] = n
        sess["recent_files"] = paths
        # 저널에 내용이 있는데 아직 큐레이션하지 않았다 = 저장 후보가 남아 있다
        mem = st.get("memory") or {}
        mem["dirty"] = True
        st["memory"] = mem
    st["session"] = sess
    osmem.save_state(st)
    return n, paths


def main():
    try:
        d = osmem.hook_json() or {}
        reason = d.get("hook_event_name") or "unknown"
        n, _ = flush(d, reason)
        if n:
            # SessionEnd 출력은 어차피 표시되지 않지만, PreCompact 에서는 유용하다
            osmem.emit({"systemMessage": "💾 상태 저장 (이번 세션 수정 파일 %d개)" % n})
    except Exception:
        pass        # 세션 종료를 막지 않는다


def selftest():
    st = osmem.load_state()
    print("현재 state:")
    print("  state        : %s" % st.get("state"))
    print("  current_task : %s" % st.get("current_task"))
    d, t, pct = osmem.progress(st)
    print("  progress     : %s" % ("— (체크리스트 없음)" if pct is None else "%d%% (%d/%d)" % (pct, d, t)))
    print("  session      : %s" % json.dumps(st.get("session"), ensure_ascii=False))
    n, paths = journal_summary((st.get("session") or {}).get("id"))
    print("\n저널 요약: 수정 파일 %d개" % n)
    for p in paths:
        print("  " + p)
    print("\n(셀프테스트는 state 를 쓰지 않는다 — 읽기만 했다)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    main()
