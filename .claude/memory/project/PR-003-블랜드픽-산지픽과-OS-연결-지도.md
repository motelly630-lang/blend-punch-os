---
id: PR-003
type: project
title: 블랜드픽·산지픽(같은 Next.js 앱)은 OS 운영 DB 를 직접 읽고 쓴다 — 연결 지도
status: active
tags: [블랜드픽, 산지픽, blend-pick, shop.blendpunch.com, sanjipick, 판매채널, 연동, 공유DB, shop_users, 문의, 인플루언서, 캠페인, 마이그레이션]
paths: ["app/models/influencer.py", "app/models/campaign.py", "app/models/product.py", "app/models/brand.py", "app/models/sales_page.py", "app/models/shop_user.py", "app/models/inquiry.py", "app/routers/inquiry.py"]
updated: 2026-09-24
---

**구조 (2026-09-24 운영 서버 설정·블랜드픽 코드·nginx 기록으로 확인):**
- 같은 EC2 에서 두 프로그램: OS(`blendpunch.service`, uvicorn :8000, os.blendpunch.com) /
  블랜드픽(`blend-pick.service`, Next.js :3000, `/home/ubuntu/blend-pick`) — shop.·sanjipick.·sanji.blendpunch.com 셋 다 여기로.
  nginx access.log 는 **네 사이트 공용**이라 경로만 보고 OS 요청으로 단정하지 않는다.
- DB 서버(RDS) 하나에 DB 두 개: 블랜드픽 전용 `blendpunch_shop`(주문·결제·반품·배송·리뷰) +
  **OS 운영 DB `blendpunch_dev` 를 블랜드픽이 직접 연결**(`lib/db.ts`, env `DATABASE_URL`).

**블랜드픽이 OS 에 닿는 곳 (이걸 바꾸면 블랜드픽이 깨질 수 있다 → [[RG-007]]):**
| OS | 블랜드픽이 하는 일 |
|---|---|
| `products` `brands` `campaigns` `sales_pages` `influencers` | 읽기 (화면 표시) |
| `influencers` | 관리자 화면에서 **추가·수정·삭제** |
| `campaigns` | 수정 |
| `shop_users` | 회원가입·로그인·탈퇴·이메일인증 (회원이 OS DB 에 저장됨) |
| `POST /inquiries/api/submit`, `GET /inquiries/api/user/{id}` | 1:1 문의 (서버 내부 localhost:8000 호출, env `OS_API_URL`) |

**닿지 않는 곳:** 주문·결제(블랜드픽이 토스를 직접 확인, 자체 DB). OS `/api/v1` 과 옛 `/shop` 은 미사용
(2주 기록에 봇 접속뿐) → `/shop` 은 2026-09-24 삭제([[DE-007]], `43220bc`).

**확인한 위험 (조치 안 함, 대표님 판단 대기):**
1. 블랜드픽 `.env.local`(→ `blendpunch_dev`)과 `.env.production`(→ 로컬용 `blendpunch`)이 다른 DB 를 가리킨다.
   Next.js 는 `.env.local` 이 우선이라 지금은 운영 DB 로 추정 — `.env.local` 이 사라지면 엉뚱한 DB 로 바뀐다.
2. 블랜드픽 관리자 화면에서 OS 인플루언서를 **삭제**할 수 있고, OS 쪽에는 기록이 남지 않는다.

**검증 방법:** 블랜드픽 코드는 이 저장소에 없다. EC2 에서 읽기로만 확인:
`grep -rn "from influencers\|update influencers" /home/ubuntu/blend-pick/app /home/ubuntu/blend-pick/lib`.
env 는 **키 이름만** 본다 (값·비밀번호 출력 금지).

관련: [[DE-007]], [[RG-007]], [[PR-002]]
