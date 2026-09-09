# 제품 소싱·제안서 AI 에이전트 — 설계서

> blend-punch-os 통합 버전 (FastAPI + PostgreSQL RDS + Jinja2/htmx + 중앙 ClaudeClient + Google Sheets API)
> 작성: 2026-06-03 · 상태: 설계 확정 대기

## 0. 목표와 범위

사장님이 정의한 9단계 에이전트를 **기존 OS에 통합**한다. 스펙에 적힌 Next.js/Supabase는
개념만 차용하고, 실제 구현은 OS 스택을 따른다. 이미 풍부한 `Product` 모델·엑셀 임포트·
`review_status` 승인 워크플로우·강화된 `ClaudeClient`(structured outputs)를 최대한 재사용한다.

### 9단계 → OS 구성요소 매핑

| # | 사장님 요구 | OS 구현 | 신규/재사용 |
|---|---|---|---|
| 1 | 엑셀/PDF 업로드 | `/sourcing/upload` (기존 import_products 패턴 확장) | 재사용+확장 |
| 2 | 상품/브랜드/옵션/소비자가/공급가/공구가/배송비/출고마감/AS/인증 추출 | **ExtractorAgent** (structured outputs) → `Product` 필드 | 신규(추출) |
| 3 | 공급가·공구가 기준 마진율 자동 계산 | **pricing.py** (순수 Python) | 신규 |
| 4 | 셀러 수수료율별 예상 정산금 계산 | **pricing.py** | 신규 |
| 5 | 웹서치로 공식정보·경쟁상품·후기키워드·장점·주의사항 보강 | **ResearchAgent** (Claude `web_search` 서버툴) | 신규 |
| 6 | 의료기기/식품/건기식/화장품 광고 위험표현 분리 | **ComplianceAgent** (structured outputs) | 신규 |
| 7 | 정리 내용 구글 스프레드시트 자동 입력 | **sheets_sync.py** (Google Sheets API) | 신규 |
| 8 | 최종 검수 → 사람 승인 | 기존 `Product.review_status` 워크플로우 재사용 | 재사용 |
| 9 | 카드뉴스/릴스후킹/상세페이지요약/셀러전달 문구 생성 | **CopywriterAgent** (structured outputs) | 신규(일부 content_angle 재사용) |

### MVP (1차 구현 범위)

**엑셀 업로드 → 상품정보 추출 → 가격/마진 계산 → 구글시트 입력** + 검수 화면.
(웹서치·규제표현분리·카피생성은 2차)

---

## 1. 폴더 구조

기존 OS 구조에 맞춰 `app/sourcing/` 패키지 신설. 에이전트는 `app/sourcing/agents/`에 모은다.

```
app/
├── routers/
│   └── sourcing.py                  # /sourcing/* 라우트 (업로드·검수·시트동기화)
├── sourcing/                        # ★ 신규 패키지
│   ├── __init__.py
│   ├── pipeline.py                  # 오케스트레이터 (단계 순차 실행 + 상태기록)
│   ├── pricing.py                   # 마진/정산 계산 (순수 Python, 테스트 가능)
│   ├── schemas.py                   # structured outputs용 JSON Schema 모음
│   ├── sheets_sync.py               # Google Sheets API 연동
│   ├── compliance_rules.py          # 규제 카테고리 표현 규칙(상수 + 프롬프트)
│   └── agents/
│       ├── __init__.py
│       ├── extractor.py             # ExtractorAgent  (1·2단계)
│       ├── researcher.py            # ResearchAgent   (5단계, 웹서치)
│       ├── compliance.py            # ComplianceAgent (6단계)
│       └── copywriter.py            # CopywriterAgent (9단계)
├── prompts/
│   ├── sourcing_extract.md          # 추출 프롬프트
│   ├── sourcing_research.md         # 웹서치 보강 프롬프트
│   ├── sourcing_compliance.md       # 규제표현 분리 프롬프트
│   └── sourcing_copy.md             # 카피 생성 프롬프트
├── models/
│   └── sourcing_batch.py            # SourcingBatch (업로드 1건=배치 추적)
├── templates/sourcing/
│   ├── upload.html                  # 파일 업로드 + 진행상황
│   ├── review.html                  # 추출결과 검수 테이블 (htmx 인라인 편집)
│   └── batch_detail.html            # 배치 상세 + 시트동기화 버튼
└── static/uploads/sourcing/         # 업로드 원본 보관
```

