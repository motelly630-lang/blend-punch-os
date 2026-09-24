---
name: ec2-deploy
description: blend-punch-os(os.blendpunch.com)를 EC2 서버에 배포할 때 사용. 사용자가 "배포해", "서버에 반영", "deploy", "EC2에 올려", "프로덕션 반영" 등을 말하거나, 로컬에서 코드/템플릿/정적파일을 수정한 뒤 운영 서버에 적용해야 할 때. EC2 IP가 자주 바뀌므로 항상 DNS로 현재 IP를 먼저 확인하는 절차 포함.
version: 1.1.0
---

# EC2 배포 (blend-punch-os)

`os.blendpunch.com` (EC2)에 변경사항을 안전하게 배포하는 절차.

## ⚠️ 실행 위치: Windows 는 WSL, macOS 는 터미널 그대로

- **Windows:** SSH 키(`~/.ssh/blendpunch-key.pem`)와 `git`·`scp` 는 모두 WSL 안에만 있다.
  **모든 명령을 `wsl -- bash -lc "..."` 로 감싼다.** Windows `ssh.exe` 로 `\\wsl$` 위의 키를 쓰면 권한 검사에서 막힌다.
- **macOS:** 아래 명령을 `wsl` 없이 그대로 실행한다. 키는 맥의 `~/.ssh/blendpunch-key.pem` (권한 600).
  `getent` 가 없으므로 `deploy.sh` 는 IP 를 `dig` → `python3` 로 대신 찾는다.
- 운영 SSH 쓰기는 자동 권한 판정에서 막힐 수 있다 — 그때는 사용자가 `!` 로 직접 실행한다.

## ⚠️ 가장 중요: IP가 자주 바뀐다
EC2 퍼블릭 IP가 수시로 변경됨 (3.38.104.216 → 3.35.19.151 → 3.34.51.70 ...).
**메모리에 적힌 IP를 믿지 말고, 배포할 때마다 DNS로 현재 IP를 다시 확인할 것.**

```bash
wsl -- bash -lc "getent hosts os.blendpunch.com"   # Windows(WSL): 현재 A 레코드 = 진짜 IP (Cloudflare proxy 꺼져있음)
dig +short os.blendpunch.com                        # macOS
```

## 서버 정보
- **User**: `ubuntu`  ·  **SSH Key**: `~/.ssh/blendpunch-key.pem` (WSL 홈)
- **앱 경로**: `/home/ubuntu/blend-punch-os/`
- **venv**: `.venv/bin/python`, `.venv/bin/uvicorn`
- **systemd 서비스**: `blendpunch.service` → 재시작 `sudo systemctl restart blendpunch`
- **git 원격**: SSH 배포키 방식 (`git@github.com:motelly630-lang/blend-punch-os.git`, branch `master`)
  - 배포키: `~/.ssh/bp_deploy_key` (EC2). GitHub 저장소 Deploy keys에 등록돼 있어야 `git pull` 동작.
  - ⚠️ git 원격 URL에 절대 토큰(ghp_)을 박지 말 것 — 과거 노출 사고 있었음.

## 배포 방법 2가지

> 아래 명령은 **프로젝트 루트에서 실행**한다고 가정한다. 프로젝트를 UNC(`\\wsl$\Ubuntu\...`)로
> 열어 두면 `wsl` 이 cwd 를 POSIX 로 변환해 주므로 그대로 동작한다.
> 다른 위치에서 돌려야 하면 `cd ~/blend-punch-os && ...` 를 앞에 붙인다.

### 방법 A) git (정석 — 커밋된 변경사항 배포)
로컬에서 commit + push 후 EC2에서 받는다. **GitHub에 배포키가 등록돼 있을 때만 동작.**
헬퍼 스크립트 사용 (Windows 는 `wsl -- bash -lc "..."` 로 감싼다):
```bash
bash .claude/skills/ec2-deploy/scripts/deploy.sh check   # 1) 점검만 — 서버 변경 없음. 먼저 보여주고 승인받는다
bash .claude/skills/ec2-deploy/scripts/deploy.sh git     # 2) 배포
```
`git` 모드가 하는 일 ([[RG-004]]·[[DE-002]] 준수):
1. 로컬 HEAD == origin/master 확인 (push 안 된 커밋이면 중단)
2. EC2 추적파일 변경 없음 · fast-forward 가능 · 비밀파일 미추적 확인 (하나라도 어긋나면 중단)
3. EC2 에 `deploy-backup-<시각>.tar.gz` 백업
4. `git merge --ff-only` → **재시작 전** `import app.main` 검사 (실패 시 원복하고 재시작 안 함)
5. 재시작 → 로그 오류 확인 → `is-active` · `/login` 응답 확인. 되돌리기 명령을 출력한다

### 방법 B) scp 직접 복사 (빠른 핫픽스 — 특정 파일만)
커밋 없이 수정 파일 몇 개만 즉시 반영할 때. (정적파일, 템플릿 등)
```bash
wsl -- bash -lc "bash .claude/skills/ec2-deploy/scripts/deploy.sh scp <파일1> <파일2> ..."
# 예: ... deploy.sh scp static/og-image.png app/templates/public/base.html
```
경로는 **프로젝트 루트 기준 상대경로**로 넘기면 EC2의 같은 경로로 복사됨.

## 배포 후 검증 (필수)
배포가 실제로 반영됐는지 라이브로 확인:
```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" https://os.blendpunch.com/
# 정적파일 바꿨으면: curl -sI https://os.blendpunch.com/static/<파일> | head -1
# 메타/HTML 바꿨으면: curl -s https://os.blendpunch.com/<경로> | grep '<확인할 문자열>'
```
(curl 은 Windows 에서 직접 실행해도 된다 — 외부 HTTP 요청뿐이라 WSL 이 필요 없다.)

## 마이그레이션 (DB 스키마 변경 시에만)
```bash
wsl -- bash -lc "ssh -i ~/.ssh/blendpunch-key.pem ubuntu@\$(getent hosts os.blendpunch.com | awk '{print \$1}') 'cd /home/ubuntu/blend-punch-os && .venv/bin/python migrate.py'"
```

## 체크리스트
1. [ ] `deploy.sh check` 결과를 사용자에게 보여주고 배포 승인 (재시작 중 수 초 접속 끊김 고지)
   - **올라갈 커밋 목록에 보류 항목이 섞였는지 표시한다** (IM-015): `state.json` 의 보류 task·결정 기록(DE-*)에서
     "개발자 논의 후"·"보류"로 적힌 것과 겹치는 커밋이 있으면 목록에서 짚고, 되돌려 둘지 먼저 묻는다
     (2026-09-24: 보류된 쇼핑몰 삭제가 다른 기능 배포에 딸려 갈 뻔함). 되돌림 커밋으로 상쇄된 경우 `git diff <운영HEAD> HEAD -- <경로>` 로 실제 차이를 확인해 알린다.
   - **"급하니 빨리 배포"를 권하기 전에** 그 기능이 실제로 쓰이는지 결정 기록에서 확인한다 (IM-014: 안 쓰는 쇼핑몰을 급하다고 권함).
2. [ ] 배포 방법 선택 (git / scp) — IP 확인·재시작·is-active·/login 확인은 스크립트가 한다
3. [ ] 로그인이 필요한 화면은 사용자에게 확인 요청 (curl 은 비로그인이라 FeatureGate 로 리다이렉트된다)
4. [ ] (스키마 변경 시) migrate.py 실행 — 대상 DB 확인 (운영 = `blendpunch_dev`)
5. [ ] changelog 에 배포 기록 (이전→새 HEAD, 백업 파일명)
