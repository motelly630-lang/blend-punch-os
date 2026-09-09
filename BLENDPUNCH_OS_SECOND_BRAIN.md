# 블렌드펀치 OS — 세컨드 브레인 인수인계 문서

> **이 문서의 독자는 사람이 아니라, 블렌드펀치의 시스템과 업무를 장기적으로 기억·관리할 AI(세컨드 브레인)입니다.**
> 코드 설명서가 아니라, "블렌드펀치가 공동구매 업무를 어떻게 운영하고 그 업무가 OS 안에서 어떻게 연결되는가"를 설명하는 문서입니다.
>
> 작성 기준일: 2026-07-23 · 대상 시스템: `blend-punch-os` (운영 도메인 `os.blendpunch.com`)
> 분석 방식: 저장소 전체(모델 36개, 라우터 47개, AI API 11개, 소싱 파이프라인, 템플릿 30여 폴더)를 코드로 직접 교차 확인.

---

## 📌 이 문서를 읽는 법 (라벨 규칙)

문장 앞의 태그로 "무엇이 사실이고 무엇이 추정/계획인지"를 구분합니다. **이 구분은 절대 섞지 마십시오.**

- **【사실】** — 코드에서 직접 확인된 내용. 파일 경로·줄번호가 근거로 붙습니다.
- **【추론】** — 코드 정황으로 미루어 판단한 내용. 100% 확정은 아님.
- **【계획】** — 문서·시안·메모리에만 있고 코드로 구현되지 않은 아이디어/미래 방향. (대표의 구상 포함)

구현 수준은 4단계로 표기합니다:
- **✅ 정상 사용 가능** / **🟡 구현됐으나 검수 필요** / **🟠 일부만 구현** / **⚪ 계획·문서 단계**

기술 용어는 뒤에 바로 업무상 의미를 붙입니다. 예: `soft-delete`(실제로 지우지 않고 "보관됨" 표시만 하는 삭제).

---

# 1. 블렌드펀치 OS 개요

## OS를 만든 목적
【사실】 블렌드펀치 OS는 **인플루언서 기반 공동구매(공구) 사업을 처음부터 끝까지 한 시스템에서 운영**하기 위한 내부 업무 플랫폼입니다. FastAPI(웹 서버) + PostgreSQL(데이터베이스) + Jinja2/htmx/Alpine.js(화면)로 만들어진 웹 애플리케이션입니다.

【사실】 하나의 프로그램 안에서 다음이 모두 연결됩니다:
- 제품·브랜드·인플루언서 같은 **자산 관리**
- 공구를 실제로 진행하는 **캠페인 관리**
- 소비자에게 파는 **판매 페이지·주문·결제(토스페이먼츠)**
- 돈을 나누는 **정산**
- 영업(아웃리치·CRM·제안서)과 **AI 자동화**

## 해결하려는 공동구매 운영 문제
【추론】 코드 구조로 볼 때 OS가 해결하려는 문제는:
1. 제품 정보가 엑셀·벤더 제안서 등 제각각인 것을 → **표준 제품 데이터로 정규화** (`app/routers/import_products.py`, `app/sourcing/`)
2. "어떤 인플루언서에게 어떤 제품을 붙일까"를 → **캠페인·CRM·AI 추천으로 체계화**
3. 공구 판매를 → **비밀 판매 페이지 + 셀러 추적 링크**로 운영 (`app/routers/sales_pages.py`, `shop.py`)
4. 복잡한 **한국 세무 정산(사업자/간이/프리랜서)** 을 자동 계산 (`app/routers/settlements.py`)

## 현재 운영 시스템으로서의 역할
【사실】 이 OS는 **실제 운영 중**입니다(`os.blendpunch.com`). 로그인, 제품/캠페인/주문 관리, 토스 결제 승인, 정산, 협력사 포털이 모두 살아 있는 라우트로 존재합니다. 매일 새벽 2시 S3 백업, 매일 오전 9시 트렌드 브리핑이 스케줄러로 돌아갑니다(`app/scheduler.py`).

## 장기적으로 지향하는 플랫폼/SaaS 방향
【사실】 코드에는 이미 **멀티테넌트 SaaS(여러 회사가 한 시스템을 나눠 쓰는 구조)의 뼈대가 구현**되어 있습니다: `Company`(회사) + `CompanyFeature`(회사별 기능 on/off) + `company_id`로 데이터 분리 + 요금제(beta/basic/pro) (`app/services/feature_flags.py`).
【추론】 현재는 사실상 단일 회사(`company_id=1` = 블렌드펀치)로만 운영되지만, 다른 회사에 OS를 빌려주는 SaaS로 확장하도록 미리 설계되어 있습니다.
【계획】 메모리 기준, 소비자 쇼핑몰(`blendpunch.com`, Next.js)·`local` 산지공구·자비스 컨트롤타워 등은 **별도 프로젝트**이며 이 저장소가 아닙니다(혼동 주의 — 13·14장 참조).

---

# 2. 사용자 유형과 권한

【사실】 로그인 계정은 `User` 모델 하나이며, `role`(역할) 문자열과 `company_id`로 권한이 갈립니다. 인증은 **JWT를 담은 httponly 쿠키, bcrypt 해시, 8시간 만료**입니다(`app/auth/service.py`, `app/auth/dependencies.py`).

## 코드에 실제로 구현되어 강제되는 역할

| 역할(코드값) | 업무상 의미 | 코드에서 하는 일 | 상태 |
|---|---|---|---|
| `admin` (`company_id=NULL`) = **슈퍼어드민** | 블렌드펀치 대표/최고관리자 | 모든 회사·기능·사용자·백업·매뉴얼 관리. 모든 기능 게이트 통과 | ✅ 강제됨 (`dependencies.py:44-48`) |
| `admin` (회사 소속) | 회사 단위 관리자 | 제품/캠페인 삭제, 문의 관리 등 일부 관리 작업 | ✅ (`dependencies.py:38-41`) |
| `staff` | 운영 담당자(사원) | 협력사 모듈 등 대부분의 실무 화면 접근 | ✅ (`dependencies.py:57-61`) |
| `partner` | 협력사(공급사) 담당자 | `/portal`(보기 전용 포털)만 접근. 그 외 모든 경로는 강제 리다이렉트 | ✅ 전면 격리 (`main.py:220`) |

## 코드에는 있으나 실제로는 안 쓰이는(레거시) 역할
- **【사실】 `manager`, `viewer`** — `ROLE_LEVEL`과 라벨에는 존재하고 `require_manager`/`require_staff`가 받아주지만, **사용자 생성 UI는 `admin/staff/partner` 3종만 제공**합니다(`auth.py:262`). → 옛 잔재.

## 대표가 요청 목차에 넣은 세부 역할 vs 실제 코드

요청 목차에는 **대표(사장님)·PM·CS 담당자·상품등록 담당자·인플루언서·브랜드/공급사·일반 구매자**가 나열되어 있으나, **코드상 로그인 역할은 위 4종뿐**입니다. 나머지는 다음과 같이 처리됩니다:

