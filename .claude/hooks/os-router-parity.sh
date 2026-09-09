#!/usr/bin/env bash
# os-router-parity.py 를 항상 WSL 의 python3 으로 실행시키기 위한 얇은 래퍼.
#
# 왜 필요한가: settings.json 에 `python3 ...` 를 그대로 쓰면 Windows Claude Code 에서는
# Windows 의 python3.exe 가 잡힌다. 그러면 스크립트가 UNC 경로 기준으로 돌아 경로 비교가
# 전부 어긋나고, 검사가 '조용히 아무것도 안 하는' 상태가 된다.
# 훅 커맨드를 `bash <이 파일>` 로 두면 Windows 에서는 bash.exe(WSL 런처)를 거치므로
# 항상 WSL 안의 python3 이 쓰인다.
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if ! command -v python3 >/dev/null 2>&1; then
  # 조용히 넘기지 않는다 — 검사가 돌지 않았다는 사실을 알린다.
  echo '{"systemMessage":"✗ 라우터 정합성 검사 미실행 — WSL 에서 python3 를 찾지 못했습니다"}'
  exit 0
fi

exec python3 "$HERE/os-router-parity.py" "$@"
