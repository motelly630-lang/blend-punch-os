#!/usr/bin/env bash
# blend-punch-os EC2 배포 헬퍼 — WSL(Windows) · macOS 공용
# 사용법:
#   deploy.sh check                    # 배포 전 점검만 (읽기 전용 — 서버를 바꾸지 않는다)
#   deploy.sh git                      # 커밋된 변경 배포: 점검 → 백업 → ff-only → import 검사 → 재시작
#   deploy.sh scp <파일1> <파일2> ...  # 특정 파일만 직접 복사 (핫픽스)
#
# Windows 에서는 WSL 안에서 실행한다 (SSH 키·git 이 WSL 에만 있다):
#   wsl -- bash -lc "cd ~/blend-punch-os && bash .claude/skills/ec2-deploy/scripts/deploy.sh git"
# macOS 에서는 터미널에서 그대로:
#   bash .claude/skills/ec2-deploy/scripts/deploy.sh git
set -euo pipefail

KEY="$HOME/.ssh/blendpunch-key.pem"
# 스크립트 위치(.claude/skills/ec2-deploy/scripts/)에서 프로젝트 루트를 유도한다
LOCAL=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)
REMOTE="/home/ubuntu/blend-punch-os"
DOMAIN="os.blendpunch.com"

[ -r "$KEY" ] || { echo "❌ SSH 키를 읽을 수 없음: $KEY (Windows 라면 WSL 안에서 실행 중인지 확인)"; exit 1; }
[ -d "$LOCAL/app" ] || { echo "❌ 프로젝트 루트 판별 실패: $LOCAL"; exit 1; }

# --- 1) 현재 IP를 DNS로 확인 (IP가 자주 바뀜) ---
# getent 는 Linux 전용이라 macOS 에서는 dig → python3 순으로 대체한다.
resolve_ip() {
  {
    getent hosts "$1" 2>/dev/null | awk '{print $1}'
    command -v dig >/dev/null 2>&1 && dig +short "$1" A 2>/dev/null
    python3 -c 'import socket,sys; print(socket.gethostbyname(sys.argv[1]))' "$1" 2>/dev/null
  } | grep -E '^[0-9]+(\.[0-9]+){3}$' | head -n 1 || true
}
IP=$(resolve_ip "$DOMAIN")
if [ -z "$IP" ]; then echo "❌ $DOMAIN IP를 못 찾음"; exit 1; fi
HOST="ubuntu@$IP"
SSH="ssh -i $KEY -o StrictHostKeyChecking=no -o ConnectTimeout=15 $HOST"
echo "🌐 현재 EC2 IP: $IP"
echo "📁 로컬 루트: $LOCAL"

MODE="${1:-}"; shift || true

# 로컬 HEAD 가 origin/master 에 올라가 있어야 EC2 가 받을 수 있다
target_commit() {
  git -C "$LOCAL" fetch -q origin master
  local head origin
  head=$(git -C "$LOCAL" rev-parse HEAD)
  origin=$(git -C "$LOCAL" rev-parse origin/master)
  if [ "$head" != "$origin" ]; then
    echo "❌ 로컬 HEAD(${head:0:7}) ≠ origin/master(${origin:0:7}) — 먼저 push/pull 로 맞추세요" >&2
    exit 1
  fi
  echo "$origin"
}