| 요청한 역할 | 코드상 실제 | 상태 |
|---|---|---|
| 대표 | `admin`(슈퍼어드민) 계정 하나로 수행 | ✅ |
| 관리자 / PM / 운영 / CS / 상품등록 담당자 | **모두 `staff` 역할 하나로 통합**. 세분화된 권한 없음 | 🟠 세분화 미구현 |
| **인플루언서** | **로그인 계정 아님.** `/influencers`에서 관리되는 *데이터 레코드*일 뿐 (`app/models/influencer.py`). 인플루언서 본인이 로그인하는 기능은 없음 | ⚪ 셀프서비스 미구현 |
| **브랜드/공급사** | `Brand`(단순 목록)과 `Partner`(협력사) 로 존재. 협력사 담당자만 `partner` 역할로 로그인해 `/portal` 보기 가능 | ✅ 협력사 포털만 |
| **일반 구매자** | **로그인 없음.** 공개 쇼핑몰(`/shop/{slug}`)에서 비회원으로 결제. `ShopUser`(카카오 로그인 고객) 모델은 정의만 되어 있고 **어디에도 연결 안 됨** | 🟠 쇼핑몰은 비회원 / ⚪ 회원기능 미연결 |

> **⚠️ 세컨드 브레인 주의:** "CS 담당자 권한", "상품등록 담당자 권한" 같은 세분화 권한은 **대표의 구상일 수는 있으나 코드에는 없습니다.** 있다고 기록하지 마십시오.

## 권한을 강제하는 두 가지 실제 장치
【사실】
1. **역할 의존성**(`require_admin` 등) — 특정 라우트에 붙어 역할을 검사.
2. **기능 게이트 미들웨어**(`FeatureGateMiddleware`, `main.py:127`) — 로그인한 사용자의 회사(`company_id`)가 그 기능을 켰는지 URL prefix로 검사. **대부분의 라우터는 역할 대신 이 기능 on/off로만 통제**됩니다.

【사실 · 중요】 기능별 최소 역할(`min_role`)을 검사하는 `require_feature()` 함수는 **정의만 되어 있고 어떤 라우터에서도 사용되지 않습니다**(`dependencies.py:81-108`). 따라서 `min_role: admin`으로 표시된 자동화·소싱·셀러 기능도 **회사에서 기능만 켜져 있으면 로그인한 아무 직원이나 접근 가능**합니다. (10장 기술부채 참조)

---

# 3. 전체 메뉴와 화면 구조

【사실】 사이드바 메뉴는 `app/templates/base.html:90-275`에 정의되며, 각 항목은 `is_feature_enabled()`로 회사가 켠 기능만 노출됩니다. 슈퍼어드민은 하단 "⚙️ 설정" 그룹을 추가로 봅니다.

## 3-1. 영업 그룹

| 메뉴 | 라우트 | 대상 | 목적 | 주요 기능 | 연결 | 상태 |
|---|---|---|---|---|---|---|
| 캠페인 | `/campaigns` | staff+ | 공구 진행 건 관리 | 목록(진행/보관 탭)·달력·매출/수수료 집계·상세 손익·자동정산 | 제품·인플루언서·판매페이지·정산 | ✅ |
| 제안서 | `/proposals` | staff+ | 인플루언서/셀러에 보낼 제안 문구 저장 | 제품시트·DM·카카오 문구, 공유 카드, AI 생성 | 제품·인플루언서·캠페인 | ✅ |
| 아웃리치 | `/outreach` | staff+ | 대량 DM 발송·응답 KPI 추적 | 담당자별 발송/응답/성사율, CRM 전환 | CRM·이메일·인플루언서 | ✅ |
| CRM 파이프라인 | `/crm` | staff+ | 인플루언서 딜 칸반보드 | 단계 관리·샘플 발송 로그·이메일 | 인플루언서·제품·샘플 | ✅ |

## 3-2. 자산 그룹

| 메뉴 | 라우트 | 목적 | 주요 기능 | 상태 |
|---|---|---|---|---|
| 제품 | `/products` | 판매 제품 관리 | 브랜드 카드 그리드, 상세, 폼(가격/옵션/배송/이미지), 엑셀 임포트, 인라인 자동저장, 복제, 누끼(배경제거) | ✅ |
| 브랜드 | `/brands` | 브랜드/공급사 목록 | 로고 업로드, 엑셀 일괄등록, 클라이언트 검색 | ✅ |
| 인플루언서 | `/influencers` | 인플루언서 데이터 관리 | 갤러리/리스트 토글, URL 붙여넣기 AI 추출, 정산용 계좌·사업자 정보 | ✅ |

## 3-3. 협력사 (사이드바 항상 노출)

| 메뉴 | 라우트 | 대상 | 목적 | 상태 |
|---|---|---|---|---|
| 협력사 | `/partners` | staff+ (내부) | 공급사(협력사) 등록·제품 배정·계약/정산주기, 포털 계정 발급 | ✅ |
| (외부) 협력사 포털 | `/portal` | `partner` 역할 | 협력사 담당자 전용 **보기 전용** 화면: 공구 스케줄·정산 일정·제품 검수·샘플 발송 | ✅ (2026-07-13 운영 반영) |

## 3-4. 커머스 그룹

| 메뉴 | 라우트 | 목적 | 주요 기능 | 상태 |
|---|---|---|---|---|
| 판매 페이지 | `/sales-pages` | 공구 판매 페이지(관리자 CRUD) | slug·재고·옵션·애드온·기간·셀러코드 제한 설정, 활성/마감 | ✅ (셀러코드 제한은 미적용 🟠) |
| 주문 관리 | `/orders` | 주문/배송 관리 | 목록 필터, 엑셀 내보내기, CSV 대량 송장 등록, 개별 발송/배송완료/취소, 카카오 알림 | ✅ (환불 ⚪) |
| 공구 신청 | `/applications` | 인바운드 공구 신청 접수 | 신청 목록·상태(new/reviewing/approved/rejected) | ✅ |
| 정산 | `/settlements` | 인플루언서 정산 | 유형별 세무 계산, 확정/지급, 엑셀 내보내기, 월별 손익계산기 | 🟡 (프리랜서 공식 불일치 — 7·10장) |

## 3-5. AI & 자동화 그룹

| 메뉴 | 라우트 | 목적 | 상태 |
|---|---|---|---|
| 제품 소싱 | `/sourcing` | 엑셀/벤더 제안서 → AI 추출·가격계산·구글시트 | 🟡 (로컬 검증, 배포 여부 확인 필요) |
| 자동화 센터 | `/automation` | AI 콘텐츠 생성 허브(수동) | ✅ |
| 트렌드 | `/trends/feed` | 트렌드 피드 + 제품 매칭 | ✅ |

## 3-6. 설정 그룹 (슈퍼어드민 전용)

| 메뉴 | 라우트 | 목적 | 상태 |
|---|---|---|---|
| 회사 관리 | `/companies` | 테넌트(회사) 생성·기능 플랜·사용자 배정 | ✅ |
| 기능 관리 | `/settings/features` | 회사별 기능 on/off | ✅ |
| 매뉴얼 관리 | `/settings/manuals` | 페이지별 도움말 편집 | ✅ |
| 백업 관리 | `/settings/backup` | 백업 이력·수동 실행 | ✅ |
| 사용자 관리 | `/users` | 계정 생성/역할 | ✅ |
| 출결 관리 | `/attendance` | 직원 로그인/로그아웃 기록·페이지 방문 추적 | ✅ |
| 문의 관리 | `/inquiries` | 고객 문의(CS) 답변 | ✅ |

