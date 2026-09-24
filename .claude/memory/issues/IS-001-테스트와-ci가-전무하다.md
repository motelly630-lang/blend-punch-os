---
id: IS-001
type: issue
title: 테스트·CI·린트가 부족하다 — regression guard 의 근본 공백 (일부 영역만 테스트 있음)
status: active
tags: [테스트, pytest, ci, 린트, ruff, mypy, 기술부채, regression, 검증]
paths: ["pyproject.toml", "tests/**", ".github/**"]
updated: 2026-09-24
---

**갱신 (2026-09-24):** 커밋된 테스트 8파일 90건 — 캠페인 3 · Slack 2 · 인플루언서 2 · Meta 1
(`git ls-files tests` + `def test_` 수로 확인). 위 날짜 기록의 "미커밋 테스트 4파일"은 이 맥북
작업트리에 없다 (다른 머신 여부 미확인). **여전히 없는 것:** 제품·주문·정산 등 나머지 영역, CI, 린트.

**갱신 (2026-09-23):** `83aefe1` 로 격리 테스트 하네스가 들어왔다 — `tests/_env.py`(임시 SQLite,
외부 호출 mock) + 캠페인 테스트 2파일 15건. 실행: `.venv/bin/python -m unittest discover -s tests -t .`
(pytest 아님, stdlib unittest). **여전히 없는 것:** 캠페인 외 영역 테스트(작업트리에 미커밋 테스트
4파일 있음 — 상품·주문결제·에이전트API·단위), CI, 린트. 아래 2026-09-11 기록은 당시 상태다.

전수 확인 결과 (2026-09-11):
- `test_*.py` / `*_test.py` / `tests/` / `conftest.py` / `pytest.ini` — **0건** (`.venv` 내부 제외)
- `pyproject.toml` 에 `[tool.pytest.ini_options]` 없음. `pytest`·`ruff`·`mypy` 의존성도 없음
- `.github/workflows/` 없음. CI 없음

**영향:** "테스트로 검증했다"고 말할 수 없다. 현재 가능한 검증은 (a) 훅 셀프테스트,
(b) `import app.main` 사전검사, (c) 라이브 curl, (d) LLM 심사(`tenant-scope-reviewer`) 뿐이다.
[[RG-002]] 같은 규칙은 기계적으로 확인할 방법이 없다.

**계획 (Phase 3):** 최소 pytest 하네스를 깐다. 최고가치 3건부터 —
테넌트 스코프 / 정산 계산 불일치(`BLENDPUNCH_OS_SECOND_BRAIN.md` §7 에 문서화된 두 경로 차이) /
`visibility_status` 정규화([[RG-003]]).

그때까지는 보고에서 **무엇으로 확인했는지 정확히 적는다**([[PF-001]]).
