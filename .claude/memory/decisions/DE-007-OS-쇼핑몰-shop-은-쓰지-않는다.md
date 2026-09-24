---
id: DE-007
type: decision
title: OS 안의 쇼핑몰(/shop 판매 화면)은 쓰지 않고 삭제했다 — 판매는 블랜드픽·산지픽
status: active
supersedes:
tags: [쇼핑몰, shop, 판매페이지, 결제, 토스, 고객주문, 우선순위, 산지픽, 블랜드픽, 판매채널, 연동]
paths: ["app/routers/shop.py", "app/templates/shop/**"]
updated: 2026-09-24
---

OS 에 들어 있는 고객용 판매 화면(`/shop/{slug}`, `app/routers/shop.py` · `app/templates/shop/`)은
운영에서 쓰지 않는다. 대표님 결정 (2026-09-24, 명시): "그거 샵은 안 쓸거야 우리 이미 따로 만들어놔서 그거는 포기".

**영향 / 어떻게 다루나:**
- 이 화면의 버그·개선은 우선순위에서 뺀다. 이 화면 때문에 급하게 배포하지 않는다.
- **삭제함 (2026-09-24, 대표님 "쇼핑몰 삭제하고", `43220bc`)** — `app/routers/shop.py`·`app/templates/shop/`·`app/api/payments.py`
  와 `/shop` 링크. DB 데이터·모델(SalesPage·Seller·Order·ShopUser)은 남김. 블랜드픽이 OS `/shop` 을 부르지 않음을
  확인한 뒤 지웠다 ([[PR-003]]). 되돌리기: `git revert 43220bc`.
- 2026-09-24 `dc3bfca` 에 이 화면의 tojson 수정이 들어 있지만 운영 배포는 하지 않았다 (대표님 "배포 무시").
- 실제 판매 채널은 **산지픽 · 블랜드픽** (대표님, 2026-09-24). OS 는 나중에 이 두 곳과 **연결할 계획**이다
  (시기·방식 미정 — 지금 만들지 않는다). 연결 방식(API·주문 수집 등)은 미확인.

**탈락 대안:** OS 쇼핑몰을 계속 고쳐 쓰기 — 대표님이 이미 별도 쇼핑몰을 운영해 중복이다.
삭제 — 되돌리기 어렵고 대표님이 요청하지 않았다.

관련: [[IS-006]], [[PR-003]], [[RG-007]]
