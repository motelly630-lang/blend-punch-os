---
id: DE-009
type: decision
title: OS 쇼핑몰(/shop)·결제단 삭제 확정 — OS 는 판매량·일정·제품·영상을 모으는 통합 아카이브로
status: active
supersedes: DE-007
tags: [쇼핑몰, shop, 결제, 토스, 삭제, 블랜드픽, 산지픽, 아카이브, 판매량, 일정, 영상, 방향, 보안]
paths: ["app/routers/shop.py", "app/api/payments.py", "app/templates/shop/**", "app/routers/orders.py", "app/routers/inquiry.py"]
updated: 2026-09-28
---

**결정 (대표님, 2026-09-28, 명시):** "3번 쇼핑몰 코드가 사실 os에서 내가 직접 만든 건데 … 삭제하고 os를 그냥 전체적인
통합적인 느낌으로 결제단 빼고 판매량 체크하고 일정 체크하고 제품들 넣는, 영상 넣어서 쓰는 아카이브로 만들면 좋을 듯"

**한 일:** `43220bc` 삭제 재적용 → `4cb6b4d` (브랜치 `fix/security-2026-09-28`, 로컬 — 배포 전).
계기: 보안 점검에서 `/shop/{slug}/prepare` 가 화면이 보낸 가격을 믿어 1원 결제가 가능했다 (옵시디언 `10_Projects/Security_Audit_2026-09-28_OS.md`).

**남기는 것:** SalesPage·Seller·Order·ShopUser 모델과 데이터. 블랜드픽이 쓰는 주소는 지우지 않고 **같은 서버 안 요청만** 받는다
(`require_internal_request`): `/inquiries/api/*`(블랜드픽 1:1 문의, 확인됨 [[PR-003]]), `/orders/api/create`
(코드 설명엔 "blend-pick 호출"인데 [[PR-003]] 은 "블랜드픽은 OS 주문 안 부름" — **불일치, 배포 전 EC2 블랜드픽 코드로 확인**).

**배포 전 확인 (EC2 읽기, 승인 필요):**
1. nginx 가 OS 로 넘길 때 `X-Forwarded-For`/`X-Real-IP` 를 붙이는지 — 안 붙이면 내부 전용 검사가 바깥 요청을 못 거른다.
2. 블랜드픽이 `/orders/api/create`·`/inquiries/api/*` 를 **localhost:8000** 으로 부르는지 (공개 주소로 부르면 막혀서 깨진다):
   `grep -rn "orders/api\|inquiries/api\|OS_API_URL" /home/ubuntu/blend-pick/app /home/ubuntu/blend-pick/lib` (env 는 키 이름만).

**방향 (OS 의 역할):** 결제·주문 접수는 블랜드픽·산지픽. OS 는 판매량 확인·공구 일정 확인·제품(영상 포함) 아카이브의 통합 관리처.
구체 설계는 아직 없음 — 판매량은 블랜드픽 주문을 어떻게 가져올지(주문 생성 API / DB 읽기 / 엑셀)부터 정해야 한다.

관련: [[DE-007]](대체됨), [[PR-003]], [[RG-007]]
