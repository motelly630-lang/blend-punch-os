---
id: RG-001
type: regression
title: 새 라우터는 include_router 와 _setup_filters() 루프에 둘 다 등록한다
status: active
tags: [라우터, router, main, 필터, jinja, 500, 등록, parity]
paths: ["app/main.py", "app/routers/**", "app/api/**"]
updated: 2026-09-11
---

**지킬 조건:** `app/main.py` 의 `include_router(...)` 에 추가한 라우터는 `_setup_filters()` 의
모듈 루프에도 들어가야 한다.

**깨지면 어떻게 되는가:** 부팅은 조용히 성공하고, 그 화면 **첫 요청에서야** `won`/`date` 등
undefined filter 로 500 이 난다. 즉 배포 직후에는 멀쩡해 보인다.

**검증 방법 (R1 기계적 — 이미 자동화돼 있음):**
```bash
python3 .claude/hooks/os-router-parity.py --selftest   # 정규화 규칙 확인
```
`PostToolUse(Write|Edit)` 훅이 `app/main.py`·`app/routers/*.py`·`app/api/*.py` 수정 시 자동 검사한다.
AST 로 `include_router` 등록 집합과 필터 루프 집합을 비교하고, 그 라우터가 렌더하는 템플릿
(+`extends`/`include` 체인)이 실제로 커스텀 필터를 쓰는 경우만 경고한다.

**예외:** JSON 전용 라우터(`templates = ` 정의가 없는 모듈)는 루프에 넣으면 오히려 터진다.
훅이 이 경우를 자동으로 걸러낸다.

현황: `include_router` 39회, 필터 루프 37개 모듈.
