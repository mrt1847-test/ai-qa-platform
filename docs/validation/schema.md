# Schema 무결성

기준일: 2026-11-01. 검사 함수는 `validate_schema(store) -> SchemaIntegrityReport`다. 빈 DB를 끝까지 migrate한 뒤 재시작하고, `0008_long_term_facts`까지만 적용한 DB를 닫았다가 `0009_indexes`로 올린 결과가 같다.

`PRAGMA integrity_check`는 `ok`이고 `PRAGMA foreign_key_check` 위반은 0이다. `PRAGMA foreign_keys`는 1이다. `sqlite_master`의 FK 부모 표는 canonical migration 결과에 모두 있다.

필수 조회 인덱스는 현재 컬럼에 맞춘다.

| DATA_DESIGN §4 조회 | 현재 인덱스 |
|---|---|
| 케이스 목록 | `automation_cases_archive(project_id, archived_at, case_id)`. `updated_at` 컬럼은 없다 |
| version revision | `case_versions(case_id, revision)` UNIQUE |
| 녹화·manifest·materialization | 기존 UNIQUE `(project, case, recording)`, `(recording, revision)`, `(manifest)` |
| 이벤트·action 순번 | `attempt_events(project, attempt, local_seq)` UNIQUE, `actions` PK `(project, attempt, action_seq)` |
| REC/ITEM job 하나 | `jobs_recording_owner`, `jobs_case_run_owner` partial UNIQUE |
| queue | `jobs_queue(project_id, status, job_id)`. `created_at` 컬럼은 없다 |
| 자원 lease | `leases_resource(physical_key_id, generation) WHERE physical_key_id IS NOT NULL` |
| ITEM 기간·케이스 | `case_runs_requested`, `case_runs_case_requested`. `requested_at`을 쓴다. `verification_digest`와 `display_result`는 case_runs 컬럼이 아니라 이 인덱스에 넣지 않는다 |
| check 상태 | `check_results_status(project_id, check_id, status, attempt_id)` |
| 보호·승인·장기 seq | `artifact_protections_artifact`, `approval_events_case`, `item_finalizations_seq`, `item_lifecycle_seq`, `usage_adjustments_seq`. `project_commit_clock` PK와 `protection_releases(project, protection)` UNIQUE는 기존 제약이다 |

봉인된 case version의 `content_hash` UPDATE는 거부된다. nullable FK probe는 folder, suite version, trial case run, physical key에 대해 NULL 삽입은 통과하고 없는 부모 id는 거부한다. 두 번째 recording owner job도 거부한다. probe 행은 rollback되어 저장되지 않는다.

승인/GC 경합 서비스와 성능 gate는 이 문서의 통과 범위가 아니다. 새 표를 추가하면 이 검사를 다시 실행한다. `0010_resource_observations`와 `0011_case_proposals` 추가 뒤 빈 DB 재시작, `0008` upgrade, 행이 있는 DB에서 다시 통과했다.
