---
id: IS-002
type: issue
title: EC2 git 드리프트 · origin 미push · 노출 토큰 — 전부 해소됨
status: resolved
tags: [ec2, git, 드리프트, push, origin, deploy-key, 토큰, pat, 배포, bundle, 해소됨]
paths: [".claude/skills/ec2-deploy/**"]
updated: 2026-09-11
---

**2026-09-11 전부 해소.** 기록을 남기는 이유는 같은 상황이 다시 생겼을 때 절차를 재사용하기 위해서다.

## 무엇이 문제였나

EC2 는 그동안 scp 로 배포돼 와서 **git 상태가 실제 배포 내용을 알려주지 않았다** — HEAD 는
`e562af4` 에 멈춘 채 추적파일 113 항목이 dirty 였고 `git pull` 은 충돌했다. 로컬은 origin 보다
8커밋 앞서 있었고, 로컬 remote URL 에는 classic PAT 가 평문으로 박혀 있었다.

## 어떻게 해소했나

1. **remote 를 SSH 로 전환** — `.git/config` 에서 토큰 제거. push 용 키 `~/.ssh/bp_github` 를
   저장소 Deploy keys 에 **write access 로** 등록.
2. **push 8커밋** — `e562af4..7cd863b`.
3. **EC2 트리 정리** — 이 시점엔 EC2 배포키가 미등록이라 `fetch` 가 막혀 **`git bundle` 로 우회**했다:
   ```bash
   git bundle create /tmp/bpos.bundle ^e562af4 master          # 로컬
   scp ... ubuntu@<ip>:/tmp/
   git fetch /tmp/bpos.bundle master:refs/remotes/origin/master # EC2
   git reset --hard refs/remotes/origin/master
   ```
   사전에 백업(`pre-reset-<stamp>.tar.gz`)과 blob SHA 전수 비교([[RG-004]])를 했다 —
   동일 359 / 다름 2(`.gitignore`·`uv.lock`, 런타임 무관) / 없음 67(개발용 문서).
   **`app/` 코드 차이 0건** 이었으므로 운영 코드는 바뀌지 않았고 재시작도 불필요했다.
   결과: 추적파일 수정 **113 → 0건**.
4. **EC2 배포키 등록** — `~/.ssh/bp_deploy_key.pub`(`ec2-deploy-blend-punch-os`,
   지문 `SHA256:zQw4Sa37d4iwxEl+SSZoNENUuXgV8VN84EaOEYFyzcA`)를 Deploy keys 에
   **write access 없이** 등록. EC2 는 pull 만 한다.
5. **노출 토큰 폐기 확인** — `api.github.com/user` 인증 시도 → **HTTP 401**. GitHub classic 토큰
   목록에도 없다(만료본도 목록에 남으므로 "없다 = 삭제됨"). 커밋 이력에 들어간 적이 없어
   히스토리 재작성은 불필요했다.

## 확인된 최종 상태

`git pull --ff-only origin master` 가 EC2 에서 정상 동작한다 → **`deploy.sh git` 정석 경로 복구.**
EC2 HEAD = origin/master, 추적파일 수정 0건, `systemctl is-active` active,
`/` 302 · `/login` 200 · `/public/products` 200.

잔재 파일 9개는 [[IS-004]] 로 분리했다.

관련: [[DE-002]], [[RG-004]], [[IS-004]]
