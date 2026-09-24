---
id: IS-006
type: issue
title: tojson 을 큰따옴표 속성에 넣어 화면이 깨지는 곳이 8곳 남아 있다 (제품 수정 등)
status: active
tags: [tojson, 템플릿, 깨짐, 제품수정, 제품상세, cs, 쇼핑몰, alpine, 버그]
paths: ["app/templates/products/form.html", "app/templates/products/detail.html", "app/templates/cs/detail.html", "app/templates/shop/product.html"]
updated: 2026-09-24
---

[[RG-006]] 검사기(`check_tojson_attr.py`)가 2026-09-24 에 찾은 위반 8건:
`products/form.html` 18·240·492·508, `products/detail.html` 201, `cs/detail.html` 200·247,
`shop/product.html` 39.

**확인한 것:** 제품 수정 화면은 카테고리가 있는 제품이면 `x-data="productPage([` 에서 속성이 끊긴다
(임시 SQLite 격리 렌더로 확인). 나머지 7곳은 **정적 검사 결과만** 있다 — 값에 문자열이 없으면
(빈 목록·숫자) 겉으로는 안 깨질 수 있어 실제 영향은 화면별로 미확인.

**해결 방법:** 각 줄의 `| tojson` → `| tojson | forceescape`. 고친 뒤 검사기 0건 + 해당 화면 렌더 확인.
대표님 승인 대기 (요청 범위 밖에서 발견).

관련: [[RG-006]]
