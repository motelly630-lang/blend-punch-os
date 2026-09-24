# blend-punch-os 프로젝트 메모리 인덱스

세션 시작 시 **이 파일만** 컨텍스트에 주입된다. 각 항목의 전문은 필요할 때 Read 한다.
키워드로 찾기: `/os-mem find <키워드>` · 저장/수정: `/os-mem save` · 상태: `/os-mem state`

> 규칙: 여기 있는 한 줄 요약은 **포인터**다. 원본 문서 내용을 이 파일로 옮겨 적지 않는다.
> 새 문서를 만들기 전에 같은 type + 겹치는 tags 를 먼저 검색하고, 있으면 그 문서를 update 한다.

## PROJECT — 시스템 구조·설계

| id | 내용 | 파일 |
|---|---|---|
| PR-001 | 어디를 먼저 읽어야 하는가 (CLAUDE.md / SECOND_BRAIN / os-locate 진입점) | `project/PR-001-*.md` |
| PR-002 | 멀티테넌시는 2축 — `company_id`(내부) + `partner_id`(협력사 포털) | `project/PR-002-*.md` |

## DECISIONS — 확정된 결정과 근거

| id | 내용 | 파일 |
|---|---|---|
| DE-001 | 편집은 Windows, 실행·빌드·git 은 전부 WSL (uv/npm 을 Windows 에서 쓰면 환경이 깨진다) | `decisions/DE-001-*.md` |
| DE-002 | EC2 파일 배포는 작업트리가 아니라 `git archive HEAD` 로 보낸다 (WIP 혼입 방지) | `decisions/DE-002-*.md` |
| DE-003 | 프로젝트 메모리는 repo 안 파일 — DB·harness memory 가 아니다 | `decisions/DE-003-*.md` |
| DE-004 | 정적 파일은 nginx 가 직접 서빙·압축. uvicorn 워커 증설은 스케줄러 중복 때문에 금지 | `decisions/DE-004-*.md` |
| DE-005 | 인플루언서 주민등록번호는 OS 에 저장하지 않는다 (세무 쪽 별도 관리, 평문 저장 금지) | `decisions/DE-005-*.md` |
| DE-006 | 인스타 프로필 자동 수집은 Meta 공식 Business Discovery API (봇 로그인 금지) | `decisions/DE-006-*.md` |
| DE-007 | OS 안의 쇼핑몰(`/shop`)은 안 쓴다 — 별도 쇼핑몰 사용. 코드는 남김, 우선순위 제외 | `decisions/DE-007-*.md` |

## PREFERENCES — 반복 요구하는 작업 방식

| id | 내용 | 파일 |
|---|---|---|
| PF-001 | 한국어로 답하고, 검증한 것만 쓰고, 진행률 같은 수치를 창작하지 않는다 | `preferences/PF-001-*.md` |
| PF-002 | 최소 변경 — 대규모 수정은 이유·영향범위 설명 후 승인받고 한다 | `preferences/PF-002-*.md` |
| PF-003 | 배운 것은 성격별로 나눠 **적용 조건**을 붙여 기존 것을 개선 (명시/추론 구분) — `/os-learn` | `preferences/PF-003-*.md` |

## REGRESSION — 수정 전에 확인할 불변조건

| id | 조건 | 검증 | 파일 |
|---|---|---|---|
| RG-001 | 새 라우터는 `include_router` + `_setup_filters()` **둘 다** 등록 | R1 기계적 (훅 자동) | `regression/RG-001-*.md` |
| RG-002 | 모든 조회·생성은 `get_company_id(user)` 로 스코프 (자동 생성 경로 포함) | R3 심사형 | `regression/RG-002-*.md` |
| RG-003 | `products.status`/`visibility_status` 는 영문 소문자 정규화값만 | R2 SQL | `regression/RG-003-*.md` |
| RG-004 | EC2 `reset --hard`/`pull` 전에 blob SHA 전수 비교 + 백업 | R2 수동 | `regression/RG-004-*.md` |
| RG-005 | tailwind safelist 정규식의 `^...$` 앵커 유지 (없으면 CSS 가 5배 부풂) | R2 용량확인 | `regression/RG-005-*.md` |
| RG-006 | JSON 을 큰따옴표 속성에 넣을 땐 `tojson` 뒤에 `forceescape` (안 하면 Alpine 화면 깨짐) | R1 테스트 자동 | `regression/RG-006-*.md` |

