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

**근거 / 깨지면 어떻게 되는가:** Jinja 의 `tojson` 은 `< > & '` 만 바꾸고 `"` 는 그대로 둔다.
값에 문자열이 하나라도 있으면(`["뷰티"]`) 속성이 중간에 끊겨 화면 위쪽에 코드가 글자로 보이고
Alpine 동작(버튼·접기·선택)이 전부 멈춘다. 2026-09-24 인플루언서 편집 화면에서 헤드리스
스크린샷으로 발견, `3442a3b` 에서 수정. 같은 패턴이 다른 화면에 남아 있다 → [[IS-006]].

**검증 방법 (R1 기계적):** `python3 .claude/lib/check_tojson_attr.py` → 위반 0건이면 종료코드 0.
(`--selftest` 로 검사기 자체 확인. 고치기 전 `92e6277` 의 인플루언서 폼에서 1건을 잡는 것 확인함)

관련: [[IS-006]], [[RG-001]]
