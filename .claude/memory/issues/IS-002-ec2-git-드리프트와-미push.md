---
id: IS-002
type: issue
title: EC2 git HEAD 드리프트 + origin 미push 5커밋 + GitHub 키/토큰 작업 대기
status: active
tags: [ec2, git, 드리프트, push, origin, deploy-key, 토큰, pat, 배포, 미해결]
paths: [".claude/skills/ec2-deploy/**"]
updated: 2026-09-11
---

**상태 (2026-09-11 기준, 미해결):**

1. **EC2 git HEAD 가 `e562af4` 에 멈춰 있다.** 운영 파일은 2026-09-10 에 18개를 배포해 최신이지만
   git 트리는 정리되지 않아 dirty 하다(수정 49 / 추적외 포함 105항목). 따라서 **EC2 의 git 상태는
   실제 배포 내용을 알려주지 않는다.** `git pull` 은 충돌해서 동작하지 않는다.
2. **로컬 `master`(`a6b7975`)가 origin 보다 5커밋 앞서 있다.** origin/master = `e562af4`.
3. **GitHub 작업 2건 대기 중** — 사용자 웹 작업이 필요하다:
   - Deploy key 등록 (`~/.ssh/bp_github` 공개키, **Allow write access 체크**) — 미완료
     확인: `wsl -d Ubuntu -- ssh -T git@github.com` → 현재 `Permission denied (publickey)`
   - 노출됐던 classic PAT revoke — 미완료. 로컬 remote 는 이미 SSH 로 전환해 `.git/config` 에서
     토큰을 제거했다. GitHub 토큰 목록에서 **Last used 가 2026-09-10 인 것**이 해당 토큰이다
     (값·프리픽스는 여기 적지 않는다 — 이 디렉터리는 커밋된다)

**막힌 이유:** 키가 등록되기 전에는 push 가 불가능하고, push 없이는 EC2 `git reset --hard origin/master`
로 트리를 정리할 수 없다.

**해소 순서:** 키 등록 → 토큰 revoke → push 5커밋 → (백업 + [[RG-004]] 전수 비교 후)
EC2 `fetch` + `reset --hard origin/master` → 이후 배포는 `deploy.sh git` 정석 경로.

관련: [[DE-002]], [[RG-004]]