## 3-7. 사이드바에 없지만 존재하는 화면 (숨은/외부 연결)
- **【사실】 셀러 관리** `/sellers` — 기능은 구현됐으나 **메인 사이드바 링크 없음**(feature=sellers, min_role=admin). 셀러 코드·주문 추적.
- **【사실】 시즌 엔진** `/trends/engine` — 트렌드 하위, 별도 사이드바 링크 없음.
- **【사실】 공개 카탈로그** `/public/products` — 로그인 없이 보는 제품 카탈로그(비회원). `X-Robots-Tag: noindex`로 검색 차단(`main.py:111`).
- **【사실】 공개 쇼핑몰** `/shop/{slug}` — 판매 페이지의 실제 소비자 구매 화면(비회원, 토스 결제).
- **【사실】 레거시** `/catalog` — `/public`으로 완전 대체됨. **모든 경로가 301 리다이렉트**(`catalog.py`). 템플릿은 고아 상태.
- **【사실】 외부 앱 링크** — 사이드바의 "공구 인사이트"는 `insight.blendpunch.com`(별도 앱), 하단 "공구 인사이트/인사이트 관리" 링크도 외부.

---

# 4. 핵심 데이터 구조

【사실】 거의 모든 모델에 `company_id`(소속 회사, 기본 1) 컬럼이 있어 회사별로 데이터가 분리됩니다. 삭제 방식은 두 가지: `is_archived`(보관 표시) 또는 `is_active`(비활성). **`deleted_at`/`is_deleted` 같은 완전 소프트삭제 컬럼은 어떤 모델에도 없습니다.**

## 4-1. Product (제품) — `app/models/product.py`
- **의미:** 공구 카탈로그의 중심 제품. 캠페인·판매페이지·주문·제안서가 모두 이걸 참조.
- **필수값:** `name`(상품명), `brand`(브랜드 **이름 문자열**), `category`.
- **가격 필드(중요):** `consumer_price`(소비자가·공개), `groupbuy_price`(공구가·공개), `supplier_price`(공급가·**내부전용**), `vendor_commission_rate`(벤더수수료·**내부전용**), `seller_commission_rate`(셀러수수료·공개), `discount_rate`, `margin_rate`(자동계산 캐시). **모든 %는 0~1 소수로 저장**(폼에서 100으로 나눔).
- **상태값:** `status`(draft/active/archived — 단 코드가 `hidden`도 씀), `visibility_status`(active/hidden), `review_status`(AI 파이프라인: draft→structured→reviewed→strategy_checked→approved/rejected), `is_published`(쇼핑몰 노출), `is_archived`(보관=소프트삭제), `is_complete`+`missing_fields`(입력 완성도 자동판정).
- **관계:** 브랜드와는 **FK가 아니라 `brand` 문자열로 연결**(주의!). `partner_id`(공급 출처), `sourcing_batch_id`는 FK 제약 없는 soft ref.
- **⚠️ 재고 없음:** Product에는 재고/수량 컬럼이 **없습니다.** `set_options`(JSON)는 옵션 "설명"일 뿐 재고 아님. **실제 재고는 `SalesPage`에 있습니다.**
- **주의점:** 옛 `price` 필드와 신 가격블록(`consumer_price` 등)이 **공존·중복**. 가시성 제어가 `status`/`visibility_status`/`is_archived`/`is_published` 4개로 갈려 복잡.

## 4-2. Brand (브랜드/공급사) — `app/models/brand.py`
- **의미:** 브랜드 목록. 제품은 이걸 이름 문자열로만 참조하므로 사실상 "가벼운 관리 목록".
- **필드:** `name`(**전역 unique** — ⚠️ 멀티테넌트와 충돌, 10장), `logo`, `description`, `is_archived`, AI용 `review_status`/`priority_score`.
- **관계:** 제품 저장 시 `_ensure_brand()`가 없는 브랜드명을 자동 생성하지만, **엑셀 임포트 경로는 이를 건너뜀** → 브랜드 데이터가 어긋날 수 있음.

## 4-3. Influencer (인플루언서) — `app/models/influencer.py`
- **의미:** 공구 진행자. 정산에 필요한 세무·계좌 정보도 보관.
- **필드:** `platform`(instagram/youtube/tiktok/blog/naver), `handle`, `followers`, `categories`(JSON), 연락처, **정산 정체성**: `business_type`(사업자/간이/프리랜서), `bank_name`/`account_number`/`account_holder`, 사업자·프리랜서 세부 필드.
- **상태값:** `status`(active/inactive/blacklist), `is_archived`(소프트삭제).
- **레거시:** `engagement_rate`(폼에서 제거됐으나 DB 잔존), `has_campaign_history`가 문자열 "true"/"false".

## 4-4. Campaign (공구 진행 건) — `app/models/campaign.py`
- **의미:** 인플루언서 × 제품 공구 1건. 정산을 만들어내는 단위.
- **필드:** `product_id`(FK), `influencer_id`(FK), `partner_id`, 기간(`start_date`/`end_date`), 수수료 분배(`seller_commission_amount`/`vendor_commission_amount` = 매출×율, 자동계산), DB 연결 없이 쓰는 수기 필드(`product_name_manual` 등), `campaign_type`(internal/external).
- **상태값:** planning/negotiating/contracted/active/completed/cancelled. **날짜 기반 자동 상태 전환** 있음(8장).
- **관계:** `product`, `influencer`에 실제 `relationship()` 존재.

## 4-5. Order (주문) — `app/models/order.py`
- **의미:** 소비자가 판매페이지에서 산 B2C 주문. 토스 결제 연동.
- **필드:** `order_number`(BP-날짜-랜덤, unique), `sales_page_id`/`product_id`/`seller_id`(FK), `seller_code`(항상 저장되는 비정규화값), 구매자·배송지·라인아이템(옵션/수량/단가/합계/애드온), 결제(`payment_key`, `payment_status`), 배송(`carrier_name`, `tracking_number`, `shipped_at`), `is_test`.
- **상태값 두 종류:** `payment_status`(pending/paid/cancelled/refunded — **refunded는 코드가 절대 안 씀**), `order_status`(pending/confirmed/shipping/delivered/cancelled).
- **주의:** 소프트삭제 없음(취소는 상태로만). 관계 객체 없이 FK 컬럼만.

## 4-6. SalesPage (판매 페이지) — `app/models/sales_page.py`
- **의미:** 소비자에게 보이는 공구 랜딩. **실제 재고가 여기 있음.**
- **필드:** `slug`(unique, `/shop/{slug}`), `product_id`(FK), `editor_content`(붙여넣기 HTML), `price`/`original_price`, **`stock_quantity`(None=무제한)**, **`options` JSON `[{name,price,stock}]`**(옵션별 재고), `addon_products`, 기간, `campaign_id`(FK), `is_published`, `allowed_seller_codes`(셀러 제한 목록 — **저장만 되고 미적용**).
- **상태값:** draft/scheduled/active/ended/closed. 실제 노출 상태는 날짜+재고로 실시간 재계산.

## 4-7. Seller (셀러) — `app/models/seller.py`
- **의미:** 판매를 일으키는 추적 코드(`?seller=xxx`). 로그인 계정 아님.
- **필드:** `seller_code`(unique), `name`, `influencer_id`(FK), `is_active`.

