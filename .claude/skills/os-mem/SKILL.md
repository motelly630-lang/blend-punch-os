---
name: os-mem
description: 프로젝트 메모리(.claude/memory/)를 읽고 쓰고 합친다. "메모리에 저장해", "이거 기억해", "기억해둬", "결정 기록해", "지금 상태 뭐야", "어디까지 했지", "관련 메모리 찾아", "task 업데이트" 같은 요청, 또는 세션에서 확정된 결정·운영규칙·불변조건·미해결 문제가 나왔을 때 사용. 모든 대화를 저장하지 않고 장기적으로 쓸모 있는 것만 구조화해 기록한다.
argument-hint: "[save|find <키워드>|state|update <id>|supersede <id>|task]"
metadata:
  lifecycle: draft
  version: 0.1.0
  updated: 2026-09-11
  regression_rules: []
---

# 프로젝트 메모리 큐레이션

저장소 구조·프론트매터 규약은 `.claude/memory/INDEX.md` 하단 「저장소 규약」에 있다.
공유 라이브러리는 `.claude/lib/osmem.py` (python3 stdlib 만). 실행은 전부 WSL 경유:

```bash
wsl -- bash -lc "cd /home/blendpunch/blend-punch-os && python3 .claude/lib/osmem.py --selftest"
```

## 절대 규칙

1. **모든 것을 저장하지 않는다.** 다음 세션에도 쓸모 있는 것만 남긴다. 한 번 쓰고 버릴 맥락,
   대화 요약, 이미 코드·git 이력·`CLAUDE.md` 에 있는 사실은 저장하지 않는다.
2. **쓰기 전에 검색한다.** 같은 `type` + 겹치는 `tags` 를 먼저 찾는다. 있으면 **새로 만들지 말고
   그 문서를 update/merge** 한다. 중복 문서를 쌓는 것이 이 시스템을 망치는 첫 번째 경로다.
3. **충돌하면 최신 확정을 우선한다.** 새 문서에 `supersedes: <옛 id>` 를 적고 옛 문서를
   `status: superseded` + `superseded_by:` 로 내린다. **삭제하지 않는다.**
   issue 가 해결되면 `status: resolved` 로 바꾸고 **무엇을 어떻게 해소했는지 절차를 남긴다**
   (같은 상황이 다시 왔을 때 재사용할 수 있어야 한다). 기본 조회는 `active` 만 본다.
4. **비밀값을 쓰지 않는다.** 이 디렉터리는 커밋된다. 비밀번호·API 키·토큰·접속문자열은
   값이 아니라 **위치만** 가리킨다. 커밋 전 `git diff` 로 확인한다.
5. **검증한 것만 쓴다.** 수치·경로·커밋 해시는 실제 확인한 값만. 미확인은 "미확인"으로 적는다.
6. **문서를 추가/수정하면 `INDEX.md` 의 해당 표도 같이 갱신한다.** 인덱스가 빠지면
   세션 시작 주입에서 보이지 않아 존재하지 않는 것과 같다. INDEX 는 **120줄 상한**.
7. 개인·범프로젝트 사실(이 프로젝트에 국한되지 않는 것)은 여기가 아니라 내장 harness memory 에.

## save — 이번 세션에서 남길 것을 기록

1. 후보를 뽑는다. 출처는 (a) 이번 세션에서 사용자가 확정한 결정·규칙, (b) 실제로 겪은 실패와
   원인, (c) 기계 저널 `.claude/state/journal-<session>.jsonl` (있으면), (d) 새로 드러난 미해결 문제.
2. 각 후보를 분류한다 — `project` `decision` `preference` `workflow` `issue` `regression`.
   어디에도 안 맞으면 저장하지 않는다(그게 정답인 경우가 많다).
3. **기존 문서를 검색한다** (아래 find). 겹치면 update 경로로 간다.
4. 사용자에게 **제안 목록을 먼저 보여준다** — `type / 제목 / 한 줄 요약 / 신규 or 기존 갱신`.
   승인 없이 쓰지 않는다.
5. 승인된 것만 쓴다. ID 는 `python3 -c "import sys; sys.path.insert(0,'.claude/lib'); import osmem; print(osmem.next_id('decision'))"`
   로 받는다(번호 재사용 금지). 파일명은 `<ID>-<한글-또는-영문-슬러그>.md`.
6. `INDEX.md` 표에 한 줄 추가 → `state.json` 의 `memory.updated` 갱신.
7. 무엇을 어디에 썼는지 경로 목록으로 보고한다.

문서 본문 형식 (짧게, 15~25줄):

```markdown
<한 문단: 무엇을 지키거나 알아야 하는가>

**근거 / 깨지면 어떻게 되는가:** <실제 사례가 있으면 커밋 해시·날짜와 함께>
**검증 방법:** <명령 또는 확인 경로>
**탈락 대안:** <decision 인 경우 필수 — 무엇을 왜 안 골랐는가>

관련: [[다른-id]]
```

`decision` 은 **탈락 대안을 반드시 적는다.** 고른 것만 적으면 나중에 쓸모가 없다.

## find — 관련 메모리 찾기

```bash
wsl -- bash -lc "cd /home/blendpunch/blend-punch-os && grep -ril '<키워드>' .claude/memory --include='*.md'"
```

키워드가 안 맞으면 `tags` 를 훑는다:
```bash
wsl -- bash -lc "cd /home/blendpunch/blend-punch-os && grep -h '^tags:' .claude/memory/*/*.md"
```

찾은 문서는 **필요한 것만 Read** 한다. 전부 읽지 않는다.
`status: superseded` 문서는 이력 확인 목적이 아니면 무시한다.

## state / task — 현재 상태

```bash
wsl -- bash -lc "cd /home/blendpunch/blend-punch-os && cat .claude/memory/state.json"
```

`state.json` 필드: `state`(idle|active|blocked) · `current_task` · `tasks[]`(id/title/status) ·
`last_checkpoint` · `memory` · `session`.

**진행률은 `tasks[]` 의 done/total 로만 계산한다.** 체크리스트가 없으면 `—` 로 표시하고
숫자를 만들지 않는다(`osmem.progress()` 가 `None` 을 주는 이유).

task 를 갱신할 때는 `tasks[]` 의 `status` 만 바꾼다(`todo`→`doing`→`done`). 작업이 바뀌면
`current_task` 와 `tasks[]` 를 함께 교체한다. 쓰기는 `osmem.save_state()` (원자적)를 쓴다.

## update / supersede

- **update**: 기존 문서 본문을 고치고 `updated:` 를 오늘로. 같은 사실의 보강·정정은 전부 여기.
- **supersede**: 결론이 **뒤바뀐** 경우에만. 새 문서에 `supersedes: <옛 id>`,
  옛 문서는 `status: superseded` + `superseded_by: <새 id>`. INDEX 표에서 옛 항목을 제거한다.

판단 기준: "과거 기록이 지금도 참인가?" 참이지만 불완전 → update. 거짓이 됨 → supersede.

## 하지 말 것

- 세션 대화를 요약해 저장하기 (이 시스템의 목적이 아니다)
- 코드에서 바로 읽을 수 있는 사실을 메모리에 복제하기 (갈라져서 거짓이 된다)
- `CLAUDE.md` / `BLENDPUNCH_OS_SECOND_BRAIN.md` 내용을 옮겨 적기 — **포인터만** 둔다
- 사용자 승인 없이 문서를 쓰거나 지우기
- 앱의 `agent_memory` 테이블을 건드리기 (그쪽은 제품의 AI 파이프라인용이다)
