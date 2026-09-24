#!/usr/bin/env python3
"""IM-012 검사 — 템플릿의 폼·htmx 주소가 실제로 있는 서버 주소인가.

2026-09-24 인플루언서 등록 폼 action 에서 `/` 하나가 빠져 `/influencersnew` 로 보내 운영 404 가 났다.
저장 로직 테스트는 주소로 직접 보내서 이런 화면 쪽 실수를 못 잡는다.

- 서버 주소 목록은 앱을 켜지 않고 코드(ast)로 읽는다: `APIRouter(prefix=…)` + `@router.post("…")`,
  `@app.get(…)`, `include_router(…, prefix=…)`. 그래서 빠르고 stdlib 만 쓴다 (훅에서 매 저장마다 돈다).
- `{% if %}A{% else %}B{% endif %}` · `{{ x + '/edit' if c else 'new' }}` 는 **분기마다 따로** 본다.
- `{{ … }}` 값은 한 경로 조각으로 본다 (`/products/{{ p.id }}/edit` → `/products/*/edit`).

사용:  python3 .claude/lib/check_form_urls.py [템플릿 파일|폴더 …]   (기본 app/templates)
종료코드: 위반 0건 = 0, 있으면 1.   확인: --selftest
"""
import ast
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
ROUTE_DIRS = ("app",)
HTTP = {"get", "post", "put", "patch", "delete", "api_route"}

_ATTR = re.compile(r'\b(action|hx-post|hx-get|hx-put|hx-patch|hx-delete)\s*=\s*"([^"]*)"')
_IFELSE = re.compile(r"\{%-?\s*if\b[^%]*%\}(.*?)\{%-?\s*else\s*-?%\}(.*?)\{%-?\s*endif\s*-?%\}", re.S)
_IFONLY = re.compile(r"\{%-?\s*if\b[^%]*%\}(.*?)\{%-?\s*endif\s*-?%\}", re.S)
_STR = re.compile(r"""'([^']*)'|"([^"]*)\"""")


# ── 서버 주소 목록 (정적 분석) ─────────────────────────────────────────────────

