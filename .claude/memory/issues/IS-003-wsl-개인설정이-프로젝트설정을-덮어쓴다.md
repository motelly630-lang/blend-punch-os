---
id: IS-003
type: issue
title: WSL 개인 설정이 프로젝트 설정을 덮어쓴다 (skills/agents/hooks 전부 내용 다름)
status: active
tags: [claude-code, 설정, skills, hooks, agents, 섀도잉, 중복, wsl, 개인설정]
paths: [".claude/skills/**", ".claude/hooks/**", ".claude/agents/**"]
updated: 2026-09-11
---

`/home/blendpunch/.claude/` (WSL 개인 설정)에 프로젝트와 **같은 이름의 사본**이 있고,
2026-09-11 `diff -rq` 결과 **전부 내용이 다르다**:

```
skills/ec2-deploy/{SKILL.md,scripts/deploy.sh}   ≠ 프로젝트본
skills/os-ai-pipeline/{SKILL.md,scripts/*}       ≠ 프로젝트본
skills/os-locate/SKILL.md                        ≠ 프로젝트본
agents/tenant-scope-reviewer.md                  ≠ 프로젝트본
hooks/{os-build-css.sh,os-router-parity.py}      ≠ 프로젝트본
skills/obsidian-log/                             ← 개인본에만 있음
hooks/os-router-parity.sh                        ← 프로젝트본에만 있음
```

**영향:** 스킬 해석 우선순위가 Personal > Project 다. **WSL 안에서 Claude Code 를 실행하면
버전관리되는 프로젝트본이 아니라 오래된 개인본이 동작한다.** 프로젝트본을 고쳐도 효과가 없다.
Windows 에서 실행할 때는 개인 스킬 디렉터리가 없어 프로젝트본이 정상 적용된다.

**계획 (Phase 4):** 프로젝트를 단일 출처로 확정하고 개인본을 아카이브한다.
사용자가 과거에 "WSL `~/.claude` 원본은 수정하지 말라"고 했으므로 **승인 후** 진행한다.
`obsidian-log` 는 개인 지식베이스(Obsidian 볼트) 기록용이라 범프로젝트 성격이다 —
프로젝트 이전 대상이 아닐 수 있다.
