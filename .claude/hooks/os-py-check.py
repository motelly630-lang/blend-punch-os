#!/usr/bin/env python3
r"""PostToolUse(Write|Edit) 훅 — 방금 수정한 .py 파일의 문법을 즉시 검사한다.

이 저장소에는 린트·CI 가 없어서, 괄호 하나 빠진 파일이 서버를 켜기 전까지(운영이면 배포 후
사이트 전체 다운까지) 드러나지 않는다. 저장 직후 파싱만 해 보면 그걸 0초 만에 잡는다.

검사는 프로젝트 .venv 의 python(3.12)으로 한다. 시스템 python3 은 맥에서 3.9 라서
3.10+ 문법(match, 새 f-string 등)을 오류로 오판한다. .venv 가 없으면 python3 으로 하되
그 사실을 알린다.

결과 전달:
  - 문법 오류 → exit 2 + stderr. PostToolUse 에서 exit 2 는 stderr 를 Claude 에게 보여준다
    (이미 저장된 파일을 되돌리지는 않는다 — Claude 가 보고 고치게 한다).
  - 대상 아님(.py 아님, 프로젝트 밖) → 조용히 종료.
  - 검사 자체를 못 함 → systemMessage 로 알리고 작업은 막지 않는다.

확인:  python3 .claude/hooks/os-py-check.py --selftest
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import osmem  # noqa: E402

VENV_PY = osmem.PROJECT / ".venv" / "bin" / "python"
SKIP_PARTS = {".venv", "node_modules", ".git"}
PARSE = "import ast,sys; p=sys.argv[1]; ast.parse(open(p, encoding='utf-8').read(), p)"


def interpreter():
    return (str(VENV_PY), True) if VENV_PY.is_file() else ("python3", False)


def check(path):
    """(ok, 메시지). ok=None 이면 검사 자체 실패."""
    py, is_venv = interpreter()
    try:
        r = subprocess.run([py, "-c", PARSE, str(path)], capture_output=True,
                           text=True, timeout=10)
    except Exception as e:
        return None, "검사 실행 실패: %s" % e
    if r.returncode == 0:
        return True, "" if is_venv else "(.venv 없음 — 시스템 python3 로 검사)"
    # 트레이스백 마지막 몇 줄만 — File/줄/캐럿/SyntaxError
    tail = "\n".join(r.stderr.strip().splitlines()[-4:])
    return False, tail


def target(raw):
    p = osmem.to_posix(raw)
    if p.startswith("__"):
        return None
    path = Path(p)
    if path.suffix != ".py":
        return None
    try:
        relp = path.resolve().relative_to(osmem.PROJECT)
    except Exception:
        return None
    if SKIP_PARTS & set(relp.parts):
        return None
    return path


def main():
    d = osmem.hook_json()
    if d is None:
        osmem.emit({"systemMessage": "✗ 파이썬 문법 검사 미실행 — 훅 입력을 읽지 못했습니다"})
        return 0
    ti = d.get("tool_input") or {}
    path = target(ti.get("file_path") or "")
    if path is None or not path.is_file():
        return 0
    ok, msg = check(path)
    if ok is None:
        osmem.emit({"systemMessage": "✗ 파이썬 문법 검사 미실행 (%s) — %s" % (osmem.rel(path), msg)})
        return 0
    if ok:
        return 0
    sys.stderr.write(
        "✗ 문법 오류: %s — 이 파일은 지금 import 되지 않습니다(서버 기동 실패). 바로 고치세요.\n%s\n"
        % (osmem.rel(path), msg))
    return 2


def selftest():
    import tempfile
    py, is_venv = interpreter()
    print("interpreter=%s (venv=%s)" % (py, is_venv))
    tmp = osmem.PROJECT / ".claude" / "state"
    tmp.mkdir(parents=True, exist_ok=True)
    cases = [("good", "def f(x):\n    match x:\n        case 1:\n            return f'{x!r:>{3}}'\n", True),
             ("bad", "def f(:\n    pass\n", False)]
    fails = 0
    for name, src, want in cases:
        with tempfile.NamedTemporaryFile("w", suffix=".py", dir=tmp, delete=False) as f:
            f.write(src)
        ok, msg = check(Path(f.name))
        Path(f.name).unlink()
        res = "OK" if ok == want else "FAIL"
        fails += res == "FAIL"
        print("  %-5s want=%s got=%s %s" % (name, want, ok, res))
    for raw, want in [("/x/y.py", None), ("app/main.txt", None),
                      (str(osmem.PROJECT / "app" / "main.py"), "app/main.py"),
                      (str(osmem.PROJECT / ".venv" / "a.py"), None)]:
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
        osmem.emit({"systemMessage": "✗ 파이썬 문법 검사 훅 오류: %s" % e})
        sys.exit(0)