## 4-8. Settlement (정산) — `app/models/settlement.py`
- **의미:** 인플루언서(셀러)에게 지급할 정산액. **캠페인 단위, 세무 처리 포함.**
- **필드:** `influencer_id`/`campaign_id`(FK), `seller_type`, `sales_amount`, `commission_rate`, `commission_amount`, `vat_amount`(부가세), `tax_amount`(원천징수), `final_payment`(최종지급), 계좌 **스냅샷**(생성 시점 고정).
- **상태값:** pending/confirmed/paid.

## 4-9. Transaction (거래·손익) — `app/models/transaction.py`
- **의미:** 회사 매출/비용 장부. 손익계산기에 집계.
- **필드:** `type`(revenue/cost), `source`(smartstore/external_link/manual), `category`(비용용), `amount`, `transaction_date`, `campaign_id`(선택 FK).
- **주의:** 결제 성공 시 자동 생성되는 매출 거래는 `source`가 무조건 "smartstore"로 하드코딩됨.

## 4-10. Partner + PartnerContact (협력사) — `app/models/partner.py`
- **의미:** 제품을 공급하는 협력사(공급사). **`company_id`(SaaS 테넌트)와 다름** — 제품의 "출처".
- **필드:** `name`, 연락처, `contract_terms`, `settlement_cycle`, `settlement_days`(기본 14), `is_active`. `PartnerContact`는 개별 담당자, 포털 로그인용 `user_id` 연결 가능.

## 4-11. CrmPipeline + SampleLog (CRM) — `app/models/crm.py`
- **의미:** 인플루언서 딜 파이프라인 + 샘플 발송 추적.
- **상태값:** CRM = new/dm_sent/replied/sample_requested/sample_sent/negotiating/completed/rejected. SampleLog = pending/sent/delivered/reviewing/returned.

## 4-12. 그 외 주요 모델
- **OutreachLog** — DM/아웃리치 활동 로그. 상태 sent/replied/deal/hold/rejected(+옛 한글 상태 잔존). `influencer_id`/`product_id`는 FK 없는 soft ref.
- **Proposal** — 제안 문구(email/kakao). `sent_at`/`response_received` 필드는 있으나 **갱신 라우트 없음(반쯤 미완성)**.
- **GroupBuyApplication** — 인바운드 공구 신청. 상태 new/reviewing/approved/rejected.
- **ShopUser** — 쇼핑몰 고객(카카오/이메일). **정의만 됐고 어디에도 연결 안 됨(미사용)**. 로그인은 admin `User`로 처리됨.
- **User** — 관리자/직원/협력사 계정(2장).
- **Company / CompanyFeature** — SaaS 테넌트 + 기능 토글.
- **BusinessInfo** — 전자상거래법 사업자 정보(싱글톤 id=1). 정산 계산과 무관, 표기용.
- **AI 파이프라인 모델**: AgentLog(단계 로그), AgentMemory(성공패턴 학습), HumanReviewQueue(결재 대기), PipelineJob(작업 상태), TriggerLog(자동 실행 로그). **이들은 `company_id`에 FK 제약이 없음**(다른 모델과 다름).
- **SourcingBatch** — 소싱 업로드 1건 추적.
- **Inquiry** — 고객 문의(CS). 상태 pending/read/replied.
- **EmailLog** — 발송 이메일 이력(아웃리치/CRM 사이드채널).
- **BackupLog / AttendanceLog / PageVisitLog / PageManual** — 백업 이력 / 직원 출결 / 페이지 방문 / 페이지 도움말.

---

# 5. 공동구매 전체 업무 흐름

각 단계에 담당자·화면·데이터·자동/수동·누락을 표시합니다. (전형적 흐름 【추론】 + 각 화면의 존재 【사실】)

### ① 브랜드·제품 확보 → 브랜드 등록 → 제품 등록
- **담당자:** staff(상품등록 담당) / **화면:** `/brands`, `/products/new`, 엑셀 임포트 `/products/import`, AI 소싱 `/sourcing`
- **자동:** 제품 저장 시 브랜드 자동 생성(`_ensure_brand`), 완성도 자동 판정. AI로 제품 필드 채우기(`/api/ai/product-fill`).
- **사람 확인:** 공급가·수수료 등 내부 가격. **누락:** 엑셀 임포트는 완성도 판정·브랜드 자동생성을 건너뜀.

### ② 공급가·판매가·수수료 설정
- 제품 폼 Phase-5 가격블록(`consumer_price`/`supplier_price`/`groupbuy_price`/수수료율). **자동:** `margin_rate` 계산.

### ③ 인플루언서 매칭
- **화면:** `/influencers`, `/crm`, AI 추천 `/api/ai/recommend-sellers`. **자동:** AI 셀러 추천 점수. **사람:** 최종 매칭은 캠페인/제안서를 사람이 생성.
- **누락:** 인플루언서↔제품 직접 매칭 테이블 없음 — 캠페인/제안서로 간접 연결.

### ④ 샘플·콘텐츠 준비
- **화면:** `/crm`(SampleLog 샘플 발송), 제안서/AI 콘텐츠(`/api/ai/seller-content`, `/api/ai/dm`). **자동:** 샘플 추가 시 파이프라인 sample_sent로 전진.

### ⑤ 공구 일정 확정 → 캠페인
- **화면:** `/campaigns/new`. 기간·수수료 분배 입력. **자동:** 날짜 기반 상태 전환, 수수료액 자동계산.

### ⑥ 판매 페이지 생성
- **화면:** `/sales-pages/new`. slug·재고·옵션·기간·셀러코드. **비밀 링크:** `{base}/shop/{slug}?seller={코드}` (셀러 추적).
- **주의:** 셀러코드 제한(`allowed_seller_codes`)은 저장만 되고 검증 안 됨.

### ⑦ 공구 오픈 → 주문·결제
- **화면(비회원):** `/shop/{slug}`. **자동:** 오픈/마감을 날짜·재고로 실시간 판정. 토스 결제 → `/shop/success` → 서버 승인.
- **자동:** 결제 승인 시 재고 차감 + 매출 Transaction 생성 + 주문 confirmed.

### ⑧ 발주·배송
- **화면:** `/orders`. **자동:** CSV 대량 송장 업로드 → 배송상태 + 카카오 알림톡(기본 mock). 엑셀 내보내기.
- **누락:** "발주(공급사에 주문 전달)"는 별도 화면 없음 — 협력사 포털의 보기 전용 스케줄이 근접.

### ⑨ 취소·환불·CS
- **취소:** `/orders/{id}/cancel` — 상태만 cancelled. **CS:** `/inquiries`(고객 문의 답변).
- **⚠️ 누락:** **환불 미구현** — 토스 취소 API 호출 없음, 재고 복구 없음, 매출 거래 취소 없음, `refunded` 상태 미사용.

### ⑩ 공구 종료 → 정산
- **자동:** 캠페인이 `completed`가 되면 `_auto_settle`이 Settlement 생성/재계산(확정·지급된 건은 건드리지 않음). **화면:** `/settlements`.
- **⚠️ 주의:** 프리랜서 정산 공식이 소싱 시뮬과 실제 정산이 다름(7·10장). 환불이 정산에 반영 안 됨.

### ⑪ 결과 기록·재진행
- **화면:** `/settlements?tab=calc`(월별 손익), 대시보드. AgentMemory에 성공 패턴 학습.

