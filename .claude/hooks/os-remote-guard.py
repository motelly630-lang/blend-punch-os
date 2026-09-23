#!/usr/bin/env python3
r"""PreToolUse(Bash) 훅 — 운영 서버·원격에 닿는 명령은 자동 모드에서도 항상 사람에게 묻는다.

대표님 원칙: "서버(EC2/RDS) 설정 변경·재시작·배포는 먼저 확인받는다."
그 원칙을 문서가 아니라 장치로 강제한다. 막지는 않고(deny 아님) 확인 창을 띄운다(ask).

대상 (명령 어디에 있든 — `wsl -- bash -lc "..."` 안쪽도 포함):
  ssh · scp · rsync · sftp        EC2 접속·파일 전송
  git push                        원격 저장소 반영
  aws <서비스> <조회 아닌 동작>     describe-/list-/get- 으로 시작하지 않는 AWS 호출

오탐(예: `grep "ssh "`)은 확인 창이 한 번 더 뜨는 것뿐이라 감수한다. 놓치는 쪽이 더 비싸다.

확인:  python3 .claude/hooks/os-remote-guard.py --selftest
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import osmem  # noqa: E402

# 명령 위치로 볼 수 있는 앞 경계: 시작, 공백, 따옴표, ; & | ( `
B = r"(?:^|[\s;&|(`'\"])"
RULES = [
    (B + r"(ssh|scp|sftp|rsync)(?=\s|$)", "원격 서버 접속·파일 전송"),
    (B + r"git(?:\s+-C\s+\S+)?\s+push\b", "원격 저장소에 push"),
    (B + r"aws\s+[a-z0-9-]+\s+(?!describe-|list-|get-|help\b|wait\b)[a-z]", "AWS 리소스 변경 가능 호출"),
]


def classify(cmd):
    for pat, why in RULES:
        if re.search(pat, cmd or ""):
            return why
    return None


def main():
    d = osmem.hook_json()
    if d is None:
        return 0  # 입력을 못 읽으면 기본 권한 흐름에 맡긴다
    cmd = (d.get("tool_input") or {}).get("command") or ""
    why = classify(cmd)
    if not why:
        return 0
    osmem.emit({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": "⚠ %s — 운영에 영향을 줄 수 있어 항상 확인받습니다 (os-remote-guard)" % why,
    }})
    return 0


def selftest():
    cases = [
        ("ssh -i ~/.ssh/k.pem ubuntu@1.2.3.4 'ls'", True),
        ('wsl -- bash -lc "cd /x && ssh ubuntu@h uptime"', True),
        ("scp a.tar ubuntu@h:/tmp/", True),
        ("rsync -av ./ h:/app/", True),
        ("git push origin master", True),
        ("git -C ~/p push", True),
        ('wsl -- bash -lc "cd /x && git push"', True),
        ("aws ec2 reboot-instances --instance-ids i-1", True),
        ("aws s3 rm s3://b/k", True),
        ("aws ec2 describe-instances", False),
        ("aws sts get-caller-identity", False),
        ("git status --short && git log -3", False),
        ("git pull", False),
        ("ls ~/.ssh", False),
        ("cat .claude/skills/ec2-deploy/SKILL.md", False),
        ("uv run python migrate.py", False),
    ]
    fails = 0
    for cmd, want in cases:
        got = classify(cmd) is not None
        res = "OK" if got == want else "FAIL"
        fails += res == "FAIL"
        print("  %-4s ask=%-5s %s" % (res, got, cmd))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    try:
        sys.exit(main())
    except Exception as e:
        # 판정 실패 시 조용히 통과시키지 않는다 — 확인 창으로 떨어뜨린다
        osmem.emit({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "ask",
            "permissionDecisionReason": "os-remote-guard 판정 오류(%s) — 안전하게 확인받습니다" % e}})
        sys.exit(0)
