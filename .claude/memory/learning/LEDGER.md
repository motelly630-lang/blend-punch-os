# 학습 반영 원장 (LEDGER)

`/os-learn` 이 쓰는 append-only 장부. **무엇을 · 왜 · 어떤 조건에서 · 어디를 바꿨고 · 어떻게 되돌리는지**.
형식·상태값은 `.claude/skills/os-learn/SKILL.md` §6. 점검: `python3 .claude/lib/learn.py lint`.

- 상태: `applied`(반영됨) · `proposed`(승인·승격 대기) · `deferred`(보류) · `rejected`(버림) · `reverted`(되돌림)
- 근거: **명시** = 대표님이 직접 정한 원칙(발언 인용) · **추론** = 사례에서 끌어낸 개선안
- 비밀값·개인정보는 적지 않는다. 지우지 않는다 — 뒤집히면 새 항목 + `reverted`.

## 항목

### IM-001 · 2026-09-24 · applied
- 세션: a4d542f4
- 근거: 추론 (사실은 확인 — 운영 nginx 로그 `POST /influencersnew 404`, 대표님 "넣어봤거든? 근대 404오류가 나옴")
- 신호: 대표님이 결과를 지적 + 실패 원인·해결 확인
- 사례: 인플루언서 폼 템플릿을 다시 쓰며 `action` 의 `/` 누락 (`3442a3b`) → 운영 404 → `29c455c` 수정.
  테스트가 저장 주소로 직접 POST 해서 화면 쪽 실수를 못 잡았다.
- 적용 조건: **폼 템플릿을 새로 쓰거나 구조를 바꿀 때만** (단순 문구 수정엔 해당 없음)
- 변경: `.claude/skills/gen-test/SKILL.md` §1 "폼 템플릿…" 추가 · `~/.claude/skills/quality-gate/SKILL.md` 웹 화면 행
  (이전 상태: git 7a26276 · 전역은 백업 `~/.claude/backups/learn/2026-09-24/quality-gate.SKILL.md`)
- 검증: `tests/test_influencer_form.py::test_폼이_보내는_주소가_실제_저장주소다` 가 버그 버전에서 FAIL, 수정본에서 OK (2026-09-24)
- 평가: EV-001

### IM-002 · 2026-09-24 · applied
- 세션: a4d542f4
- 근거: 추론 (사실은 확인 — 헤드리스 스크린샷에 x-data 코드가 글자로 노출, 렌더 HTML 에서 `selected: ["` 확인)
- 신호: 작업 중 실패 원인·해결 확인
- 사례: `| tojson` 을 큰따옴표 속성에 넣어 인플루언서 편집 화면이 깨져 있었다 (기존 버그). `forceescape` 로 수정.
- 적용 조건: Jinja 템플릿에서 JSON 을 **큰따옴표 HTML 속성**에 넣을 때 (`<script>` 안·작은따옴표 속성은 제외)
- 변경: `.claude/memory/regression/RG-006-json을-html-속성에-넣을-때는-이스케이프한다.md` ·
  `.claude/lib/check_tojson_attr.py` (검사기) · `.claude/memory/issues/IS-006-tojson-속성-깨짐이-다른-화면에-남아있다.md`
  (이전 상태: git 7a26276 — 신규 파일)
- 검증: 검사기 `--selftest` ok · 고치기 전 `92e6277` 폼에서 1건 검출 · 현재 8건 검출(IS-006) · 제품 수정 화면 실제 깨짐 렌더로 확인
- 평가: EV-001

### IM-003 · 2026-09-24 · applied
- 세션: a4d542f4
- 근거: 추론 (사실은 확인 — 튜플 목록 전송 422 → dict+files 전송 302)
- 신호: 작업 중 실패 원인·해결 확인
- 사례: 같은 이름 칸이 두 번 가는 폼을 TestClient 로 흉내 낼 때 `data=[(k,v)…]` 가 422.
- 적용 조건: 같은 이름 칸을 여러 번 보내는 multipart 폼을 테스트할 때
- 변경: `.claude/skills/gen-test/SKILL.md` §1 (IM-001 과 같은 단락) (이전 상태: git 7a26276)
- 검증: `test_선택안한_유형의_칸은_비우고_나머지는_저장한다` 통과