---

# 6. 기능별 상세 설명

### 브랜드 관리 ✅ (`app/routers/brands.py`)
로고 업로드(누끼 자동), 엑셀 일괄등록(2컬럼: 이름·설명), 중복명은 IntegrityError→리다이렉트, 검색은 **클라이언트 JS**(페이지네이션 없음). 삭제=`is_archived=True`. **브랜드는 제품과 FK가 아닌 이름 문자열로 연결.**

### 제품 관리 ✅ (`app/routers/products.py`, 667줄)
폼 필드 다수(가격/옵션/배송/이미지/포지셔닝). 이미지는 업로드 우선, URL도 가능. **저장 경로가 4개**(전체 폼, `PATCH .../json`, `PATCH .../field` 인라인, `.../upload-image`). 검색=서버(`q`, 카테고리, 완성도), 페이지네이션 없이 **300건 하드캡**. 삭제=admin 전용 `is_archived`.

### 제품 옵션 및 재고 관리 🟠
**제품 옵션(`set_options`)은 설명용**이라 재고 없음. **판매 가능한 옵션·재고는 판매페이지(`SalesPage.options`, `stock_quantity`)에만 존재.** 재고 차감은 결제 승인 시점(`payments.py:65-79`). **취소 시 재고 복구 없음.**

### 인플루언서 관리 ✅ (`app/routers/influencers.py`)
갤러리/리스트 토글, URL 붙여넣기 AI 추출(동시 3개 제한), 정산용 계좌·세무 정보. 삭제=`is_archived`.

### 공구 일정 및 캠페인 관리 ✅ (`app/routers/campaigns.py`, 621줄)
목록(진행/보관 탭)·달력 JSON·매출/수수료 집계. 인라인 생성/수정. 날짜 기반 자동 상태+자동 보관. `completed` 시 자동 정산 생성.

### 주문 및 결제 관리 ✅ (`app/routers/orders.py`, `app/api/payments.py`)
- **결제(토스):** `confirm_toss_payment`가 실제 토스 API 호출, 금액 위변조 검사, 멱등 처리, 재고 차감, 매출 거래 생성. **승인만 구현, 취소/환불/웹훅 없음.**
- **주문 생성 경로 2개:** 내부 쇼핑몰(`/shop/{slug}/prepare`), 외부 API(`/orders/api/create` — 외부 Next.js 쇼핑몰용, 무인증).

### 발주 관리 🟠
독립된 "발주" 모듈 없음. 협력사 포털의 보기 전용 공구/제품 스케줄이 대체.

### 배송 및 송장 관리 ✅
개별 발송(`/orders/{id}/ship`) + CSV 대량 송장(`/orders/bulk-ship`, UTF-8/CP949). `carrier_name`+`tracking_number`+`shipped_at`. 카카오 알림톡(best-effort, 기본 mock).

### 취소·교환·환불 🟠
취소만(상태 변경). **교환·환불 미구현.**

### CS 관리 ✅ (`app/routers/inquiry.py`)
고객 문의: 외부 제출(무인증) → 관리자 답변. 상태 pending/read/replied. 쇼핑몰 고객(`ShopUser`)과 연결. (아웃바운드 이메일 `emails.py`는 별개 — B2B 영업용)

### 정산 관리 🟡 (`app/routers/settlements.py`)
유형별 세무 계산(7장), 확정/지급, 엑셀 내보내기, `calc` 탭에서 월별 손익. **프리랜서 공식 불일치·환불 미반영·시점 키 불일치 문제 있음(10장).**

### 공개 제품 카탈로그 ✅ (`app/routers/public.py`)
`/public/products` 비회원 열람. 안전 DTO(`PublicProduct`)로 **내부가격 완전 제외**. 검색·카테고리·정렬·**실제 페이지네이션(24개/페이지)**. 검색엔진 색인 차단.

### 자체 쇼핑몰 ✅ (`app/routers/shop.py`)
`/shop/{slug}` = 판매페이지 1건 = 단일제품 구매 퍼널(장바구니 없음). 별도로 외부 Next.js 소비자몰용 JSON API(`app/api/public_v1.py`)가 `is_published` 제품/페이지 제공.

### 호텔·여행 공동구매 ⚪ (미구현 — 시안만)
**【사실】 백엔드 전무.** `static/redesign/`·`docs/redesign/`에 정적 HTML 시안(h01~h04 소비자, ha01~ha07 관리자)만 존재. 시안 문서가 제안한 `products.product_type='hotel'` + `hotels`/`hotel_rooms`/`hotel_date_inventory`/`hotel_reservations` 테이블은 **실제 스키마에 없음**. (현재 `Product.product_type`은 무관한 A/B/C/D 분류값). 메모리도 "개발 전"으로 확인.

### 엑셀 일괄 등록·다운로드 ✅/🟠
- **제품 임포트:** 29개 필드 매핑, 자동매핑→미리보기→확정, 22컬럼 템플릿 다운로드, AI 보강 옵션.
- **브랜드 임포트:** 2컬럼, 템플릿 다운로드 **없음**.
- **내보내기:** 주문(`/orders/export`), 정산(`/settlements/export`)만 엑셀 내보내기. **제품/브랜드 데이터 내보내기 없음.**

### 선착순 구매자 추출 ⚪ (미구현)
**전용 기능 없음.** "선착순"은 AI 카피 문구에만 등장. 주문을 `created_at` 순으로 필터·정렬·엑셀 내보내기 하는 것이 가장 근접한 대체.

### 검색·필터·페이지네이션 🟠 (일관성 없음)
- 공개 목록만 **진짜 서버 페이지네이션**. 관리자 목록은 **300건 하드캡**(페이지네이션 없음). 브랜드 목록은 클라이언트 JS 검색.

### 사용자 및 권한 관리 ✅/🟠
슈퍼어드민이 `/users`에서 계정 생성(admin/staff/partner). **역할별 세분 권한(min_role)은 미강제(2장).**

### 알림과 자동화 🟡
- **카카오 알림톡**(배송) + **이메일 발송** 모두 **기본값이 mock 모드**(`config.py`, `kakao_mock=True`/`email_mock=True`). 실발송하려면 `.env` 전환 필요.
- 자동화는 6장 아래 "자동화" 참조.

### 백업과 보안 ✅
- **백업:** APScheduler로 매일 02:00 KST S3 백업(`scheduler.py`) + 수동 실행. `BackupLog` 이력.
- **보안:** JWT 쿠키(httponly), bcrypt, AI API 분당 20회 IP 제한, CORS 화이트리스트, 공개경로 noindex. **미흡:** 단일세션(`current_token`) 검증 미흡, 쿼리별 테넌트 필터링(누락 시 유출 위험).

### 자동화 (자동화 센터 vs AI 파이프라인 — 별개)
- **자동화 센터** `/automation` ✅ — 수동 단발 AI 도구 허브. 실제 생성은 `/api/ai/*` 엔드포인트.
- **5단계 AI 파이프라인** `/pipeline` ✅ — 사원→대리→과장→팀장→이사(`app/agents/`). Decision Engine(역할별 임계값), Human Review Queue(`/pipeline/queue`, 점수 미달 시 사람 결재), 배치 처리, PipelineJob(재시작에도 상태 유지). **트리거는 수동**(관리자가 Start 클릭). **유일한 진짜 자동화**: 이사 승인 시 캠페인+DM 제안서 자동 생성(`decision_engine.py`, TriggerLog 기록).

