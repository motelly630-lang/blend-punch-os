#!/usr/bin/env bash
# PostToolUse(Write|Edit) hook — blend-punch-os 템플릿 수정 시 Tailwind 정적빌드 자동 실행.
# Tailwind는 CDN 없이 정적빌드만 쓰므로, 새 클래스를 추가하면 재빌드 전까지 스타일이 적용되지 않는다.
#
# Windows Claude Code / WSL Claude Code 양쪽에서 동작한다:
#   - settings.json 은 `bash <이 파일의 POSIX 절대경로>` 로 호출한다.
#     Windows 에서 `bash` 는 WindowsApps 의 WSL 런처라 이 스크립트는 항상 WSL 안에서 실행된다.
#   - 그때 훅 입력의 file_path 는 `\\wsl$\Ubuntu\home\...` 형식으로 들어오므로 POSIX 로 정규화한다.
#
# 실패를 조용히 넘기지 않는다:
#   - 대상이 아닌 파일(템플릿 아님, 프로젝트 밖) → 조용히 종료. 이건 실패가 아니라 '해당 없음'이다.
#   - 진짜 실패(입력 파싱 불가 / node 없음 / tailwind 없음 / 빌드 실패) → 반드시 systemMessage 로 알린다.
#
# 정규화가 제대로 도는지 확인:  bash .claude/hooks/os-build-css.sh --selftest
set -uo pipefail

PROJECT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

# --- 훅 경로 정규화기 (셀프테스트와 실제 실행이 같은 코드를 쓴다) ---
NORMALIZER='
import json, re, sys

def to_posix(p):
    """훅이 준 파일 경로를 WSL POSIX 경로로 바꾼다. 못 바꾸면 마커를 붙여 돌려준다."""
    if not p:
        return "__EMPTY__"
    q = p.replace("\\", "/")
    m = re.match(r"^//wsl(?:\$|\.localhost)/[^/]+(/.*)$", q, re.I)
    if m:
        return m.group(1)
    if re.match(r"^[A-Za-z]:/", q):
        return "__NOT_IN_WSL__"      # Windows 드라이브(스크래치패드 등) — 이 프로젝트가 아니다
    if q.startswith("//"):
        return "__UNKNOWN_UNC__"     # 형태를 못 알아본 UNC — 이건 알려야 한다
    return q
'

if [ "${1:-}" = "--selftest" ]; then
  python3 -c "$NORMALIZER"'
cases = [
    r"\\wsl$\Ubuntu\home\blendpunch\blend-punch-os\app\templates\cs\list.html",
    r"\\wsl.localhost\Ubuntu\home\blendpunch\blend-punch-os\app\templates\base.html",
    "/home/blendpunch/blend-punch-os/app/templates/base.html",
    r"C:\Users\Mypc\AppData\Local\Temp\x.html",
    r"\\server\share\x.html",
    "",
]
for c in cases:
    print("  %-72s -> %s" % (repr(c), to_posix(c)))
'
  echo "PROJECT=$PROJECT"
  exit 0
fi

msg() {
  # $1 = systemMessage, $2 = (선택) 모델에게 줄 추가 컨텍스트
  MSG="$1" CTX="${2:-}" python3 -c '
import json, os
out = {"systemMessage": os.environ["MSG"]}
ctx = os.environ.get("CTX") or ""
if ctx:
    out["hookSpecificOutput"] = {"hookEventName": "PostToolUse", "additionalContext": ctx}
print(json.dumps(out, ensure_ascii=False))
'
}