- 라우터 등록: `app/main.py`의 import 블록 + `app.include_router(...)` + `_setup_filters()` 루프에 `sourcing` 추가 (메모리 규칙).
- Google 자격증명: `.env`에 `GOOGLE_SA_JSON`(서비스계정 키 경로/JSON), `SOURCING_SHEET_ID`.

---

## 2. 데이터베이스 테이블 구조

### 2-1. `Product` 확장 (기존 컬럼 최대 재사용 — 신규 5개만 추가)

기존 컬럼으로 이미 커버됨: `name`(상품명), `brand`(브랜드명), `set_options`(옵션),
`consumer_price`(소비자가), `supplier_price`(공급가, 내부), `groupbuy_price`(공구가),
`shipping_cost`/`shipping_type`(배송비), `dispatch_days`(출고마감), `seller_commission_rate`,
`vendor_commission_rate`(내부 마진), `discount_rate`, `key_benefits`, `content_angle`,
`review_status`(승인 워크플로우), `missing_fields`, `is_complete`.

추가 컬럼 (nullable, 안전 마이그레이션):

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `as_info` | Text | A/S 정보 (보증기간·교환반품·연락처) |
| `cert_info` | JSON | 인증정보 list[{type, number, authority}] (KC·식약처 등) |
| `margin_rate` | Float | (공구가-공급가)/공구가 자동계산 캐시값 |
| `compliance` | JSON | 규제표현 분리 결과 {category, safe[], risky[], notes} |
| `generated_copy` | JSON | {card_news, reels_hook, detail_summary, seller_message} |
| `sourcing_batch_id` | String(36) FK | 소속 배치 (nullable) |

> 정산금은 셀러 수수료율 변수라 컬럼으로 고정하지 않고 `pricing.py`에서 on-the-fly 계산.

### 2-2. `SourcingBatch` (신규) — 업로드 1건 추적

```python
class SourcingBatch(Base):
    __tablename__ = "sourcing_batches"
    id              = String(36) PK (uuid)
    company_id      = Integer FK(companies.id) default 1, index
    source_filename = String(300)              # 원본 파일명
    source_path     = String(500)              # static/uploads/sourcing/...
    file_type       = String(10)               # xlsx|pdf|csv
    status          = String(20) default "uploaded"
                      # uploaded → extracting → extracted → priced
                      #   → researched → review → synced → done | failed
    total_rows      = Integer default 0
    extracted_count = Integer default 0
    error_count     = Integer default 0
    error_log       = JSON                     # list[{row, message}]
    sheet_url       = Text nullable            # 동기화된 구글시트 URL
    synced_at       = DateTime nullable
    created_by      = Integer FK(users.id) nullable
    created_at      = DateTime default utcnow
    updated_at      = DateTime onupdate utcnow
    # products = relationship → Product.sourcing_batch_id
```

마이그레이션: `migrate.py`에 `add_column_if_missing`/`create_all` 패턴으로 추가 (재실행 안전).

---

## 3. 구글 시트 컬럼 구조

시트 1행 = 헤더, 2행~ = 상품. 내부전용 컬럼(공급가·벤더마진)은 **별도 탭** 또는 색상 구분.
`SOURCING_SHEET_ID` 문서에 `상품마스터` / `정산시뮬` 두 탭.

### 탭 1 — `상품마스터`

| 열 | 헤더 | 출처 필드 |
|---|---|---|
| A | 배치ID | SourcingBatch.id |
| B | 상품명 | name |
| C | 브랜드 | brand |
| D | 카테고리 | category |
| E | 옵션 | set_options(요약 문자열) |
| F | 소비자가 | consumer_price |
| G | 공급가(내부) | supplier_price |
| H | 공구가 | groupbuy_price |
| I | 할인율 | discount_rate |
| J | **마진율** | margin_rate (계산) |
| K | 배송비 | shipping_cost |
| L | 출고마감 | dispatch_days |
| M | A/S | as_info |
| N | 인증정보 | cert_info(요약) |
| O | 셀러수수료율 | seller_commission_rate |
| P | 핵심혜택 | key_benefits(요약) |
| Q | 경쟁상품(웹서치) | research.competitors |
| R | 후기키워드 | research.review_keywords |
| S | 주의사항 | research.cautions |
| T | 규제표현-안전 | compliance.safe |
| U | 규제표현-위험 | compliance.risky |
| V | 카드뉴스문구 | generated_copy.card_news |
| W | 릴스후킹 | generated_copy.reels_hook |
| X | 상세요약 | generated_copy.detail_summary |
| Y | 셀러전달문구 | generated_copy.seller_message |
| Z | 검수상태 | review_status |
| AA | 검토자메모 | internal_notes |

