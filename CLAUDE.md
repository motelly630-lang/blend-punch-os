# blend-punch-os

공동구매 운영 B2B OS. FastAPI + PostgreSQL(RDS) + Jinja2 + Tailwind(정적빌드) + htmx + Alpine.js.
운영: `os.blendpunch.com` (EC2 + Cloudflare).

> **이 파일은 지도(map)입니다.** 사업 배경·업무 흐름·모델 필드 상세는
> `BLENDPUNCH_OS_SECOND_BRAIN.md`(572줄)에 있으니 **필요할 때만** 열어보세요.

## 실행

```bash
uv run uvicorn app.main:app --reload --port 8000   # 로컬 (EC2는 .venv/bin/python)
npm run build:css                                  # 템플릿에 새 Tailwind 클래스 추가 시 필수
uv run python migrate.py                           # DB 마이그레이션 (재실행 안전)
```

## 코드 지도 — 기능 → 파일

기능 하나는 보통 **라우터 + 모델 + 템플릿 폴더** 3점 세트입니다. 이름이 전부 동일합니다:

```
app/routers/<name>.py  ↔  app/models/<name>.py  ↔  app/templates/<name>/
```

예: CS 모듈 = `app/routers/cs.py` + `app/models/cs.py` + `app/templates/cs/` + `app/cs/`(헬퍼).

| URL prefix | 라우터 | 비고 |
|---|---|---|
| `/products` `/brands` `/influencers` `/campaigns` | 동명 라우터 | 핵심 마스터 4종 |
| `/products/import` 등 | `import_*.py` | Excel 임포트 (4종) |
| `/orders` `/sales-pages` `/shop` `/sellers` | 동명 라우터 | 커머스 |
| `/settlements` `/transactions` | 동명 라우터 | 정산·손익 |
| `/cs` / `/portal/cs` | `cs.py`(1278줄) / `portal_cs.py` | 내부 CS / 협력사 CS |
| `/partners` `/portal` | `partners.py` / `portal.py` | 협력사 모듈 / 외부 포털 |
| `/crm` `/outreach` `/proposals` `/applications` | 동명 라우터 | 영업 |
| `/trends` | `trends.py` + `trend_engine.py` | prefix 공유 (둘 다 확인) |
| `/sourcing` | `sourcing.py` + `app/sourcing/` | 소싱 에이전트 |
| `/automation` | `automation.py` | 자동화·트리거 |
| `/settings` | `backup.py` `business_info.py` `feature_flags.py` | **prefix 3개 공유** |
| `/settings/sheets` | `sheets.py` + `app/integrations/sheets_*.py` | 통합 스프레드시트 양방향 연동 |
| `/catalog` `/companies` `/manuals` `/emails` `/attendance` `/inquiries` | 동명 라우터 | 부가 |
| `/public` `/api/v1` | `public.py` / `app/api/public_v1.py` | 외부 공개 |

**라우터 외 영역**

- `app/api/ai_*.py` — AI 엔드포인트 (제품/제안서/DM/추천/이미지/챗 등 10종)
- `app/ai/` — AI 실행 로직. **클라이언트는 `app/ai/client.py` 중앙 사용**
- `app/agents/` — 5단계 파이프라인(`product_pipeline.py`, `brand_pipeline.py`, `decision_engine.py`, `runner.py`)
- `app/services/` — 알림·이메일·이미지·인스타·시트자동동기화 등 외부 연동 로직
- `app/auth/` — `dependencies.py`(권한 의존성), `tenant.py`(멀티테넌시)

## 반드시 지킬 규칙

1. **새 라우터 추가 시** `app/main.py`의 `include_router` + `_setup_filters()` 루프에 **둘 다** 등록.
2. **Tailwind 정적빌드** — 템플릿에 새 클래스를 쓰면 `npm run build:css` 없이는 스타일이 적용되지 않음. CDN 없음.
3. **AI 키** — `settings.anthropic_api_key` 사용. `os.getenv` 금지.
4. **인증** — JWT 쿠키 8시간, bcrypt 직접 호출 (passlib 아님).
5. **Alpine.js** — 중첩 `x-data` 금지. hidden input의 `:value`를 신뢰하지 말고 `@submit` 핸들러에서 값 구성.
6. **모든 폼은 POST-Redirect-GET.**
7. **DB 분리** — 운영 = `blendpunch_dev`, 로컬 = `blendpunch` (같은 RDS 인스턴스, 다른 데이터). 마이그레이션 실행 시 대상 확인.

## 배포

`ec2-deploy` 스킬 사용. EC2 IP가 자주 바뀌므로 **항상 DNS로 현재 IP를 먼저 확인**.
SSH `ubuntu@`, key `~/.ssh/blendpunch-key.pem`, 앱 경로 `/home/ubuntu/blend-punch-os/`.
