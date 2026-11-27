# HS-2 Postgres 구현 인계

- 상태: **complete — 코드와 실제 임시 Postgres 계약 검사**. 실제 Supabase 운영 연결/이관/배포 수용은 미실행이다.
- 기준: master `3525226`; [계획](../../superpowers/plans/2026-11-25-hosted-runtime.md), [DB 계약](../../managed-pc/POSTGRES_STORE.md).

## 제공 interface

`StorageConfig.from_settings()`와 `open_store()`가 명시 backend를 선택한다. hosted 기본은 Postgres, local은 SQLite다. 원격 접속 실패를 SQLite로 우회하지 않는다. 기존 Store/도메인 interface를 유지하며 qmark, INSERT OR IGNORE, JSON scalar, rowid 순서를 bounded adapter로 처리한다. statement/batch savepoint와 rollback 후 기존 conflict 예외 경계를 유지한다. writer는 advisory lock, 독립 read는 readonly repeatable-read snapshot이다.

`store/sql/hosted_v1.sql`/JSON은 61개 migration 단계의 최종 schema를 재현한 초기 snapshot이다. 표132/index35/FK193/trigger114와 deferred package/source 관계를 보존한다. source/rendered/guard catalog hash를 대조해 guard 비활성화·함수 변조·snapshot drift를 거절한다. 생성은 `python -B tools/export_postgres_schema.py --check`로 확인한다. 기존 운영 schema를 지우거나 덮어쓰는 자동 migration은 없다.

검토에서 실제 queued recording의 Boolean JSON guard, NULL parameter typing, reconciliation executemany, video의 trailing rowid unpack 결함을 재현·수정했다. 단순 표 생성 통과를 도메인 성공으로 대신하지 않았다.

## 검증

2026-11-27:

```text
python -B -m pytest tests/integration/test_hs2_postgres.py tests/integration/test_hs2_domain_postgres.py tests/integration/test_hs2_schema.py tests/integration/test_hs2_worker_postgres.py tests/integration/test_hosted_portability.py -q -p no:cacheprovider --tb=short
29 passed in 60.82s
```

공식 PostgreSQL 17.12 portable binary를 `.review-work` 안의 loopback fixture로만 실행했다. `AIQA_TEST_POSTGRES_URL`은 그 임시 서버를 가리키고 검사별 고유 `aiqa_test_*` schema만 생성/제거했다. 실제 사용자 DB는 건드리지 않았다. 프로젝트/케이스/버전/package/source, 검토/승인 pointer의 원자성, deferred COMMIT 실패, writer 경합/rollback, readonly snapshot, queue claim/evidence receipt, guard 변조와 배치 reconciliation을 확인했다. 마지막 portability 검사는 Windows registry/DLL을 숨긴 별도 프로세스이며 실제 Linux 검사가 아니다. 로그 `.review-work/hosted-runtime/final-postgres.log`.

별도 추가 검사 `test_first_admin_oidc_and_browser_receipt_survive_restart_on_postgres`: **1 passed in6.85s**. 실제 앱 factory의 request-owned connection 재사용을 유지한 상태에서 첫 admin bootstrap 멱등성→모의 OIDC→dataset 저장→새 앱 instance의 같은 receipt 재사용→다른 body409까지 확인했다. 위29개 실행과 합쳐 새 전체 실행 수로 표기하지 않는다.

출하 전 추가 검사에서 Windows `core.autocrlf=true`의 새 Git checkout이 SQL bytes를 바꿔 manifest hash를 깨는 RED를 재현했다. `.gitattributes`에서 snapshot SQL/JSON과 worker shell만 LF로 고정했고 오프라인 schema 검사 **8 passed in1.83s**를 확인했다. hash 검증을 완화하지 않았다. 이 묶음은 앞29개와 별도이며 새 checkout 검사1개를 추가로 포함한다.

## 제약과 다음

Supabase **직접 또는 session pooler**만 지원한다. session 설정을 보존하지 않는 transaction pooler는 지원하지 않는다. 원격 TLS/role/네트워크와 실제 Linux/Fly는 HS-4에서 확인한다. 기존 SQLite backup/restore는 hosted에서 명시 거절하며 Postgres+private object 운영 backup은 별도 준비한다. 기존 로컬 데이터 이관은 이 카드 범위가 아니다. 원격 파일은 [HS-3](HS-3.md)이다.
