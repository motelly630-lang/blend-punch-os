---
id: IS-001
type: issue
title: 테스트·CI·린트가 전무하다 — regression guard 의 근본 공백
status: active
tags: [테스트, pytest, ci, 린트, ruff, mypy, 기술부채, regression, 검증]
paths: ["pyproject.toml", "tests/**", ".github/**"]
updated: 2026-09-11
---

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
