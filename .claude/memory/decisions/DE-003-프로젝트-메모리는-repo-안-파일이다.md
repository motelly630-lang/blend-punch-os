---
id: DE-003
type: decision
title: 프로젝트 메모리는 repo 안 파일이다 (DB 아님, harness memory 아님)
status: active
tags: [메모리, memory, 저장소, 설계, state, db, harness, 영속]
paths: [".claude/memory/**", ".claude/lib/osmem.py", ".claude/state/**"]
updated: 2026-09-11
---

`.claude/memory/` 에 마크다운 + `state.json` 으로 둔다. `.claude/state/` 는 머신 로컬(gitignore).

근거:
- **git 이 곧 수정이력·머지·롤백**이다. "무엇을 언제 왜 고쳤는지"가 공짜로 따라온다.
- grep 으로 찾을 수 있고 DB 연결이 필요 없다. 팀과 공유된다.
- state 를 **repo 안**에 두므로 Windows/WSL 어느 쪽에서 실행해도 같은 파일을 본다.

탈락 대안:
- **Postgres 테이블** — `.claude/settings.json` 이 DB MCP 의 mutation·DDL 을 82건 deny 중이고,
  마이그레이션이 필요하며 `*.db` 는 gitignore 된다. 게다가 앱에 이미 `agent_memory` 테이블이
  있어 **이름이 충돌**한다(그쪽은 제품의 AI 파이프라인용이다. 건드리지 않는다).
- **내장 harness memory**(`~/.claude/projects/*/memory/`) — 머신 로컬, 버전관리 안 됨, 게다가
  프로젝트 스코프가 `C--Users-Mypc`(Windows 홈)로 잘못 잡혀 WSL 프로젝트에는 `memory/`가 없다.
  → **개인·범프로젝트 사실 전용**으로만 쓴다. 프로젝트 지식은 여기 쓰지 않는다.

원칙: 훅은 영구 메모리를 **말없이 쓰지 않는다.** 기계 저널만 남기고, 영구 기록은
`/os-mem` 큐레이션으로 승인 후 기록한다.