### 탭 2 — `정산시뮬` (셀러 수수료율별 예상 정산금)

| 열 | 헤더 |
|---|---|
| A | 상품명 |
| B | 공구가 |
| C | 공급가 |
| D | 마진(원) = 공구가-공급가 |
| E~I | 수수료율 10/12/15/18/20%별 셀러정산금·벤더정산금 (pricing.py 계산) |

> MVP는 `상품마스터` 탭의 A~O,Z열(추출+가격) + `정산시뮬`까지. Q~Y(웹서치·규제·카피)는 2차.

---

## 4. API 라우트 구조 (`app/routers/sourcing.py`, prefix `/sourcing`)

| 메서드 | 경로 | 설명 | 단계 |
|---|---|---|---|
| GET | `/sourcing` | 배치 목록 + 새 업로드 진입 | — |
| GET | `/sourcing/upload` | 업로드 폼 | 1 |
| POST | `/sourcing/upload` | 파일 저장 → SourcingBatch 생성 → 추출 트리거 → PRG redirect | 1·2 |
| GET | `/sourcing/{batch_id}` | 배치 상세 + 추출 상품 테이블 | — |
| GET | `/sourcing/{batch_id}/review` | 검수 화면 (htmx 인라인 편집) | 8 |
| POST | `/sourcing/{batch_id}/extract` | (재)추출 실행 | 2 |
| POST | `/sourcing/{batch_id}/price` | 가격/마진/정산 재계산 | 3·4 |
| POST | `/sourcing/{batch_id}/enrich` | 웹서치 보강 (2차) | 5 |
| POST | `/sourcing/{batch_id}/compliance` | 규제표현 분리 (2차) | 6 |
| POST | `/sourcing/{batch_id}/copy` | 카피 생성 (2차) | 9 |
| POST | `/sourcing/product/{pid}/approve` | 개별 상품 승인 (review_status→approved) | 8 |
| POST | `/sourcing/{batch_id}/sync-sheet` | 구글시트 동기화 | 7 |
| GET | `/sourcing/{batch_id}/status` | 진행상황 폴링(htmx) JSON | — |

- 인증: 기존 `get_current_user` 의존성 재사용 (JWT 쿠키).
- 무거운 단계(추출/웹서치)는 동기 처리 시 타임아웃 우려 → MVP는 행 수 제한(예: ≤50) 동기,
  이후 BackgroundTasks 또는 기존 PipelineJob 패턴으로 비동기 전환.

---

## 5. 에이전트 역할 정의서

모든 AI 에이전트는 **강화된 중앙 `ClaudeClient`**를 사용한다. JSON이 필요한 에이전트는
`complete_json(system, user, schema=SCHEMA)`로 **structured outputs**를 써서 구조를 보장한다.
(스키마는 `app/sourcing/schemas.py`에 정의)

### 5-1. ExtractorAgent (`agents/extractor.py`) — 1·2단계

- **입력**: 업로드 엑셀 행(또는 PDF 텍스트), 원본 컬럼명 자유형
- **역할**: 자유형 데이터에서 표준 필드(상품명·브랜드·옵션·소비자가·공급가·공구가·배송비·출고마감·A/S·인증정보) 추출·정규화
- **출력 스키마**: `EXTRACT_SCHEMA` → Product 필드로 매핑, 누락은 `missing_fields`에 기록
- **모델 호출**: `complete_json(schema=EXTRACT_SCHEMA)` (엑셀은 행 배치, PDF는 페이지 텍스트)
- **비고**: 기존 `prompts/product_import_fill.md` 로직 계승·강화

### 5-2. PricingAgent → 사실은 순수 함수 (`pricing.py`) — 3·4단계

