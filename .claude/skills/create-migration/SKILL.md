---
name: create-migration
description: blend-punch-os 의 DB 구조 변경(컬럼 추가·새 테이블·인덱스·데이터 정규화)을 모델 수정 → migrate.py 추가 → 로컬 실행 → 대상 DB 확인 → 결과 조회 순서로 안전하게 한다. 사용자가 /create-migration 으로 부를 때만 사용.
disable-model-invocation: true
---

# DB 구조 변경 (create-migration)

이 프로젝트엔 Alembic 이 없다. **`migrate.py` 하나가 전부**이고, 재실행해도 안전해야 한다.
운영 DB 이름이 `blendpunch_dev`(이름과 달리 운영), 로컬이 `blendpunch` 라 대상 혼동이 가장 큰 위험이다.

## 0. 먼저 알아둘 함정
- `_add_column()` 은 **모든 예외를 삼킨다.** "이미 있음"뿐 아니라 오타·잘못된 타입도 조용히 건너뛴다.
  → 실행 로그의 `+ table.col` 줄과 **4단계 조회**로만 성공을 판단한다.
- DB 는 **PostgreSQL** 이다. 타입은 Postgres 문법으로: `VARCHAR(n)` `TEXT` `INTEGER` `FLOAT` `BOOLEAN`
  `JSON` `TIMESTAMP`(❌ `DATETIME`). 기본값은 `DEFAULT ...`.
- 새 **테이블**은 `ALTER` 가 아니라 `init_db()` 의 `create_all` 로 생긴다 → 모델 모듈을
  `app/database.py` `init_db()` import 목록에 추가해야 한다 (빠지면 테이블이 안 생긴다).
- 테넌트 테이블이면 `company_id`(필요 시 `partner_id`) 컬럼 + 인덱스 — [RG-002] 참조.
- 제품 코드값(`status`/`visibility_status`)을 건드리면 [RG-003] 을 먼저 읽는다.

## 1. 계획을 쓰고 승인받기
```
무엇을 : 테이블.컬럼 타입 기본값 / 새 테이블 / 인덱스 / 데이터 UPDATE
왜     : 어떤 기능에 필요한가
영향   : 기존 데이터에 무슨 일이 생기나 (NULL 로 채워짐? UPDATE 로 바뀌는 행 수?)
되돌리기: 컬럼 추가는 남아도 무해. 데이터 UPDATE 는 되돌릴 수 없음 → 범위를 먼저 SELECT 로 센다
```
**데이터 UPDATE/DELETE 가 들어가면 반드시 승인받는다.** 컬럼·인덱스 추가만이면 알리고 진행.

## 2. 코드 수정
1. 모델: `app/models/<name>.py` 에 `Column(...)` 추가 (migrate.py 의 타입과 일치시킨다).
2. `migrate.py` 의 `migrate()` 안, **맨 아래 해당 섹션**에 추가. 기존 줄은 고치지 않는다.
   ```python
   # --- <테이블> (<기능 이름>, YYYY-MM-DD) ---
   _add_column(conn, "<테이블>", "<컬럼> <타입> [DEFAULT ...]")
   conn.execute(text("CREATE INDEX IF NOT EXISTS idx_<테이블>_<컬럼> ON <테이블>(<컬럼>)")); conn.commit()
   ```
   - 데이터 UPDATE 는 `WHERE` 로 재실행해도 결과가 같게 (이미 바뀐 행은 안 건드리게) 쓴다.
3. 새 테이블이면 `init_db()` import 목록에 모듈 추가.

## 3. 로컬 실행 — 대상 DB 확인 후
```bash
# 1) 대상 DB 이름 확인 (비밀번호는 출력하지 않는다)
uv run python -c "from app.database import engine; print(engine.url.get_backend_name(), engine.url.database)"
#    → 반드시 'postgresql blendpunch' 여야 한다. blendpunch_dev 면 즉시 중단하고 .env 를 확인.
# 2) 실행
uv run python migrate.py 2>&1 | tail -30
```
Windows 에서는 위 명령을 `wsl -- bash -lc "cd /home/blendpunch/blend-punch-os && ..."` 로 감싼다.
로컬 DB 는 두 머신이 공유한다 — 다른 머신에서 같은 작업 중이 아닌지 확인.

## 4. 결과 확인 (os-db-local MCP, 읽기 전용)
```sql
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_schema='public' AND table_name='<테이블>' AND column_name IN ('<컬럼>');
```
- 인덱스: `SELECT indexname FROM pg_indexes WHERE tablename='<테이블>';`
- 데이터 UPDATE: 대상 행 수를 전후로 센다.
- 로그에 `+` 줄이 없고 조회에도 없으면 **조용히 실패한 것** — 타입/문법을 다시 본다.
- `migrate.py` 를 한 번 더 실행해 에러 없이 끝나는지(재실행 안전) 확인.

## 5. 앱 확인
- 서버를 켜서(`uv run uvicorn app.main:app --port 8000`) 해당 화면이 500 없이 열리는지.
- 관련 테스트가 있으면 실행 (`/gen-test` 로 추가 가능).

## 6. 운영 반영은 여기서 하지 않는다
운영(`blendpunch_dev`) 마이그레이션은 **배포와 함께 `ec2-deploy` 스킬**로, 대표님 승인 후에만.
보고할 때 "운영 반영 시 migrate.py 실행 필요"를 명시하고, 커밋 메시지에도 적는다.
운영 반영 뒤에는 os-db-prod MCP 로 4단계와 같은 조회를 해서 확인한다.

## 보고
```
변경  : 테이블.컬럼 (타입) / 인덱스 / UPDATE n행
로컬  : 대상 DB 확인 결과, migrate 로그 요약, 조회 결과, 재실행 결과
남은 것: 운영 반영 필요 여부 (배포 때 migrate.py)
```
