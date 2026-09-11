#!/usr/bin/env bash
# os-mem-load.py 를 항상 WSL 의 python3 으로 실행시키기 위한 얇은 래퍼.
#
# 왜 필요한가: settings.json 에 `python3 ...` 를 그대로 쓰면 Windows Claude Code 에서는
# Windows 의 python3.exe 가 잡힌다. 그러면 프로젝트 경로가 UNC 기준으로 어긋나 메모리를
# 찾지 못하고 '조용히 아무것도 안 하는' 상태가 된다.
# 훅 커맨드를 `bash <이 파일>` 로 두면 Windows 에서는 bash.exe(WSL 런처)를 거치므로
# 항상 WSL 안의 python3 이 쓰인다. (os-router-parity.sh 와 같은 패턴)
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if ! command -v python3 >/dev/null 2>&1; then
  # 조용히 넘기지 않는다 — 메모리가 로드되지 않았다는 사실을 알린다.
  echo '{"systemMessage":"✗ 프로젝트 메모리 미로드 — WSL 에서 python3 를 찾지 못했습니다"}'
  exit 0
fi

exec python3 "$HERE/os-mem-load.py" "$@"
