#!/usr/bin/env bash
# blend-punch-os EC2 배포 헬퍼
# 사용법:
#   deploy.sh git                      # git pull 방식 (커밋된 변경 배포)
#   deploy.sh scp <파일1> <파일2> ...  # 특정 파일만 직접 복사 (핫픽스)
#
# 반드시 WSL 안에서 실행한다 (SSH 키·git·scp 가 WSL 에만 있다).
# Windows 에서는:  wsl -- bash -lc "bash <이 스크립트 경로> git"
set -euo pipefail

KEY="$HOME/.ssh/blendpunch-key.pem"
# 스크립트 위치(.claude/skills/ec2-deploy/scripts/)에서 프로젝트 루트를 유도한다
LOCAL=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)
REMOTE="/home/ubuntu/blend-punch-os"
DOMAIN="os.blendpunch.com"

[ -r "$KEY" ] || { echo "❌ SSH 키를 읽을 수 없음: $KEY (WSL 안에서 실행 중인지 확인)"; exit 1; }
[ -d "$LOCAL/app" ] || { echo "❌ 프로젝트 루트 판별 실패: $LOCAL"; exit 1; }

# --- 1) 현재 IP를 DNS로 확인 (IP가 자주 바뀜) ---
IP=$(getent hosts "$DOMAIN" | awk '{print $1}' | head -1)
if [ -z "$IP" ]; then echo "❌ $DOMAIN IP를 못 찾음"; exit 1; fi
HOST="ubuntu@$IP"
SSH="ssh -i $KEY -o StrictHostKeyChecking=no -o ConnectTimeout=15 $HOST"
echo "🌐 현재 EC2 IP: $IP"
echo "📁 로컬 루트: $LOCAL"

MODE="${1:-}"; shift || true

case "$MODE" in
  git)
    echo "📦 [git] EC2에서 pull + 재시작"
    $SSH "cd $REMOTE && git pull origin master && sudo systemctl restart blendpunch"
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
    echo "사용법: deploy.sh git | deploy.sh scp <파일...>"; exit 1
    ;;
esac

# --- 검증 ---
sleep 2
echo "✅ 서비스 상태: $($SSH 'systemctl is-active blendpunch')"
echo "🔍 라이브 응답: $(curl -s -o /dev/null -w 'HTTP %{http_code}' https://$DOMAIN/)"
echo "배포 완료."
