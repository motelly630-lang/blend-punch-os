---
id: RG-007
type: regression
title: 블랜드픽이 쓰는 OS 표·주소의 구조를 바꾸기 전에 블랜드픽 영향을 확인한다
status: active
tags: [블랜드픽, 산지픽, 마이그레이션, 스키마, 컬럼, 테이블, shop_users, influencers, campaigns, products, brands, sales_pages, 문의, 공유DB]
paths: ["app/models/influencer.py", "app/models/campaign.py", "app/models/product.py", "app/models/brand.py", "app/models/sales_page.py", "app/models/shop_user.py", "app/routers/inquiry.py", "migrate.py"]
updated: 2026-09-24
---

**지킬 조건:** 다음을 **이름 변경·삭제·타입 변경·NOT NULL 추가**하려면, 먼저 블랜드픽 코드가 그 칸을 쓰는지 확인하고
대표님께 영향을 알린다. 칸 **추가**(NULL 허용)와 OS 화면만 바꾸는 작업은 해당 없음.
- 표: `influencers` `campaigns` `products` `brands` `sales_pages` `shop_users`
- 주소: `/inquiries/api/submit`, `/inquiries/api/user/{id}`

**근거 / 깨지면 어떻게 되는가:** 블랜드픽·산지픽(실제 결제받는 쇼핑몰)이 OS 운영 DB 를 SQL 로 직접 읽고 쓴다([[PR-003]]).
OS 에서 칸 이름 하나만 바꿔도 OS 테스트는 전부 통과하는데 **쇼핑몰 화면·회원가입·문의가 깨진다.** 블랜드픽 코드는
이 저장소에 없어서 테스트로 못 잡는다.

**검증 방법 (R2 수동):** EC2 에서 읽기로만 —
`grep -rnw "<칸이름>" /home/ubuntu/blend-pick/app /home/ubuntu/blend-pick/lib` → 결과가 있으면 영향 있음.
마이그레이션이면 `create-migration` 절차 안에서 확인한다.

관련: [[PR-003]], [[DE-007]]