### IM-004 · 2026-09-24 · applied
- 세션: a4d542f4
- 근거: 추론 (사실은 확인 — `git ls-files tests` 8파일, `def test_` 90건)
- 신호: 기록이 현실과 달라짐
- 사례: "테스트가 없다"(PF-002) · "캠페인 2파일뿐"(gen-test) · "캠페인 15건만"(INDEX) — 실제 8파일 90건
- 적용 조건: 사실 정정 (모든 작업)
- 변경: `.claude/memory/preferences/PF-002-최소변경과-대규모-수정-전-승인.md` · `.claude/memory/issues/IS-001-테스트와-ci가-전무하다.md` ·
  `.claude/memory/INDEX.md` · `.claude/skills/gen-test/SKILL.md` (이전 상태: git 7a26276)
- 검증: 수치는 명령 결과로만 적음. 숫자가 다시 낡지 않게 gen-test 는 "`ls tests/` 로 확인"으로 바꿈

### IM-005 · 2026-09-24 · proposed
- 세션: a4d542f4
- 근거: 추론
- 신호: 한 번 쓴 검증 절차가 효과 있었음 (IM-002 버그를 이걸로 발견)
- 사례: 로그인 필요한 화면을 임시 SQLite 격리 서버(로그인 쿠키 주입) + 헤드리스 크롬 스크린샷으로 확인
- 적용 조건: 로그인 뒤 화면(템플릿·Alpine)을 고쳤을 때
- 변경: 없음 — **1회 사용이라 스킬로 만들지 않음.** 다음 UI 작업에서 다시 쓰면 `gen-test` 부록 또는
  새 스킬(`os-screen-check`)로 승격. 스크립트 원형은 이 세션의 임시 폴더(scratchpad `serve.py`)에만 있어 세션이 끝나면 사라진다 — 승격 때 다시 작성.

### IM-006 · 2026-09-24 · proposed
- 세션: a4d542f4
- 근거: 추론 (`learn.py lint` info)
- 신호: 기록끼리 충돌 — 트리거 겹침
- 사례: "어디까지 했지" 가 `os-checkpoint` 와 `os-mem` 설명에 모두 있다
- 적용 조건: 스킬 선택
- 변경 제안: `os-mem` 설명에서 "어디까지 했지" 를 빼고 `os-checkpoint resume` 을 원본으로. 대표님 확인 후.

### IM-007 · 2026-09-24 · applied
- 세션: a4d542f4
- 근거: 명시 ("앞으로 내가 너와 나누는 대화와 실제 작업에서 배운 내용을 축적해서 … 체계를 만들고 싶어", [[PF-003]])
- 신호: 대표님이 원칙을 명시
- 사례: 학습 반영 체계 도입
- 적용 조건: 대표님이 "배운 것 반영" 을 요청할 때 (`/os-learn`)
- 변경: `.claude/skills/os-learn/SKILL.md` · `.claude/lib/learn.py` · `.claude/memory/learning/LEDGER.md` ·
  `.claude/memory/preferences/PF-003-배운-것은-성격별로-나눠-조건부로-반영한다.md` · `.claude/hooks/os-mem-load.py`(반영 대기 알림) ·
  `CLAUDE.md` · `.claude/memory/INDEX.md` (이전 상태: git 7a26276)
- 검증: `learn.py --selftest` · `lint` error 0 · `os-mem-load.py --selftest` · 전체 테스트

### IM-008 · 2026-09-24 · rejected
- 세션: a4d542f4
- 근거: 추론
- 신호: 작은 실패 반복 (이 세션 2회)
- 사례: zsh 에서 `echo =====` 가 `=` 확장으로 에러 (구분선 출력용, 작업 결과 영향 없음)
- 버린 이유: 셸 문법 사소한 실수, 결과에 영향 없음 — 영구 규칙으로 만들 가치 없음

### IM-009 · 2026-09-24 · applied
- 세션: a4d542f4
- 근거: 추론 (**실제 훅 입력의 필드명은 미확인** — 공식 문서 기억상 `prompt`, 코드는 `user_input` 만 읽음)
- 신호: 작업 중 확인 — "배운 것 반영해줘" 입력을 `prompt` 필드로 넣으면 포인터가 안 붙었다
- 사례: `os-mem-route.py` 가 `user_input` 만 읽는다. 필드명이 `prompt` 라면 관련 메모리 포인터가 그동안 안 붙었을 수 있다
- 적용 조건: UserPromptSubmit 훅 입력 읽기
- 변경: `.claude/hooks/os-mem-route.py` — `user_input` 없으면 `prompt` 도 읽음 (이전 상태: git 7a26276)
- 검증: 두 필드명 모두 🧭 포인터 주입 확인, 슬래시 명령은 여전히 건너뜀, `--selftest` 통과.
  **남은 확인:** 실제 세션에서 태그 단어가 든 요청에 `🧭 관련 메모리` 가 뜨는지 (다음 요청에서 확인)
  **확인됨 (2026-09-24):** 다음 대표님 메시지("…스킬로 만들면…")에 실제로 `PF-003` 포인터가 주입됐다.

