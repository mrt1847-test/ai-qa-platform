# J · 보관·장애·비용·최종 동선 · 상세 작업서 v0.7

제품 설계 v0.6 + [공통 보완 계약](CONTRACTS.md). **제품 미착수: 완료0 / 17**.
[전체 색인](README.md) · [인계 양식](HANDOFF.md) · [UI 추적](UI_COVERAGE.md) · [요구/시험 추적](COVERAGE.md).

문서 전체를 한 번에 구현하지 않는다. **카드 한 개**와 직접 선행 근거를 읽는다.
파일/DTO/시험은 향후 산출물이며 현재 존재·통과를 뜻하지 않는다.
검증 projection은 실제 관찰에서 계산한다. [검증 예시 해석](README.md#4-카드의-검증-예시를-해석하는-법)을 따른다.

| 작업 | 선행 | 결과 |
|---|---|---|
| [W26-01](#w26-01) | [W25-03](09-results-and-analytics.md#w25-03) | detail/파일 만료·최소 facts·tombstone |
| [W26-02](#w26-02) | [W26-01](10-retention-and-release-gates.md#w26-01) | active protection·manual pin·release·GC 경합 |
| [W26-03](#w26-03) | [W26-02](10-retention-and-release-gates.md#w26-02) | 공간·보호/삭제예정·보관 조작 UI |
| [W26-04](#w26-04) | [W26-03](10-retention-and-release-gates.md#w26-03) | 일관 SQLite·artifact manifest 백업 |
| [W26-05](#w26-05) | [W26-04](10-retention-and-release-gates.md#w26-04) | 별도 경로 복원·검사·재설정 UI |
| [W27-01](#w27-01) | [W26-05](10-retention-and-release-gates.md#w26-05) | 중복·늦은 event·finish·복구 경합 matrix |
| [W27-02](#w27-02) | [W27-01](10-retention-and-release-gates.md#w27-01) | worker/API/USB/browser/PC 장애 matrix |
| [W27-03](#w27-03) | [W27-02](10-retention-and-release-gates.md#w27-02) | 용량·정제·파일손상·보관 장애 matrix |
| [W27-04](#w27-04) | [W27-03](10-retention-and-release-gates.md#w27-03) | metadata 부하·query plan·문서 추적 재대조 |
| [W32-01](#w32-01) | [W27-04](10-retention-and-release-gates.md#w27-04) | role 비용·계측 누락·표본 산식 검증 |
| [W32-02](#w32-02) | [W32-01](10-retention-and-release-gates.md#w32-01) | 대표 30–50 TC·3 구성·실제 품질/비용 측정 |
| [W32-03](#w32-03) | [W32-02](10-retention-and-release-gates.md#w32-02) | 월 3000 workload 추정·release_label UI |
| [W28-01](#w28-01) | [W32-03](10-retention-and-release-gates.md#w32-03) | 전체 추적표·부분 구현·차단·후속 경계 audit |
| [W28-02](#w28-02) | [W28-01](10-retention-and-release-gates.md#w28-01) | UI01–06·14–16·공통 상태 실제 동선 |
| [W28-03](#w28-03) | [W28-02](10-retention-and-release-gates.md#w28-02) | UI07–13 승인→수행→분석/내보내기 동선 |
| [W28-04](#w28-04) | [W28-03](10-retention-and-release-gates.md#w28-03) | 양 플랫폼 정상·결함·변경·격리 합격 |
| [W28-05](#w28-05) | [W28-04](10-retention-and-release-gates.md#w28-04) | 사용 안내·제약·최종 체크와 다음 인계 |

<a id="w26-01"></a>

## W26-01 — detail/파일 만료·최소 facts·tombstone

- [ ] **W26-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W26-01.md`(완료 시 생성).
- **직접 선행:** [W25-03](09-results-and-analytics.md#w25-03)
- **읽기:** CONTRACTS C00 / C01 / C03 / C04 / C08 / C10 / C11 + 직접 선행 receipt의 interface/제약. 추적: R08, R12, R15, R31.
- **변경 파일:** `src/aiqa/store/retention.py`, `src/aiqa/store/artifacts.py`, `src/aiqa/api/artifacts.py`. 담당 시험: `tests/integration/test_w26.py`.
- **입출력 계약:** `plan_retention(input: RetentionPolicy, now: UtcInstant) -> RetentionPlan`
- **구현·화면·예외:** 최소 facts/승인/manifest/lineage/hash/ledger 장기유지·detail90 일·PNG/log30 일·ACKspool7 일·정제 debug24 시간을분리한다. 만료는 payload/파일만삭제하고 identity/hash·retentionevent/tombstone 을남긴다. 미 ACKspool 은 7 일자동폐기대상이아니다.
- **검증 전제:** day30/90 경계·payload 만료·유효 approval/미 ACK·원본 finalhash·지난통계를확인한다.
- **작업 순서:** `test_w26_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w26.py::test_w26_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "core_facts_deleted": 0,
  "expired_has_tombstone": True,
  "unacked_spool_deleted": 0,
  "old_stats_available": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w26-02"></a>

## W26-02 — active protection·manual pin·release·GC 경합

- [ ] **W26-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W26-02.md`(완료 시 생성).
- **직접 선행:** [W26-01](10-retention-and-release-gates.md#w26-01)
- **읽기:** CONTRACTS C00 / C01 / C03 / C04 / C08 / C10 / C11 + 직접 선행 receipt의 interface/제약. 추적: R08, R12, R15, R34.
- **변경 파일:** `src/aiqa/store/artifacts.py`, `src/aiqa/api/retention.py`. 담당 시험: `tests/integration/test_w26.py`.
- **입출력 계약:** `POST /api/v1/artifacts/{a}/retention-protections; POST /api/v1/retention-protections/{p}/release; claim_gc_artifact(now: UtcInstant) -> GcClaim | None`
- **구현·화면·예외:** 유효한과거 approval 의 script/plan/lock/mapping/source/trial 을 default 와무관하게보호한다. review30 일/연장·revoke90 일·manual/backup/buildpin 을 typedappend 로관리한다. ready→delete_pendingclaim 과 approve 재검사경합을짧은 transaction 으로처리하고 provenance 는보존한다. manual release API는 manual 보호만 해제한다. approval/review/backup/build 보호는 각 수명 API로만 해제하고 일반 pin 해제로 우회할 수 없다.
- **검증 전제:** oldvalidapproval·여러 pin·한 pin 해제·GC/approve 동시·delete_pendingpin 요청·중복 release 를검사한다.
- **작업 순서:** `test_w26_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w26.py::test_w26_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "valid_old_approval_gc": False,
  "one_release_ignores_other_pin": False,
  "delete_pending_approve": False,
  "provenance_deleted": False,
  "manual_can_release_approval_pin": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w26-03"></a>

## W26-03 — 공간·보호/삭제예정·보관 조작 UI

- [ ] **W26-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W26-03.md`(완료 시 생성).
- **직접 선행:** [W26-02](10-retention-and-release-gates.md#w26-02)
- **읽기:** CONTRACTS C00 / C01 / C03 / C04 / C08 / C10 / C11 + 직접 선행 receipt의 interface/제약. 추적: R13, R15, R21, R30, UI-15.06, UI-07.10.
- **변경 파일:** `src/aiqa/web/templates/settings.html`, `src/aiqa/web/templates/components/retention.html`, `src/aiqa/api/retention.py`. 담당 시험: `tests/integration/test_w26.py`.
- **입출력 계약:** `GET /api/v1/projects/{p}/storage; POST /api/v1/projects/{p}/retention-previews -> RetentionPlan`
- **구현·화면·예외:** UI15/07 에서 DB 최소 facts·파일/보호/삭제예정·20GB 전체/RECITEM500MB·artifact 만료/누락/누가왜 pin 을표시한다. manual 보관/해제와정책변경은영향을확인하고보호초과때새행동중지/부분저장안내다. 이력 purge 는 MVP 노출하지않는다. 전체20GB는 project 합산 파일 저장소 한도이며 project 화면에 전체/자기 project 사용량을 나란히 표시한다.
- **검증 전제:** 보호파일로한도초과·499/500MB 경계·pin/release 권한·삭제계획·증거만료링크를확인한다.
- **작업 순서:** `test_w26_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w26.py::test_w26_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "protected_files_auto_deleted": 0,
  "quota_stops_new_actions": True,
  "partial_record_saved": True,
  "purge_button_present": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w26-04"></a>

## W26-04 — 일관 SQLite·artifact manifest 백업

- [ ] **W26-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W26-04.md`(완료 시 생성).
- **직접 선행:** [W26-03](10-retention-and-release-gates.md#w26-03)
- **읽기:** CONTRACTS C00 / C01 / C03 / C04 / C08 / C10 / C11 / C12 + 직접 선행 receipt의 interface/제약. 추적: R12, R14, R15, UI-15.07.
- **변경 파일:** `src/aiqa/store/backup.py`, `src/aiqa/api/backups.py`, `src/aiqa/web/templates/settings.html`. 담당 시험: `tests/integration/test_w26.py`.
- **입출력 계약:** `POST /api/v1/projects/{p}/backups -> JobReceipt; create_backup(input: BackupSpec) -> BackupReceipt`
- **구현·화면·예외:** UI15에서 ‘이 PC 전체 저장소 백업’으로 범위를 명시하고 local_owner만 접수/조회/다운로드하게 한다. project 경로는 요청 이력의 namespace이며 project-only 백업이 아니다. API 소유 storage service가 SQLite online snapshot/project별 commit cursor map·ready artifact manifest·GC 일시 정지/임시 보호를 만든다. worker는 scoped HTTP로 snapshot bytes/파일을 복사할 뿐 live DB나 snapshot을 SQL로 열지 않는다. 비공개 backup receipt에 길이/hash·완료/incomplete를 기록하고 OS secret 평문 복사0·관리 QA=null이다.
- **검증 전제:** GC 동시·copy 중 누락/실패·다른 project 포함 DB 변경·project-only actor의 접수/다운로드·worker DB open spy·secret store/backup 내용을 검사한다.
- **작업 순서:** `test_w26_04`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w26.py::test_w26_04 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "consistent_db_snapshot": True,
  "project_only_actor_allowed": False,
  "worker_opens_sqlite": False,
  "plain_secret_in_backup": False,
  "missing_file_backup_complete": False,
  "backup_job_qa": None
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w26-05"></a>

## W26-05 — 별도 경로 복원·검사·재설정 UI

- [ ] **W26-05 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W26-05.md`(완료 시 생성).
- **직접 선행:** [W26-04](10-retention-and-release-gates.md#w26-04)
- **읽기:** CONTRACTS C00 / C01 / C03 / C04 / C08 / C10 / C11 / C12 + 직접 선행 receipt의 interface/제약. 추적: R08, R12, R14, R15, R26, UI-15.08.
- **변경 파일:** `src/aiqa/store/backup.py`, `src/aiqa/api/backups.py`, `src/aiqa/launcher.py`, `src/aiqa/web/templates/restore.html`. 담당 시험: `tests/integration/test_w26.py`.
- **입출력 계약:** `validate_restore(input: RestoreSpec) -> RestoreValidation; activate_restore(input: RestoreActivation) -> RestoreReceipt`
- **구현·화면·예외:** 기존 liveDB 위덮어쓰기없이별도비동기화경로로복원검사하고 schema/FK/integrity/manifest/hash/누락 facts·필요 key 재설정을표시한다. 활성화는명시확인·진행 job 정리후관리절차다. queued/running 재실행 0·worker 세션폐기/자원 quarantine→진단이다. 복원 활성화도 local_owner 전용·이 PC 전체 저장소 영향이며 모든 project의 진행 REC/RUN 정리·API storage 유지보수 모드에서 수행한다. 프로젝트 권한만으로 전체 DB를 내려받거나 활성화할 수 없다.
- **검증 전제:** 손상 DB·누락 PNG·schema 불일치·OSsecret 없음·과거 queued/running 이있는 backup 을복원한다.
- **작업 순서:** `test_w26_05`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w26.py::test_w26_05 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "auto_replayed_jobs": 0,
  "old_leases_reused": False,
  "secret_reset_required": True,
  "invalid_restore_activated": False,
  "project_only_actor_can_activate": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w27-01"></a>

## W27-01 — 중복·늦은 event·finish·복구 경합 matrix

- [ ] **W27-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W27-01.md`(완료 시 생성).
- **직접 선행:** [W26-05](10-retention-and-release-gates.md#w26-05)
- **읽기:** CONTRACTS C00 / C01 / C03 / C04 / C05 / C07 / C08 / C09 / C10 + 직접 선행 receipt의 interface/제약. 추적: R08, R12, R15, R16.
- **변경 파일:** `tests/integration/test_fault_delivery.py`, `docs/validation/fault-delivery.md`. 담당 시험: `tests/integration/test_w27.py`.
- **입출력 계약:** `FaultCase(id, target, injection_point, repetitions, expected_invariants) -> FaultEvidence`
- **구현·화면·예외:** REC/ITEM 각각 event 중복/변경 body·ACK 전단절·finish/cancel 경합·lateevidence·recoverymaterialization·approvalGC 를각최소 3 회재현한다. 실제 dispatch 수/result/sourcehash/default 를대조하고결함은원소유 task 를재개한다.
- **검증 전제:** 저장된 faultmatrix 행별 3 회실행과원본전후 snapshot 을수집한다.
- **작업 순서:** `test_w27_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w27.py::test_w27_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "repetitions_per_fault_min": 3,
  "duplicate_external_actions": 0,
  "sealed_hash_changes": 0,
  "missing_evidence_approved": 0
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w27-02"></a>

## W27-02 — worker/API/USB/browser/PC 장애 matrix

- [ ] **W27-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W27-02.md`(완료 시 생성).
- **직접 선행:** [W27-01](10-retention-and-release-gates.md#w27-01)
- **읽기:** CONTRACTS C00 / C01 / C03 / C04 / C05 / C07 / C08 / C09 / C10 + 직접 선행 receipt의 interface/제약. 추적: R05, R11, R12, R15, R16, R26.
- **변경 파일:** `tests/integration/test_fault_processes.py`, `docs/validation/fault-processes.md`. 담당 시험: `tests/integration/test_w27.py`.
- **입출력 계약:** `run_fault_scenario(input: ProcessFaultSpec) -> FaultEvidence`
- **구현·화면·예외:** 모델대기취소·USBoffline·browser/driver/VMcrash·worker/API 중단·PC 절전/복귀·IME/cleanup 실패를 REC/ITEM 각각재현한다. 새행동차단·lease/quarantine·QAFAIL 우선/관리 null·자동 resume0 을검증한다.
- **검증 전제:** 각장애최소 3 회·dispatch 전/후구분·실제 process/leaseproof 를기록한다.
- **작업 순서:** `test_w27_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w27.py::test_w27_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "repetitions_per_fault_min": 3,
  "unknown_reclicked": False,
  "unproven_resource_reassigned": False,
  "management_qa": None
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w27-03"></a>

## W27-03 — 용량·정제·파일손상·보관 장애 matrix

- [ ] **W27-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W27-03.md`(완료 시 생성).
- **직접 선행:** [W27-02](10-retention-and-release-gates.md#w27-02)
- **읽기:** CONTRACTS C00 / C01 / C03 / C04 / C05 / C07 / C08 / C09 / C10 + 직접 선행 receipt의 interface/제약. 추적: R07, R12, R14, R15, R30.
- **변경 파일:** `tests/integration/test_fault_storage.py`, `docs/validation/fault-storage.md`. 담당 시험: `tests/integration/test_w27.py`.
- **입출력 계약:** `run_storage_fault(input: StorageFaultSpec) -> FaultEvidence`
- **구현·화면·예외:** diskfull·spoolwritefail·redactorfail·rename 후 crash·ready 파일없음/hashcorruption·GC/reviewexpiry/backupincomplete 를각 3 회검증한다. 원문 secret/hiddenreasoning 저장 0·전캡처실패행동 0·부분기록보존/승인차단을확인한다.
- **검증 전제:** 각주입점의실제파일·DBstate·UIreason·전후 command 수를검사한다.
- **작업 순서:** `test_w27_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w27.py::test_w27_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "raw_secret_persisted": False,
  "pre_capture_fail_dispatches": 0,
  "incomplete_saved_as_complete": False,
  "original_hash_replaced": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w27-04"></a>

## W27-04 — metadata 부하·query plan·문서 추적 재대조

- [ ] **W27-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W27-04.md`(완료 시 생성).
- **직접 선행:** [W27-03](10-retention-and-release-gates.md#w27-03)
- **읽기:** CONTRACTS C00 / C01 / C03 / C04 / C05 / C07 / C08 / C09 / C10 + 직접 선행 receipt의 interface/제약. 추적: R12, R15, R16, R32.
- **변경 파일:** `tools/validation/benchmark_metadata.py`, `tests/integration/test_metadata_queries.py`, `docs/validation/metadata-load.md`. 담당 시험: `tests/integration/test_w27.py`.
- **입출력 계약:** `benchmark_metadata(input: MetadataWorkload) -> MetadataBenchmarkReport`
- **구현·화면·예외:** 합성 ITEM10000/action100000 의실제 DB/queryplan·최근 30 일추세 p95≤1000ms·event200 개 pagep95≤500ms 제안목표를측정한다. 파일 IO/기기지연은별도, DATA22/실행 10 시나리오의근거 task/결함상태를대조한다.
- **검증 전제:** 같은 indexedDB 에서조건/반복수/장비와측정치·누락근거를기록한다.
- **작업 순서:** `test_w27_04`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w27.py::test_w27_04 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "items": 10000,
  "actions": 100000,
  "trend_target_ms": 1000,
  "event_page_target_ms": 500,
  "untracked_scenarios": 0
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w32-01"></a>

## W32-01 — role 비용·계측 누락·표본 산식 검증

- [ ] **W32-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W32-01.md`(완료 시 생성).
- **직접 선행:** [W27-04](10-retention-and-release-gates.md#w27-04)
- **읽기:** CONTRACTS C00 / C01 / C06 / C09 / C10 + 직접 선행 receipt의 interface/제약. 추적: R13, R35.
- **변경 파일:** `src/aiqa/domain/costs.py`, `tests/integration/test_cost_accounting.py`, `src/aiqa/contracts/benchmarks.py`. 담당 시험: `tests/integration/test_w32.py`.
- **입출력 계약:** `summarize_workload_cost(input: WorkloadFacts) -> WorkloadCostSummary`
- **구현·화면·예외:** authoring/verification/healing/maintenance·모든 retry/check/episode·tariff/통화/partial·lateledger/asof·미사용 0/누락 null 을검증한다. 서로다른통화를임의합산하지않고기기점유시간은달러로꾸미지않는다.
- **검증 전제:** 2role 측정+1role 미보고·healer 전송 retry·가격변경·복수통화·lateasoffixture 를집계한다.
- **작업 순서:** `test_w32_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w32.py::test_w32_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "unreported_usage": None,
  "unused_role_cost": "0",
  "mixed_currencies_combined": False,
  "late_asof_respected": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w32-02"></a>

## W32-02 — 대표 30–50 TC·3 구성·실제 품질/비용 측정

- [ ] **W32-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W32-02.md`(완료 시 생성).
- **직접 선행:** [W32-01](10-retention-and-release-gates.md#w32-01)
- **읽기:** CONTRACTS C00 / C01 / C06 / C09 / C10 + 직접 선행 receipt의 interface/제약. 추적: R06, R13, R16, R17, R33, R35.
- **변경 파일:** `tools/validation/benchmark_replay.py`, `docs/validation/replay-costs.md`. 담당 시험: `tests/integration/test_w32.py`.
- **입출력 계약:** `benchmark_replay(workload: WorkloadSpec, policies: list[ExecutionPolicy]) -> BenchmarkReport`
- **구현·화면·예외:** 대표 30–50 TC 의 정상/제품 FAIL/locator 변화/결과 불명에서 결정적 OFF·필요 verifier OFF·필요 verifier ON 을 같은 data/env 로 각 3 회 제안 측정한다. authoring 별도·사람 oracle·거짓 PASS/assist/unassisted·role calls/p50p95/저장량·조건/미계측을 기록한다. AI 필수 검사를 결정적 OFF 비교에서 제거하지 않고 동일 oracle 을 유지할 수 있는 cohort 만 비교한다. 전체 표본과 구성별 비교 가능 표본 수를 따로 표시한다.
- **검증 전제:** 표본정의/선정이유/실제 tariff·각구성 3 회와사람 판정을대조한다.
- **작업 순서:** `test_w32_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w32.py::test_w32_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "policies": 3,
  "proposed_repeats": 3,
  "false_pass_tolerated": 0,
  "authoring_separate": True,
  "oracle_weakened_for_cost": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w32-03"></a>

## W32-03 — 월 3000 workload 추정·release_label UI

- [ ] **W32-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W32-03.md`(완료 시 생성).
- **직접 선행:** [W32-02](10-retention-and-release-gates.md#w32-02)
- **읽기:** CONTRACTS C00 / C01 / C06 / C09 / C10 + 직접 선행 receipt의 interface/제약. 추적: R13, R21, R35, UI-12.08, UI-13.03.
- **변경 파일:** `src/aiqa/domain/costs.py`, `src/aiqa/web/templates/analytics.html`, `src/aiqa/web/templates/report.html`, `docs/validation/monthly-workload.md`. 담당 시험: `tests/integration/test_w32.py`.
- **입출력 계약:** `estimate_monthly_regression(input: WorkloadAssumptions, benchmark: BenchmarkReport) -> MonthlyEstimate`
- **구현·화면·예외:** 3000TC×1data×1 환경·월 1 회를명시하고 RUN 최대 100 따라최소 30RUN/release_label 로집계한다. 최초녹화/반복검증/치유빈도/전체재녹화·추가 data/env/retry 를별도산식/표본조건으로표시한다. 부족계측을고정금액/성공률로채우지않는다.
- **검증 전제:** 측정된표본과 healing0/관측빈도/추가 env2·미보고 usage 조건으로추정과 UI 를검증한다.
- **작업 순서:** `test_w32_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w32.py::test_w32_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "base_items": 3000,
  "minimum_runs": 30,
  "extra_environment_multiplier": 2,
  "unknown_cost_fabricated": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w28-01"></a>

## W28-01 — 전체 추적표·부분 구현·차단·후속 경계 audit

- [ ] **W28-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W28-01.md`(완료 시 생성).
- **직접 선행:** [W32-03](10-retention-and-release-gates.md#w32-03)
- **읽기:** CONTRACTS C00 / C01 / C03 / C04 / C05 / C06 / C07 / C08 / C09 / C10 / C11 + 직접 선행 receipt의 interface/제약. 추적: R16, R21, R27, R28.
- **변경 파일:** `docs/validation/coverage-audit.md`, `tests/acceptance/test_plan_coverage.py`. 담당 시험: `tests/integration/test_w28.py`.
- **입출력 계약:** `audit_release_coverage(input: CoverageEvidenceIndex) -> CoverageAudit`
- **구현·화면·예외:** R32 개 P0·선택 TC·UI16 화면/조작·공통상태·UI21/DATA22/실행 10 의실제증거를대조한다. 담당 task 존재는구현 PASS 가아니며 SKIP/mock/불명은필수 gate 미충족이다. 미구현 UI 탭/끊긴 링크/임시데이터를찾아원작업을재개한다.
- **검증 전제:** 모든 leaf 완료보고와실제파일/test/UI 증거를독립대조하고하나누락/위조 PASSfixture 로차단한다.
- **작업 순서:** `test_w28_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w28.py::test_w28_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "unowned_p0_requirements": 0,
  "required_skip_as_pass": False,
  "mock_as_device_evidence": False,
  "placeholder_features_accepted": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w28-02"></a>

## W28-02 — UI01–06·14–16·공통 상태 실제 동선

- [ ] **W28-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W28-02.md`(완료 시 생성).
- **직접 선행:** [W28-01](10-retention-and-release-gates.md#w28-01)
- **읽기:** CONTRACTS C00 / C01 / C03 / C04 / C05 / C06 / C07 / C08 / C09 / C10 / C11 + 직접 선행 receipt의 interface/제약. 추적: R16, R21, R26, R27, R28, R29, R30.
- **변경 파일:** `tests/acceptance/test_management_recording_journey.py`, `docs/validation/ui-management-recording.md`. 담당 시험: `tests/integration/test_w28.py`.
- **입출력 계약:** `run_ui_journey(input: RecordingJourneyFixture) -> UiJourneyEvidence`
- **구현·화면·예외:** TC0 개에서 project→환경/키/data→기기선택→자연어→AI 녹화→종료/실패/중단저장→case/REC/source/package 를 Web/Android 각각실행한다. UI01–06/14–16 전조작과 0 건/403/409/422/stale/뒤로/키보드/1024/1440 을 UI 추적표기준으로확인한다.
- **검증 전제:** 실제 API/DB/worker·합성업무대상과두기기로입력저장/새로고침·모의데이터제거를확인한다.
- **작업 순서:** `test_w28_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w28.py::test_w28_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "platforms": 2,
  "tc_required": False,
  "recording_approval_gate": False,
  "unwired_ui_controls": 0,
  "secret_leaks": 0
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w28-03"></a>

## W28-03 — UI07–13 승인→수행→분석/내보내기 동선

- [ ] **W28-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W28-03.md`(완료 시 생성).
- **직접 선행:** [W28-02](10-retention-and-release-gates.md#w28-02)
- **읽기:** CONTRACTS C00 / C01 / C03 / C04 / C05 / C06 / C07 / C08 / C09 / C10 / C11 + 직접 선행 receipt의 interface/제약. 추적: R08, R16, R21, R22, R24, R27, R31, R32, R33.
- **변경 파일:** `tests/acceptance/test_review_execution_journey.py`, `docs/validation/ui-review-execution.md`. 담당 시험: `tests/integration/test_w28.py`.
- **입출력 계약:** `run_ui_journey(input: ReviewExecutionJourneyFixture) -> UiJourneyEvidence`
- **구현·화면·예외:** 출처/trial 보기→OFF 시범/사후 action 검토/승인·반려·철회→single/selection/mixedsuite→취소/skip/새 rerun→리포트/누적/비교/CSV/HTML 을모두 UI 에서실행한다. 재녹화실패 default 유지·suite 명시교체·정상/치유 PASS/원본 FAIL 분리를검증한다.
- **검증 전제:** UI07–13 의각조작을실제 DB/파일/worker 결과와대조하고 disabled 이유·흐름복원·완료 counts 를확인한다.
- **작업 순서:** `test_w28_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w28.py::test_w28_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "unwired_ui_controls": 0,
  "approval_before_storage": False,
  "old_run_changed": False,
  "terminal_buckets": 7,
  "false_passes": 0
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w28-04"></a>

## W28-04 — 양 플랫폼 정상·결함·변경·격리 합격

- [ ] **W28-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W28-04.md`(완료 시 생성).
- **직접 선행:** [W28-03](10-retention-and-release-gates.md#w28-03)
- **읽기:** CONTRACTS C00 / C01 / C03 / C04 / C05 / C06 / C07 / C08 / C09 / C10 / C11 + 직접 선행 receipt의 interface/제약. 추적: R04, R05, R06, R14, R16, R17, R34, R35.
- **변경 파일:** `tools/validation/run_mvp_gate.py`, `docs/validation/mvp-results.md`. 담당 시험: `tests/integration/test_w28.py`.
- **입출력 계약:** `evaluate_mvp_gate(input: MvpEvidenceSet) -> MvpGateReport`
- **구현·화면·예외:** 각플랫폼정상 20 회(첫≥18/20·허용 retry 포함≥19/20 제안), 값불일치/요소부재/timeout 각 5 회·위치/문구변경각 5 회를사람 oracle 과대조한다. 거짓 PASS0·증거누락승인 0·중복제어 0·source 덮어쓰기 0·격리/dispatch/key 없는 0 호출을검증한다. 부족조건은명시차단이다.
- **검증 전제:** 실측회수/성공률/QA 정확도와 W27 장애·W32 비용근거를함께판정한다.
- **작업 순서:** `test_w28_04`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w28.py::test_w28_04 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "platforms": 2,
  "false_passes": 0,
  "missing_evidence_approvals": 0,
  "duplicate_resource_owners": 0,
  "source_overwrites": 0
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w28-05"></a>

## W28-05 — 사용 안내·제약·최종 체크와 다음 인계

- [ ] **W28-05 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W28-05.md`(완료 시 생성).
- **직접 선행:** [W28-04](10-retention-and-release-gates.md#w28-04)
- **읽기:** CONTRACTS C00 / C01 / C03 / C04 / C05 / C06 / C07 / C08 / C09 / C10 / C11 + 직접 선행 receipt의 interface/제약. 추적: R16, R21, R26, R27, R35.
- **변경 파일:** `README.md`, `docs/validation/mvp-results.md`, `docs/execution/HANDOFF.md`, `WORK_PROGRESS.md`. 담당 시험: `tests/integration/test_w28.py`.
- **입출력 계약:** `publish_local_usage_docs(evidence: MvpGateReport) -> DocumentationReceipt`
- **구현·화면·예외:** 실제설치/시작/환경준비·키관리·녹화저장/사후승인·replay/검증/healing·실패/복원/비용안내를검증된지원범위대로정리한다. 제품 leaf/W/단계완료는근거와동기화하며배포/PR/클라우드는자동진행하지않는다.
- **검증 전제:** 새작업자가안내대로첫 TC0 동선·장애복구경로를찾고문서/구현/알려진제약을대조한다.
- **작업 순서:** `test_w28_05`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w28.py::test_w28_05 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "unsupported_claims": 0,
  "unlinked_evidence": 0,
  "progress_matches_verified": True,
  "automatic_deployment": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

## 영역 종료 점검

- 카드 체크·TASK_INDEX 상태·인계 근거가 일치해야 한다.
- [COVERAGE](COVERAGE.md)·[UI_COVERAGE](UI_COVERAGE.md)에서 담당 항목의 실제 증거를 연결한다.
- 후속 기능을 미리 완료 처리하지 않는다. 실패/계약 변경은 [REVIEW](REVIEW.md)에 기록하고 영향 작업을 재개한다.