- **AI 미사용** (결정적 계산이라 LLM 불필요·정확).
- `margin_rate = (groupbuy_price - supplier_price) / groupbuy_price`
- `settlement(commission_rate)`: 셀러정산 = 공구가×(1-수수료) 등 정책에 맞춘 함수
- 수수료율 시나리오 배열(10~20%) 일괄 계산 → `정산시뮬` 탭/검수화면 표시
- **테스트 우선**: 단위테스트로 경계값 검증

### 5-3. ResearchAgent (`agents/researcher.py`) — 5단계 (2차)

- **역할**: 상품명+브랜드로 웹서치 → 공식정보/경쟁상품/후기키워드/장점/주의사항 보강
- **도구**: Claude **web_search 서버툴**(`web_search_20260209`) — 결과를 structured output으로 정리
- **출력**: `RESEARCH_SCHEMA` {official_info, competitors[], review_keywords[], pros[], cautions[], sources[]}
- **비고**: 인용(sources) 보존 → 검수자가 출처 확인 가능

### 5-4. ComplianceAgent (`agents/compliance.py`) — 6단계 (2차)

- **역할**: 카테고리가 의료기기/식품/건기식/화장품이면 광고 **위험표현 vs 사용가능표현** 분리
- **입력**: 카테고리 + 추출/웹서치 텍스트 + `compliance_rules.py`의 카테고리별 금지/주의 규칙
- **출력**: `COMPLIANCE_SCHEMA` {category, safe[], risky[{phrase, reason, alt}], disclaimer}
- **비고**: 규칙은 코드 상수로 관리(법령 업데이트 대응). LLM은 매칭·치환 제안만, 최종은 사람 승인.

### 5-5. CopywriterAgent (`agents/copywriter.py`) — 9단계 (2차)

- **역할**: 상품별 카드뉴스 문구·릴스 후킹·상세페이지 요약·셀러 전달 문구 생성
- **입력**: 정규화 상품정보 + 웹서치 보강 + compliance.safe(안전표현만 사용)
- **출력**: `COPY_SCHEMA` {card_news, reels_hook, detail_summary, seller_message}
- **가드**: compliance.risky 표현은 사용 금지(프롬프트+사후 필터)

### 5-6. Orchestrator (`pipeline.py`)

- 단계 순차 실행 + `SourcingBatch.status` 갱신 + 행별 에러 격리(`error_log`).
- 단계 재실행 가능(idempotent). 실패 행은 건너뛰고 카운트.
- 8단계(사람 승인)는 자동 통과 금지 — `review_status`가 `approved`된 상품만 시트 `done` 처리.

### 5-7. ReviewGate (사람 승인) — 8단계

- 신규 AI 단계는 모두 `review_status`를 `structured`/`reviewed`까지만 올리고,
  **`approved`는 사람이 검수화면에서 클릭**해야 전환 (기존 워크플로우 그대로).
- 자비스 결재함(jarvis)과 연동 여지: 승인 대기 건을 DecisionItem으로 푸시 가능(후속).

---

## 6. 구현 순서 (MVP → 확장)

1. **DB**: Product 5컬럼 + SourcingBatch + migrate.py (재실행 안전)
2. **pricing.py** + 단위테스트 (마진·정산)
3. **ExtractorAgent** + `EXTRACT_SCHEMA` + sourcing_extract.md
4. **sheets_sync.py** (서비스계정 인증 → 상품마스터/정산시뮬 탭 쓰기)
5. **routers/sourcing.py** + 업로드/검수 템플릿 + main.py 등록(+_setup_filters)
6. 로컬 검증(`uv run uvicorn ... --port 8000`) → ec2-deploy
7. (2차) ResearchAgent / ComplianceAgent / CopywriterAgent + 해당 라우트·시트열

---

## 7. 미해결/확인 필요

- **Google Sheets 자격증명**: 서비스계정 키 발급 + 대상 시트 공유 필요 (사장님 작업)
- **A/S·인증정보 원본**: 엑셀에 컬럼이 있는지, 없으면 웹서치/수기 보강인지
- **정산 공식 정확화**: 셀러정산 = 공구가×(1-수수료)인지, 마진 배분 방식 확정 필요
- **PDF 추출**: MVP는 엑셀만, PDF는 2차 (pypdf/pdfplumber 텍스트화 후 ExtractorAgent)
