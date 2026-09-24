---
name: gen-test
description: blend-punch-os 에 기존 테스트 하네스(tests/_env.py, unittest, 임시 SQLite)를 따라 자동 테스트를 추가하고 실행한다. 기능을 고치거나 버그를 잡은 뒤 그 동작을 고정하고 싶을 때, 사용자가 "테스트 만들어줘", "테스트 추가", "재발 방지", "이거 다시 안 깨지게" 라고 할 때, 또는 /gen-test <대상> 으로 부를 때 사용. 트리거 - 테스트, unittest, 회귀, 재발 방지, 검증 자동화.
---

# 테스트 추가 (gen-test)

현재 테스트는 일부 영역뿐이다 ([IS-001] — `ls tests/` 로 확인). 한 번에 많이 만들지 말고, **방금 고친 것·깨지면 비싼 것**부터
작게 늘린다. 테스트는 운영·개발 DB 에 절대 닿지 않는다 — `tests/_env.py` 가 임시 SQLite 로 바꾼다.

## 1. 무엇을 테스트할지 정하기
우선순위:
1. 방금 고친 버그 — 고치기 전엔 실패하고, 고친 후엔 통과하는 테스트
2. 테넌트 격리 — 회사 B 사용자가 회사 A 데이터를 못 보고/못 고치는지 ([RG-002])
3. 돈이 걸린 계산 — 수수료·정산·가격
4. 폼 POST → 302 리다이렉트(PRG) → 저장 값

대상 1개에 테스트 3~8개. 대상 라우터·모델을 먼저 읽고 실제 동작 기준으로 쓴다(추측 금지).

### 폼 템플릿을 새로 쓰거나 구조를 바꿨을 때 (IM-001 · IM-003)
저장 주소로 **직접 POST 하는 테스트만으로는 화면 쪽 실수를 못 잡는다** (2026-09-24: action 의 `/` 가
빠져 운영에서 404 — `29c455c`). 다음 둘을 같이 쓴다:
1. **GET 으로 화면을 받아** 렌더된 `action="…"`(htmx 면 `hx-post`)이 실제 라우트 주소인지 확인
   (새 화면 + 편집 화면 둘 다).
2. 같은 이름 칸이 여러 번 가는 폼(숨은 빈 칸으로 지우는 패턴)은 브라우저 모양대로 보낸다:
   `data={"칸": ["옛값", ""]}` + `files={"profile_image": ("", b"", "application/octet-stream")}`
   (multipart 강제). `data=[(k, v), …]` 튜플 목록은 이 경로에서 422 가 났다.
JSON 을 속성에 넣는 템플릿이면 `python3 .claude/lib/check_tojson_attr.py` 도 돌린다 ([RG-006]).

## 2. 파일 규칙 — `tests/test_campaigns.py` 를 본보기로 읽고 따른다
- 위치: `tests/test_<기능>.py`, **첫 줄 import 는 반드시** `from tests import _env`
  (app 보다 먼저 import 해야 DB 가 임시 SQLite 로 바뀐다)
- 도구: `from tests._env import SessionLocal, client_for, make_user, uid`
  - `make_user(role="admin", company_id=1)` — 회사 1·2 가 자동 시드된다
  - `client_for(user)` — 로그인 쿠키가 붙은 TestClient (`follow_redirects=False`)
  - `uid()` — 이름 충돌 방지용 짧은 난수
- 데이터 생성은 `_mk_<모델>()` 헬퍼 함수로 (SessionLocal 열고 add/commit/close)
- 표준 라이브러리 `unittest` 만 쓴다. pytest·새 패키지 추가 금지.
- 테스트 이름·docstring 은 한국어로 "무엇이 보장되는지"를 쓴다.
- 가상 데이터만 (`가상상품`, `가상셀러`). 실제 고객·브랜드 이름 금지.

```python
"""<기능>: <보장하는 것 한 줄씩>."""
from tests import _env
from tests._env import SessionLocal, client_for, make_user, uid

import unittest

from app.models.<name> import <Model>


def _mk_<name>(company_id=1, **kw):
    db = SessionLocal()
    try:
        o = <Model>(company_id=company_id, name=f"가상{uid()}", **kw)
        db.add(o); db.commit()
        return o.id
    finally:
        db.close()


class <기능>TenantIsolation(unittest.TestCase):
    def test_다른_회사_데이터는_404(self):
        oid = _mk_<name>(company_id=1)
        c = client_for(make_user(company_id=2))
        r = c.get(f"/<prefix>/{oid}")
        self.assertIn(r.status_code, (403, 404))
```

## 3. 외부 호출
- AI·메일·알림·카카오는 `_env` 가 비우거나 mock 한다. 새 외부 호출(토스·인스타 등)은
  테스트 안에서 해당 함수를 교체(`unittest.mock.patch`)한다. 실제 네트워크로 나가면 안 된다.
- 앱 lifespan(스케줄러)은 돌지 않는다 — `TestClient` 를 `with` 없이 쓰는 이유.

## 4. 실행
```bash
.venv/bin/python -m unittest tests.test_<기능> -v          # 새 파일만
.venv/bin/python -m unittest discover -s tests -t . -v     # 전체 (기존 것 안 깨졌는지)
```
Windows 에서는 `wsl -- bash -lc "cd /home/blendpunch/blend-punch-os && ..."` 로 감싼다.

## 5. 확인
- 버그 수정 테스트면: 수정을 잠시 되돌렸을 때 **실패하는지**까지 확인하면 가장 좋다
  (되돌린 건 반드시 원복하고 `git diff` 로 확인).
- 실패하면 테스트가 틀렸는지 코드가 틀렸는지 먼저 가린다. 테스트를 통과시키려고 앱 코드를 몰래 고치지 않는다.
- 새로 드러난 앱 버그는 고치기 전에 대표님께 보고한다.

## 보고
```
추가  : tests/test_<기능>.py — 테스트 n개 (무엇을 보장하는지 목록)
결과  : 새 파일 n/n 통과, 전체 m/m 통과 (실패는 출력 그대로)
발견  : 테스트 중 드러난 앱 문제 (있으면)
```
