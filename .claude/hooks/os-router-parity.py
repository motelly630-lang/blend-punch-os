#!/usr/bin/env python3
r"""PostToolUse(Write|Edit) hook — blend-punch-os 라우터 3점세트 정합성 검증.

CLAUDE.md 규칙 1: 새 라우터는 app/main.py의 include_router 와 _setup_filters() 루프에
'둘 다' 등록해야 한다. 필터 루프 등록을 빠뜨리면 부팅은 조용히 성공하고, 해당 화면
첫 요청에서야 `won`/`date` 등 undefined filter 로 500이 난다.

include_router 는 모듈 상단 별칭(auth_router 등)을, 필터 루프는 함수 내부 별칭(d, p, i ...)을
쓰므로 이름 비교로는 대조할 수 없다. AST 로 `import app.routers.X as Y` 를 모아 별칭→모듈로
정규화한 뒤 두 집합을 비교한다.

노이즈를 막기 위해 2단 필터를 둔다:
  1) `templates = ` 정의가 있는 모듈만 (JSON API 라우터는 루프에 넣으면 오히려 터진다)
  2) 그 라우터가 렌더하는 템플릿(+extends/include 체인)이 커스텀 필터를 실제로 쓰는 경우만
예: app/routers/shop.py 는 루프에 없지만 base.html 을 상속하지 않고 커스텀 필터도 쓰지 않아
현재는 문제가 없다 — 나중에 `| won` 을 추가하는 순간 경고가 뜬다.

Windows Claude Code 대응:
  훅 입력의 file_path 가 `\\wsl$\Ubuntu\home\...` UNC 형식으로 들어오므로 POSIX 로 정규화한다.
  정규화 규칙 확인:  python3 .claude/hooks/os-router-parity.py --selftest

실패를 조용히 넘기지 않는다:
  - 대상 아님(라우터/main.py 가 아님, 프로젝트 밖 파일) → 조용히 종료. 실패가 아니라 '해당 없음'.
  - 진짜 실패(입력 파싱 불가, 알 수 없는 UNC, main.py 파싱 불가, 필터 루프 소실) → systemMessage.
"""
import ast
import json
import re
import sys
from pathlib import Path

# 훅 파일 위치에서 프로젝트 루트를 유도한다 (.claude/hooks/ 아래에 있다)
PROJECT = Path(__file__).resolve().parents[2]
MAIN = PROJECT / "app" / "main.py"
ROUTER_PKGS = ("app.routers.", "app.api.")


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False))


def to_posix(p):
    """훅이 준 파일 경로를 WSL POSIX 경로로 바꾼다. 못 바꾸면 마커를 돌려준다."""
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


def selftest():
    cases = [
        r"\\wsl$\Ubuntu\home\blendpunch\blend-punch-os\app\routers\cs.py",
        r"\\wsl.localhost\Ubuntu\home\blendpunch\blend-punch-os\app\main.py",
        "/home/blendpunch/blend-punch-os/app/routers/cs.py",
        r"C:\Users\Mypc\AppData\Local\Temp\x.py",
        r"\\server\share\x.py",
        "",
    ]
    for c in cases:
        print("  %-70s -> %s" % (repr(c), to_posix(c)))
    print("PROJECT=%s" % PROJECT)
    print("MAIN exists=%s" % MAIN.is_file())


def hook_file_path():
    """(정규화된 경로, 실패마커) — 실패마커가 있으면 호출자가 반드시 보고한다."""
    try:
        d = json.load(sys.stdin)
    except Exception:
        return None, "__PARSE_FAIL__"
    ti = d.get("tool_input") or {}
    tr = d.get("tool_response") or {}
    raw = ti.get("file_path") or (tr.get("filePath") if isinstance(tr, dict) else None)
    norm = to_posix(raw or "")
    if norm in ("__PARSE_FAIL__", "__UNKNOWN_UNC__", "__EMPTY__"):
        return None, norm
    if norm == "__NOT_IN_WSL__":
        return None, None          # 대상 아님 — 실패가 아니다
    return norm, None


def alias_map(tree):
    """별칭 -> 모듈 경로 (app.routers.* / app.api.* 만)"""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith(ROUTER_PKGS):
                    out[a.asname or a.name] = a.name
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module + ".").startswith(ROUTER_PKGS[0][:-1] + "."):
                for a in node.names:
                    out[a.asname or a.name] = f"{node.module}.{a.name}"
            elif node.module in ("app.routers", "app.api"):
                for a in node.names:
                    out[a.asname or a.name] = f"{node.module}.{a.name}"
    return out


def registered_aliases(tree):
    """app.include_router(<alias>.router) 로 등록된 별칭"""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr == "include_router"):
            continue
        if not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name):
            found.append(arg.value.id)
        elif isinstance(arg, ast.Name):
            found.append(arg.id)
    return found


