---
name: os-checkpoint
description: 작업 체크포인트를 남기고 복원한다. "체크포인트 찍어", "여기까지 저장해", "롤백 지점 만들어", "어디까지 했지", "이어서 하자", "지난번에 뭐 하다 말았지" 같은 요청, 그리고 위험한 작업 직전(마이그레이션·대규모 수정·배포) 또는 검증 통과 직후에 사용. 세션이 중간에 끊겨도 다음 세션이 이어받을 수 있게 한다.
argument-hint: "[create <메모> | list | resume]"
metadata:
  lifecycle: draft
  version: 0.1.0
  updated: 2026-09-11
  regression_rules: [RG-004]
---

# 작업 체크포인트

세션이 끊겨도 **어디까지 했는지 / 무엇이 남았는지 / 어떤 파일을 건드렸는지 / 무엇으로 검증했는지**
를 다음 세션이 알 수 있게 남긴다.

저장 위치 — 요약과 상세를 나눈다:

| 무엇 | 어디 | 공유 |
|---|---|---|
| 최신 체크포인트 요약 | `.claude/memory/state.json` 의 `last_checkpoint` | 커밋됨 (팀 공유·상태바 표시) |
| 체크포인트 상세 이력 | `.claude/state/checkpoints/<ts>.json` | 머신 로컬 (gitignore) |
| 이번 세션 수정 저널 | `.claude/state/journal-<session>.jsonl` | 머신 로컬, 훅이 자동 기록 |

## 언제 찍는가

- 작업 **시작** 시 (되돌아올 지점)
- **마이그레이션 실행 전** (`migrate.py`)
- **대규모 수정 전** (파일 5개 이상 건드릴 예정)
- **검증 통과 직후** (여기까지는 확실히 동작한다는 표시)
- **배포 전**

위험한 작업 앞에서는 **사용자가 요청하지 않아도 먼저 제안**한다. 되돌릴 수 없는 일을 하기
전에 되돌아올 지점을 만드는 것이 이 스킬의 존재 이유다.

## create — 체크포인트 남기기

1. 사실을 모은다 (추측하지 않는다):
   ```bash
   wsl -- bash -lc "cd /home/blendpunch/blend-punch-os && git rev-parse --short HEAD && git status --porcelain"
   ```
   저널도 읽는다: `.claude/state/journal-<session>.jsonl` — 이번 세션에 실제로 수정한 파일 목록.
2. `.claude/state/checkpoints/<YYYYMMDD-HHMMSS>.json` 에 쓴다:
   ```json
   {
     "id": "CP-005", "at": "2026-09-11T14:00:00+0900",
     "git": "6820fcb", "dirty": ["scripts/enrich_products.py"],
     "note": "무엇을 하던 중인지 한 줄",
     "done": ["완료한 것"], "remaining": ["남은 것"],
     "verified": "무엇으로 확인했는지 — 셀프테스트/curl/import검사 등. 안 했으면 '검증 안 함'"
   }
   ```
3. `state.json` 의 `last_checkpoint` 를 `{id, at, git, note}` 로 갱신한다 (`osmem.save_state`).
4. 경로와 git rev 를 보고한다.

**`verified` 를 낙관적으로 쓰지 않는다.** 이 프로젝트에는 테스트가 없다([[IS-001]]).
"테스트 통과"라고 쓸 수 있는 상황은 거의 없다. 무엇으로 확인했는지 그대로 적는다.

## list — 체크포인트 목록

```bash
wsl -- bash -lc "cd /home/blendpunch/blend-punch-os && ls -1t .claude/state/checkpoints/ 2>/dev/null | head -10"
```
각 항목의 `at` · `git` · `note` 만 한 줄씩 보여준다. 전문을 다 읽지 않는다.

## resume — 이어서 하기

새 세션에서 "어디까지 했지" 를 물었을 때의 절차:

1. `state.json` 을 읽는다 — `current_task`, `tasks[]`, `last_checkpoint`.
2. 최신 체크포인트 상세를 읽는다 (`done` / `remaining` / `verified`).
3. **현재 git 상태와 대조한다** — 체크포인트의 `git` rev 이후로 커밋이 있었는지,
   dirty 파일이 그대로인지. 어긋나면 그 사실을 먼저 보고한다.
4. "여기까지 했고, 이게 남았고, 이건 아직 검증 안 됐다" 를 요약한 뒤 다음 행동을 제안한다.

**체크포인트는 git 상태를 되돌리지 않는다.** 코드를 되돌리려면 `git` 을 직접 쓴다 —
이 스킬은 *맥락*을 복원할 뿐이다. 코드 롤백은 체크포인트의 `git` rev 를 참조해
사용자에게 방법을 제안하고 승인받아 실행한다.

## 하지 말 것

- 체크포인트를 남발하지 않는다 (매 수정마다 찍으면 의미가 없다). 위 「언제 찍는가」 기준을 지킨다.
- `verified` 에 확인하지 않은 것을 적지 않는다.
- 체크포인트 상세를 `.claude/memory/` 에 쓰지 않는다 — 거기는 **영구 지식**이고
  체크포인트는 **진행 상태**다. 영구히 남길 교훈이 생겼다면 `/os-mem save` 로 따로 기록한다.
