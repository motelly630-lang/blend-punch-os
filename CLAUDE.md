# blend-punch-os

공동구매 운영 B2B OS. FastAPI + PostgreSQL(RDS) + Jinja2 + Tailwind(정적빌드) + htmx + Alpine.js.
운영: `os.blendpunch.com` (EC2 + Cloudflare).

> **이 파일은 지도(map)입니다.** 사업 배경·업무 흐름·모델 필드 상세는
> `BLENDPUNCH_OS_SECOND_BRAIN.md`(572줄)에 있으니 **필요할 때만** 열어보세요.

## 실행환경 — 머신 2대

| 머신 | 저장소 위치 | 명령 실행 |
|---|---|---|
| **Windows 데스크톱** | WSL `/home/blendpunch/blend-punch-os` (UNC 로 열림) | 아래 규칙대로 **전부 `wsl -- bash -lc`** |
| **macOS 맥북** | `~/blend-punch-os` | 터미널에서 **그대로** 실행 (`uv run …`, `npm …`, `git …`). `wsl` 없음 |

**맥북이면 이 절의 나머지(Windows 전용 규칙)는 건너뛴다.** 두 머신이 같은 로컬 DB(`blendpunch`)를
공유하므로 한쪽에서 바꾼 데이터는 다른 쪽에도 보인다. 작업 전 `git pull`, 끝나면 commit·push —
두 머신에서 동시에 같은 작업을 하지 않는다. 비밀파일(`.env`·`google_sa.json`)은 각 머신에 따로 있다.

### Windows — 편집은 Windows, 실행은 WSL

이 저장소는 **WSL Ubuntu(`/home/blendpunch/blend-punch-os`)에서만 실행**된다.
Claude Code는 Windows PowerShell에서 돌고 프로젝트를 UNC(`\\wsl$\Ubuntu\...`)로 연다.

| 하는 일 | 어디서 |
|---|---|
| 파일 읽기·검색·수정 (Read/Edit/Grep/Glob) | Windows에서 그대로 — UNC 정상 동작 |
| **실행·빌드·테스트·git — 전부** | `wsl -- bash -lc "<명령>"` |

**Windows에서 직접 실행 금지 (프로젝트 명령 전부):** `uv` · `python` · `pytest` · `npm` · `git`

- `uv run`을 Windows에서 실행하면 Linux `.venv`(python3.12)가 Windows용으로 **재생성되어
  WSL과 EC2 실행환경이 함께 깨진다.** 가장 위험한 명령.
- `npm`은 `node_modules/.bin`에 Linux 심볼릭 링크만 있어 실패하고, Windows에서 `npm install`을
  돌리면 Linux `node_modules`가 깨진다.
- `git`은 Windows에 **설치되어 있지 않다.** git 상태·diff·커밋은 전부 `wsl` 경유로만 확인된다.
- cwd가 UNC라 cmd.exe 기반 도구는 조용히 `C:\Windows`에서 돈다.

**기존 Linux `.venv` / `node_modules`는 Windows용으로 재생성하지 않는다.**

## 실행

