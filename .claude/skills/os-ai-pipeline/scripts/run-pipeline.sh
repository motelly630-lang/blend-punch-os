#!/usr/bin/env bash
# blend-punch-os AI 파이프라인 실행 헬퍼
# 사용법: run-pipeline.sh <product_id> [base_url]
# 환경변수 필수: OS_USER, OS_PASS
#
# 반드시 WSL 안에서 실행한다.
# Windows 에서는:  wsl -- bash -lc "OS_USER=... OS_PASS='...' bash <이 스크립트 경로> <product_id>"
set -euo pipefail

PID="${1:?❌ product_id 필요}"
BASE="${2:-http://127.0.0.1:8000}"
: "${OS_USER:?❌ OS_USER 환경변수 필요}"
: "${OS_PASS:?❌ OS_PASS 환경변수 필요}"
JAR="$(mktemp)"
trap 'rm -f "$JAR"' EXIT

# 1) 로그인 → 쿠키 저장
curl -s -c "$JAR" -o /dev/null \
  --data-urlencode "username=$OS_USER" \
  --data-urlencode "password=$OS_PASS" \
  "$BASE/login"
if [ "$(grep -vc '^#' "$JAR" 2>/dev/null || echo 0)" -lt 1 ]; then
  echo "❌ 로그인 실패 (쿠키 없음) — 아이디/비번/서버주소 확인"; exit 1
fi
echo "🔑 로그인 OK"

# 2) 파이프라인 시작
echo "🚀 파이프라인 시작: product=$PID @ $BASE"
curl -s -b "$JAR" -X POST "$BASE/api/pipeline/product/$PID/start" | python3 -m json.tool || true

# 3) 진행 폴링 (최대 ~3분)
echo "⏳ 진행 상황:"
RESP="{}"
for i in $(seq 1 60); do
  sleep 3
  RESP="$(curl -s -b "$JAR" "$BASE/api/pipeline/poll/product/$PID")"
  JS="$(printf '%s' "$RESP" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("job_status","?"))' 2>/dev/null || echo "?")"
  DN="$(printf '%s' "$RESP" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("steps_done","?"))' 2>/dev/null || echo "?")"
  echo "  [$i] job=$JS  steps=$DN/5"
  [ "$JS" = "done" ] || [ "$JS" = "error" ] && break
done

# 4) 결과 요약 + 결재큐
echo "📋 단계별 결정:"
printf '%s' "$RESP" | python3 -c '
import sys, json
d = json.load(sys.stdin)
for s in d.get("steps", []):
    print("  - %s: %s  (score=%s, risk=%s)" % (
        s.get("role_label"), s.get("decision"), s.get("score"), s.get("risk_level")))
print("  review_status:", d.get("review_status_label"))
print("  review_queue_id:", d.get("review_queue_id"))
print("  auto_triggered:", d.get("triggered"))
' 2>/dev/null || echo "  (결과 파싱 실패)"

echo "🗂  결재 대기열 (queue/list):"
curl -s -b "$JAR" "$BASE/api/pipeline/queue/list" | python3 -m json.tool 2>/dev/null | head -40 || echo "  (조회 실패)"
echo "✅ 완료. 승인하려면: POST $BASE/api/pipeline/queue/<id>/approve"