# --- 훅 stdin JSON 에서 수정된 파일 경로 추출 + 정규화 ---
FILE=$(python3 -c "$NORMALIZER"'
try:
    d = json.load(sys.stdin)
except Exception:
    print("__PARSE_FAIL__"); sys.exit(0)
ti = d.get("tool_input") or {}
tr = d.get("tool_response") or {}
p = ti.get("file_path") or (tr.get("filePath") if isinstance(tr, dict) else "") or ""
print(to_posix(p))
')
RC=$?

if [ $RC -ne 0 ]; then
  msg "✗ build:css 훅 실행 실패 — python3 로 훅 입력을 읽지 못했습니다 (exit $RC)"
  exit 0
fi

case "$FILE" in
  __PARSE_FAIL__)
    msg "✗ build:css 훅 실행 실패 — 훅 입력 JSON 파싱 불가. Tailwind 재빌드가 되지 않았습니다." \
        "PostToolUse 훅이 stdin JSON 을 읽지 못했습니다. 템플릿을 수정했다면 'wsl -- bash -lc \"cd /home/blendpunch/blend-punch-os && npm run build:css\"' 를 수동 실행하세요."
    exit 0 ;;
  __UNKNOWN_UNC__)
    msg "✗ build:css 훅 — 알 수 없는 UNC 경로 형식이라 대상 판별 실패. 재빌드가 되지 않았습니다." \
        "훅이 받은 file_path 가 예상한 \\\\wsl\$\\<distro>\\... 형식이 아닙니다. .claude/hooks/os-build-css.sh 의 정규화 규칙을 갱신해야 합니다."
    exit 0 ;;
  __EMPTY__)
    msg "✗ build:css 훅 — Write/Edit 인데 file_path 가 비어 있습니다. 대상 판별 불가." \
        "훅 입력에 tool_input.file_path 와 tool_response.filePath 가 모두 없습니다."
    exit 0 ;;
  __NOT_IN_WSL__)
    exit 0 ;;   # Windows 드라이브 파일 — 이 프로젝트 대상 아님 (실패 아님)
esac

# blend-punch-os 템플릿(.html)이 아니면 아무것도 하지 않는다 (실패 아님)
case "$FILE" in
  "$PROJECT"/app/templates/*.html) ;;
  *) exit 0 ;;
esac

# 훅은 nvm PATH를 물려받지 못할 수 있으므로 node를 직접 찾는다
if ! command -v node >/dev/null 2>&1; then
  NODE_BIN=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1)
  [ -n "$NODE_BIN" ] && PATH="$NODE_BIN:$PATH"
fi
command -v node >/dev/null 2>&1 || {
  msg "✗ build:css 실패 — node 를 찾을 수 없어 재빌드하지 못했습니다" \
      "템플릿을 수정했지만 Tailwind 재빌드에 실패했습니다(node 없음). 스타일이 적용되지 않습니다."
  exit 0
}

cd "$PROJECT" 2>/dev/null || {
  msg "✗ build:css 실패 — 프로젝트 디렉터리로 이동 불가: $PROJECT"
  exit 0
}

TW=node_modules/.bin/tailwindcss
[ -x "$TW" ] || {
  msg "✗ build:css 실패 — tailwindcss 미설치 (WSL 에서 npm install 필요)" \
      "node_modules/.bin/tailwindcss 가 없습니다. 스타일이 적용되지 않습니다. 반드시 WSL 에서 설치하세요: wsl -- bash -lc 'cd /home/blendpunch/blend-punch-os && npm install'"
  exit 0
}

if OUT=$("$TW" -i static/css/input.css -o static/css/app.css --minify 2>&1); then
  echo '{"systemMessage":"✓ Tailwind 재빌드 완료 (static/css/app.css)","suppressOutput":true}'
else
  # 빌드 실패는 조용히 넘기지 않는다 — 스타일이 안 먹는 원인이 되므로 모델에게 알린다
  printf '%s' "$OUT" | python3 -c '
import json, sys
err = sys.stdin.read()[-1500:]
print(json.dumps({
    "systemMessage": "✗ Tailwind 빌드 실패 — static/css/app.css 가 갱신되지 않았습니다",
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": "npm run build:css 실패. 스타일이 적용되지 않습니다. 오류:\n" + err,
    },
}, ensure_ascii=False))
'
fi
exit 0
