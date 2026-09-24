#!/usr/bin/env python3
"""RG-006 검사 — 큰따옴표 HTML 속성 안에 이스케이프 없는 `| tojson` 이 있는가.

Jinja 의 tojson 은 < > & ' 만 바꾸고 큰따옴표(")는 그대로 둔다. 그래서
x-data="{ sel: {{ cats | tojson }} }" 처럼 쓰면 JSON 의 " 가 속성을 중간에 끊어
Alpine 이 깨진다 (2026-09-24 인플루언서 편집 화면, 3442a3b 에서 수정).
안전한 형태: `| tojson | forceescape`, 작은따옴표 속성, <script> 안.
⚠️ `| tojson | e` 는 안전하지 않다 — tojson 결과가 이미 Markup 이라 e 는 아무것도 안 바꾼다 (2026-09-24 확인).

사용:  python3 .claude/lib/check_tojson_attr.py [템플릿 폴더]   (기본 app/templates)
종료코드: 위반 0건 = 0, 있으면 1.  python3 stdlib 만 쓴다.
"""
import re
import sys
from pathlib import Path

MARK = "\x00TJ\x00"
_EXPR = re.compile(r"\{\{.*?\}\}", re.S)
_STMT = re.compile(r"\{%.*?%\}|\{#.*?#\}", re.S)
_SCRIPT = re.compile(r"<script\b.*?</script>", re.S | re.I)
_SAFE = re.compile(r"\|\s*forceescape\b")
# 큰따옴표 속성 값 전체 (치환 뒤라 값 안에는 " 가 없다). 그 안의 MARK 를 하나씩 센다
_DQ_ATTR = re.compile(r'=\s*"([^"]*)"')


def _sub_expr(m):
    s = m.group(0)
    if "tojson" in s and not _SAFE.search(s.split("tojson", 1)[1]):
        return MARK
    return "X"


def check_text(text):
    """위반 줄 번호 목록. 줄 번호를 지키려고 치환 결과의 줄 수를 원본과 맞춘다."""
    def keep_lines(repl):
        return lambda m: repl(m) + "\n" * m.group(0).count("\n")

    t = _STMT.sub(keep_lines(lambda m: ""), text)
    t = _EXPR.sub(keep_lines(_sub_expr), t)
    t = _SCRIPT.sub(lambda m: "\n" * m.group(0).count("\n"), t)
    hits = []
    for m in _DQ_ATTR.finditer(t):
        start = m.start()
        # 속성이 태그 안인지: 직전의 < 가 > 보다 뒤에 있어야 한다
        if t.rfind("<", 0, start) <= t.rfind(">", 0, start):
            continue
        i = t.find(MARK, m.start(1), m.end(1))
        while i != -1:
            hits.append(t.count("\n", 0, i) + 1)
            i = t.find(MARK, i + 1, m.end(1))
    return sorted(set(hits))


def selftest():
    bad = '<div x-data="{ s: {{ c | tojson }} }"></div>'
    ok1 = '<div x-data="{ s: {{ c | tojson | forceescape }} }"></div>'
    ok2 = "<div x-data='{ s: {{ c | tojson }} }'></div>"
    ok3 = "<script>const a = {{ c | tojson }};</script>"
    multi = '<div\n  x-data="{\n  a: 1,\n  s: {{ c | tojson if c else \'[]\' }},\n}"></div>'
    assert check_text(bad) == [1], check_text(bad)
    assert check_text(ok1) == [] and check_text(ok2) == [] and check_text(ok3) == []
    assert check_text(multi) == [4], check_text(multi)
    two = '<div x-data="f(\n {{ a | tojson }},\n 1,\n {{ b | tojson }})"></div>'
    assert check_text(two) == [2, 4], check_text(two)
    assert check_text('<input value="{{ m | tojson | e }}">') == [1]
    print("selftest ok")


def main(argv):
    if argv[1:2] == ["--selftest"]:
        selftest()
        return 0
    root = Path(argv[1]) if len(argv) > 1 else Path("app/templates")
    total = 0
    for p in sorted(root.rglob("*.html")):
        for ln in check_text(p.read_text(encoding="utf-8")):
            print(f"{p}:{ln}")
            total += 1
    print(f"위반 {total}건", file=sys.stderr)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
