# C · 세션·작업 큐·중단 · 상세 작업서 v0.8

제품 설계 v0.6 + [보완 계약](CONTRACTS.md). **완료10 / 13**.
[Current 큐](../../NEXT_ACTION.md) · [전체 색인](README.md) · [차단/선행 수정](SCHEDULING.md) · [인계](HANDOFF.md).

카드 한 개와 직접 선행 근거만 읽는다. 기존 코드/complete/blocked 기록을 재사용한다.
검증 등급·live 수용을 구분한다. core fixture는 실제 native 근거가 아니며 최종 검증을 생략하지 않는다.

| 작업 | 직접 선행 | 결과 | 상태 |
|---|---|---|---|
| [W07-01](#w07-01) | [W06-09](02b-job-evidence-schema.md#w06-09) | 자원 inventory·전역 물리 기기 identity | complete |
| [W07-02](#w07-02) | [W07-01](03-worker-and-sessions.md#w07-01), [W01-02](01-foundation-probes.md#w01-02) | Web VM·context·script/driver session 수명 | not_started |
| [W07-03](#w07-03) | [W07-01](03-worker-and-sessions.md#w07-01), [W02-04](01-foundation-probes.md#w02-04) | 호스트 USB session·앱 준비·IME snapshot | not_started |
| [W07-04](#w07-04) | [W07-02](03-worker-and-sessions.md#w07-02), [W07-03](03-worker-and-sessions.md#w07-03), [W09-03](03-worker-and-sessions.md#w09-03) | release·quarantine·recover 증명 | not_started |
| [W08-01](#w08-01) | [W06-09](02b-job-evidence-schema.md#w06-09), [W00-04](00-bootstrap.md#w00-04) | purpose 별 payload 와 영구 접수 receipt | complete |
| [W08-02](#w08-02) | [W08-01](03-worker-and-sessions.md#w08-01) | 원자 claim·slot1·순차 선행 | complete |
| [W08-03](#w08-03) | [W08-02](03-worker-and-sessions.md#w08-02) | heartbeat·generation·runner ACK 멱등 | complete |
| [W08-04](#w08-04) | [W08-03](03-worker-and-sessions.md#w08-03) | event cursor·spool ACK·late inbox | complete |
| [W08-05](#w08-05) | [W08-04](03-worker-and-sessions.md#w08-04) | API 재시작과 유효 runner 조정 | complete |
| [W09-01](#w09-01) | [W08-05](03-worker-and-sessions.md#w08-05) | 영구 취소 flag·늦은 응답 행동 차단 | complete |
| [W09-02](#w09-02) | [W09-01](03-worker-and-sessions.md#w09-01) | watchdog·lease 여유·실행 한도 | complete |
| [W09-03](#w09-03) | [W09-02](03-worker-and-sessions.md#w09-02) | Windows process tree·VM 정리와 격리 | complete |
| [W09-04](#w09-04) | [W09-03](03-worker-and-sessions.md#w09-03), [W23-01](09-results-and-analytics.md#w23-01) | lost·취소·정리 결과와 QA 분리 | complete |

<a id="w07-01"></a>

## W07-01 — 자원 inventory·전역 물리 기기 identity

- [x] **W07-01 완료** — 상태: `complete`. 근거: [W07-01 인계](../validation/tasks/W07-01.md).
- **직접 선행:** [W06-09](02b-job-evidence-schema.md#w06-09)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C14 + 직접 선행 receipt의 interface/제약. 추적: R02, R14, R25.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W07-02, W07-03, W07-04에서 별도로 요구한다.
- **실제 통합 담당:** [W07-02](03-worker-and-sessions.md#w07-02), [W07-03](03-worker-and-sessions.md#w07-03), [W07-04](03-worker-and-sessions.md#w07-04). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/worker/resources.py`, `src/aiqa/api/resources.py`, `src/aiqa/contracts/resources.py`. 시험: `tests/integration/test_w07.py`.
- **입출력 계약:** `report_inventory(worker: WorkerScope, input: InventoryReport) -> InventoryReceipt; resource_key(worker_id: UUID, native_id: str) -> str`
- **구현·화면·예외:** Web VM/Chromium 과 Android serial·state·OS/build·capture geometry·권한·IME·마지막 관찰을 보고한다. project 별 resource 별칭이어도 동일 host/serial lease 는 하나다. raw CDP/ADB credential 은 UI 에 전달하지 않는다.
- **검증 전제:** 프로젝트 A/B의 같은 serial alias·offline/unauthorized/busy inventory 보고를 test-only 입력으로 API에 보내고 실제 DB identity/권한을 검사한다. native 관찰은 W07-02/03의 gate다.
- **작업 순서:** `test_w07_01`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w07.py::test_w07_01 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "physical_resource_count": 1,
  "alias_double_booking": False,
  "ui_raw_handle": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w07-02"></a>

## W07-02 — Web VM·context·script/driver session 수명

- [ ] **W07-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W07-02.md`(구현 때 생성).
- **직접 선행:** [W07-01](03-worker-and-sessions.md#w07-01), [W01-02](01-foundation-probes.md#w01-02)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 + 직접 선행 receipt의 interface/제약. 추적: R04, R14, R25.
- **검증 등급:** `live_integration`. 환경: `local_python`, `local_linux_vm`.
- **변경 파일:** `src/aiqa/environments/base.py`, `src/aiqa/environments/isolated_local_chromium.py`, `src/aiqa/worker/isolated_web.py`. 시험: `tests/integration/test_w07.py`.
- **입출력 계약:** `acquire_environment(spec: EnvironmentSpec, lease: Lease) -> SessionHandle; release_environment(session: SessionHandle) -> CleanupReport`
- **구현·화면·예외:** 같은 PC VM 의 driver·제한 IPC·별도 script 권한/egress 를 session/generation 에 묶는다. attempt 별 새 context·관리 탭/개인 profile 분리·중복 release 안전성을 구현한다.
- **검증 전제:** 두 attempt 에서 context isolation·lease 가 다른 IPC command·VM 부재·release 두 번을 관찰한다.
- **작업 순서:** `test_w07_02`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w07.py::test_w07_02 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "contexts_separate": True,
  "wrong_generation_command": False,
  "vm_missing_native_fallback": False,
  "release_idempotent": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w07-03"></a>

## W07-03 — 호스트 USB session·앱 준비·IME snapshot

- [ ] **W07-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W07-03.md`(구현 때 생성).
- **직접 선행:** [W07-01](03-worker-and-sessions.md#w07-01), [W02-04](01-foundation-probes.md#w02-04)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 + 직접 선행 receipt의 interface/제약. 추적: R02, R05, R14, R25.
- **검증 등급:** `live_integration`. 환경: `local_python`, `usb_android`.
- **변경 파일:** `src/aiqa/environments/usb_android.py`, `src/aiqa/worker/resources.py`. 시험: `tests/integration/test_w07.py`.
- **입출력 계약:** `prepare_android_session(spec: EnvironmentSpec, lease: Lease) -> SessionHandle`
- **구현·화면·예외:** host ADB 지정 serial·화면 잠금/권한·foreground·IME 이전값을 session 에 고정한다. 승인하지 않은 unlock/clear/install 은 하지 않고 캡처 불가를 명시한다.
- **검증 전제:** ready/locked/FLAG_SECURE·다른 serial·허용 없는 reset 을 준비해 physical 상태와 API 결과를 대조한다.
- **작업 순서:** `test_w07_03`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w07.py::test_w07_03 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "serial_pinned": True,
  "locked_blocked": True,
  "unapproved_reset_count": 0
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w07-04"></a>

## W07-04 — release·quarantine·recover 증명

- [ ] **W07-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W07-04.md`(구현 때 생성).
- **직접 선행:** [W07-02](03-worker-and-sessions.md#w07-02), [W07-03](03-worker-and-sessions.md#w07-03), [W09-03](03-worker-and-sessions.md#w09-03)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 + 직접 선행 receipt의 interface/제약. 추적: R11, R12, R15, R25.
- **검증 등급:** `live_integration`. 환경: `local_python`, `local_linux_vm`, `usb_android`.
- **변경 파일:** `src/aiqa/worker/resources.py`, `src/aiqa/api/worker.py`, `src/aiqa/environments/base.py`. 시험: `tests/integration/test_w07.py`.
- **입출력 계약:** `recover_resource(worker: WorkerScope, resource_id: UUID, proof: RecoveryProof) -> ResourceView`
- **구현·화면·예외:** browser/process/temp·USB/IME 복구 결과가 증명된 때만 ready 다. lease 만료는 해제 증명이 아니고 quarantine 유지, recovery 는 별도 진단이며 진행 job 재개가 아니다.
- **검증 전제:** 정리 성공/실패/timeout 과 stale generation recovery·실제 process 생존을 비교한다.
- **작업 순서:** `test_w07_04`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w07.py::test_w07_04 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "failed_cleanup_state": "quarantined",
  "expired_lease_auto_ready": False,
  "stale_recovery_rejected": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w08-01"></a>

## W08-01 — purpose 별 payload 와 영구 접수 receipt

- [x] **W08-01 완료** — 상태: `complete`. 근거: [W08-01 인계](../validation/tasks/W08-01.md).
- **직접 선행:** [W06-09](02b-job-evidence-schema.md#w06-09), [W00-04](00-bootstrap.md#w00-04)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C14 + 직접 선행 receipt의 interface/제약. 추적: R10, R12.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/store/queue.py`, `src/aiqa/api/jobs.py`, `src/aiqa/contracts/jobs.py`. 시험: `tests/integration/test_w08.py`.
- **입출력 계약:** `enqueue_job(tx: Transaction, input: JobSubmission, key: IdempotencyKey) -> JobReceipt`
- **구현·화면·예외:** C04 purpose allowlist·owner CHECK·scope·멱등 key/body 를 검사하고 REC/ITEM 생성과 job/receipt 를 한 transaction 에 저장한다. 장기 작업은 202/IDs 로 응답하고 API 재시작 후 queue 를 읽는다.
- **검증 전제:** 같은 key/body 두 번·다른 body·unknown purpose·REC/job 사이 rollback 을 요청한다.
- **작업 순서:** `test_w08_01`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w08.py::test_w08_01 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "same_key_job_count": 1,
  "different_body_status": 409,
  "unknown_purpose_status": 422,
  "partial_owner_rows": 0
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w08-02"></a>

## W08-02 — 원자 claim·slot1·순차 선행

- [x] **W08-02 완료** — 상태: `complete`. 근거: [W08-02 인계](../validation/tasks/W08-02.md).
- **직접 선행:** [W08-01](03-worker-and-sessions.md#w08-01)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C14 + 직접 선행 receipt의 interface/제약. 추적: R10, R12, R22, R25.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/store/queue.py`, `src/aiqa/api/worker.py`, `src/aiqa/worker/service.py`. 시험: `tests/integration/test_w08.py`.
- **입출력 계약:** `claim_job(worker: WorkerScope, now: UtcInstant) -> JobLease | None`
- **구현·화면·예외:** 총 slot1·physical resource1·앞 ITEM terminal+정리·approved purpose/scope 를 같은 짧은 transaction 에서 검사한다. 관리 job 도 slot 을 소비하되 physical session 은 purpose 에 따른다.
- **검증 전제:** 동시 worker claim·동일 기기 별칭·관리 job 과 RUN·앞 ITEM cleanup 중 다음 claim 을 경쟁시킨다.
- **작업 순서:** `test_w08_02`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w08.py::test_w08_02 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "active_slots_max": 1,
  "per_device_max": 1,
  "double_claims": 0,
  "claim_before_cleanup": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w08-03"></a>

## W08-03 — heartbeat·generation·runner ACK 멱등

- [x] **W08-03 완료** — 상태: `complete`. 근거: [W08-03 인계](../validation/tasks/W08-03.md).
- **직접 선행:** [W08-02](03-worker-and-sessions.md#w08-02)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C14 + 직접 선행 receipt의 interface/제약. 추적: R10, R12.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/api/worker.py`, `src/aiqa/store/queue.py`, `src/aiqa/worker/service.py`. 시험: `tests/integration/test_w08.py`.
- **입출력 계약:** `renew_lease(worker: WorkerScope, lease: LeaseToken) -> LeaseView; acknowledge_attempt(lease: LeaseToken, runner_nonce: UUID) -> AttemptReceipt`
- **구현·화면·예외:** worker 2 초 poll·heartbeat10 초·lease45 초를 적용한다. claim 에서 만든 attempt 에 같은 lease/nonce ACK 는 같은 attempt/runner 를 확인할 뿐 새로 만들지 않는다. expired generation 은 409 다. 모델 대기에도 heartbeat 가 동작한다.
- **검증 전제:** fake clock 과 네트워크 지연으로 중복 ACK·다른 nonce·lease 만료·model 대기를 재현한다.
- **작업 순서:** `test_w08_03`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w08.py::test_w08_03 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "duplicate_ack_attempts": 1,
  "stale_generation_status": 409,
  "lease_seconds": 45,
  "heartbeat_seconds": 10
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w08-04"></a>

## W08-04 — event cursor·spool ACK·late inbox

- [x] **W08-04 완료** — 상태: `complete`. 근거: [W08-04 인계](../validation/tasks/W08-04.md).
- **직접 선행:** [W08-03](03-worker-and-sessions.md#w08-03)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C14 + 직접 선행 receipt의 interface/제약. 추적: R07, R12, R15.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/api/worker.py`, `src/aiqa/store/evidence.py`, `src/aiqa/worker/service.py`. 시험: `tests/integration/test_w08.py`.
- **입출력 계약:** `ingest_events(lease: LeaseToken, events: list[EventEnvelope]) -> IngestReceipt`
- **구현·화면·예외:** attempt/local_seq/hash 멱등 ingest 와 committed contiguous seq 를 반환한다. generation 만료/terminal 뒤 event 는 stale 감사 inbox 로 분리하고 QA 를 바꾸지 않는다. UI project commit cursor 와 attempt seq 를 혼용하지 않는다.
- **검증 전제:** seq1/3 도착·2 재전송·동일 3·다른 3·terminal 후 4 를 보내고 확정 result/hash 를 조회한다.
- **작업 순서:** `test_w08_04`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w08.py::test_w08_04 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "gap_ack_before_seq2": 1,
  "contiguous_ack_after_seq2": 3,
  "changed_event_status": 409,
  "terminal_hash_unchanged": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w08-05"></a>

## W08-05 — API 재시작과 유효 runner 조정

- [x] **W08-05 완료** — 상태: `complete`. 근거: [W08-05 인계](../validation/tasks/W08-05.md).
- **직접 선행:** [W08-04](03-worker-and-sessions.md#w08-04)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C14 + 직접 선행 receipt의 interface/제약. 추적: R10, R12, R15, R26.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/store/queue.py`, `src/aiqa/worker/service.py`, `src/aiqa/api/lifecycle.py`. 시험: `tests/integration/test_w08.py`.
- **입출력 계약:** `reconcile_jobs(now: UtcInstant) -> ReconciliationReport`
- **구현·화면·예외:** API 시작 시 queued 를 유지하고 lease/worker 상태를 검사한다. 살아 있는 유효 generation 만 계속할 수 있고 watchdog 경과/terminal/재부팅 runner 를 자동 재개하지 않는다. stale/lost 결과와 resource quarantine 을 남긴다.
- **검증 전제:** queued 와 running 이 있는 상태에서 API 만 재시작·worker 사망·PC 재시작을 구분해 복원한다.
- **작업 순서:** `test_w08_05`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w08.py::test_w08_05 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "queued_preserved": True,
  "dead_runner_resumed": False,
  "expired_resource": "quarantined"
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w09-01"></a>

## W09-01 — 영구 취소 flag·늦은 응답 행동 차단

- [x] **W09-01 완료** — 상태: `complete`. 근거: [W09-01 인계](../validation/tasks/W09-01.md).
- **직접 선행:** [W08-05](03-worker-and-sessions.md#w08-05)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C09 / C14 + 직접 선행 receipt의 interface/제약. 추적: R11, R12.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/store/queue.py`, `src/aiqa/worker/control.py`, `src/aiqa/api/jobs.py`. 시험: `tests/integration/test_w09.py`.
- **입출력 계약:** `cancel_job(actor: Actor, job_id: UUID, expected_state: str) -> JobSnapshot; RunControl.checkpoint() -> ControlDecision`
- **구현·화면·예외:** 취소 요청을 DB 에 먼저 기록하고 모델 전후/lookup 전/dispatch 직전에 신뢰 checkpoint 를 둔다. UI 요청 성공·runner 정지·cleanup 완료를 분리한다. finalizing/terminal 의 새 취소는 409, 같은 key 기존 취소 재전송은 원래 receipt 이며 결과 변경 0 이다.
- **검증 전제:** model 대기 중 cancel→늦은 유효 action 응답과 finish/cancel 동시 경합을 주입한다.
- **작업 순서:** `test_w09_01`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w09.py::test_w09_01 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "late_response_dispatches": 0,
  "cancel_persisted": True,
  "terminal_result_changed": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w09-02"></a>

## W09-02 — watchdog·lease 여유·실행 한도

- [x] **W09-02 완료** — 상태: `complete`. 근거: [W09-02 인계](../validation/tasks/W09-02.md).
- **직접 선행:** [W09-01](03-worker-and-sessions.md#w09-01)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C09 / C14 + 직접 선행 receipt의 interface/제약. 추적: R11, R12, R13.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/worker/control.py`, `src/aiqa/worker/runner.py`. 시험: `tests/integration/test_w09.py`.
- **입출력 계약:** `RunControl.authorize_next_action(now: MonotonicInstant, lease: LeaseView) -> ControlDecision`
- **구현·화면·예외:** watchdog30 초·action 전 lease 여유 10 초·전체 600 초/action50/model80 제안 한도를 적용한다. 전송 retry/model retry 와 실제 action/whole attempt 수를 구별한다.
- **검증 전제:** fake clock 경계 29/30 초·lease 남은 9/10 초·action49/50/51 을 관찰한다.
- **작업 순서:** `test_w09_02`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w09.py::test_w09_02 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "watchdog_seconds": 30,
  "minimum_lease_margin": 10,
  "action51_dispatched": False,
  "automatic_attempt_retries": 0
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w09-03"></a>

## W09-03 — Windows process tree·VM 정리와 격리

- [x] **W09-03 완료** — 상태: `complete`. 근거: [W09-03 인계](../validation/tasks/W09-03.md).
- **직접 선행:** [W09-02](03-worker-and-sessions.md#w09-02)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C09 / C14 + 직접 선행 receipt의 interface/제약. 추적: R11, R15, R25.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/worker/processes.py`, `src/aiqa/worker/runner.py`, `src/aiqa/worker/isolated_web.py`. 시험: `tests/integration/test_w09.py`.
- **입출력 계약:** `stop_runner(attempt_id: UUID, grace_seconds: int = 5) -> StopReport; cleanup_attempt(attempt_id: UUID, deadline_seconds: int = 30) -> CleanupReport`
- **구현·화면·예외:** 취소 5 초 유예 후 Windows child tree/VM script/context 를 정리한다. 호스트 API 나 다른 사용자 프로세스를 이름만 보고 종료하지 않는다. proof 없으면 quarantine, finally 경로는 engine 예외에도 실행한다.
- **검증 전제:** 호스트의 테스트용 child process를 실제 생성/종료하고 관련 없는 process 보존을 검사한다. VM/IME 실패는 테스트용 provider로 오류 경로만 검사하며 실제 환경 정리는 W07-04/W27-02에서 확인한다.
- **작업 순서:** `test_w09_03`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w09.py::test_w09_03 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "cancel_grace": 5,
  "cleanup_limit": 30,
  "unrelated_processes_killed": 0,
  "unproven_resource": "quarantined"
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w09-04"></a>

## W09-04 — lost·취소·정리 결과와 QA 분리

- [x] **W09-04 완료** — 상태: `complete`. 근거: [W09-04 인계](../validation/tasks/W09-04.md).
- **직접 선행:** [W09-03](03-worker-and-sessions.md#w09-03), [W23-01](09-results-and-analytics.md#w23-01)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C09 / C14 + 직접 선행 receipt의 interface/제약. 추적: R06, R11, R12, R31.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/worker/runner.py`, `src/aiqa/domain/verdicts.py`, `src/aiqa/store/queue.py`. 시험: `tests/integration/test_w09.py`.
- **입출력 계약:** `finalize_job_control(input: JobFinishInput) -> JobSnapshot`
- **구현·화면·예외:** REC/관리 job 은 모든 종료 사유에서 QA=null 이다. ITEM 의 관측된 required violation 은 cancel/lost 에도 FAIL latch, 없는 불명 실행은 INCONCLUSIVE 다. cleanup failure 는 별도 fact 와 resource 상태로 남긴다.
- **검증 전제:** recording/export/package_rebuild/model_check lost·위반 후 cancel·dispatch 뒤 crash 결과를 관찰한다.
- **작업 순서:** `test_w09_04`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w09.py::test_w09_04 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "management_verdict": None,
  "recording_verdict": None,
  "violation_then_cancel": "FAIL",
  "uncertain_after_dispatch": "INCONCLUSIVE"
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

## 영역 종료 점검

- 카드·TASK_INDEX·실제 인계 상태를 맞춘다. 과거 완료를 문서 정리로 다시 구현하거나 무효화하지 않는다.
- 부모 W는 소속 leaf와 parent_gate_tasks/원래 통합 조건까지 만족해야 완료다.
- [UI_COVERAGE](UI_COVERAGE.md)·[COVERAGE](COVERAGE.md)의 실제 수용 조건은 그대로 유지한다.
