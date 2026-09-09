---
name: os-locate
description: blend-punch-os에서 수정할 파일과 라인을 최소 토큰으로 정확히 찾을 때 사용. 사용자가 "OO 기능 수정해", "OO 화면 고쳐", "OO 버그 잡아", "OO 추가해" 같이 특정 기능을 지목했고 어떤 파일을 건드려야 할지 아직 모를 때. 파일 전체 읽기·광범위 grep 대신 3단계 정밀 탐색으로 라인 번호까지 특정한다. 이미 대상 파일을 알고 있으면 사용하지 말 것.
version: 1.1.0
---

# 작업 대상 정밀 탐색 (blend-punch-os)

목적: **파일을 통째로 읽지 않고** 수정할 지점의 파일:라인을 특정한다.
`app/routers/cs.py`는 1278줄, `main.py`는 578줄이다. 전체 읽기는 대부분 낭비다.

## 도구 선택 (Windows Claude Code 기준)

탐색은 **Grep/Glob/Read 도구를 그대로 쓴다** — UNC 경로에서 정상 동작하고 빠르다.
아래 grep 예시를 셸로 돌려야 할 때만 `wsl -- bash -lc "<명령>"` 으로 감싼다.
(Windows PowerShell 에서 직접 실행하면 cwd 가 UNC 라 cmd 기반 도구가 엉뚱한 곳에서 돈다.)
프로젝트를 UNC 로 열어 두면 `wsl` 이 cwd 를 POSIX 로 변환하므로 **이미 프로젝트 루트에서 시작한다** —
`cd <절대경로>` 는 불필요하다. 다른 위치에서 돌려야 하면 `cd ~/blend-punch-os && ...` 를 앞에 붙인다.

## 원칙 4개

1. **라우터부터.** 기능은 거의 항상 URL에 대응한다. URL prefix → 라우터 파일은 `CLAUDE.md`의 코드 지도에 표로 있다. 지도를 먼저 보고, 없을 때만 grep.
2. **grep은 `-n`으로 라인만.** 내용 확인은 그 다음 단계에서 `Read`의 `offset`/`limit`으로.
3. **`Read` 전체 호출 금지** — 300줄 넘는 파일은 항상 offset/limit. 함수 하나 보려고 1200줄을 읽지 않는다.
4. **`app/`만 본다.** `node_modules/`, `__pycache__/`, `backups/`, `static/css/app.css`(빌드 산출물)는 항상 제외.

## 3단계 절차

### 1단계 — 진입점 찾기 (grep 1~2회)

UI 문구/버튼명을 알고 있을 때 (가장 강력):

```bash
grep -rn "화면에_보이는_문구" app/templates/ --include=*.html | head
```

URL을 알고 있을 때:

```bash
grep -rn '"/경로' app/routers/*.py | head          # prefix 확인
grep -n '@router\.\(get\|post\)' app/routers/<name>.py   # 엔드포인트 목록 + 라인
```

기능명만 알 때 — 라우터/모델/템플릿을 한 번에:

```bash
grep -rln "키워드" app/routers app/models app/services app/templates
```

### 2단계 — 범위 좁히기

핸들러 하나의 라인 범위를 얻는다:

```bash
grep -n "def \|@router" app/routers/<name>.py | sed -n '/찾는이름/,+3p'
```

템플릿이 어느 핸들러에서 렌더되는지:

```bash
grep -n "templates/<dir>/" app/routers/<name>.py
```

모델 필드만 필요하면 모델 파일은 짧으니(보통 30~80줄) 그냥 `Read`해도 된다.

### 3단계 — 부분 읽기

2단계에서 얻은 라인 번호로 `Read(file, offset=N-10, limit=80)`.
필요하면 확장하되, 처음부터 전체를 읽지 않는다.

## 자주 쓰는 지름길

| 상황 | 명령 |
|---|---|
| 3점 세트 전체 위치 | `ls app/routers/<n>.py app/models/<n>.py app/templates/<n>/` |
| 권한 체크 지점 | `grep -n "require_\|Depends(" app/routers/<n>.py \| head` |
| AI 프롬프트 위치 | `grep -rn "키워드" app/ai/ app/agents/ app/api/ai_*.py` |
| 시트 연동 필드 매핑 | `grep -n "키워드" app/integrations/sheets_*.py` |
| Jinja 필터 정의 | `grep -n "def format_" app/main.py` |
| 마이그레이션 추가 위치 | `grep -n "def \|ALTER\|ADD COLUMN" migrate.py \| tail -20` |

## 마지막에 확인할 것

- 템플릿에 **새 Tailwind 클래스**를 추가했다면 → 재빌드. `.claude/hooks/os-build-css.sh` 훅이 자동 처리하지만, 훅 메시지가 안 보이면 수동:
  `wsl -- bash -lc "npm run build:css"`
- **새 라우터**를 만들었다면 → `app/main.py`의 `include_router` + `_setup_filters()` 양쪽 등록
  (`.claude/hooks/os-router-parity.sh` 훅이 누락을 잡아준다)
- 배포는 `ec2-deploy` 스킬