def filtered_aliases(tree):
    """`for mod in [d, p, i, ...]:` 형태의 필터 등록 루프에서 별칭 수집"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        if not (isinstance(node.target, ast.Name) and isinstance(node.iter, ast.List)):
            continue
        body = ast.dump(node)
        if "filters" not in body:
            continue
        return [e.id for e in node.iter.elts if isinstance(e, ast.Name)]
    return None


def module_file(mod):
    return PROJECT / (mod.replace(".", "/") + ".py")


def read(p):
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def custom_filters(tree):
    """main.py 가 실제로 등록하는 필터 이름 (하드코딩하지 않는다)"""
    names = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "filters"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            names.add(node.slice.value)
    return names


def defines_templates(mod):
    return re.search(r"^templates\s*=", read(module_file(mod)), re.M) is not None


def used_filters(mod, filters):
    """라우터가 렌더하는 템플릿 + extends/include 체인에서 쓰이는 커스텀 필터"""
    src = read(module_file(mod))
    todo = [t for t in re.findall(r"[\"']([\w/.-]+\.html)[\"']", src)]
    seen, hits = set(), set()
    tdir = PROJECT / "app" / "templates"
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        body = read(tdir / name)
        if not body:
            continue
        for f in filters:
            if re.search(r"\|\s*" + re.escape(f) + r"\b", body):
                hits.add(f)
        todo += re.findall(r"{%-?\s*(?:extends|include)\s+[\"']([\w/.-]+\.html)[\"']", body)
    return hits


def main():
    if "--selftest" in sys.argv:
        selftest()
        return

    path, failure = hook_file_path()
    if failure:
        detail = {
            "__PARSE_FAIL__": "훅 stdin JSON 을 파싱하지 못했습니다.",
            "__UNKNOWN_UNC__": "file_path 가 예상한 \\\\wsl$\\<distro>\\... 형식이 아닙니다. "
                               ".claude/hooks/os-router-parity.py 의 정규화 규칙을 갱신해야 합니다.",
            "__EMPTY__": "Write/Edit 인데 file_path 가 비어 있습니다.",
        }[failure]
        emit({
            "systemMessage": "✗ 라우터 정합성 검사를 수행하지 못했습니다 — 검사 미실행",
            "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": detail},
        })
        return
    if not path:
        return

    p = Path(path)
    try:
        rel = p.resolve().relative_to(PROJECT)
    except (ValueError, OSError):
        return  # 프로젝트 밖 파일 — 대상 아님 (실패 아님)
    parts = rel.parts
    is_main = rel == Path("app/main.py")
    is_router = len(parts) == 3 and parts[0] == "app" and parts[1] in ("routers", "api") and parts[2].endswith(".py")
    if not (is_main or is_router):
        return

    try:
        tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as e:
        emit({"systemMessage": f"✗ 라우터 정합성 검사 실패 — app/main.py 파싱 불가: {e}"})
        return

    amap = alias_map(tree)
    loop = filtered_aliases(tree)
    if loop is None:
        emit({
            "systemMessage": "✗ _setup_filters() 의 필터 등록 루프를 찾지 못했습니다 — 훅 갱신 필요",
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": (
                    "os-router-parity.py 가 app/main.py 에서 `for mod in [...]` 필터 루프를 "
                    "찾지 못했습니다. 루프 구조가 바뀌었다면 훅을 함께 수정해야 합니다."
                ),
            },
        })
        return

    filters = custom_filters(tree)
    reg = {amap.get(a, a) for a in registered_aliases(tree)}
    flt = {amap.get(a, a) for a in loop}

    broken = []
    for mod in sorted(reg - flt):
        if not mod.startswith(ROUTER_PKGS) or not defines_templates(mod):
            continue
        used = used_filters(mod, filters)
        if used:
            broken.append((mod, sorted(used)))
    if not broken:
        return

    names = ", ".join(m.split(".")[-1] for m, _ in broken)
    emit({
        "systemMessage": f"🔴 필터 루프 미등록 라우터 {len(broken)}건: {names} — 해당 화면 500 발생",
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                "다음 라우터는 app/main.py 의 include_router 에는 있지만 _setup_filters() 의 "
                "필터 등록 루프에는 없고, 그 템플릿이 커스텀 필터를 사용합니다. "
                "부팅은 성공하지만 해당 화면 첫 요청에서 undefined filter 로 500 이 납니다.\n"
                + "\n".join(
                    f"  - {m}  ({module_file(m).relative_to(PROJECT)})  사용 필터: {', '.join(u)}"
                    for m, u in broken
                )
                + "\n\n조치: _setup_filters() 안에서 해당 모듈을 import 하고 "
                "`for mod in [...]` 리스트에 별칭을 추가하세요."
            ),
        },
    })


if __name__ == "__main__":
    main()
