#!/usr/bin/env python3
r"""UserPromptSubmit 훅 — 이번 요청과 관련 있는 메모리의 '포인터만' 주입한다.

목적: 모든 메모리를 매 요청마다 컨텍스트에 넣지 않는다. 요청을 보고 관련 있는 것만
골라 한 줄짜리 포인터로 알려주고, 전문은 모델이 필요할 때 Read 하게 한다.

⚠️ 이것은 **의미 검색이 아니다.** 어휘 일치(tags/title/id)로만 고른다.
동의어·의역은 놓친다. 그래서 각 문서 프론트매터의 `tags` 를 넉넉히 달아두고,
놓쳤을 때는 `/os-mem find <키워드>` 로 직접 찾는 경로를 남겨 둔다.

한국어 특성상 조사가 붙으므로(배포해줘 / 배포를) **부분 문자열 일치**로 태그를 본다.
영문 태그는 오탐(git ⊂ digit)을 막으려고 단어 경계를 요구한다.

비용: 프롬프트당 약 130ms + 주입 12줄 내외.
확인:  python3 .claude/hooks/os-mem-route.py --selftest
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import osmem  # noqa: E402

MAX_HITS = 5          # 주입할 문서 수 상한
MIN_SCORE = 3         # 태그 1개는 맞아야 한다 (제목만 겹치는 것은 버린다)
# 한국어는 짧아도 완결된 지시다("배포해줘" 4자). 감탄사/추임새만 거르는 선에서 잡는다.
MIN_PROMPT_LEN = 3

_ASCII = re.compile(r"^[\x00-\x7f]+$")


def _hit(term, prompt_low):
    """태그/토큰이 프롬프트에 있는가. 영문은 단어 경계, 한글은 부분 일치."""
    t = term.strip().lower()
    if len(t) < 2:
        return False
    if _ASCII.match(t):
        return re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(t), prompt_low) is not None
    return t in prompt_low


def score_doc(meta, prompt_low):
    """(점수, 이유). 이유는 왜 걸렸는지 사람이 납득할 수 있게 남긴다."""
    score, why = 0, []

    doc_id = (meta.get("id") or "").lower()
    if doc_id and doc_id in prompt_low:
        score += 10
        why.append("id 직접 언급")

    for tag in meta.get("tags") or []:
        if _hit(tag, prompt_low):
            score += 3
            why.append(tag)

    for tok in re.split(r"[^0-9A-Za-z가-힣]+", meta.get("title") or ""):
        if len(tok) >= 2 and _hit(tok, prompt_low):
            score += 1

    # 경로 조각이 프롬프트에 있으면 가산 (예: "products.py 고쳐")
    for p in meta.get("paths") or []:
        base = p.replace("**", "").replace("*", "").strip("/").split("/")[-1]
        if len(base) >= 4 and base.lower() in prompt_low:
            score += 2
            why.append(base)

    return score, why


def build(prompt):
    """(additional_context, system_message). 걸리는 게 없으면 (None, None)."""
    if not prompt or len(prompt.strip()) < MIN_PROMPT_LEN:
        return None, None

    low = prompt.lower()
    scored = []
    for meta in osmem.list_docs():            # status=active 만
        s, why = score_doc(meta, low)
        if s >= MIN_SCORE:
            scored.append((s, meta, why))
    if not scored:
        return None, None

    scored.sort(key=lambda x: (-x[0], x[1].get("id", "")))
    top = scored[:MAX_HITS]

    lines = ["[프로젝트 메모리] 이 요청과 관련 있을 수 있는 기록 %d건 — "
             "필요하면 해당 파일을 Read 하세요 (전문은 주입하지 않았습니다)" % len(top)]
    for s, meta, why in top:
        reason = ", ".join(dict.fromkeys(why))[:40]
        lines.append("  %-7s %-52s %s%s" % (
            meta.get("id", "?"),
            (meta.get("title") or "")[:52],
            meta.get("_path", "?"),
            ("   ← %s" % reason) if reason else ""))
    if len(scored) > len(top):
        lines.append("  (외 %d건은 점수가 낮아 생략 — `/os-mem find <키워드>` 로 직접 검색)"
                     % (len(scored) - len(top)))

    # regression 이 걸렸으면 눈에 띄게 한 줄 덧붙인다 — 수정 전에 확인해야 하는 것들이다
    if any(m.get("type") == "regression" for _, m, _ in top):
        lines.append("  ⚠️ regression 규칙이 포함돼 있습니다. 수정 전에 조건을 확인하고 "
                     "수정 후 검증하세요.")

    return "\n".join(lines), "🧭 관련 메모리 %d건" % len(top)


def main():
    d = osmem.hook_json()
    if not d:
        return                                 # 입력을 못 읽으면 조용히 통과 (프롬프트를 막지 않는다)
    if d.get("user_input_type") == "command":
        return                                 # 슬래시 명령에는 끼어들지 않는다
    try:
        # 공식 문서의 필드명은 prompt — 둘 다 받는다 (IM-009, 실제 페이로드 필드명은 미확인)
        ctx, msg = build(d.get("user_input") or d.get("prompt") or "")
    except Exception as e:
        osmem.emit({"systemMessage": "✗ 메모리 라우터 오류: %s" % e})
        return
    if not ctx:
        return
    osmem.emit({
        "systemMessage": msg,
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": ctx,
        },
    })


def selftest():
    cases = [
        "배포해줘",
        "ec2에 올려줘",
        "라우터 하나 추가하려는데",
        "products.py 에서 테넌트 격리 확인해줘",
        "css 가 너무 큰 것 같은데 tailwind 설정 봐줘",
        "RG-005 내용 보여줘",
        "오늘 날씨 어때",
        "ㅇㅇ",
    ]
    docs = osmem.list_docs()
    print("활성 메모리 %d건 기준\n" % len(docs))
    for c in cases:
        ctx, msg = build(c)
        print("입력: %s" % c)
        if not ctx:
            print("  -> 관련 없음 (주입 안 함)\n")
            continue
        for ln in ctx.split("\n"):
            print("  " + ln)
        print()
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    main()
