---
name: ec2-deploy
description: blend-punch-os(os.blendpunch.com)를 EC2 서버에 배포할 때 사용. 사용자가 "배포해", "서버에 반영", "deploy", "EC2에 올려", "프로덕션 반영" 등을 말하거나, 로컬에서 코드/템플릿/정적파일을 수정한 뒤 운영 서버에 적용해야 할 때. EC2 IP가 자주 바뀌므로 항상 DNS로 현재 IP를 먼저 확인하는 절차 포함.
version: 1.1.0
---

# EC2 배포 (blend-punch-os)

`os.blendpunch.com` (EC2)에 변경사항을 안전하게 배포하는 절차.

## ⚠️ 실행 위치: 반드시 WSL

SSH 키(`~/.ssh/blendpunch-key.pem`)와 `git`·`scp` 는 모두 WSL 안에만 있다.
Windows Claude Code 에서 작업 중이라면 **모든 명령을 `wsl -- bash -lc "..."` 로 감싼다.**
Windows 의 `ssh.exe` 로 `\\wsl$` 위의 키를 쓰면 권한 검사에서 막힌다.

## ⚠️ 가장 중요: IP가 자주 바뀐다
EC2 퍼블릭 IP가 수시로 변경됨 (3.38.104.216 → 3.35.19.151 → 3.34.51.70 ...).
**메모리에 적힌 IP를 믿지 말고, 배포할 때마다 DNS로 현재 IP를 다시 확인할 것.**

```bash
wsl -- bash -lc "getent hosts os.blendpunch.com"   # 현재 A 레코드 = 진짜 IP (Cloudflare proxy 꺼져있음)
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

### 방법 A) git pull (정석 — 커밋된 변경사항 배포)
로컬에서 commit + push 후 EC2에서 pull. **GitHub에 배포키가 등록돼 있을 때만 동작.**
헬퍼 스크립트 사용:
```bash
wsl -- bash -lc "bash .claude/skills/ec2-deploy/scripts/deploy.sh git"
```

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
1. [ ] DNS로 현재 IP 확인
2. [ ] 배포 방법 선택 (git / scp)
3. [ ] 서비스 재시작 (`systemctl restart blendpunch`)
4. [ ] `systemctl is-active`로 active 확인
5. [ ] curl로 라이브 검증
6. [ ] (스키마 변경 시) migrate.py 실행