# 읽기 전용 점검: EC2 작업트리 드리프트 · ff 가능 여부 · 들어갈 커밋 · 비밀파일 미추적 ([[RG-004]])
remote_check() {
  $SSH bash -s "$1" <<'REMOTE'
set -u
cd /home/ubuntu/blend-punch-os
echo "EC2 HEAD: $(git rev-parse --short HEAD)"
DIRTY=$(git status --porcelain --untracked-files=no)
if [ -n "$DIRTY" ]; then echo "❌ EC2 에 커밋 안 된 추적파일 변경이 있음 — 덮어쓰기 전에 확인 필요:"; echo "$DIRTY" | head -n 20; exit 2; fi
echo "추적파일 변경: 없음"
git fetch -q origin master
if ! git merge-base --is-ancestor HEAD "$1"; then echo "❌ fast-forward 불가 (EC2 에만 있는 커밋 존재)"; exit 2; fi
N=$(git rev-list --count HEAD.."$1")
echo "들어갈 커밋: ${N}개"; git log --oneline HEAD.."$1" | head -n 20
if git ls-tree -r --name-only "$1" | grep -qE '(^|/)(\.env|google_sa\.json|instagram_session\.json)$'; then
  echo "❌ 비밀파일이 git 에 추적되고 있음 — 배포하면 운영 파일을 덮어쓴다"; exit 2
fi
echo "비밀파일 추적: 없음"
REMOTE
}

case "$MODE" in
  check)
    TARGET=$(target_commit)
    echo "🔎 [check] 배포 전 점검 (서버 변경 없음) — 대상 ${TARGET:0:7}"
    remote_check "$TARGET"
    echo "점검 끝. 배포하려면: deploy.sh git"
    exit 0
    ;;
  git)
    TARGET=$(target_commit)
    echo "🔎 배포 전 점검 — 대상 ${TARGET:0:7}"
    remote_check "$TARGET"
    echo "📦 [git] 백업 → ff-only → import 검사 → 재시작"
    $SSH bash -s "$TARGET" <<'REMOTE'
set -u
cd /home/ubuntu/blend-punch-os
PREV=$(git rev-parse HEAD)
STAMP=$(date +%Y%m%d-%H%M%S)
BK=/home/ubuntu/deploy-backup-$STAMP.tar.gz
tar czf "$BK" --exclude='__pycache__' app scripts migrate.py || { echo "❌ 백업 실패 — 중단"; exit 1; }
echo "백업: $BK ($(du -h "$BK" | cut -f1))"
git merge --ff-only -q "$1" || { echo "❌ ff 실패 — 중단 (변경 없음)"; exit 1; }
echo "코드: ${PREV:0:7} → $(git rev-parse --short HEAD)"
if ! .venv/bin/python -c "import app.main" >/tmp/import_check.log 2>&1; then
  echo "❌ import 실패 — 원복하고 재시작하지 않음"; tail -n 15 /tmp/import_check.log
  git reset -q --hard "$PREV"; echo "원복: $(git rev-parse --short HEAD)"; exit 1
fi
echo "import 사전검사 통과 → 재시작"
T0=$(date '+%F %T')
sudo systemctl restart blendpunch
sleep 4
echo "재시작 후 로그 (오류·기동):"
sudo journalctl -u blendpunch --since "$T0" --no-pager | grep -iE 'error|traceback|exception|Application startup' | cut -c1-200 | tail -n 10
echo "되돌리기: cd $PWD && git reset --hard ${PREV:0:7} && sudo systemctl restart blendpunch"
REMOTE
    ;;
  scp)
    if [ "$#" -eq 0 ]; then echo "❌ scp 모드는 파일 목록이 필요함"; exit 1; fi
    echo "📤 [scp] 파일 복사: $*"
    for f in "$@"; do
      scp -i "$KEY" -o StrictHostKeyChecking=no "$LOCAL/$f" "$HOST:$REMOTE/$f"
      echo "   ✓ $f"
    done
    echo "🔄 서비스 재시작"
    $SSH "sudo systemctl restart blendpunch"
    ;;
  *)
    echo "사용법: deploy.sh check | deploy.sh git | deploy.sh scp <파일...>"; exit 1
    ;;
esac

# --- 검증 ---
sleep 2
echo "✅ 서비스 상태: $($SSH 'systemctl is-active blendpunch')"
echo "🔍 라이브 응답: $(curl -s -o /dev/null -w 'HTTP %{http_code}' https://$DOMAIN/login) (/login)"
echo "배포 완료."