---

# 7. 핵심 계산 로직

【사실】 **금액은 전부 `float × round()` (또는 `int(round())`) — `Decimal` 미사용, floor/ceil 없음.** %는 DB에 0~1 소수로 저장. 파일: `app/sourcing/pricing.py`, `app/routers/settlements.py`, `app/routers/campaigns.py`, `app/routers/shop.py`, `app/api/payments.py`.

## 7-1. 소싱 계산 — `app/sourcing/pricing.py` (결정적, AI 아님)
- **마진율** `margin_rate = round((groupbuy_price - supplier_price) / groupbuy_price, 4)`. 공구가≤0이면 None. (`pricing.py:37-40`)
- **마진액** `= int(round(groupbuy_price - supplier_price))`. (`:43-44`)
- **할인율** `= round(1 - groupbuy_price/consumer_price, 4)`. 소비자가≤0이면 None. (`:47-50`)
- **정산 `settle()`** (`:86-108`), 상수 VAT_RATE=0.10, WITHHOLDING_RATE=0.033:
  - 수수료 `commission = total_sales × commission_rate`
  - **사업자:** 정산 = commission (부가세·원천 0)
  - **간이사업자:** vat = commission×0.10 → 정산 = commission − vat
  - **프리랜서:** vat = commission×0.10; wh = (commission − vat)×0.033; **정산 = commission − vat − wh**

## 7-2. 실제 정산 DB 엔진 — `app/routers/settlements.py::calc_settlement()` (`:22-59`)
이것이 실제 Settlement 레코드를 쓰고, 캠페인 자동정산도 사용. **프리랜서 공식이 7-1과 다름:**
- **사업자:** final = round(commission)
- **간이사업자:** vat = round(commission×0.1); final = round(commission) − vat
- **프리랜서:** `공급가액 = commission/1.1`; vat = round(commission − 공급가액)(표시용); 원천 = round(공급가액×0.033); **final = round(commission) − 원천** (**부가세는 차감 안 함**)

## 7-3. ⚠️ 두 공식의 결과 차이 (커미션 100,000원 예시)
| 엔진 | 프리랜서 최종 지급액 |
|---|---|
| 7-1 `pricing.settle` (소싱 시뮬·구글시트) | **87,030원** (부가세+원천 둘 다 차감) |
| 7-2 `calc_settlement` (실제 정산·자동정산) | **97,000원** (원천만 차감) |

→ **【사실】 어느 쪽이 맞는지 코드가 말하지 않음. 대표 확인 필요.**(14장 질문)

## 7-4. 캠페인 수수료 분배 — `campaigns.py::_parse_form_fields` (`:248-261`)
`seller_amount = round(actual_revenue × seller_rate)`, `vendor_amount = round(actual_revenue × vendor_rate)`. **세금 없는 총액 분배** — 세무 정산(Settlement)과 별개이며 서로 대사(reconcile)되지 않음.

## 7-5. 주문 금액 — `shop.py`
`total = round(base_price×qty + Σ(addon.price×qty) + shipping)`. 할인율 표시 `= round((1 - price/original_price)×100)`.

## 7-6. PG(토스) 수수료
**【사실】 코드에 PG 수수료 계산 로직 없음.** 결제 승인만 하고 수수료 차감/기록은 하지 않음.

## 7-7. 월별 정산 집계 — `settlements.py` `calc` 탭 (`:149-215`)
`total_revenue`(Transaction revenue 합) − `total_cost`(cost 합) − `total_settlement_pnl`(Settlement final_payment, paid+confirmed) = `net_profit`.
- **⚠️ 시점 키 불일치:** Transaction은 `transaction_date` 기준, Settlement 손익은 `created_at` 기준, 정산 목록/내보내기는 자유텍스트 `period_label` 기준 → 같은 정산의 "월"이 화면마다 다를 수 있음.
- **⚠️ 확정(미지급)도 손익에 비용 반영**, 환불은 매출에서 안 빠짐.

## 7-8. 카테고리 추천 수수료 — `app/sourcing/category_rules.py`
기본 0.15. 화장품/뷰티 0.20, 다이어트/건기식/육아/반려동물 0.18, 식품/주방/리빙 0.15, 가전 0.12.

---

# 8. 상태값과 상태 전환

## 8-1. 제품 (`review_status`, AI 파이프라인)
`draft → structured → reviewed → strategy_checked → approved` / `rejected`. 자동 전환(파이프라인 각 단계). 사람이 결재큐에서 되돌림 가능. 코드: `app/agents/runner.py`, `human_review_queue.py`.
- 별도 `status`(draft/active/archived, 코드가 hidden도 사용), `visibility_status`(active/hidden), `is_archived`, `is_published` — 폼/삭제로 수동.

## 8-2. 캠페인 (`app/models/campaign.py`, `campaigns.py:26`)
planning → active → completed (날짜 자동, `_auto_status`) / negotiating·contracted(수동) / cancelled(수동, 자동전환에 덮이지 않음). completed 진입 시 자동 정산. 월 지나면 자동 보관.

## 8-3. 주문 (`app/models/order.py`)
- **payment_status:** pending(prepare) → paid(결제승인) / cancelled(취소). **refunded는 미사용.**
- **order_status:** pending → confirmed(결제) → shipping(발송) → delivered(배송완료) / cancelled(취소). 결제=자동, 발송/배송/취소=수동. **되돌리기 로직 없음.**

## 8-4. 판매페이지 (`sales_page.py:27`)
draft/scheduled/active/ended/closed(수동 activate/close). **실제 노출 상태는 날짜+재고로 실시간 재계산**(저장된 status와 별개).

## 8-5. 정산 (`settlement.py:24`)
pending → confirmed → paid. 모두 수동 버튼. 되돌리기 라우트 없음.

## 8-6. CS·공구신청·아웃리치·CRM·샘플·이메일
- 문의: pending → read(자동, 상세 열람 시) → replied(답변).
- 공구신청: new/reviewing/approved/rejected(수동).
- 아웃리치: sent/replied/deal/hold/rejected(+옛 한글 상태). CRM으로 전환 가능.
- CRM: new→dm_sent→replied→sample_requested→sample_sent→negotiating→completed/rejected. 샘플 추가 시 sample_sent 자동 전진.
- 샘플: pending/sent/delivered/reviewing/returned.
- 이메일: pending/sent/failed/replied/converted.

---

# 9. 현재 구현 수준

## ✅ 1. 정상 사용 가능
로그인/권한, 제품·브랜드·인플루언서 관리, 캠페인, 판매페이지, 쇼핑몰+토스 결제 승인, 주문·배송(송장), 공개 카탈로그, 공구 신청, CS 문의, 아웃리치, CRM, 제안서, 자동화 센터, AI 파이프라인+결재큐, 협력사 관리+포털, 트렌드 피드+시즌엔진, 사용자/회사/기능/매뉴얼/백업 관리, 출결. (근거: 해당 라우터·모델·템플릿 모두 존재·등록·일관)