def _const(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _kw(call, name):
    for k in call.keywords:
        if k.arg == name:
            return _const(k.value)
    return None


def collect_routes(root=PROJECT):
    """[(METHOD, path)] — 파일마다 라우터 변수의 prefix 를 기억해 데코레이터 경로에 붙인다."""
    files = [p for d in ROUTE_DIRS for p in sorted((Path(root) / d).rglob("*.py"))]
    include_prefix = {}                      # 모듈.라우터 → include_router 때 붙는 prefix
    out = []
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        prefixes = {}                        # 변수명 → prefix
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                fn = node.value.func
                name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                if name in ("APIRouter", "FastAPI"):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            prefixes[t.id] = _kw(node.value, "prefix") or ""
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "include_router":
                p = _kw(node, "prefix")
                if p and node.args:
                    include_prefix[ast.unparse(node.args[0])] = p
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                    continue
                meth, owner = dec.func.attr, dec.func.value
                if meth not in HTTP or not isinstance(owner, ast.Name) or owner.id not in prefixes:
                    continue
                path = _const(dec.args[0]) if dec.args else _kw(dec, "path")
                if path is None:
                    continue
                methods = [meth.upper()]
                if meth == "api_route":
                    ms = next((k.value for k in dec.keywords if k.arg == "methods"), None)
                    methods = [_const(e).upper() for e in getattr(ms, "elts", []) if _const(e)] or ["GET"]
                full = prefixes[owner.id] + path
                for m in methods:
                    out.append((m, full, f.stem))
    # include_router(x.router, prefix="/p") 로 붙는 prefix (현재 main.py 에는 없지만 대비)
    res = []
    for m, path, stem in out:
        extra = next((p for k, p in include_prefix.items() if k.split(".")[0] == stem), "")
        res.append((m, extra + path))
    return sorted(set(res))


def _route_regex(path):
    rx = re.sub(r"\\\{[^}]+?:path\\\}", ".+", re.escape(path))
    rx = re.sub(r"\\\{[^}]+\\\}", "[^/]+", rx)
    return re.compile("^" + rx + "$")


# ── 템플릿 주소 → 분기별 후보 ─────────────────────────────────────────────────

def _expr_variants(expr):
    """`{{ … }}` 한 개 → 가능한 문자열 조각들. 삼항식은 양쪽을 다 본다."""
    body = expr.strip()[2:-2].strip()
    parts = re.split(r"\s+if\s+.+?\s+else\s+", body, maxsplit=1) if " if " in body and " else " in body else [body]
    outs = []
    for part in parts:
        pieces = [p.strip() for p in part.split("+")]
        s = ""
        for p in pieces:
            m = _STR.fullmatch(p.split("|")[0].strip())
            s += (m.group(1) if m.group(1) is not None else m.group(2)) if m else "*"
        outs.append(s)
    return outs


def url_variants(url):
    """템플릿 속 주소 하나 → 분기별로 펼친 주소 목록 (Jinja 조각은 * 로)."""
    work = [url]
    for _ in range(4):                                   # 중첩 대비 몇 번 펼친다
        nxt = []
        for u in work:
            m = _IFELSE.search(u) or _IFONLY.search(u)
            if not m:
                nxt.append(u)
                continue
            if m.re is _IFELSE:
                nxt += [u[:m.start()] + m.group(1) + u[m.end():], u[:m.start()] + m.group(2) + u[m.end():]]
            else:
                nxt += [u[:m.start()] + m.group(1) + u[m.end():], u[:m.start()] + u[m.end():]]
        work = nxt
    out = []
    for u in work:
        u = re.sub(r"\{%.*?%\}", "", u)
        pieces = [[""]]
        pos = 0
        for m in re.finditer(r"\{\{.*?\}\}", u, re.S):
            pieces.append([u[pos:m.start()]])
            pieces.append(_expr_variants(m.group(0)))
            pos = m.end()
        pieces.append([u[pos:]])
        combos = [""]
        for opts in pieces:
            combos = [c + o for c in combos for o in opts]
        out += [c.split("?")[0].split("#")[0] for c in combos]
    return sorted(set(out))


def _matches(url, method, routes):
    if "*" in url:
        # * 는 경로 한 조각 이상일 수 있다 (id + '/edit' 등) → 후보 주소를 정규식으로
        rx = re.compile("^" + ".+".join(re.escape(x) for x in url.split("*")) + "$")
        cands = [p for m, p in routes if method in (None, m)]
        concrete = [re.sub(r"\{[^}]+\}", "ID", p) for p in cands]
        return any(rx.match(c) for c in concrete) or any(_route_regex(p).match(url.replace("*", "ID")) for p in cands)
    return any((method in (None, m)) and _route_regex(p).match(url) for m, p in routes)


def check_text(text, routes):
    """[(줄, 속성, 원래주소, 안 맞는 분기)]"""
    bad = []
    for m in _ATTR.finditer(text):
        attr, url = m.group(1), m.group(2)
        if not (url.startswith("/") or url.startswith("{")):
            continue                                       # 빈값·상대주소·외부주소는 대상 아님
        method = None if attr == "action" else attr[3:].upper()
        for v in url_variants(url):
            if not v.startswith("/") or v.startswith("//") or v == "/":
                continue
            if not _matches(v, method, routes):
                bad.append((text.count("\n", 0, m.start()) + 1, attr, url, v))
    return bad


def selftest():
    routes = [("POST", "/influencers/new"), ("POST", "/influencers/{influencer_id}/edit"),
              ("POST", "/sales-pages/new"), ("POST", "/sales-pages/{page_id}/edit"), ("GET", "/p/{id}")]
    ok = [
        '<form action="/influencers/{% if inf %}{{ inf.id }}/edit{% else %}new{% endif %}">',
        '<form action="/sales-pages/{{ page.id + \'/edit\' if page else \'new\' }}">',
        '<a hx-get="/p/{{ x.id }}?tab=1">',
        '<form action="">', '<form action="https://example.com/x">',
    ]
    for t in ok:
        assert check_text(t, routes) == [], (t, check_text(t, routes))
    bad = '<form action="/influencers{% if inf %}/{{ inf.id }}/edit{% else %}new{% endif %}">'
    got = check_text(bad, routes)
    assert [g[3] for g in got] == ["/influencersnew"], got
    assert check_text('<button hx-post="/p/{{ x }}">', routes)          # GET 만 있는데 POST
    print("selftest ok")
    return 0


def main(argv):
    if argv[1:2] == ["--selftest"]:
        return selftest()
    targets = [Path(a) for a in argv[1:]] or [PROJECT / "app/templates"]
    files = [f for t in targets for f in ([t] if t.is_file() else sorted(t.rglob("*.html")))]
    routes = collect_routes()
    total = 0
    for f in files:
        for ln, attr, url, v in check_text(f.read_text(encoding="utf-8"), routes):
            print("%s:%d  %s=\"%s\"  → 없는 주소 %s" % (f, ln, attr, url[:80], v))
            total += 1
    print("위반 %d건 (서버 주소 %d개 기준)" % (total, len(routes)), file=sys.stderr)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
