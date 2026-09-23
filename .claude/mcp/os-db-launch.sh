#!/usr/bin/env bash
# blend-punch-os DB MCP 런처 (os-db-local / os-db-prod)
#
# 목적: Windows Claude Code 가 MCP 프로세스를 WSL 안에서 띄우게 한다.
#       DB 자격증명은 WSL 의 ~/.claude/os-db-ro.env 에서만 읽는다.
#       Windows 디스크에는 접속문자열이 저장되지 않는다.
#
# 사용:  bash .claude/mcp/os-db-launch.sh local|prod
# 점검:  bash .claude/mcp/os-db-launch.sh local --check     (기동 가능 여부만, 접속문자열 미출력)
#
# ⚠️ stdout 은 MCP JSON-RPC 전용이다. 진단 메시지는 반드시 stderr(>&2) 로 낸다.
#    접속문자열은 어떤 경우에도 출력하지 않는다.
set -uo pipefail

TARGET="${1:-}"
MODE="${2:-run}"
ENV_FILE="${OS_DB_ENV_FILE:-$HOME/.claude/os-db-ro.env}"
# 버전 고정 — npx -y 가 새 버전을 받아 동작(SSL 해석 등)이 조용히 바뀌지 않게
MCP_PKG="@henkey/postgres-mcp-server@1.0.7"
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# AWS RDS 공개 CA 번들 (비밀 아님, https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem)
RDS_CA="$HERE/rds-global-bundle.pem"

die() { echo "os-db-launch: $*" >&2; exit 1; }

case "$TARGET" in
  local) VAR=CLAUDE_RO_LOCAL ;;
  prod)  VAR=CLAUDE_RO_PROD ;;
  *)     die "대상이 없습니다. 사용법: os-db-launch.sh local|prod" ;;
esac

[ -r "$ENV_FILE" ] || die "자격증명 파일을 읽을 수 없습니다: $ENV_FILE (WSL 안에서 실행되고 있는지 확인)"

set -a
# shellcheck disable=SC1090
. "$ENV_FILE" || die "자격증명 파일 로드 실패: $ENV_FILE"
set +a

CONN="${!VAR:-}"
[ -n "$CONN" ] || die "$ENV_FILE 에 $VAR 가 정의되어 있지 않습니다"

# RDS 는 SSL 을 강제한다(rds.force_ssl). sslmode 없이 붙으면 서버가 끊는다:
#   no pg_hba.conf entry for host "...", user "claude_ro", database "...", no encryption
# SSL 정책은 여기(버전관리 대상)에 두고 자격증명 파일은 순수 credential 로 유지한다.
case "$CONN" in
  *sslmode=*) : ;;
  *\?*)       CONN="$CONN&sslmode=require" ;;
  *)          CONN="$CONN?sslmode=require" ;;
esac

# node 는 nvm 설치라 비대화형 셸 PATH 에 없다 — 직접 찾는다.
# (/mnt/c 의 Windows node 를 절대 쓰지 않도록 nvm 경로를 앞에 붙인다)
if ! command -v node >/dev/null 2>&1 || case "$(command -v node)" in /mnt/*) true ;; *) false ;; esac; then
  NODE_BIN=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1)
  [ -n "$NODE_BIN" ] || die "WSL 안에서 node 를 찾지 못했습니다 (~/.nvm/versions/node/*/bin 없음)"
  PATH="$NODE_BIN:$PATH"
fi
export PATH
command -v node >/dev/null 2>&1 || die "node 실행 파일을 찾지 못했습니다"

# pg-connection-string 2.7+ 는 sslmode=require 를 verify-full 로 해석한다 → 인증서 검증을 한다.
# RDS CA 는 Node 기본 신뢰목록에 없어 "self-signed certificate in certificate chain" 으로 실패했다.
# 검증을 끄지 않고(no-verify 금지) RDS 공개 CA 를 신뢰목록에 추가한다.
[ -r "$RDS_CA" ] || die "RDS CA 번들이 없습니다: $RDS_CA"
export NODE_EXTRA_CA_CERTS="$RDS_CA"

export POSTGRES_CONNECTION_STRING="$CONN"
unset CLAUDE_RO_LOCAL CLAUDE_RO_PROD CONN

if [ "$MODE" = "--check" ]; then
  echo "target      : $TARGET" >&2
  echo "env file    : $ENV_FILE (읽기 OK)" >&2
  echo "node        : $(node -v)  ($(command -v node))" >&2
  echo "conn string : 설정됨 (내용 미출력)" >&2
  case "$POSTGRES_CONNECTION_STRING" in
    *sslmode=*) echo "sslmode     : 적용됨" >&2 ;;
    *)          echo "sslmode     : ⚠️ 없음 — RDS 가 연결을 거부한다" >&2 ;;
  esac
  echo "rds ca      : $RDS_CA ($(grep -c 'BEGIN CERTIFICATE' "$RDS_CA") certs)" >&2
  echo "mcp package : $MCP_PKG" >&2
  exit 0
fi

exec npx -y "$MCP_PKG"
