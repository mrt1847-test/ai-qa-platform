# E-1 · 행동·증거·spool·모델 계측 · 상세 작업서 v0.8

제품 설계 v0.6 + [보완 계약](CONTRACTS.md). **완료8 / 12**.
[Current 큐](../../NEXT_ACTION.md) · [전체 색인](README.md) · [차단/선행 수정](SCHEDULING.md) · [인계](HANDOFF.md).

카드 한 개와 직접 선행 근거만 읽는다. 기존 코드/complete/blocked 기록을 재사용한다.
검증 등급·live 수용을 구분한다. core fixture는 실제 native 근거가 아니며 최종 검증을 생략하지 않는다.

| 작업 | 직접 선행 | 결과 | 상태 |
|---|---|---|---|
| [W13-01](#w13-01) | [W06-09](02b-job-evidence-schema.md#w06-09), [W04-03](02a-assets-and-scope.md#w04-03) | 행동 제안 schema·대상·도구 정책 gate | complete |
| [W13-02](#w13-02) | [W13-01](05a-action-evidence-and-models.md#w13-01) | 메모리 정제·전 캡처와 실제 하위 행동 | complete |
| [W13-03](#w13-03) | [W13-02](05a-action-evidence-and-models.md#w13-02) | durable dispatch journal·명령 ACK 경계 | complete |
| [W13-04](#w13-04) | [W13-03](05a-action-evidence-and-models.md#w13-03) | 후 캡처·검증 연결·결과불명 보존 | complete |
| [W14-01](#w14-01) | [W06-09](02b-job-evidence-schema.md#w06-09) | 정제 spool·seq·hash·ACK journal | complete |
| [W14-02](#w14-02) | [W14-01](05a-action-evidence-and-models.md#w14-01) | staging→rename→ready·ingest ACK | complete |
| [W14-03](#w14-03) | [W14-02](05a-action-evidence-and-models.md#w14-02) | 파일 reconcile·missing/corruption 조회 | complete |
| [W14-04](#w14-04) | [W14-03](05a-action-evidence-and-models.md#w14-03) | terminal 뒤 read-only 증거 복구 | complete |
| [W15-01](#w15-01) | [W06-09](02b-job-evidence-schema.md#w06-09), [W04-04](02a-assets-and-scope.md#w04-04), [W08-01](03-worker-and-sessions.md#w08-01) | 공통 model broker·role/check/episode 권한 | not_started |
| [W15-02](#w15-02) | [W15-01](05a-action-evidence-and-models.md#w15-01) | usage·retry·late settlement ledger | not_started |
| [W15-03](#w15-03) | [W15-02](05a-action-evidence-and-models.md#w15-02) | 호출 전 예산 예약·deadline·취소 | not_started |
| [W15-04](#w15-04) | [W15-03](05a-action-evidence-and-models.md#w15-03), [W03-01](01-foundation-probes.md#w03-01) | 모델 연결 검사·비용·무키 replay 안내 UI | not_started |

<a id="w13-01"></a>

## W13-01 — 행동 제안 schema·대상·도구 정책 gate

- [x] **W13-01 완료** — 상태: `complete`. 근거: [W13-01 인계](../validation/tasks/W13-01.md).
- **직접 선행:** [W06-09](02b-job-evidence-schema.md#w06-09), [W04-03](02a-assets-and-scope.md#w04-03)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C14 + 직접 선행 receipt의 interface/제약. 추적: R06, R14, R29.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W16-04, W29-03, W30-03에서 별도로 요구한다.
- **실제 통합 담당:** [W16-04](05b-recording-workflow.md#w16-04), [W29-03](06-replay-packages.md#w29-03), [W30-03](06-replay-packages.md#w30-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/recording/action_executor.py`, `src/aiqa/security/action_policy.py`, `src/aiqa/contracts/actions.py`. 시험: `tests/integration/test_w13.py`.
- **입출력 계약:** `PolicyGate.authorize(proposal: ActionProposal, context: StepContext) -> ActionDecision`
- **구현·화면·예외:** tap/type/swipe/back 와 Web 지원 action 을 typed schema 로 제한하고 URL redirect/package/allowlist·승인입력·required path 를 검사한다. 화면/DOM 속 지시는 실행권한이 아니며 raw shell/code 는 거부한다.
- **검증 전제:** 화면 prompt injection·범위밖 URL/package·unknownaction·입력변경·helper rawcommand 를 제안한다.
- **작업 순서:** `test_w13_01`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w13.py::test_w13_01 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "out_of_scope_dispatches": 0,
  "raw_shell_allowed": False,
  "screen_instruction_authoritative": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w13-02"></a>

## W13-02 — 메모리 정제·전 캡처와 실제 하위 행동

- [x] **W13-02 완료** — 상태: `complete`. 근거: [W13-02 인계](../validation/tasks/W13-02.md).
- **직접 선행:** [W13-01](05a-action-evidence-and-models.md#w13-01)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C14 + 직접 선행 receipt의 interface/제약. 추적: R07, R14, R29.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W16-04, W29-03, W30-03에서 별도로 요구한다.
- **실제 통합 담당:** [W16-04](05b-recording-workflow.md#w16-04), [W29-03](06-replay-packages.md#w29-03), [W30-03](06-replay-packages.md#w30-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/security/redaction.py`, `src/aiqa/recording/action_executor.py`, `src/aiqa/adapters/cuawright_web.py`, `src/aiqa/adapters/mobile_agent_android.py`. 시험: `tests/integration/test_w13.py`.
- **입출력 계약:** `prepare_action(proposal: ActionProposal, observation: Observation) -> PreparedAction`
- **구현·화면·예외:** 원본 PNG/DOM/stdout/messages 는 메모리에서 필터 후 보관본만 spool 로 보낸다. compound step 을 각 actual action 으로 분해하고 각각 전캡처를 얻는다. 필터/전캡처 실패는 command 금지, 원본 reasoning debug 저장도금지다. 실제 native/모델 연동 수용은 별도 live gate에 남기고 이 카드의 contract fixture 검증과 구분한다.
- **검증 전제:** 명시된 PNG/DOM/로그 fixture와 3개 ActionProposal을 메모리 필터·보관 경로에 넣어 전 캡처 실패/정제 실패의 command0을 확인한다. 실제 upstream capture hook은 W16-04/W29-03/W30-03에서 입증한다.
- **작업 순서:** `test_w13_02`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w13.py::test_w13_02 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "actions": 3,
  "before_artifacts": 3,
  "raw_secret_on_disk": False,
  "pre_capture_failure_dispatches": 0
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w13-03"></a>

## W13-03 — durable dispatch journal·명령 ACK 경계

- [x] **W13-03 완료** — 상태: `complete`. 근거: [W13-03 인계](../validation/tasks/W13-03.md).
- **직접 선행:** [W13-02](05a-action-evidence-and-models.md#w13-02)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C14 + 직접 선행 receipt의 interface/제약. 추적: R11, R12, R17, R33.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W16-04, W29-03, W30-03에서 별도로 요구한다.
- **실제 통합 담당:** [W16-04](05b-recording-workflow.md#w16-04), [W29-03](06-replay-packages.md#w29-03), [W30-03](06-replay-packages.md#w30-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/recording/action_executor.py`, `src/aiqa/worker/dispatch_journal.py`, `src/aiqa/replay/action_executor.py`. 시험: `tests/integration/test_w13.py`.
- **입출력 계약:** `dispatch_action(prepared: PreparedAction, control: RunControl) -> DispatchReceipt`
- **구현·화면·예외:** planned→lookup_failed 또는 dispatch_started 를 로컬 durable journal 에 flush 한 뒤 native API 를 한 번 호출한다. 이후 acknowledged/observed/unknown 을 append 하며 ACK 미수신을 lookup_failed 로 되돌리지 않는다. journal writefail 이면 dispatch0 이다. 실제 native/모델 연동 수용은 별도 live gate에 남기고 이 카드의 contract fixture 검증과 구분한다.
- **검증 전제:** 실제 durable journal과 테스트용 command executor로 flush 실패·native-call 직후 timeout/ACK 누락을 주입해 순서/횟수를 검사한다. VM/ADB API 경계의 실제 검증은 지정 live task에 남긴다.
- **작업 순서:** `test_w13_03`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w13.py::test_w13_03 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "journal_failure_dispatches": 0,
  "post_dispatch_retries": 0,
  "timeout_reclassified_lookup": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w13-04"></a>

## W13-04 — 후 캡처·검증 연결·결과불명 보존

- [x] **W13-04 완료** — 상태: `complete`. 근거: [W13-04 인계](../validation/tasks/W13-04.md).
- **직접 선행:** [W13-03](05a-action-evidence-and-models.md#w13-03)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C14 + 직접 선행 receipt의 interface/제약. 추적: R06, R07, R12, R29.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W16-04, W29-03, W30-03에서 별도로 요구한다.
- **실제 통합 담당:** [W16-04](05b-recording-workflow.md#w16-04), [W29-03](06-replay-packages.md#w29-03), [W30-03](06-replay-packages.md#w30-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/recording/action_executor.py`, `src/aiqa/contracts/evidence.py`, `src/aiqa/validation/observations.py`. 시험: `tests/integration/test_w13.py`.
- **입출력 계약:** `observe_action(receipt: DispatchReceipt, control: RunControl) -> ActionObservation`
- **구현·화면·예외:** 즉시 후 PNG·capture 시각/geometry·실제명령결과·error/check refs 를 동일 action 에 연결한다. 후캡처 누락/정제실패/rotation 은 incomplete/unknown 이며 재탭 0 이다. read-only 재관찰은 delayed 로 구별한다. 실제 native/모델 연동 수용은 별도 live gate에 남기고 이 카드의 contract fixture 검증과 구분한다.
- **검증 전제:** 테스트용 observer 결과를 실제 evidence 저장에 연결해 3행동 전후6개·후 누락·delayed·rotation 오류를 검사한다. 테스트 capture를 실제 기기 근거로 기록하지 않는다.
- **작업 순서:** `test_w13_04`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w13.py::test_w13_04 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "normal_before_after_png": 6,
  "missing_after_redispatches": 0,
  "delayed_as_immediate": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w14-01"></a>

## W14-01 — 정제 spool·seq·hash·ACK journal

- [x] **W14-01 완료** — 상태: `complete`. 근거: [W14-01 인계](../validation/tasks/W14-01.md).
- **직접 선행:** [W06-09](02b-job-evidence-schema.md#w06-09)
- **읽기:** CONTRACTS C00 / C01 / C03 / C05 / C07 / C14 + 직접 선행 receipt의 interface/제약. 추적: R07, R12, R14, R15.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/worker/spool.py`, `src/aiqa/worker/service.py`, `src/aiqa/contracts/evidence.py`. 시험: `tests/integration/test_w14.py`.
- **입출력 계약:** `append_evidence(envelope: EvidenceEnvelope) -> LocalReceipt; acknowledge_spool(receipt: IngestReceipt) -> AckState`
- **구현·화면·예외:** attempt/local_seq/hash·정제 PNG/log 를 durable spool 에 append 한다. 서버 contiguous ACK/hash 가 검증된 파일만 정리 가능하다. 최대 7 일은 ACK 된 spool 정책이고 미 ACK 자료는 자동폐기하지 않으며 한도압박시 새행동을 멈춘다.
- **검증 전제:** 전송전/후 crash·중복전송·seq gap·7 일 경과 미 ACK·disk full 을 주입한다.
- **작업 순서:** `test_w14_01`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w14.py::test_w14_01 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "unacked_deleted": 0,
  "ack_hash_required": True,
  "duplicate_actions_from_upload": 0,
  "pressure_stops_actions": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w14-02"></a>

## W14-02 — staging→rename→ready·ingest ACK

- [x] **W14-02 완료** — 상태: `complete`. 근거: [W14-02 인계](../validation/tasks/W14-02.md).
- **직접 선행:** [W14-01](05a-action-evidence-and-models.md#w14-01)
- **읽기:** CONTRACTS C00 / C01 / C03 / C05 / C07 / C14 + 직접 선행 receipt의 interface/제약. 추적: R07, R12, R14, R29.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/store/evidence.py`, `src/aiqa/store/artifacts.py`, `src/aiqa/api/artifacts.py`. 시험: `tests/integration/test_w14.py`.
- **입출력 계약:** `ingest_artifact(lease: LeaseToken, input: ArtifactUpload) -> ArtifactReceipt`
- **구현·화면·예외:** generated object key·길이/hash·같은볼륨 tmp flush/rename 뒤 DBready+ref/ACK 를 확정한다. project/owner/lease/size 를 검사하고 임의 path·확장자 MIME 불일치·hash 오류는 quarantine/거부다.
- **검증 전제:** rename 뒤 DBfail·중복 hash 업로드·다른 project owner·잘못된 hash/길이·path traversal 을 요청한다.
- **작업 순서:** `test_w14_02`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w14.py::test_w14_02 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "ack_before_ready": False,
  "hash_mismatch_ready": False,
  "path_escape": False,
  "duplicate_receipt_same": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w14-03"></a>

## W14-03 — 파일 reconcile·missing/corruption 조회

- [x] **W14-03 완료** — 상태: `complete`. 근거: [W14-03 인계](../validation/tasks/W14-03.md).
- **직접 선행:** [W14-02](05a-action-evidence-and-models.md#w14-02)
- **읽기:** CONTRACTS C00 / C01 / C03 / C05 / C07 / C14 + 직접 선행 receipt의 interface/제약. 추적: R07, R14, R15.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/store/artifacts.py`, `src/aiqa/api/artifacts.py`, `src/aiqa/web/templates/components/evidence_state.html`. 시험: `tests/integration/test_w14.py`.
- **입출력 계약:** `reconcile_artifacts() -> ArtifactReconcileReport; GET /api/v1/artifacts/{a} -> ArtifactStream | EvidenceUnavailable`
- **구현·화면·예외:** orphan tmp/rename-after-crash·DBready 파일없음/hash 변경을 점검하고 운영보관상태를 갱신한다. 원본 result/hash 를 새파일로 대체하지 않으며 missing/expired/corruption 을 UI 에서 구별한다.
- **검증 전제:** 각 파일상태를 실제저장소에 만들고 권한내 image/log GET·ready 조건·기존 finalhash 를 확인한다.
- **작업 순서:** `test_w14_03`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w14.py::test_w14_03 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "missing_file_returned_success": False,
  "corruption_detected": True,
  "original_result_hash_changed": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w14-04"></a>

## W14-04 — terminal 뒤 read-only 증거 복구

- [x] **W14-04 완료** — 상태: `complete`. 근거: [W14-04 인계](../validation/tasks/W14-04.md).
- **직접 선행:** [W14-03](05a-action-evidence-and-models.md#w14-03)
- **읽기:** CONTRACTS C00 / C01 / C03 / C05 / C07 / C14 + 직접 선행 receipt의 interface/제약. 추적: R12, R15, R30.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/recording/recovery.py`, `src/aiqa/api/recordings.py`, `src/aiqa/worker/service.py`. 시험: `tests/integration/test_w14.py`.
- **입출력 계약:** `POST /api/v1/recordings/{r}/evidence-recoveries -> JobReceipt; recover_evidence(input: EvidenceRecoverySpec) -> ManifestReceipt`
- **구현·화면·예외:** evidence_sync 는 제어권한없는 관리 job·owner null/source ref 다. 실제 미전송 capture 만 새 recovery manifest 로 보존하고 같은 key 같은 receipt/다른 body409. 늦은사진은 delayed, 기존 version/QA/승인변경 0 이며 새 materialization 은 W16-07 이다.
- **검증 전제:** lost REC 의 원래 미전송후 PNG 와 나중찍은 PNG 를 업로드하고 중복/변경 body 를 보낸다.
- **작업 순서:** `test_w14_04`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w14.py::test_w14_04 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "recovery_new_manifest": True,
  "old_result_unchanged": True,
  "delayed_satisfies_immediate": False,
  "recovery_dispatches": 0
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w15-01"></a>

## W15-01 — 공통 model broker·role/check/episode 권한

- [ ] **W15-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W15-01.md`(구현 때 생성).
- **직접 선행:** [W06-09](02b-job-evidence-schema.md#w06-09), [W04-04](02a-assets-and-scope.md#w04-04), [W08-01](03-worker-and-sessions.md#w08-01)
- **읽기:** CONTRACTS C00 / C01 / C04 / C06 / C14 + 직접 선행 receipt의 interface/제약. 추적: R13, R14, R17, R33.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W15-04, W32-02에서 별도로 요구한다.
- **실제 통합 담당:** [W15-04](05a-action-evidence-and-models.md#w15-04), [W32-02](10-retention-and-release-gates.md#w32-02). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/models/client.py`, `src/aiqa/models/broker.py`, `src/aiqa/contracts/models.py`. 시험: `tests/integration/test_w15.py`.
- **입출력 계약:** `ModelClient.invoke(request: ModelRequest, control: RunControl) -> ModelResponse`
- **구현·화면·예외:** authoring/verification/healing/maintenance 요청을 broker 한곳으로 모으고 role binding·check/episode owner·actualmodel·callID 를 검사한다. replay script 에는 key/modelnetwork 를 주지 않고 일반 action actor0 를 강제한다.
- **검증 전제:** 등록하지않은 check·잘못된 role·다른 ITEM episode·script 직접 model 호출·정상 authoring 을 대조한다.
- **작업 순서:** `test_w15_01`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w15.py::test_w15_01 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "unowned_call_allowed": False,
  "cross_item_call_allowed": False,
  "script_has_key": False,
  "authoring_metered": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w15-02"></a>

## W15-02 — usage·retry·late settlement ledger

- [ ] **W15-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W15-02.md`(구현 때 생성).
- **직접 선행:** [W15-01](05a-action-evidence-and-models.md#w15-01)
- **읽기:** CONTRACTS C00 / C01 / C04 / C06 / C14 + 직접 선행 receipt의 interface/제약. 추적: R13, R35.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W15-04, W32-02에서 별도로 요구한다.
- **실제 통합 담당:** [W15-04](05a-action-evidence-and-models.md#w15-04), [W32-02](10-retention-and-release-gates.md#w32-02). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/models/usage.py`, `src/aiqa/store/usage.py`, `src/aiqa/models/client.py`. 시험: `tests/integration/test_w15.py`.
- **입출력 계약:** `record_model_usage(input: ModelCallSettlement) -> UsageReceipt; append_usage_adjustment(input: UsageAdjustmentInput) -> UsageLedgerView`
- **구현·화면·예외:** 모든 실제 전송/retry 를 call 로 세고 nullableinput/output/cache/image·measured/estimated/unreported·actualmodel·tariff/currency 를 기록한다. 미사용 0/not_used 와 계측누락 null/unknown 을 분리하고 늦은정산은 appendseq 다.
- **검증 전제:** usage 미보고·일부 role 누락·429 재전송·latebill·중복 providerrequest 를 계수한다.
- **작업 순서:** `test_w15_02`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w15.py::test_w15_02 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "unreported_tokens": None,
  "unused_role_calls": 0,
  "partial_total": "partial",
  "late_rewrites_original": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w15-03"></a>

## W15-03 — 호출 전 예산 예약·deadline·취소

- [ ] **W15-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W15-03.md`(구현 때 생성).
- **직접 선행:** [W15-02](05a-action-evidence-and-models.md#w15-02)
- **읽기:** CONTRACTS C00 / C01 / C04 / C06 / C14 + 직접 선행 receipt의 interface/제약. 추적: R11, R13, R33.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W15-04, W32-02에서 별도로 요구한다.
- **실제 통합 담당:** [W15-04](05a-action-evidence-and-models.md#w15-04), [W32-02](10-retention-and-release-gates.md#w32-02). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/models/budget.py`, `src/aiqa/models/broker.py`, `src/aiqa/worker/control.py`. 시험: `tests/integration/test_w15.py`.
- **입출력 계약:** `reserve_model_call(input: ModelReservation, control: RunControl) -> Reservation; settle_model_call(reservation: Reservation, response: ModelResponse) -> Settlement`
- **구현·화면·예외:** 호출전최대비용/시간/호출수를 원자예약하고 응답후정산한다. strict 가격불명은차단·estimate 명시시불완전표시, 늦은응답은행동불가다. healer 합계 2 회는전송 retry 포함이며 일반 retry2 보다 우선한다.
- **검증 전제:** 동시예산예약·가격누락·호출 80/81·취소응답·healer2 회후 retry 를 주입한다.
- **작업 순서:** `test_w15_03`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w15.py::test_w15_03 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "overbooked_reservations": 0,
  "strict_unknown_price_allowed": False,
  "healer_third_call": False,
  "late_action_dispatched": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w15-04"></a>

## W15-04 — 모델 연결 검사·비용·무키 replay 안내 UI

- [ ] **W15-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W15-04.md`(구현 때 생성).
- **직접 선행:** [W15-03](05a-action-evidence-and-models.md#w15-03), [W03-01](01-foundation-probes.md#w03-01)
- **읽기:** CONTRACTS C00 / C01 / C04 / C06 + 직접 선행 receipt의 interface/제약. 추적: R13, R14, R17, UI-15.05.
- **검증 등급:** `live_integration`. 환경: `local_python`, `model_binding`.
- **변경 파일:** `src/aiqa/api/model_bindings.py`, `src/aiqa/web/templates/settings.html`, `src/aiqa/worker/model_check.py`. 시험: `tests/integration/test_w15.py`.
- **입출력 계약:** `POST /api/v1/model-bindings/{b}/checks -> JobReceipt; GET /api/v1/model-bindings/{b}/compatibility -> CompatibilityReport`
- **구현·화면·예외:** UI15 에 role 별호환·마지막검사/actualmodel·usage 상태/비용·key 가용성을 표시한다. 검사실행은 명시 model_check 관리 job·QA=null, 비용안내후요청한다. 결정적/OFFreplay 는 모델연결검사없이도 허용한다.
- **검증 전제:** key 없는 binding·검사 timeout·호환실패·실제허용최소호출·결정적 replay 의 preflight 를 확인한다.
- **작업 순서:** `test_w15_04`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w15.py::test_w15_04 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "check_job_verdict": None,
  "replay_requires_model_check": False,
  "key_plaintext_echo": False,
  "test_calls_metered": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

## 영역 종료 점검

- 카드·TASK_INDEX·실제 인계 상태를 맞춘다. 과거 완료를 문서 정리로 다시 구현하거나 무효화하지 않는다.
- 부모 W는 소속 leaf와 parent_gate_tasks/원래 통합 조건까지 만족해야 완료다.
- [UI_COVERAGE](UI_COVERAGE.md)·[COVERAGE](COVERAGE.md)의 실제 수용 조건은 그대로 유지한다.
