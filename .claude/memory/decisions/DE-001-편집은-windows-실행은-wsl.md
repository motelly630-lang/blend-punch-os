---
id: DE-001
type: decision
title: 편집은 Windows, 실행·빌드·git 은 전부 WSL
status: active
tags: [환경, wsl, windows, 실행, git, uv, npm, venv, unc, 경로]
paths: ["CLAUDE.md", ".claude/hooks/**", ".claude/lib/osmem.py"]
updated: 2026-09-11
---

Claude Code 는 Windows PowerShell 에서 돌고 프로젝트를 UNC(`\\wsl$\Ubuntu\...`)로 연다.
**파일 읽기·검색·수정은 Windows 에서, 실행·빌드·테스트·git 은 전부 `wsl -- bash -lc "..."` 로** 한다.

근거 (각각 실제로 깨진 적이 있다):
- `uv run` 을 Windows 에서 돌리면 Linux `.venv`(python3.12)가 Windows 용으로 재생성돼
  **WSL 과 EC2 실행환경이 함께 깨진다.** 가장 위험한 명령.
- `npm` 은 `node_modules/.bin` 이 Linux 심볼릭 링크라 실패하고, Windows `npm install` 은
  Linux `node_modules` 를 깨뜨린다.
- `git` 은 Windows 에 **설치되어 있지 않다.** 상태·diff·커밋은 전부 wsl 경유.

파생 결과 — 훅은 UNC 경로를 받는다. 그래서 `osmem.to_posix()` 로 정규화해야 하고,
WSL 에는 `jq`·`sqlite3`·`rg` 가 없으므로 **훅은 python3(3.12.3) + stdlib 만** 쓴다.

탈락 대안: 전부 Windows 로 통일(= Linux venv/node_modules 포기, EC2 와 환경 분리) /
전부 WSL 에서 Claude Code 실행(= 개인 설정 섀도잉 문제, [[IS-003]]).

관련: [[PR-001]], [[IS-003]]
