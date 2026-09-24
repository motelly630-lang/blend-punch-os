---
id: RG-006
type: regression
title: JSON 을 큰따옴표 HTML 속성에 넣을 때는 tojson 뒤에 forceescape 를 붙인다
status: active
tags: [tojson, forceescape, jinja, alpine, x-data, 템플릿, 폼, 따옴표, 편집화면, 깨짐, 카테고리]
paths: ["app/templates/**/*.html"]
updated: 2026-09-24
---

**지킬 조건:** Jinja 템플릿에서 `{{ x | tojson }}` 을 **큰따옴표로 감싼 HTML 속성**
(`x-data="…"`, `value="…"`) 안에 넣을 때는 `| tojson | forceescape` 로 쓴다.
`<script>` 안, 작은따옴표 속성(`x-data='…'`)은 그대로 둬도 된다.
**`| tojson | e` 는 안전하지 않다** — tojson 결과가 이미 안전 표시(Markup)라 `e` 는 아무것도 바꾸지 않는다 (2026-09-24 확인).

**근거 / 깨지면 어떻게 되는가:** Jinja 의 `tojson` 은 `< > & '` 만 바꾸고 `"` 는 그대로 둔다.
값에 문자열이 하나라도 있으면(`["뷰티"]`) 속성이 중간에 끊겨 화면 위쪽에 코드가 글자로 보이고
Alpine 동작(버튼·접기·선택)이 전부 멈춘다. 2026-09-24 인플루언서 편집 화면에서 헤드리스
스크린샷으로 발견, `3442a3b` 에서 수정. 같은 패턴 11곳을 [[IS-006]] 에서 모두 수정.

**검증 방법 (R1 기계적, 테스트로 강제):** `tests/test_template_json_attrs.py` — 검사기 0건 + 제품 수정·제품 상세·
쇼핑몰 화면 속성 온전성. 단독 실행: `python3 .claude/lib/check_tojson_attr.py` → 위반 0건이면 종료코드 0.
(`--selftest` 로 검사기 자체 확인. 고치기 전 `92e6277` 의 인플루언서 폼에서 1건을 잡는 것 확인함)

관련: [[IS-006]], [[RG-001]]
