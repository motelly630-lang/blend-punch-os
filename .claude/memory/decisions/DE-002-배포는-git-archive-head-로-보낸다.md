---
id: DE-002
type: decision
title: EC2 파일 배포는 작업트리가 아니라 git archive HEAD 로 보낸다
status: active
tags: [배포, deploy, ec2, scp, git-archive, wip, 커밋]
paths: [".claude/skills/ec2-deploy/**", "app/**", "migrate.py"]
updated: 2026-09-11
---

`deploy.sh scp` 는 **작업트리 파일**을 복사한다. 미커밋 WIP 가 섞여 운영에 올라갈 수 있다.
2026-09-10 배포 당시 `scripts/enrich_products.py` 에 미커밋 변경(+45/-10)이 있었다.

그래서 파일 배포는 이렇게 한다:

```bash
git archive HEAD -- <파일들> | ssh ... "tar -x -C /home/ubuntu/blend-punch-os"
```

보낸 뒤 **반드시 blob SHA 로 검증**한다 — EC2 에서 `git hash-object <path>` 와
로컬 `git rev-parse HEAD:<path>` 를 비교. 2026-09-10 배포는 18/18 일치 확인 후 진행했다.

재시작 전에 `.venv/bin/python -c 'import app.main'` 으로 **import 사전검사**를 한다.
깨진 상태로 `systemctl restart` 하면 운영이 내려간다.

탈락 대안: `deploy.sh git`(= EC2 트리가 dirty 해서 `git pull` 이 충돌, [[IS-002]]) /
작업트리 scp(= WIP 혼입 위험, 위 사유).

관련: [[RG-004]] reset 전 전수 비교, [[IS-002]] EC2 드리프트
