---
id: IS-002
type: issue
title: EC2 배포키가 GitHub에 미등록 — deploy.sh git 경로가 막혀 있다 (드리프트·push·토큰은 해소)
status: active
tags: [ec2, git, 드리프트, push, origin, deploy-key, 토큰, pat, 배포, bundle]
paths: [".claude/skills/ec2-deploy/**"]
updated: 2026-09-11
---

## 해소된 것 (2026-09-11)

- **origin 미push 8커밋 → push 완료** (`e562af4..7cd863b`). 로컬 remote 는 SSH 키
  `~/.ssh/bp_github` 를 쓴다(GitHub Deploy keys 에 write access 로 등록됨).
- **EC2 git 트리 드리프트 해소.** `e562af4` → `7cd863b`, 추적파일 수정 **113 → 0건**.
  GitHub fetch 가 막혀 있어 `git bundle` 로 우회했다:
  ```bash
  git bundle create /tmp/bpos.bundle ^e562af4 master     # 로컬
  scp ... && git fetch /tmp/bpos.bundle master:refs/remotes/origin/master && git reset --hard origin/master
  ```
  사전검증(동일 359 / 다름 2 / 없음 67) + 백업 `pre-reset-20260911-133536.tar.gz` 후 실행.
  `app/` 코드 차이는 0건이었으므로 **운영 코드는 한 줄도 바뀌지 않았고 재시작도 불필요**했다.
  검증: `systemctl is-active` active, 에러로그 0건, `/` 302 · `/login` 200 · `/public/products` 200.

## 남은 것

1. **EC2 배포키가 GitHub 에 등록돼 있지 않다** → `deploy.sh git`(`git pull`) 이 여전히 막힌다.
   EC2 쪽 설정은 정상이다 (`~/.ssh/config` 의 `Host github.com` → `IdentityFile ~/.ssh/bp_deploy_key`).
   GitHub 이 그 키를 거부한다: `Permission denied (publickey)`.
   - 키: `~/.ssh/bp_deploy_key.pub`, 이름 `ec2-deploy-blend-punch-os`,
     지문 `SHA256:zQw4Sa37d4iwxEl+SSZoNENUuXgV8VN84EaOEYFyzcA`
   - 해소: 그 공개키를 저장소 Deploy keys 에 등록한다. **write access 는 주지 않는다**(EC2 는 pull 만 한다).
   - 등록 전까지 배포는 [[DE-002]] 의 `git archive HEAD` 또는 위 bundle 방식을 쓴다.
(끝)

## 노출 토큰 — 해소 완료 (2026-09-11)

로컬 `.git/config` 에서 제거 → GitHub 에서도 삭제됨. **`api.github.com/user` 인증 시도 → HTTP 401**
로 폐기를 확인했다. classic 토큰 목록에는 만료본 2개(`blend punch-ods` Jul 4 만료 / `blend-punch`
Jun 10 만료)만 남아 있고 문제의 토큰은 목록에 없다 — GitHub 은 만료본도 목록에 남기므로
"목록에 없다 = 삭제됐다" 가 성립한다. 커밋 이력에도 들어간 적이 없어 히스토리 재작성은 불필요하다.

남은 만료본 2개는 인증이 불가능해 위험하지 않다. 목록 정리 차원에서 지워도 되고 둬도 된다.

관련: [[DE-002]], [[RG-004]], [[IS-004]]