```bash
# Windows Claude Code에서는 아래를 그대로 wsl 로 감싼다
wsl -- bash -lc "cd /home/blendpunch/blend-punch-os && uv run uvicorn app.main:app --reload --port 8000"
wsl -- bash -lc "cd /home/blendpunch/blend-punch-os && npm run build:css"
wsl -- bash -lc "cd /home/blendpunch/blend-punch-os && uv run python migrate.py"
wsl -- bash -lc "cd /home/blendpunch/blend-punch-os && git status --short"

# WSL 셸 / macOS 터미널에서 직접 작업할 때 (EC2는 .venv/bin/python)
uv run uvicorn app.main:app --reload --port 8000   # 로컬
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
8. **실행 명령은 `wsl -- bash -lc "..."`** — 위 「실행환경」 참조. Windows에서 `uv`/`npm`/`git`을 직접 쓰지 않는다.

## Claude 설정 (`.claude/`)

Windows·WSL 양쪽에서 같이 쓰는 **프로젝트 공용 설정**. 개인 설정·인증정보는 여기에 넣지 않는다.

| 경로 | 역할 |
|---|---|
| `.claude/settings.json` | 민감파일 Read/Edit deny + DB MCP의 mutation·DDL deny 82건 + 훅 등록 |
| `.claude/hooks/os-build-css.sh` | 템플릿 수정 시 Tailwind 재빌드 (규칙 2 자동화) |
| `.claude/hooks/os-router-parity.sh` → `.py` | 라우터 3점세트 정합성 검사 (규칙 1 자동화) |
| `.claude/hooks/os-mem-load.sh` → `.py` | SessionStart에 프로젝트 메모리 INDEX + 현재 상태 주입 |
| `.claude/hooks/os-mem-route.py` | UserPromptSubmit에 요청 관련 메모리 **포인터만** 주입 (어휘 일치) |
| `.claude/hooks/os-mem-journal.py` | PostToolUse(Write\|Edit)에 수정 파일을 기계적으로만 저널링 |
| `.claude/hooks/os-mem-flush.py` | SessionEnd·PreCompact에 state 확정 (SessionEnd는 1.5초 예산) |
| `.claude/hooks/os-hook.sh` | 훅 파이썬을 WSL python3으로 실행시키는 공용 래퍼 |
| `.claude/lib/osmem.py` | 메모리·상태 공유 라이브러리 (python3 stdlib만). UNC→POSIX 정규화 포함 |
| `.claude/memory/` | **프로젝트 메모리** (커밋 대상). 아래 「프로젝트 메모리」 참조 |
| `.claude/state/` | 머신 로컬 작업 상태 (gitignore). 세션 스크래치·저널·체크포인트 |
| `.claude/mcp/os-db-launch.sh` | `os-db-local`/`os-db-prod` MCP를 WSL 안에서 기동 (sslmode 부착) |
| `.claude/skills/`, `.claude/agents/` | `ec2-deploy` · `os-locate` · `os-ai-pipeline` · `os-mem` · `tenant-scope-reviewer` |

훅은 `bash .claude/hooks/<파일>` (**프로젝트 루트 기준 상대경로**)로 등록돼 있어 Windows·macOS 공용이다.
Windows 는 훅을 PowerShell 로 실행하고 `bash`(WSL 런처)가 UNC cwd 를 POSIX 로 바꿔 주므로 항상
WSL 안에서 돌며, macOS 는 `sh -c` 로 그대로 돈다. **Claude Code 는 반드시 프로젝트 루트에서 연다**
(하위 폴더에서 열면 훅을 못 찾는다). 훅이 받는 UNC 경로(`\\wsl$\...`)는 스크립트가 POSIX로 정규화한다.
정규화 동작 확인: `wsl -- bash -lc "cd /home/blendpunch/blend-punch-os && bash .claude/hooks/os-build-css.sh --selftest"`

**DB 자격증명은 WSL의 `~/.claude/os-db-ro.env`(읽기전용 롤)에만 있다. Windows 디스크로 복사하지 않는다.**

## 프로젝트 메모리 (`.claude/memory/`)

세션이 끊겨도 맥락이 남도록 **구조화된 것만** 파일로 저장한다. 대화를 요약해 쌓지 않는다.

```
INDEX.md     세션 시작 시 자동 주입되는 유일한 파일 (120줄 상한)
state.json   현재 작업 · task 체크리스트 · 체크포인트  ← 진행률의 유일한 근거
project/ decisions/ preferences/ workflows/ issues/ regression/
```

- 읽기·쓰기·검색은 `/os-mem` 스킬로 한다 (`save` `find <키워드>` `state` `update` `supersede`).
- 위험한 작업(마이그레이션·대규모 수정·배포) 전과 검증 통과 후에는 `/os-checkpoint create`.
- 세션 시작 시 INDEX + 현재 상태가 자동 주입되고, 요청마다 관련 메모리 **포인터**가 붙는다.
  포인터는 어휘 일치로 고르므로 놓칠 수 있다 — 그때는 `/os-mem find <키워드>`.
- **쓰기 전에 검색한다.** 같은 내용이 있으면 새로 만들지 말고 update/merge 한다.
- 결론이 뒤바뀌면 새 문서에 `supersedes:`, 옛 문서는 `status: superseded`. 삭제하지 않는다.
- **비밀값을 쓰지 않는다** — 커밋되는 디렉터리다. 위치만 가리킨다.
- **진행률은 `state.json`의 `tasks[]` done/total 로만 계산한다.** 체크리스트가 없으면 `—`.
- 수정 작업 전 `regression/` 에 관련 불변조건이 있는지 확인하고, 수정 후 그 조건을 확인한다.

확인: `wsl -- bash -lc "cd /home/blendpunch/blend-punch-os && python3 .claude/lib/osmem.py --selftest"`

## 배포

`ec2-deploy` 스킬 사용 (`.claude/skills/ec2-deploy/`). **반드시 WSL에서 실행** — SSH 키가 WSL 홈에 있어
Windows `ssh.exe`로는 권한 검사에서 막힌다. EC2 IP가 자주 바뀌므로 **항상 DNS로 현재 IP를 먼저 확인**.
SSH `ubuntu@`, key `~/.ssh/blendpunch-key.pem`, 앱 경로 `/home/ubuntu/blend-punch-os/`.
