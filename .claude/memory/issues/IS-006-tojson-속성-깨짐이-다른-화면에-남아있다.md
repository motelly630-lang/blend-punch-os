---
id: IS-006
type: issue
title: tojson 을 큰따옴표 속성에 넣어 화면이 깨지는 곳이 8곳 남아 있다 (제품 수정 등)
status: resolved
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

**해소 (2026-09-24, 대표님 "1번 고쳐주고"):** 검사기의 빈틈 2개를 먼저 고쳤다 — (a) 한 속성에 여러 개면
마지막 하나만 잡던 것, (b) `| tojson | e` 를 안전으로 보던 것. 그러자 **11곳**(쇼핑몰 36, 인플루언서·제품 엑셀
가져오기 미리보기 추가). 전부 `| tojson | forceescape` 로 바꿈. 확인: 검사기 0건, 새 테스트
`tests/test_template_json_attrs.py` 4건이 **고치기 전 템플릿에서 4건 모두 FAIL → 고친 뒤 OK**, 전체 94 통과.
쇼핑몰(고객 주문 화면)은 옵션이 있으면 Alpine 이 깨져 있었다(테스트로 확인). 운영 데이터 영향은 운영 DB 조회 권한이 막혀 미확인.

관련: [[RG-006]]
