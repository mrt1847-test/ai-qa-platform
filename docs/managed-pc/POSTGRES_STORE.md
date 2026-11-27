# Hosted Postgres 저장 계약

2026-11-27. HS-2의 관리 데이터 backend다. 실제 Supabase 연결·운영 배포 수용과 임시 Postgres 검사를 구분한다.

## 선택과 연결

- 로컬 기본값은 `AIQA_DATABASE_BACKEND=sqlite`다. 기존 SQLite migration/DPAPI/files 동작을 유지한다.
- hosted 기본값은 `postgres`다. `AIQA_DATABASE_URL`이 없거나 연결이 실패하면 SQLite 파일로 우회하지 않는다. 모의 hosted 테스트만 `AIQA_DATABASE_BACKEND=sqlite`를 명시한다. 실제 hosted entry preflight는 이를 거절한다.
- URL은 `postgresql://...` 또는 `postgres://...` 형식이며 원격은 TLS를 사용한다. 배포 preflight는 `sslmode=require`, `verify-ca`, `verify-full` 중 하나를 명시하도록 한다. 비밀번호의 예약 문자는 URL encoding이 필요하다. 값은 Fly 비밀에 넣고 DTO·로그·worker 환경에 보내지 않는다.
- **직접 연결 또는 session pooler**를 사용한다. adapter는 세션의 `search_path`, timeout과 트랜잭션 advisory lock을 사용하므로 transaction pooler는 지원하지 않는다. Supabase Connect에서 선택한 실제 host/port/user를 사용하고 transaction mode 주소를 복사하지 않는다. prepared statements는 비활성화한다.
- 관리 표는 public과 분리한 `aiqa` schema에 생성한다. PUBLIC schema 접근을 철회하며 브라우저/worker는 기존 인증 API로만 접근한다. Supabase Data API로 이 schema를 공개하지 않는다.

## schema와 불변성

`src/aiqa/store/sql/hosted_v1.sql`과 JSON manifest는 현재 SQLite 최종 schema에서 재현 가능하게 만든 **검토된 Postgres 초기 schema**다. 운영 시작 때 SQLite를 실행하거나 사용자 DB를 이관하지 않는다.

- 현재 기준 `0054_execution_exclusions`: 표132, 명시 index35, FK193, trigger114. PK/UNIQUE/CHECK와 deferred FK를 보존한다.
- deferred version/package/source 관계는 전체 쌍이 같은 트랜잭션에서 완성되어야 COMMIT된다. immutable version/manifest/증거·승인/영구 사실의 수정·삭제 금지를 유지한다.
- SQLite rowid에 의존하던 순서에는 trailing identity column을 사용한다. 모든 원래 열이 필요한 unpack 경로는 명시 열 목록으로 읽는다.
- JSON guard는 Postgres Boolean 조건과 호환되는 helper를 사용한다. 단순 표 생성만으로 녹화 접수 성공을 판정하지 않는다.
- 생성 SQL 파일의 해시, 원본 schema 해시, 설치된 guard/function catalog 해시를 기록한다. 코드의 생성 SQL 수정·guard 누락/비활성화·함수 변조를 확인하면 명시 migration이 필요하다는 오류로 거절한다.

현재 snapshot은 새 hosted DB 초기화용이다. 이미 존재하는 다른 Postgres schema를 자동 덮어쓰거나 지우지 않는다. 다음 schema 변경은 데이터 보존 migration을 별도로 작성해야 한다. mismatch를 고치기 위해 운영 표나 기록을 초기화하지 않는다.

재생성/드리프트 확인:

```text
python -B tools/export_postgres_schema.py --check
```

원본 migration을 의도적으로 변경했다면 같은 도구를 `--check` 없이 실행해 생성 diff를 검토한다. 이 작업은 메모리 fixture와 저장소 SQL 파일만 사용하며 운영 DB에 접속하지 않는다.

## 트랜잭션

- `Store.transaction()`은 기존 단일 writer 순서를 DB advisory lock으로 보존한다. claim/임대/승인 포인터/멱등 receipt가 서로 경합할 때 두 writer가 동시에 같은 상태를 승인하지 않는다.
- 실패 statement/batch는 내부 savepoint로 복구한 뒤 기존 도메인의 conflict 예외로 전달한다. deferred COMMIT 실패도 rollback 상태를 보존한다.
- `Store.read_transaction()`은 별도 repeatable-read readonly snapshot으로 writer fence를 잡지 않는다. 원격 근거 조회가 worker heartbeat를 막지 않는다. 기존 writer 안의 nested read는 savepoint로 같은 외부 트랜잭션을 따른다.
- 원격 upload/readback은 SQL writer 밖에서 수행한다. evidence ACK·APK 등록·export completed 기록은 검증이 끝난 뒤 짧은 트랜잭션에서 확정한다.

## 남은 운영 경계

실제 Supabase TLS/권한/네트워크 접속, 운영 backup/복원, 실제 Fly 재배포 수용은 별도다. 기존 전체-PC SQLite archive/restore를 Postgres backup으로 가장하지 않고 hosted에서는 명시 거절한다. Supabase DB와 private Storage의 운영 backup 정책은 함께 준비해야 한다.
