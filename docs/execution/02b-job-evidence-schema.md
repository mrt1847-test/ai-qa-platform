# B-2 · 자원·REC·job·증거·장기 facts schema · 상세 작업서 v0.8

제품 설계 v0.6 + [보완 계약](CONTRACTS.md). **완료10 / 10**.
[Current 큐](../../NEXT_ACTION.md) · [전체 색인](README.md) · [차단/선행 수정](SCHEDULING.md) · [인계](HANDOFF.md).

카드 한 개와 직접 선행 근거만 읽는다. 기존 코드/complete/blocked 기록을 재사용한다.
검증 등급·live 수용을 구분한다. core fixture는 실제 native 근거가 아니며 최종 검증을 생략하지 않는다.

| 작업 | 직접 선행 | 결과 | 상태 |
|---|---|---|---|
| [W06-01](#w06-01) | [W05-06](02a-assets-and-scope.md#w05-06) | REC·manifest·receipt schema | complete |
| [W06-10](#w06-10) | [W06-01](02b-job-evidence-schema.md#w06-01) | worker·물리 자원·project 별칭의 canonical schema | complete |
| [W06-02](#w06-02) | [W06-10](02b-job-evidence-schema.md#w06-10) | RUN·ITEM·job·attempt owner schema | complete |
| [W06-03](#w06-03) | [W06-02](02b-job-evidence-schema.md#w06-02) | action·check·event·usage 최소 facts schema | complete |
| [W06-04](#w06-04) | [W06-03](02b-job-evidence-schema.md#w06-03) | review·approval·typed artifact 보호 schema | complete |
| [W06-05](#w06-05) | [W06-04](02b-job-evidence-schema.md#w06-04) | package·healing·proposal schema | complete |
| [W06-06](#w06-06) | [W06-05](02b-job-evidence-schema.md#w06-05) | 장기 commit cursor·finalization·usage ledger | complete |
| [W06-07](#w06-07) | [W06-06](02b-job-evidence-schema.md#w06-06) | migration·FK·trigger·index 전체 검증 | complete |
| [W06-08](#w06-08) | [W06-07](02b-job-evidence-schema.md#w06-07) | 기기 미리보기 관찰·artifact 소속 schema | complete |
| [W06-09](#w06-09) | [W06-08](02b-job-evidence-schema.md#w06-08) | AI·TC diff 제안과 수락의 영속 계약 | complete |

<a id="w06-01"></a>

## W06-01 — REC·manifest·receipt schema

- [x] **W06-01 완료** — 상태: `complete`. 근거: [W06-01 인계](../validation/tasks/W06-01.md).
- **직접 선행:** [W05-06](02a-assets-and-scope.md#w05-06)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C07 / C12 / C14 + 직접 선행 receipt의 interface/제약. 추적: R08, R12, R30.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/store/models.py`, `migrations/versions/0003_recordings.py`, `src/aiqa/contracts/recordings.py`. 시험: `tests/integration/test_w06.py`.
- **입출력 계약:** `RecordingSession; RecordingManifest(kind: original | recovery | package_rebuild); MaterializationReceipt`
- **구현·화면·예외:** input/base/parent/source 동일 project/case·manifest revision/request key unique·produced version unique 를 강제한다. creation_kind 는 recorded, manifest.kind 가 package_rebuild 임을 구별한다. 저장/종료/완결/증거 상태는 별도 컬럼이다. recording_notes(project/REC/id/actor/time/commit_seq/text/request_key)는 append-only다. browser 메모가 worker attempt.local_seq를 직접 배정하지 않으며 기록 제어/expected/hash를 변경하지 않는다.
- **검증 전제:** 타 case input/base/source·동일 manifest 두 output·동일 request key 다른 body 를 삽입한다.
- **작업 순서:** `test_w06_01`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w06.py::test_w06_01 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "cross_case_denied": True,
  "duplicate_materialization_denied": True,
  "independent_status_axes": True,
  "notes_have_independent_sequence": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w06-10"></a>

## W06-10 — worker·물리 자원·project 별칭의 canonical schema

- [x] **W06-10 완료** — 상태: `complete`. 근거: [W06-10 인계](../validation/tasks/W06-10.md).
- **직접 선행:** [W06-01](02b-job-evidence-schema.md#w06-01)
- **읽기:** CONTRACTS C00 / C01 / C04 / C12 / C14 + 직접 선행 receipt의 interface/제약. 추적: R01, R02, R12, R25.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/store/models.py`, `src/aiqa/contracts/resources.py`, `migrations/versions/0003b_resources.py`. 시험: `tests/integration/test_w06.py`.
- **입출력 계약:** `PhysicalResourceKey(worker_id: UUID, native_id: str); ResourceAlias(project_id: UUID, physical_key_id: UUID, display_name: str, target_kind: str)`
- **구현·화면·예외:** W04-03의 worker identity를 참조해 물리 자원 key와 project별 resource 별칭을 먼저 저장한다. (worker_id,native_id) 전역 UNIQUE·별칭 같은 project FK·공용 물리 key 연결을 강제한다. W06-02의 job/attempt/lease FK가 이 canonical row를 참조하게 하며 inventory 갱신 서비스는 W07-01에서 구현한다.
- **검증 전제:** 동일 worker/serial을 project A/B에서 별칭 등록하고 다른 worker·다른 native ID·없는 worker·타 project alias 관계를 검사한다.
- **작업 순서:** `test_w06_10`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w06.py::test_w06_10 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "physical_keys_for_same_worker_serial": 1,
  "project_aliases": 2,
  "unknown_worker_rejected": True,
  "cross_project_alias_mutation_denied": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w06-02"></a>

## W06-02 — RUN·ITEM·job·attempt owner schema

- [x] **W06-02 완료** — 상태: `complete`. 근거: [W06-02 인계](../validation/tasks/W06-02.md).
- **직접 선행:** [W06-10](02b-job-evidence-schema.md#w06-10)
- **읽기:** CONTRACTS C00 / C01 / C04 / C09 / C14 + 직접 선행 receipt의 interface/제약. 추적: R09, R10, R12, R22.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/store/models.py`, `migrations/versions/0004_execution_jobs.py`, `src/aiqa/contracts/jobs.py`. 시험: `tests/integration/test_w06.py`.
- **입출력 계약:** `ExecutionSnapshot; CaseRunSnapshot; JobSpec; AttemptSnapshot`
- **구현·화면·예외:** RUN purpose trial/regression/reverification, job purpose C04 enum(backup 포함)을 고정한다. recording 은 REC 만·trial/regression 은 ITEM 만·관리는 둘 다 null CHECK, owner 별 job1 이다. reverification job 은 regression 으로 사상하며 관리 source 는 별도 ref 로 연결한다. lease와 attempt의 physical resource FK는 W06-10의 canonical key를 참조한다. suites/suite_versions/entry 기본 schema를 이 migration에서 함께 생성해 executions.suite_version FK 대상을 먼저 준비한다. 실제 묶음 편집/수행은 W21이다.
- **검증 전제:** 배타 owner·ITEM/execution scope_requested_at/purpose 불일치·관리 package_rebuild owner 를 검사한다.
- **작업 순서:** `test_w06_02`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w06.py::test_w06_02 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "double_owner_denied": True,
  "owner_job_unique": True,
  "package_rebuild_owners_null": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w06-03"></a>

## W06-03 — action·check·event·usage 최소 facts schema

- [x] **W06-03 완료** — 상태: `complete`. 근거: [W06-03 인계](../validation/tasks/W06-03.md).
- **직접 선행:** [W06-02](02b-job-evidence-schema.md#w06-02)
- **읽기:** CONTRACTS C00 / C01 / C05 / C06 / C10 / C14 + 직접 선행 receipt의 interface/제약. 추적: R06, R07, R12, R13, R29.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/store/models.py`, `migrations/versions/0005_evidence_usage.py`, `src/aiqa/contracts/evidence.py`. 시험: `tests/integration/test_w06.py`.
- **입출력 계약:** `ActionEnvelope; CheckResult; EventEnvelope; ModelCallFact`
- **구현·화면·예외:** attempt seq unique·action/check 같은 attempt·step/version mapping·dispatch journal·nullable usage·role owner 를 강제한다. identity/hash/최소 fact 와 detail_payload 를 분리하고 seal 후 UPDATE 를 거부한다.
- **검증 전제:** 같은 seq/hash 재수신·다른 hash·다른 attempt action check 연결·usage=null·seal 후 변경을 검사한다.
- **작업 순서:** `test_w06_03`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w06.py::test_w06_03 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "same_event_receipt": True,
  "different_hash_status": 409,
  "cross_attempt_denied": True,
  "unknown_usage": None
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w06-04"></a>

## W06-04 — review·approval·typed artifact 보호 schema

- [x] **W06-04 완료** — 상태: `complete`. 근거: [W06-04 인계](../validation/tasks/W06-04.md).
- **직접 선행:** [W06-03](02b-job-evidence-schema.md#w06-03)
- **읽기:** CONTRACTS C00 / C01 / C03 / C08 / C10 / C14 + 직접 선행 receipt의 interface/제약. 추적: R08, R14, R24, R30.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/store/models.py`, `migrations/versions/0006_reviews_artifacts.py`, `src/aiqa/contracts/reviews.py`. 시험: `tests/integration/test_w06.py`.
- **입출력 계약:** `ReviewSnapshot; ReviewEvidenceEntry; ArtifactRef; ArtifactProtection; ApprovalEvent`
- **구현·화면·예외:** review exact membership·결정 unique·revoke approved event 참조·artifact_ref typed owner 정확히 1·protection/release 를 정의한다. 같은 project 여도 다른 ITEM 근거는 transaction 에서 차단할 경로를 보존한다. artifact/protection의 FK 대상 app_builds/backup_receipts/manual_retention_requests 기본 schema도 먼저 생성한다. build/백업/manual 보관 동작은 W11/W26에서 구현하며 미래 서비스까지 완료 처리하지 않는다.
- **검증 전제:** typed owner0/2 개·다른 case approval pointer·중복 final decision/revoke·provenance 와 pin 분리를 검사한다.
- **작업 순서:** `test_w06_04`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w06.py::test_w06_04 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "invalid_typed_owner_denied": True,
  "foreign_approval_denied": True,
  "duplicate_decision_denied": True,
  "provenance_implies_pin": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w06-05"></a>

## W06-05 — package·healing·proposal schema

- [x] **W06-05 완료** — 상태: `complete`. 근거: [W06-05 인계](../validation/tasks/W06-05.md).
- **직접 선행:** [W06-04](02b-job-evidence-schema.md#w06-04)
- **읽기:** CONTRACTS C00 / C01 / C07 / C09 / C14 + 직접 선행 receipt의 interface/제약. 추적: R17, R33, R34.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/store/models.py`, `migrations/versions/0007_replay_healing.py`, `src/aiqa/contracts/replay.py`. 시험: `tests/integration/test_w06.py`.
- **입출력 계약:** `ReplayPackage; PackageStep; HealingEpisode; RuntimeOverride; RepairProposal`
- **구현·화면·예외:** version0..1 package·ready1·same-case 양방향 composite FK 를 deferred commit 검사한다. package body 에 produced version hash 가 없어야 한다. episode/override/proposal 의 ITEM/attempt/package 소속과 멱등 unique 를 강제한다.
- **검증 전제:** draft0/ready1·다른 case package·동일 episode override2 개·중복 episode 예약을 검사한다.
- **작업 순서:** `test_w06_05`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w06.py::test_w06_05 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "draft_package_count": 0,
  "ready_package_count": 1,
  "cross_package_denied": True,
  "episode_unique": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w06-06"></a>

## W06-06 — 장기 commit cursor·finalization·usage ledger

- [x] **W06-06 완료** — 상태: `complete`. 근거: [W06-06 인계](../validation/tasks/W06-06.md).
- **직접 선행:** [W06-05](02b-job-evidence-schema.md#w06-05)
- **읽기:** CONTRACTS C00 / C01 / C09 / C10 / C14 + 직접 선행 receipt의 interface/제약. 추적: R13, R31, R32, R35.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/store/models.py`, `migrations/versions/0008_long_term_facts.py`, `src/aiqa/contracts/reports.py`. 시험: `tests/integration/test_w06.py`.
- **입출력 계약:** `ItemFinalization; ItemLifecycleEvent; UsageAdjustment; FingerprintObservation`
- **구현·화면·예외:** 최소 facts·분모·생성/확정 seq·실제 fingerprint 관찰 seq·release_label·role model not_used/unknown 을 보존한다. late 비용은 append ledger 이며 core result/content hash UPDATE0 이다. analysis_records의 append-only 기본 schema도 여기서 생성하고 실제 분석 UI/서비스는 W23-03에서 만든다.
- **검증 전제:** 접수 seq10/확정 seq20/보정 seq30 의 as_of10·20·30 을 조회 가능한 row 로 저장한다.
- **작업 순서:** `test_w06_06`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w06.py::test_w06_06 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "finalization_unique": True,
  "late_usage_updates_original": False,
  "actual_fingerprint_has_seq": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w06-07"></a>

## W06-07 — migration·FK·trigger·index 전체 검증

- [x] **W06-07 완료** — 상태: `complete`. 근거: [W06-07 인계](../validation/tasks/W06-07.md).
- **직접 선행:** [W06-06](02b-job-evidence-schema.md#w06-06)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C07 / C08 / C10 / C14 + 직접 선행 receipt의 interface/제약. 추적: R08, R12, R15, R32.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `migrations/versions/0009_indexes.py`, `tests/integration/test_schema_integrity.py`, `docs/validation/schema.md`. 시험: `tests/integration/test_w06.py`.
- **입출력 계약:** `validate_schema(store: Store) -> SchemaIntegrityReport`
- **구현·화면·예외:** 빈 DB 와 앞선 revision DB 의 upgrade·재시작·FK 활성화·partial UNIQUE·불변 trigger·필수 query index 를 검증한다. 승인/GC 경합의 실제 서비스 검증은 W19/W26 에 남긴다. SQL DDL의 모든 FK 대상 테이블이 canonical migration 결과에 존재하는지 검사하고 nullable FK에도 실제 insert를 수행해 누락된 미래 부모를 검출한다.
- **검증 전제:** schema 를 두 방식으로 만들고 DATA_DESIGN §3–4 의 모든 제약과 integrity_check/foreign_key_check 를 대조한다.
- **작업 순서:** `test_w06_07`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w06.py::test_w06_07 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "integrity": "ok",
  "foreign_key_violations": 0,
  "required_indexes_present": True,
  "mutable_sealed_content": False,
  "all_fk_target_tables_exist": True,
  "nullable_fk_inserts_work": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w06-08"></a>

## W06-08 — 기기 미리보기 관찰·artifact 소속 schema

- [x] **W06-08 완료** — 상태: `complete`. 근거: [W06-08 인계](../validation/tasks/W06-08.md).
- **직접 선행:** [W06-07](02b-job-evidence-schema.md#w06-07)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C11 / C12 / C14 + 직접 선행 receipt의 interface/제약. 추적: R02, R07, R14, R25.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/store/models.py`, `src/aiqa/contracts/resources.py`, `migrations/versions/0010_resource_observations.py`. 시험: `tests/integration/test_w06.py`.
- **입출력 계약:** `ResourceObservation(project_id, resource_id, probe_job_id, attempt_id, captured_at, geometry, artifact_id, scope_hash)`
- **구현·화면·예외:** resource_probe에서 얻은 읽기 capture를 resource_observations에 append하고 artifact_refs에 resource_observation_id typed owner를 추가한다. 같은 project/resource/physical lease/attempt를 강제하며 REC/ITEM 행동 증거와 섞지 않는다. UI preview는 이 관찰 또는 권한 있는 실행 capture만 조회한다. 새 schema를 추가한 뒤 W06-07의 전체 migration/FK 검사를 다시 수행한다. test-only parent fixture 검사는 실제 canonical DB 통합 통과로 세지 않는다.
- **검증 전제:** 다른 project probe·다른 attempt capture·두 typed owner·preview를 녹화의 즉시 후 PNG로 연결하는 요청을 검사한다.
- **작업 순서:** `test_w06_08`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w06.py::test_w06_08 tests/integration/test_w06.py::test_w06_07 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "foreign_observation_denied": True,
  "exactly_one_artifact_owner": True,
  "probe_capture_as_recording_after": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w06-09"></a>

## W06-09 — AI·TC diff 제안과 수락의 영속 계약

- [x] **W06-09 완료** — 상태: `complete`. 근거: [W06-09 인계](../validation/tasks/W06-09.md).
- **직접 선행:** [W06-08](02b-job-evidence-schema.md#w06-08)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C11 / C12 / C14 + 직접 선행 receipt의 interface/제약. 추적: R03, R08, R12, R24, R28.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/store/models.py`, `src/aiqa/domain/proposals.py`, `src/aiqa/api/cases.py`, `migrations/versions/0011_case_proposals.py`. 시험: `tests/integration/test_w06.py`.
- **입출력 계약:** `create_case_proposal(input: CaseProposalInput) -> CaseProposalView; accept_case_proposal(proposal_id: UUID, expected_head: UUID) -> CaseVersionView`
- **구현·화면·예외:** case_edit_proposals는 project/case/base version/hash·kind(structure|tc_import)·정제 제안 body/hash·source job 또는 TC version을 고정한다. structure source는 같은 case의 structure job, tc_import는 같은 project TC다. case_proposal_decisions의 명시 수락에서만 새 case version/decision/audit를 원자 생성하며 동일 proposal의 중복 수락은 같은 receipt다. 거부/오래된 base는 기존 정의 변경0이다. 새 schema를 추가한 뒤 W06-07의 전체 migration/FK 검사를 다시 수행한다. test-only parent fixture 검사는 실제 canonical DB 통합 통과로 세지 않는다.
- **검증 전제:** TC import 거부/수락·structure job 결과 보관·다른 case 제안·head 변경409·동시 수락·API 재시작 후 diff 조회를 검사한다.
- **작업 순서:** `test_w06_09`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w06.py::test_w06_09 tests/integration/test_w06.py::test_w06_07 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "accepted_versions_per_proposal": 1,
  "rejected_versions": 0,
  "stale_head_status": 409,
  "proposal_survives_restart": True,
  "approval_copied": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

## 영역 종료 점검

- 카드·TASK_INDEX·실제 인계 상태를 맞춘다. 과거 완료를 문서 정리로 다시 구현하거나 무효화하지 않는다.
- 부모 W는 소속 leaf와 parent_gate_tasks/원래 통합 조건까지 만족해야 완료다.
- [UI_COVERAGE](UI_COVERAGE.md)·[COVERAGE](COVERAGE.md)의 실제 수용 조건은 그대로 유지한다.
