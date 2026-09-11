#!/usr/bin/env bash
# 훅 파이썬 스크립트를 항상 WSL 의 python3 으로 실행시키는 공용 래퍼.
#
# 왜 필요한가: settings.json 에 `python3 ...` 를 그대로 쓰면 Windows Claude Code 에서는
# Windows 의 python3.exe 가 잡힌다. 그러면 경로가 UNC 기준으로 어긋나 훅이 '조용히
# 아무것도 안 하는' 상태가 된다. `bash <이 파일> <스크립트>` 로 두면 Windows 에서는
# bash.exe(WSL 런처)를 거치므로 항상 WSL 안의 python3 이 쓰인다.
#
# os-router-parity.sh / os-mem-load.sh 와 같은 패턴이되, 스크립트마다 래퍼를 만들지 않는다.
#   사용: bash .claude/hooks/os-hook.sh os-mem-route.py
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SCRIPT="${1:-}"
shift || true

if [ -z "$SCRIPT" ]; then
  echo '{"systemMessage":"✗ os-hook.sh: 실행할 스크립트 이름이 없습니다"}'
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  # 조용히 넘기지 않는다 — 훅이 돌지 않았다는 사실을 알린다.
  printf '{"systemMessage":"✗ 훅 미실행(%s) — WSL 에서 python3 를 찾지 못했습니다"}\n' "$SCRIPT"
  exit 0
fi

exec python3 "$HERE/$SCRIPT" "$@"