## 🟡 2. 구현됐으나 검수 필요
- **정산** — 프리랜서 공식 불일치(7장), 시점 키 불일치, 확정건 손익 반영, 내보내기가 스냅샷 대신 현재 계좌를 읽음.
- **제품 소싱** — 로컬 E2E 검증됐으나 **운영 배포 여부 불확실**(메모리: 미배포 가능성), PDF 추출 미완, 다상품 시 느림.
- **알림(카카오/이메일)** — 기본 mock 모드. 실발송 검증 필요.

## 🟠 3. 일부만 구현
- 재고(판매페이지에만, 취소 시 복구 없음), 셀러코드 제한(미적용), 취소만 있고 환불 없음, 관리자 목록 페이지네이션(300 하드캡), 제안서 발송·응답 추적 필드(갱신 라우트 없음), 역할별 세분 권한(min_role 미강제).

## ⚪ 4. 계획·문서 단계
- **호텔·여행 공동구매**(시안만), **선착순 추출**(없음), **쇼핑몰 회원(ShopUser·카카오 로그인)**(모델만, 미연결), 인플루언서/셀러 셀프서비스 로그인(없음), PG 수수료 계산(없음), 환불 재무 처리(없음).

---

# 10. 현재 문제점과 기술 부채

> **【사실】이며, 이 문서 작성 중 코드를 수정하지 않았습니다. 세컨드 브레인도 이 항목들을 근거로 함부로 대규모 수정하지 마십시오 — 기록·주의 목적입니다.**

1. **프리랜서 정산 공식 불일치** (최우선) — `pricing.py`와 `calc_settlement`이 다른 값(7-3). 소싱 시뮬과 실제 정산이 어긋남.
2. **중복 라우트/화면** — `/catalog`(전부 리다이렉트 레거시), 공개 제품 URL 2형식(canonical + 301), 제품 저장 경로 4개.
3. **문자열로 연결된 데이터** — 제품↔브랜드가 `Product.brand` 문자열(FK 아님). 데이터 드리프트 가능. 아웃리치 날짜가 String.
4. **FK 없는 관계(soft ref)** — `Product.sourcing_batch_id`, `OutreachLog.influencer_id/product_id`, `EmailLog.related_id`, 모든 AI 파이프라인 id, 그리고 **`partner_id`(모델엔 FK지만 마이그레이션은 제약 없는 VARCHAR)**. 정합성 미보장.
5. **하드코딩된 카테고리/값** — 카테고리 추천 수수료(`category_rules.py`), Transaction `source`가 무조건 "smartstore", 요금제·기능 목록 코드 상수.
6. **사용하지 않는 필드** — `Influencer.engagement_rate`, `Product.price`(신 가격블록에 밀림), `Order.payment_status='refunded'`, Proposal 응답추적 필드, `User.subscription`.
7. **권한 문제** — `require_feature`/`min_role` 미강제 → 기능만 켜지면 아무 직원이나 자동화·소싱·셀러 접근. 단일세션(`current_token`) 미검증. **`Brand.name` 전역 unique** → 두 회사가 같은 브랜드명 등록 불가(멀티테넌트 잠재 버그).
8. **데이터 불일치 가능성** — 캠페인 총액 분배 vs 세무 정산 미대사, 정산 월 시점 3중 키, 엑셀 임포트가 브랜드 자동생성·완성도 판정 건너뜀.
9. **대량 데이터 처리** — 관리자 목록 300건 하드캡(페이지네이션 없음), 소싱/파이프라인이 스레드 기반(큐/워커 아님, 많으면 느림), 사용자 컨텍스트 인메모리 캐시(다중 서버 시 문제 가능).
10. **개인정보·보안 위험** — 인플루언서 계좌/주민번호·구매자 배송지 등 민감정보 저장(⚠️ 이 문서엔 실제 값 미포함). 테넌트 필터가 쿼리별 수동(누락 시 회사 간 유출). 정산 내보내기가 스냅샷 대신 현재 계좌 노출.
11. **운영 오류 구간** — 환불 미구현(취소 시 재고 미복구·매출 미차감), 결제 웹훅 없음(성공 리다이렉트 놓치면 미승인), 알림 mock 기본값(실발송 착오), 새 라우터 추가 시 `main.py _setup_filters()` 루프 등록 누락하면 Jinja 필터 미적용(예: shop·transactions는 현재 루프에 없음).

---

# 11. 앞으로의 개발 방향

> **전제: 현재 코드·데이터를 최대한 보존.** (12장 원칙 준수)

- **단기 개선:** ①프리랜서 정산 공식 하나로 통일(대표 확인 후), ②환불 처리(토스 취소 API + 재고 복구 + 매출 거래 취소), ③정산 월 시점 키 통일, ④정산 내보내기를 스냅샷 기준으로.
- **운영 안정화:** 관리자 목록 페이지네이션, 결제 웹훅/재확인, 테넌트 필터 누락 점검, `main.py` 필터 루프 자동화.
- **자동화:** 알림 실발송 전환·검증, AI 파이프라인 스레드→작업 큐, 선착순 추출 도구.
- **외부 쇼핑몰 개선:** `public_v1` API 강화, `ShopUser`+카카오 로그인 실제 연결.
- **브랜드·인플루언서 셀프서비스:** 인플루언서/셀러 로그인 + 대시보드(현재 없음).
- **멀티테넌트 SaaS 전환:** `Brand.name` unique를 회사별로, `min_role` 실제 강제, 회사별 온보딩.
- **결제·정산 자동화:** PG 수수료 기록, 정산 자동 지급 연동.
- **AI 기능 연결:** 소싱 파이프라인 운영 배포·PDF 추출, 자비스 결재함 연동(별도 프로젝트).
- **신규 상품유형:** 호텔·여행 공동구매(시안 완료 → 백엔드 착수 시 `product_type` 분기 + 신규 테이블).

---

# 12. 세컨드 브레인이 반드시 기억해야 할 기준

1. **기존 데이터를 훼손하는 대규모 마이그레이션을 피한다.** `migrate.py`는 컬럼 추가만 하는 재실행 안전 방식 — 이 패턴을 유지.
2. **기존 필드를 임의로 삭제하지 않는다.** 레거시 필드(`engagement_rate`, `price` 등)도 하위호환·과거 데이터 때문에 남아 있음.
3. **개발 전 현재 모델·라우트·화면을 먼저 확인한다.** 이 문서 4·3장을 근거로 삼되, 코드가 바뀌었을 수 있으니 실제 파일을 재확인.
4. **대표가 말한 아이디어와 현재 구현 기능을 구분한다.** 【계획】/【사실】 태그를 지킬 것. 호텔공구·쇼핑몰회원·선착순은 아이디어(⚪), 정산·주문·캠페인은 구현(✅).
5. **확인되지 않은 내용을 사실처럼 기록하지 않는다.** 특히 정산 공식·권한·환불처럼 돈/보안 관련은 코드로 확인 후 서술.
6. **공구 운영 업무와 OS 기능을 항상 연결해서 설명한다.** "화면 이름"이 아니라 "이 단계에서 무엇을 하고 다음에 뭐가 되는지"로.
7. **이 저장소(`blend-punch-os`)와 별도 프로젝트를 혼동하지 않는다.** `/g/` 비밀페이지·페이지별 셀러 재고 할당·소비자몰·자비스·sns-trend는 **여기가 아님**(13장).
8. **돈·개인정보는 문서/로그에 실값을 남기지 않는다.**

---

# 13. 용어집 (코드 용어 ↔ 업무 용어)