### IM-010 · 2026-09-24 · applied
- 세션: a4d542f4
- 근거: 추론 (사실은 확인 — Jinja 로 `| tojson | e` 를 렌더하면 따옴표가 그대로 나옴)
- 신호: 작업 중 실패 원인·해결 확인 — 만든 검사기에 빈틈 2개
- 사례: (a) 한 속성 안 여러 건 중 마지막만 보고 (쇼핑몰 36번 줄 누락), (b) `| tojson | e` 를 안전으로 판정.
  고치자 위반 8 → 11건. 전부 `forceescape` 로 수정 (IS-006 resolved)
- 적용 조건: Jinja 템플릿에서 JSON 을 큰따옴표 속성에 넣을 때 (RG-006 과 같음)
- 변경: `.claude/lib/check_tojson_attr.py` · `tests/test_template_json_attrs.py` ·
  `.claude/memory/regression/RG-006-json을-html-속성에-넣을-때는-이스케이프한다.md` (이전 상태: git d04f84c)
- 검증: 새 테스트 4건이 고치기 전 템플릿에서 4 FAIL → 고친 뒤 OK, 전체 94 통과, 검사기 selftest 에 두 빈틈 사례 추가

### IM-011 · 2026-09-24 · applied
- 세션: a4d542f4
- 근거: 명시 ("너가 뭔가 러닝을 했을때 나한테 알려줘 이런내용을 배워서 습득을 했다 … 이거 스킬로 만들면 어떤거랑
  연결할수있고 어떤 부분을 더 보완할수있고 어떤 점을 더 강화할수있다 그래서 이 스킬 만들어도되냐")
- 신호: 대표님이 원칙을 명시
- 적용 조건: 작업 중 §2 신호가 생겼을 때, 그 작업 보고 끝 (배운 게 없으면 붙이지 않음)
- 변경: `CLAUDE.md` 배움 카드 규칙 · `.claude/skills/os-learn/SKILL.md` §5 카드 형식 ·
  `.claude/memory/preferences/PF-003-배운-것은-성격별로-나눠-조건부로-반영한다.md` (이전 상태: git d04f84c)
- 검증: 이번 보고에 카드 형식으로 첫 적용 (IM-012)

### IM-012 · 2026-09-24 · applied
- 세션: a4d542f4
- 근거: 추론
- 신호: 같은 종류 점검을 두 번 수동으로 함 (tojson 속성 검사 · 폼 주소 ↔ 실제 라우트 검사)
- 사례: 폼 주소 검사를 전체 템플릿에 돌려 실제 문제 0건, 조건문(if/else) 합침 때문에 오탐 4건 → 수동 확인
- 적용 조건: `app/templates/**/*.html` 을 고칠 때
- 제안: 템플릿 저장 시 자동 점검 훅 (`os-build-css` 처럼 PostToolUse) — tojson 검사 + 폼 주소 검사.
  보완 필요: if/else 분기별로 주소를 나눠 보기 (오탐 제거). 대표님 답 대기.
- 승인: 대표님 "2번은 그렇게해줘" (2026-09-24)
- 변경: `.claude/lib/check_form_urls.py`(분기별 펼침 + 코드로 서버 주소 읽기) · `.claude/hooks/os-template-check.py` ·
  `.claude/settings.json`(PostToolUse 등록) · `tests/test_template_form_urls.py` · `CLAUDE.md` (이전 상태: git dc3bfca)
- 검증: 코드로 읽은 주소 300개 = 실제 앱 주소(자동 문서 4개 제외) · 전체 템플릿 오탐 0 (이전 방식 4) ·
  `3442a3b` 폼에서 `/influencersnew` 검출 · **실제 세션에서 일부러 슬래시를 빼 저장 → 훅이 즉시 경고, 되돌림** ·
  검사 0.3초 · 전체 테스트 97 통과
- 한계: Write/Edit 도구로 고친 파일만 자동 검사 (셸 수정은 테스트·직접 실행으로)

### IM-013 · 2026-09-24 · applied
- 세션: a4d542f4
- 근거: 추론 (사실은 확인 — EC2 nginx 설정·systemd·블랜드픽 코드 grep·nginx/uvicorn 기록, env 는 키 이름만)
- 신호: 작업 중 확인 — 쇼핑몰 삭제 전 영향 조사에서 블랜드픽·산지픽이 OS 운영 DB 를 직접 읽고 쓰는 것을 발견
- 사례: 대표님 "shop.blendpunch.com 이거로 지금 결제를 받고 있는대, 우리 지금 여기랑 연결되어 있어??"
- 적용 조건: OS 의 influencers·campaigns·products·brands·sales_pages·shop_users 칸 이름 변경·삭제·타입 변경·NOT NULL,
  또는 `/inquiries/api/*` 변경 때만
- 승인: 대표님 "배움카드도 기록해줘" (2026-09-24)
- 변경: `.claude/memory/project/PR-003-블랜드픽-산지픽과-OS-연결-지도.md` ·
  `.claude/memory/regression/RG-007-OS-표-구조를-바꾸기-전에-블랜드픽-영향을-확인한다.md` ·
  `.claude/skills/create-migration/SKILL.md` §0 · `.claude/memory/INDEX.md` (이전 상태: git 43220bc)
- 검증: lint error 0 · 메모리 라우터가 관련 요청에 RG-007 포인터를 붙이는지 확인

### IM-014 · 2026-09-24 · applied
- 세션: a4d542f4
- 근거: 추론
- 신호: 대표님이 결과를 지적 ("그거샵은 안쓸거야") — 안 쓰는 기능을 급하다며 배포 권유
- 적용 조건: 버그를 "급하다, 바로 배포" 로 권할 때
- 제안: `ec2-deploy` 에 "급하다고 권하기 전에 결정 기록에서 실제 사용 기능인지 확인" 한 줄
- 보류 이유: 대표님 "우선 어떻게 진행될지 모르니까 우선은 마지막에 다시알려줘" — **다음 작업 마무리 때 다시 묻는다**
- 승인: 대표님 "그럼 그렇게해줘" (2026-09-24, 배움 카드 3건 함께)
- 변경: `.claude/skills/ec2-deploy/SKILL.md` 체크리스트 1 (이전 상태: git 549b767)

### IM-015 · 2026-09-24 · applied
- 세션: a4d542f4
- 근거: 추론 (사실은 확인 — 보류된 `43220bc` 가 배포 대기 목록에 포함됨)
- 신호: 작업 중 확인 — 보류한 변경이 다른 기능 배포에 딸려 갈 뻔함
- 적용 조건: 배포 전 점검 때, 보류(개발자 논의 후 등) 항목이 있을 때
- 승인: 대표님 "그럼 그렇게해줘"
- 변경: `.claude/skills/ec2-deploy/SKILL.md` 체크리스트 1 (이전 상태: git 549b767)
- 검증: 스킬 문서 재확인, lint

### IM-016 · 2026-09-24 · applied
- 세션: a4d542f4
- 근거: 추론 (사실은 확인 — 테스트 7건 통과 뒤 reviewer 가 심각 1·중간 3 발견, 수정 후 운영 실행)
- 신호: 실패 원인·해결 확인 (실패를 운영 전에 막음)
- 적용 조건: **운영 데이터를 일괄로 바꾸는 도구·스크립트를 실행하기 전**만
- 승인: 대표님 "그럼 그렇게해줘"
- 변경: `~/.claude/skills/quality-gate/SKILL.md` DB 변경 행 · `.claude/skills/create-migration/SKILL.md` §1
  (이전 상태: git 549b767 · 전역 백업 `~/.claude/backups/learn/2026-09-24/quality-gate.SKILL.v2.md`)
- 검증: lint
- 평가: 다음 운영 일괄 변경 때 "리뷰가 찾은 결함 수 / 운영 실행 후 결함 수" 기록

## 검토 기록

한 줄 = `/os-learn` 1회 실행. 세션 앞 8자리가 여기 있으면 SessionStart 의 "반영 대기" 알림에서 빠진다.

- 2026-09-24 · 세션 a4d542f4 · 근거: 현재 대화 + git(`3442a3b` `29c455c`) + 운영 로그 · 후보 9 · 적용 6 · 대기 2 · 버림 1
- 2026-09-24 · 세션 a4d542f4 (2차) · 근거: 현재 대화 + 테스트 전후 결과 · 후보 3 · 적용 2 · 대기 1
- 2026-09-24 · 세션 a4d542f4 (3차) · 근거: 현재 대화 + EC2 읽기 조사 · 후보 2 · 적용 1 · 보류 1
- 2026-09-24 · 세션 a4d542f4 (4차) · 근거: 현재 대화 + 리뷰 결과 · 적용 3 (IM-014·015·016)
