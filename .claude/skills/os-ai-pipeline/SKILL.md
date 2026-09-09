---
name: os-ai-pipeline
description: blend-punch-os의 AI 5단계 에이전트 파이프라인(Staff→Assistant→Manager→Lead→Director)을 제품/브랜드에 실행하고 휴먼리뷰 큐를 확인할 때 사용. "제품 파이프라인 돌려", "AI로 제품 검토해", "결재큐 보여줘", "파이프라인 실행", "AI 콘텐츠 자동생성" 등. Tier 0~1 자동(콘텐츠·캠페인 초안 생성)은 파이프라인이 처리, Tier 2(외부발송·정산)는 결재큐에서 사람이 승인.
version: 1.1.0
---

# OS AI 파이프라인 실행 (blend-punch-os)

제품/브랜드에 **5단계 AI 에이전트 파이프라인**을 돌리고, 결과를 **휴먼리뷰 큐**에서 승인/반려하는 절차.

## ⚠️ 실행 위치: 반드시 WSL

앱 서버·venv 가 WSL 에만 있다. Windows Claude Code 에서는 모든 실행 명령을
`wsl -- bash -lc "..."` 로 감싼다. **Windows 에서 `uv run` 을 직접 실행하지 마라 —
Linux `.venv` 가 Windows 용으로 재생성되어 WSL·EC2 실행환경이 함께 깨진다.**

## 개념
- **5단계 역할**: Staff → Assistant → Manager → Lead → Director (각 단계가 점수/리스크 판단)
- **Decision Engine**: 역할별 threshold로 Auto-Pass / Human-Review / Reject 결정
- **자동 트리거**: 이사(Director) 승인 시 캠페인 + 제안서 자동 생성
- **Tier 게이트**: 콘텐츠·초안 생성=자동 / 외부발송·결제·정산=결재큐에서 사람 승인

## 인증
JWT 쿠키 방식. `POST /login` (form: `username`, `password`) → 쿠키 발급.
자격증명은 환경변수로 전달 (스크립트에 비번 하드코딩 금지):
```bash
export OS_USER=master
export OS_PASS='<비밀번호>'   # 메모리 참조. 셸 히스토리/로그에 남기지 말 것
```

## 주요 엔드포인트 (모두 인증 필요)
| 동작 | 메서드 · 경로 |
|------|---------------|
| 기존 제품 재검토 시작 | `POST /api/pipeline/product/{product_id}/start` |
| 브랜드 단위 시작 | `POST /api/pipeline/brand/{brand_id}/start` |
| 신규 제품 생성 파이프라인 | `POST /api/pipeline/create/product/start` (form: text/image_file/excel_file) |
| 진행 폴링 | `GET /api/pipeline/poll/{target_type}/{target_id}` → `job_status`(running/done/error), `steps`, `review_status`, `review_queue_id` |
| 결재 대기열 조회 | `GET /api/pipeline/queue/list` |
| 결재 승인 | `POST /api/pipeline/queue/{queue_id}/approve` |
| 결재 반려 | `POST /api/pipeline/queue/{queue_id}/reject` |

## 빠른 실행 (헬퍼 스크립트)
제품 하나에 파이프라인 실행 + 진행 폴링 + 결과/결재큐 요약까지:
```bash
wsl -- bash -lc "OS_USER=master OS_PASS='...' bash .claude/skills/os-ai-pipeline/scripts/run-pipeline.sh <product_id> [base_url]"
# base_url 기본값: http://127.0.0.1:8000 (로컬). 프로덕션은 https://os.blendpunch.com
```
> 프로젝트 루트에서 실행한다고 가정한다. 프로젝트를 UNC 로 열어 두면 `wsl` 이 cwd 를 POSIX 로
> 변환하므로 그대로 동작한다. 다른 위치라면 `cd ~/blend-punch-os && ...` 를 앞에 붙인다.

## ⚠️ 주의 (실제 부작용 있음)
- 파이프라인이 Director까지 승인하면 **캠페인·제안서가 자동 생성**됨 (Tier 1). 테스트는 로컬(8000)에서 먼저.
- **외부 발송(DM/이메일)·정산은 자동 금지** — 반드시 결재큐에서 사람이 승인 (Tier 2).
- 로컬 서버 실행:
  ```bash
  wsl -- bash -lc "uv run uvicorn app.main:app --reload --port 8000"
  ```

## 자율 운영으로 확장 시
이 스킬은 "명령 시 실행"용. 무인 자동화하려면 자비스(APScheduler)나 cron이 이 스크립트/엔드포인트를
주기적으로 호출 → 결과를 텔레그램 결재함으로 보내고, 사람은 승인만. (Tier 게이트 유지)