## ISSUES — 미해결 문제·기술부채

| id | 내용 | 파일 |
|---|---|---|
| IS-001 | **테스트·CI·린트 부족** — 8파일 90건(캠페인·Slack·인플루언서·Meta, unittest). 나머지 영역·CI·린트 없음 | `issues/IS-001-*.md` |
| IS-003 | WSL 개인 설정이 프로젝트 설정을 덮어쓴다 (전부 내용 다름, Phase 4) | `issues/IS-003-*.md` |
| IS-004 | EC2 에만 있는 미추적 파일 9개 — 전부 미참조 잔재, 정리 대상 | `issues/IS-004-*.md` |
| IS-005 | `static/logo.png` 이 없는데 템플릿 10곳 이상이 참조 (로고 안 보임) | `issues/IS-005-*.md` |

해소됨(`status: resolved`, 절차 재사용 목적으로 보존):
`IS-002` EC2 git 드리프트 · origin 미push · 노출 토큰 — 2026-09-11 전부 해소
`IS-006` tojson 속성 깨짐 11곳(제품·CS·쇼핑몰·가져오기) — 2026-09-24 수정 + 테스트로 강제

## WORKFLOWS

아직 없음. 반복 절차가 2회 이상 확인되면 `/os-mem save` 로 기록한다.

## LEARNING — 배운 것 반영 (`/os-learn`)

"이번 작업에서 배운 것 반영해줘" → `/os-learn`. 원장 `learning/LEDGER.md`(무엇을·왜·조건·되돌리기),
평가 사례 `learning/evals/EV-*.md`, 점검 `python3 .claude/lib/learn.py lint|pending`. 필요할 때만 Read.

## CHANGELOG

`changelog/YYYY-MM.md` — 무엇을 언제 왜 고쳤는지. append-only, 월 단위.
diff 는 옮겨 적지 않는다(커밋 해시로 `git show`). 최신: `changelog/2026-09.md`

## 저장소 규약

```
.claude/memory/          커밋 대상 — 팀 공유 지식
  INDEX.md               이 파일. 120줄 상한 (넘으면 주입 시 잘리고 경고가 뜬다)
  state.json             현재 작업·task 체크리스트·체크포인트 (진행률의 유일한 근거)
  project|decisions|preferences|workflows|issues|regression/
.claude/state/           gitignore — 머신 로컬 (세션 스크래치·저널·체크포인트)
.claude/lib/osmem.py     공유 라이브러리 (python3 stdlib 만). 확인: --selftest
```

프론트매터: `id` `type` `title` `status` `supersedes` `tags` `paths` `updated`.
`status` 는 `active`(기본) · `superseded`(결론이 뒤바뀜) · `resolved`(issue 가 해결됨) 셋이다.
기본 조회는 `active` 만 본다. 오래된 내용이 현재와 충돌하면 새 문서에 `supersedes:` 를 적고
과거 문서를 `superseded` 로 내린다. **어느 경우에도 삭제하지 않는다** — git 이력이 감사 기록이고,
해결된 issue 도 절차를 재사용하려면 남아 있어야 한다.

**비밀값을 쓰지 않는다.** 이 디렉터리는 커밋된다. 비밀번호·API 키·접속문자열은 위치만 가리킨다
(예: "접속정보는 WSL `~/.claude/os-db-ro.env`").

개인·범프로젝트 사실은 여기가 아니라 내장 harness memory 에 둔다 ([[DE-003]] 참조).
