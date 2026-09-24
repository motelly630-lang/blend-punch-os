#!/usr/bin/env python3
r"""PostToolUse(Write|Edit) 훅 — 방금 고친 템플릿(.html)의 흔한 화면 실수를 저장 즉시 잡는다 (IM-012).

검사 두 가지 (둘 다 stdlib, 앱을 켜지 않는다):
  1. 큰따옴표 속성 안 이스케이프 없는 `| tojson` → Alpine 화면 깨짐 ([RG-006], check_tojson_attr.py)
  2. 폼·htmx 주소가 실제 서버 주소가 아님 → 404 (check_form_urls.py, 2026-09-24 `/influencersnew` 사례)

결과 전달 (os-py-check.py 와 같은 방식):
  - 위반 → exit 2 + stderr. Claude 가 보고 바로 고친다 (저장된 파일을 되돌리지는 않는다).
  - 대상 아님(app/templates 밖, .html 아님) → 조용히 종료.
  - 검사 자체 실패 → systemMessage 로 알리고 작업은 막지 않는다.
한계: Write/Edit 도구로 고친 파일만 본다. 셸로 고친 파일은 `python3 .claude/lib/check_form_urls.py` 등으로 직접.

확인:  python3 .claude/hooks/os-template-check.py --selftest
"""
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))
import osmem  # noqa: E402
import check_form_urls  # noqa: E402
import check_tojson_attr  # noqa: E402

TEMPLATES = osmem.PROJECT / "app" / "templates"


def target(raw):
    p = osmem.to_posix(raw or "")
    if not p or p.startswith("__"):
        return None
    path = Path(p)
    if path.suffix != ".html":
        return None
    try:
        path.resolve().relative_to(TEMPLATES.resolve())
    except Exception:
        return None
    return path


def problems(text, routes=None):
    """사람이 읽는 위반 줄 목록."""
    out = []
    for ln in check_tojson_attr.check_text(text):
        out.append("  %d번 줄: 큰따옴표 속성 안 `| tojson` — `| tojson | forceescape` 로 (RG-006, 화면 깨짐)" % ln)
    routes = routes if routes is not None else check_form_urls.collect_routes()
    for ln, attr, url, v in check_form_urls.check_text(text, routes):
        out.append("  %d번 줄: %s 주소 `%s` 가 서버에 없음 (원문 %s) — 404 가 난다" % (ln, attr, v, url[:70]))
    return out


def main():
    d = osmem.hook_json()
    if d is None:
        return 0
    path = target((d.get("tool_input") or {}).get("file_path"))
    if path is None or not path.is_file():
        return 0
    found = problems(path.read_text(encoding="utf-8"))
    if not found:
        return 0
    sys.stderr.write("✗ 템플릿 점검: %s\n%s\n바로 고치세요.\n" % (osmem.rel(path), "\n".join(found)))
    return 2


def selftest():
    routes = [("POST", "/influencers/new"), ("POST", "/influencers/{influencer_id}/edit")]
    good = '<form action="/influencers/{% if i %}{{ i.id }}/edit{% else %}new{% endif %}">' \
           '<div x-data="{ s: {{ c | tojson | forceescape }} }"></div>'
    bad = '<form action="/influencers{% if i %}/{{ i.id }}/edit{% else %}new{% endif %}">\n' \
          '<div x-data="{ s: {{ c | tojson }} }"></div>'
    fails = 0
    for name, text, want in (("good", good, 0), ("bad", bad, 2)):
        got = len(problems(text, routes))
        res = "OK" if got == want else "FAIL"
        fails += res == "FAIL"
        print("  %-4s 위반 %d (기대 %d) %s" % (name, got, want, res))
    for raw, want in (("/x/y.html", None), (str(TEMPLATES / "a" / "b.txt"), None),
                      (str(TEMPLATES / "influencers" / "form.html"), "app/templates/influencers/form.html")):
        t = target(raw)
        got = osmem.rel(t) if t else None
        res = "OK" if got == want else "FAIL"
        fails += res == "FAIL"
        print("  target(%s) -> %s %s" % (raw, got, res))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    try:
        sys.exit(main())
    except Exception as e:  # 훅 버그로 작업을 막지 않는다 — 대신 알린다
        osmem.emit({"systemMessage": "✗ 템플릿 점검 훅 오류: %s" % e})
        sys.exit(0)