| 코드 용어 | 업무상 의미 |
|---|---|
| `Campaign` | 공동구매 진행 건 1개 (인플루언서×제품×기간) |
| `Product` | 판매 제품 (공급가/공구가/수수료 포함) |
| `Brand` | 브랜드(가벼운 목록). 실제 공급처는 `Partner` |
| `Influencer` | 공동구매 진행자(셀러). 로그인 계정 아님 |
| `Seller` | 판매 추적 코드(`?seller=xxx`), 인플루언서와 연결 가능 |
| `Partner` | 협력사=공급사(제품 출처). `company_id`(SaaS 테넌트)와 다름 |
| `Company` | SaaS 테넌트(회사). 블렌드펀치=`company_id 1` |
| `SalesPage` | 공구 판매 페이지(`/shop/{slug}`), **재고가 여기 있음** |
| `Order` | 소비자 주문(비회원 결제) |
| `Settlement` | 인플루언서 정산(세무 포함) |
| `Transaction` | 회사 매출/비용 장부(손익) |
| `Proposal` | 제안 문구(제품시트/DM/이메일) |
| `OutreachLog` / `CrmPipeline` | 대량 DM 로그 / 딜 칸반 파이프라인 |
| `GroupBuyApplication` | 인바운드 공구 신청 |
| `Inquiry` | 고객 문의(CS) |
| `SourcingBatch` | 소싱 파일 업로드 1건 |
| `review_status` | 제품 AI 검토 단계 |
| `is_archived` / `is_active` | 보관(소프트삭제) / 활성 여부 |
| `partner`(role) | 협력사 로그인 계정(포털 전용) |
| `staff`(role) | 내부 운영 직원(대부분 실무) |
| `admin`(company_id=NULL) | 슈퍼어드민(대표/최고관리자) |
| AI 파이프라인 5단계 | 사원(staff)→대리(assistant)→과장(manager)→팀장(lead)→이사(director) |

---

# 14. 확인이 필요한 질문 (대표 결정 필요)

1. **[정산·최우선] 프리랜서 정산 공식은 어느 쪽이 맞습니까?** 소싱 시뮬(부가세+원천 둘 다 차감, 87,030원) vs 실제 정산(원천만 차감, 97,000원). 둘을 하나로 통일해야 합니다.
2. **[정산] 월별 손익 집계의 기준 시점**은 거래일(`transaction_date`)입니까, 정산 생성일(`created_at`)입니까, 정산 라벨(`period_label`)입니까? 현재 세 화면이 제각각입니다.
3. **[정산] 확정(미지급) 정산을 손익 비용으로 잡는 것**이 맞습니까, 아니면 지급 완료만 잡아야 합니까?
4. **[주문] 환불 정책** — 환불이 전혀 구현돼 있지 않습니다. 토스 취소 연동 + 재고 복구 + 매출 취소가 필요합니까?
5. **[권한] 역할 세분화** — CS/상품등록/PM 등을 실제 권한으로 나눌 계획입니까, 아니면 `staff` 하나로 유지합니까? (`min_role`은 정의만 되고 미강제)
6. **[쇼핑몰] `ShopUser`(카카오 로그인 고객)** 를 실제로 붙일 계획입니까? 현재 모델만 있고 미연결이며, 쇼핑몰 API 로그인은 admin `User`로 처리됩니다.
7. **[셀러] `allowed_seller_codes`(판매페이지 셀러 제한)** 를 실제로 검증·차단해야 합니까? 지금은 저장만 되고 무시됩니다.
8. **[호텔공구] 호텔·여행 공동구매**를 실제 개발합니까? 시안(ha07)이 제안한 신규 테이블·`product_type='hotel'` 방향으로 진행할지 확정이 필요합니다.
9. **[소싱] 제품 소싱 에이전트가 운영에 배포되어 있습니까?** 메모리는 로컬 검증·미배포 가능성을 시사합니다.
10. **[멀티테넌트] `Brand.name` 전역 unique** — 여러 회사가 같은 브랜드명을 쓰게 하려면 회사별 unique로 바꿔야 합니다. 실제 다회사 운영 계획이 있습니까?
11. **[알림] 카카오·이메일 실발송 전환** 시점은 언제입니까? (현재 기본 mock)
12. **[선착순] 선착순 구매자 추출 도구**가 실제 업무에 필요합니까?

---

---

# 📄 부록: 1페이지 요약본 (세컨드 브레인 전달용)

> **블렌드펀치 OS 한눈에 — 이것만은 기억할 것**

**정체:** 인플루언서 공동구매 사업을 자산관리→영업→판매→정산까지 한 곳에서 운영하는 내부 웹 시스템(`os.blendpunch.com`, FastAPI+PostgreSQL). **멀티테넌트 SaaS 뼈대(회사·기능플래그·요금제)가 이미 구현**됐으나 현재 사실상 블렌드펀치 1개 회사로 운영.

**업무 흐름:** 브랜드/제품 확보(엑셀·AI 소싱) → 인플루언서 매칭(CRM·AI추천) → 캠페인 생성 → 판매페이지(`/shop/{slug}?seller=코드`) → 비회원 토스 결제 → 배송(CSV 송장) → 캠페인 종료 시 **자동 정산 생성** → 월별 손익.

**핵심 모델:** Campaign(공구 건)=중심. Product(제품, **재고 없음**), SalesPage(**재고·옵션 여기**), Order(비회원 주문), Settlement(세무 정산), Influencer(진행자, 로그인 아님), Seller(추적코드), Partner(공급사, 포털 로그인), Brand(제품과 **문자열 연결**).

**권한 4종:** 슈퍼어드민(대표)·staff(모든 실무)·partner(포털 전용, 전면 격리)·(레거시 manager/viewer). **역할 세분 권한(min_role)은 정의만 되고 미강제** — 기능만 켜지면 직원 누구나 접근.

**✅ 잘 되는 것:** 로그인·제품/캠페인/주문·토스 결제 승인·배송 송장·공개 카탈로그·CRM/아웃리치·AI 파이프라인+결재큐·협력사 포털·백업(매일 2시 S3).

**⚠️ 조심할 것 (돈·데이터):**
- **프리랜서 정산 공식이 두 곳에서 다름** (소싱 87,030 vs 실제 97,000) → 대표 확인 필수.
- **환불 미구현** (취소만, 재고 복구·매출 차감 없음), PG 수수료 계산 없음.
- 알림(카카오·이메일) **기본 mock**, 관리자 목록 **300건 하드캡**, 셀러코드 제한 미적용.

**⚪ 아직 없는 것 (아이디어/시안):** 호텔·여행 공동구매(시안만), 선착순 추출, 쇼핑몰 회원/카카오 로그인(ShopUser 미연결), 인플루언서 셀프 로그인.

**절대 혼동 금지:** `/g/` 비밀페이지·페이지별 재고할당·소비자몰(blendpunch.com)·자비스·sns-trend·local 산지공구는 **이 저장소가 아닌 별도 프로젝트**.

**작업 원칙:** 대규모 마이그레이션 회피 · 기존 필드 삭제 금지 · 개발 전 실제 모델/라우트 확인 · 대표 아이디어(계획)와 구현(사실) 구분 · 돈/개인정보 실값 노출 금지 · 새 라우터는 `main.py`의 `include_router`+`_setup_filters()` 루프 둘 다 등록.
