#!/usr/bin/env python3
r"""SessionStart 훅 — 프로젝트 메모리 INDEX 와 현재 상태를 컨텍스트에 주입한다.

세션이 끝나면 맥락이 사라지는 문제를 막는 토대. **과거 대화를 다시 읽지 않는다** —
압축된 INDEX.md 와 state.json 만 읽어 주입하고, 세부 문서는 필요할 때 모델이 Read 한다.

주입량 상한: INDEX.md 120줄 (osmem.INDEX_MAX_LINES). 넘으면 잘라내고 몇 줄을 생략했는지 알린다.
컨텍스트 예산을 지키는 것이 이 설계의 핵심이므로 상한을 조용히 넘기지 않는다.

실패를 조용히 넘기지 않는다:
  - INDEX.md 가 아직 없음 → 조용히 종료 (실패가 아니라 '아직 시드 안 됨')
  - 읽기/쓰기 실패 → systemMessage 로 보고하되 항상 exit 0 (세션 시작을 막지 않는다)

확인:  python3 .claude/hooks/os-mem-load.py --selftest
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import osmem  # noqa: E402


def state_block(st):
    """state.json 을 사람이 읽는 5줄 블록으로. 진행률은 체크리스트가 있을 때만 쓴다."""
    done, total, pct = osmem.progress(st)
    lines = ["## 현재 상태 (.claude/memory/state.json)"]
    lines.append("- STATE: %s" % st.get("state", "idle"))
    lines.append("- CURRENT TASK: %s" % (st.get("current_task") or "(없음)"))
    if pct is None:
        lines.append("- PROGRESS: — (task 체크리스트가 없다. 숫자를 추정하지 마라)")
    else:
        lines.append("- PROGRESS: %d%% (%d/%d)" % (pct, done, total))
    cp = st.get("last_checkpoint")
    if isinstance(cp, dict) and cp.get("at"):
        lines.append("- LAST CHECKPOINT: %s @ %s" % (cp.get("at"), cp.get("git") or "?"))
    else:
        lines.append("- LAST CHECKPOINT: (없음)")
    todo = [t for t in (st.get("tasks") or []) if isinstance(t, dict)
            and t.get("status") != "done"]
    if todo:
        lines.append("- 남은 task:")
        for t in todo[:8]:
            lines.append("  - [%s] %s" % (t.get("status", "todo"), t.get("title", "?")))
        if len(todo) > 8:
            lines.append("  - ... 외 %d건" % (len(todo) - 8))
    return "\n".join(lines)


def learn_block(sid):
    """반영 기록이 없는 지난 세션 알림 (없으면 None). 실패해도 세션 시작을 막지 않는다."""
    try:
        import learn
        rows = learn.pending(current_sid=sid)
    except Exception:
        return None, 0
    if not rows:
        return None, 0
    lines = ["## 학습 반영 대기 (`/os-learn`, 대표님이 요청할 때만 실행)"]
    for s, n, d in rows[:3]:
        lines.append("- %s 세션 %s — 파일 %d개 수정, 원장에 반영 기록 없음" % (d, s, n))
    if len(rows) > 3:
        lines.append("- ... 외 %d건" % (len(rows) - 3))
    lines.append("- 지난 세션 대화는 읽을 수 없다. 반영하려면 저널·git·changelog 만 근거로 쓴다.")
    return "\n".join(lines), len(rows)


def build_context(sid=None):
    """(additional_context, system_message). INDEX 가 없으면 (None, None)."""
    if not osmem.INDEX.is_file():
        return None, None

    raw = osmem.INDEX.read_text(encoding="utf-8")
    lines = raw.rstrip("\n").split("\n")
    omitted = 0
    if len(lines) > osmem.INDEX_MAX_LINES:
        omitted = len(lines) - osmem.INDEX_MAX_LINES
        lines = lines[:osmem.INDEX_MAX_LINES]

    st = osmem.load_state()
    parts = [
        "# 프로젝트 메모리 (자동 주입 — `.claude/memory/INDEX.md`)",
        "",
        "아래는 **인덱스**다. 전문이 필요하면 해당 파일을 Read 하라.",
        "관련 메모리를 키워드로 찾으려면 `/os-mem find <키워드>`.",
        "",
        "\n".join(lines),
        "",
        state_block(st),
    ]
    if omitted:
        parts.append("")
        parts.append("> ⚠️ INDEX.md 가 %d줄 상한을 넘어 **%d줄 생략**됐다. "
                     "`/os-mem` 으로 정리가 필요하다." % (osmem.INDEX_MAX_LINES, omitted))

    # 라벨은 TYPES 의 ID 접두를 쓴다 — project/preference 가 둘 다 'PR' 로 겹치면 안 된다
    counts = {t: len(osmem.list_docs([t])) for t in osmem.TYPES}
    total = sum(counts.values())
    msg = "🧠 메모리 %d건 로드 (%s)" % (
        total, " ".join("%s:%d" % (osmem.TYPES[k][1], v)
                        for k, v in sorted(counts.items()) if v))
    if omitted:
        msg += " · INDEX %d줄 생략" % omitted
    lb, n_pending = learn_block(sid)
    if lb:
        parts += ["", lb]
        msg += " · 📝 학습 반영 대기 %d" % n_pending
    return "\n".join(parts), msg


def touch_session(d):
    """세션 정보를 state.json 에 남긴다 — 재접속 후 '어디까지 했는지' 복원의 기준점."""
    try:
        st = osmem.load_state()
        sid = (d or {}).get("session_id")
        sess = st.get("session") or {}
        if sid and sess.get("id") != sid:
            sess = {"id": sid, "started": osmem.now_iso(), "last_seen": osmem.now_iso()}
        else:
            sess["last_seen"] = osmem.now_iso()
        st["session"] = sess
        osmem.save_state(st)
        return None
    except Exception as e:
        return "메모리 state 갱신 실패: %s" % e


def main():
    d = osmem.hook_json()          # None 이어도 계속 — 주입은 stdin 없이도 가능하다
    try:
        ctx, msg = build_context((d or {}).get("session_id"))
    except Exception as e:
        osmem.emit({"systemMessage": "✗ 메모리 로드 실패: %s" % e})
        return
    if ctx is None:
        return                     # 아직 시드되지 않음 — 조용히 종료

    warn = touch_session(d)
    if warn:
        msg = (msg or "") + " · " + warn
    osmem.emit({
        "systemMessage": msg,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": ctx,
        },
    })


def selftest():
    print("INDEX  = %s (%s)" % (osmem.rel(osmem.INDEX),
                                "있음" if osmem.INDEX.is_file() else "없음"))
    print("STATE  = %s (%s)" % (osmem.rel(osmem.STATE),
                                "있음" if osmem.STATE.is_file() else "없음"))
    ctx, msg = build_context()
    if ctx is None:
        print("결과   : INDEX 없음 → 조용히 종료 (정상)")
        return 0
    print("결과   : %s" % msg)
    print("주입 줄수: %d" % len(ctx.split("\n")))
    print("--- 주입될 내용 (앞 30줄) ---")
    for ln in ctx.split("\n")[:30]:
        print("  " + ln)
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    main()
