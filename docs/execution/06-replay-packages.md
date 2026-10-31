# F · 승인 package·모델 없는 재생 · 상세 작업서 v0.8

제품 설계 v0.6 + [보완 계약](CONTRACTS.md). **완료0 / 10**.
[Current 큐](../../NEXT_ACTION.md) · [전체 색인](README.md) · [차단/선행 수정](SCHEDULING.md) · [인계](HANDOFF.md).

카드 한 개와 직접 선행 근거만 읽는다. 기존 코드/complete/blocked 기록을 재사용한다.
검증 등급·live 수용을 구분한다. core fixture는 실제 native 근거가 아니며 최종 검증을 생략하지 않는다.

| 작업 | 직접 선행 | 결과 | 상태 |
|---|---|---|---|
| [W29-01](#w29-01) | [W16-05](05b-recording-workflow.md#w16-05), [W06-09](02b-job-evidence-schema.md#w06-09) | package body·hash·source mapping 검증 | not_started |
| [W29-02](#w29-02) | [W29-01](06-replay-packages.md#w29-01), [W01-01](01-foundation-probes.md#w01-01) | raw Web code 에서 제한 IPC compiler | not_started |
| [W29-03](#w29-03) | [W29-02](06-replay-packages.md#w29-02), [W07-02](03-worker-and-sessions.md#w07-02), [W01-02](01-foundation-probes.md#w01-02), [W13-04](05a-action-evidence-and-models.md#w13-04) | trusted driver IPC·lease·capture dispatch | not_started |
| [W29-04](#w29-04) | [W29-02](06-replay-packages.md#w29-02), [W14-03](05a-action-evidence-and-models.md#w14-03) | artifact ready 후 package/version 원자 확정 | not_started |
| [W29-05](#w29-05) | [W29-04](06-replay-packages.md#w29-04) | Web direct runner·현재 조건·actor0 | not_started |
| [W29-06](#w29-06) | [W29-04](06-replay-packages.md#w29-04), [W10-08](04a-case-management-ui.md#w10-08) | code·plan·lock·mapping·재컴파일 조회 UI | not_started |
| [W30-01](#w30-01) | [W29-04](06-replay-packages.md#w29-04), [W16-05](05b-recording-workflow.md#w16-05), [W06-09](02b-job-evidence-schema.md#w06-09) | Android trace→immutable action plan | not_started |
| [W30-02](#w30-02) | [W30-01](06-replay-packages.md#w30-01) | 결정적 binding·고정 좌표 preflight | not_started |
| [W30-03](#w30-03) | [W30-02](06-replay-packages.md#w30-02), [W07-03](03-worker-and-sessions.md#w07-03), [W13-04](05a-action-evidence-and-models.md#w13-04) | Android direct runner·행동별 현재 증거 | not_started |
| [W30-04](#w30-04) | [W30-03](06-replay-packages.md#w30-03), [W29-06](06-replay-packages.md#w29-06) | 양 플랫폼 replay 동등 계약 gate | not_started |

<a id="w29-01"></a>

## W29-01 — package body·hash·source mapping 검증

- [ ] **W29-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W29-01.md`(구현 때 생성).
- **직접 선행:** [W16-05](05b-recording-workflow.md#w16-05), [W06-09](02b-job-evidence-schema.md#w06-09)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C07 / C14 + 직접 선행 receipt의 interface/제약. 추적: R17, R29, R34.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/replay/packages.py`, `src/aiqa/contracts/replay.py`. 시험: `tests/integration/test_w29.py`.
- **입출력 계약:** `validate_package_body(body: ReplayPackageBody, source: RecordingManifest) -> PackageValidation`
- **구현·화면·예외:** source manifest/raw source hash·runtime/compiler/lock·code 또는 plan·각 step/action/line mapping 을 검증한다. produced version ID/hash 는 package hash body 밖 receipt, compiled hash 는 raw source 밖이다. 누락/불명 mapping 은 ready 금지다.
- **검증 전제:** source hash 불일치·mapping 없는 helper·hash 순환 필드·지원하지 않는 runtime 을 입력한다.
- **작업 순서:** `test_w29_01`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w29.py::test_w29_01 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "hash_cycle_allowed": False,
  "unmapped_ready": False,
  "foreign_source_allowed": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w29-02"></a>

## W29-02 — raw Web code 에서 제한 IPC compiler

- [ ] **W29-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W29-02.md`(구현 때 생성).
- **직접 선행:** [W29-01](06-replay-packages.md#w29-01), [W01-01](01-foundation-probes.md#w01-01)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C07 / C14 + 직접 선행 receipt의 interface/제약. 추적: R14, R17, R34.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/replay/compiler.py`, `src/aiqa/replay/ipc.py`, `patches/cuawright/compiler.md`. 시험: `tests/integration/test_w29.py`.
- **입출력 계약:** `compile_replay_package(source: RecordingManifest, compiler: CompilerRef) -> CompiledPackage`
- **구현·화면·예외:** W01 에서 증명한 문법 subset 만 변환하고 raw Playwright/CDP/helper/LLM/subprocess/file/network 우회를 거부한다. 동작/조건/입력/경로/expected 를 변경하지 않으며 각 실제 행동을 qa_runtime 호출에 매핑한다. 정적 AST 검사는 실제 sandbox 를 대체하지 않는다.
- **검증 전제:** 지원 문법과 동적 import/reflection/helper/raw browser 우회·compound 행동을 컴파일한다.
- **작업 순서:** `test_w29_02`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w29.py::test_w29_02 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "unsupported_rejected": True,
  "semantic_expectations_changed": False,
  "every_action_mapped": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w29-03"></a>

## W29-03 — trusted driver IPC·lease·capture dispatch

- [ ] **W29-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W29-03.md`(구현 때 생성).
- **직접 선행:** [W29-02](06-replay-packages.md#w29-02), [W07-02](03-worker-and-sessions.md#w07-02), [W01-02](01-foundation-probes.md#w01-02), [W13-04](05a-action-evidence-and-models.md#w13-04)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C07 + 직접 선행 receipt의 interface/제약. 추적: R12, R14, R17, R25, R29.
- **검증 등급:** `live_integration`. 환경: `local_python`, `local_linux_vm`.
- **변경 파일:** `src/aiqa/replay/driver.py`, `src/aiqa/replay/ipc.py`, `src/aiqa/replay/action_executor.py`, `src/aiqa/worker/isolated_web.py`. 시험: `tests/integration/test_w29.py`.
- **입출력 계약:** `ReplayActionExecutor.execute(command: ReplayCommand, control: RunControl) -> ActionObservation`
- **구현·화면·예외:** driver 만 browser/CDP handle 을 갖고 script 는 same-package typed IPC 만 사용한다. package/action mapping·generation·target scope·전후 capture·durable journal 을 강제하며 script/driver 권한/네트워크를 분리한다.
- **검증 전제:** tampered action ID·다른 lease/package·직접 targetHTTP/CDP/modelnetwork·capture 없는 dispatch 를 실제 경계에서 시도한다.
- **작업 순서:** `test_w29_03`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w29.py::test_w29_03 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "unmapped_dispatches": 0,
  "direct_browser_access": False,
  "model_network_from_script": False,
  "lease_gate_enforced": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w29-04"></a>

## W29-04 — artifact ready 후 package/version 원자 확정

- [ ] **W29-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W29-04.md`(구현 때 생성).
- **직접 선행:** [W29-02](06-replay-packages.md#w29-02), [W14-03](05a-action-evidence-and-models.md#w14-03)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C07 / C14 + 직접 선행 receipt의 interface/제약. 추적: R08, R12, R34.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/replay/packages.py`, `src/aiqa/recording/service.py`, `src/aiqa/store/artifacts.py`. 시험: `tests/integration/test_w29.py`.
- **입출력 계약:** `materialize_recording(manifest_id: UUID, compiled: CompiledPackage | None) -> MaterializationReceipt`
- **구현·화면·예외:** W16 fallback materializer 를 확장해 compiler artifact ready→case version/package/steps/receipt/CAS 를 한 transaction 에서 commit 한다. deferred composite FK 로 같은 case 양방향을 검증한다. 같은 manifest 재요청은 기존 receipt, partial commit 은 0 이다.
- **검증 전제:** artifact 준비 실패·deferred FK commit 실패·version/package 중간 crash·같은 source 동시 materialize 를 재현한다.
- **작업 순서:** `test_w29_04`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w29.py::test_w29_04 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "ready_package_count": 1,
  "partial_commit_rows": 0,
  "duplicate_manifest_versions": 1,
  "late_attach_allowed": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w29-05"></a>

## W29-05 — Web direct runner·현재 조건·actor0

- [ ] **W29-05 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W29-05.md`(구현 때 생성).
- **직접 선행:** [W29-04](06-replay-packages.md#w29-04)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C07 + 직접 선행 receipt의 interface/제약. 추적: R04, R06, R09, R17.
- **검증 등급:** `live_integration`. 환경: `local_python`, `local_linux_vm`.
- **변경 파일:** `src/aiqa/replay/web_runner.py`, `src/aiqa/worker/runner.py`, `src/aiqa/validation/web.py`. 시험: `tests/integration/test_w29.py`.
- **입출력 계약:** `ReplayRunner.run(spec: ReplaySpec, sink: EventSink, control: RunControl) -> ReplayOutcome`
- **구현·화면·예외:** 새 VM context 에서 승인 package/runtime/lock/hash 를 검증하고 순서/locator/wait/입력 ref 를 그대로 재생한다. locator10 초/navigation30 초 기본·단일 tab/고정 viewport 를 검사하고 현재 관찰을 만든다. auto route/general AI fallback 은 없다.
- **검증 전제:** key 제거/endpoint 차단·정상합성흐름·문구/값 불일치·추가탭·navigation timeout 을 실제 Chromium 에서 확인한다.
- **작업 순서:** `test_w29_05`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w29.py::test_w29_05 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "actor_calls": 0,
  "old_pass_reused": False,
  "multi_tab_blocked": True,
  "post_dispatch_timeout_reclicked": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w29-06"></a>

## W29-06 — code·plan·lock·mapping·재컴파일 조회 UI

- [ ] **W29-06 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W29-06.md`(구현 때 생성).
- **직접 선행:** [W29-04](06-replay-packages.md#w29-04), [W10-08](04a-case-management-ui.md#w10-08)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C07 / C14 + 직접 선행 receipt의 interface/제약. 추적: R07, R21, R34, UI-04.08, UI-07.01.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/api/cases.py`, `src/aiqa/web/templates/components/package_view.html`, `src/aiqa/web/templates/case_detail.html`. 시험: `tests/integration/test_w29.py`.
- **입출력 계약:** `GET /api/v1/case-versions/{v}/replay-package -> ReplayPackageView`
- **구현·화면·예외:** UI04/07 에 source/approved code 또는 plan·package/runtime/compiler/lock hash·action/line mapping·ready/차단 이유를 읽기 전용으로 표시한다. package 없음에도 기록 조회는 가능하다. rebuild 요청 route 는 W16-07 에서 연결하며 무조건 성공 버튼을 만들지 않는다.
- **검증 전제:** package null/compile failure/mapping failure/ready·파일 만료·다른 project package 조회를 확인한다.
- **작업 순서:** `test_w29_06`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w29.py::test_w29_06 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "null_package_record_visible": True,
  "raw_code_inplace_edit": False,
  "mapping_links_exact": True,
  "cross_project_denied": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w30-01"></a>

## W30-01 — Android trace→immutable action plan

- [ ] **W30-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W30-01.md`(구현 때 생성).
- **직접 선행:** [W29-04](06-replay-packages.md#w29-04), [W16-05](05b-recording-workflow.md#w16-05), [W06-09](02b-job-evidence-schema.md#w06-09)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C07 / C14 + 직접 선행 receipt의 interface/제약. 추적: R05, R14, R17, R34.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/replay/android_plan.py`, `src/aiqa/replay/packages.py`, `src/aiqa/contracts/replay.py`. 시험: `tests/integration/test_w30.py`.
- **입출력 계약:** `compile_android_plan(source: RecordingManifest) -> CompiledPackage`
- **구현·화면·예외:** Mobile-Agent trace 에서 tap/type/swipe/back·의도/target descriptor·secret ref·geometry/rotation/contentbounds·wait/check mapping 을 불변 plan 으로 만든다. 기록의 model loop/prompt 는 replay 명령이 아니다.
- **검증 전제:** 지원 4 행동·rawshell/unknown·매핑없는행동·secret literal·geometry 누락 trace 를 변환한다.
- **작업 순서:** `test_w30_01`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w30.py::test_w30_01 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "supported_actions": [
    "tap",
    "type",
    "swipe",
    "back"
  ],
  "raw_model_loop_in_plan": False,
  "secret_literal_saved": False,
  "missing_geometry_ready": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w30-02"></a>

## W30-02 — 결정적 binding·고정 좌표 preflight

- [ ] **W30-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W30-02.md`(구현 때 생성).
- **직접 선행:** [W30-01](06-replay-packages.md#w30-01)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C07 / C14 + 직접 선행 receipt의 interface/제약. 추적: R02, R05, R14, R17.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/replay/android_runner.py`, `src/aiqa/replay/targets.py`, `src/aiqa/environments/usb_android.py`. 시험: `tests/integration/test_w30.py`.
- **입출력 계약:** `resolve_recorded_target(binding: TargetBinding, observation: Observation) -> TargetResolution`
- **구현·화면·예외:** resource-id/text/context 또는 승인된 고정 좌표의 현재 조건을 검사한다. 좌표는 동일 geometry/rotation/contentbounds·승인 관찰조건에서만 사용한다. 회전/크기 불명은 BLOCKED, 임의 AI 탐색·비율추정 탭은 없다.
- **검증 전제:** 같은 UI hierarchy·중복 target·텍스트변경·1080→다른해상도·회전·좌표범위초과를 확인한다.
- **작업 순서:** `test_w30_02`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w30.py::test_w30_02 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "ambiguous_not_dispatched": True,
  "dimension_change_blocked": True,
  "guessed_coordinate_dispatches": 0
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w30-03"></a>

## W30-03 — Android direct runner·행동별 현재 증거

- [ ] **W30-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W30-03.md`(구현 때 생성).
- **직접 선행:** [W30-02](06-replay-packages.md#w30-02), [W07-03](03-worker-and-sessions.md#w07-03), [W13-04](05a-action-evidence-and-models.md#w13-04)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C07 + 직접 선행 receipt의 interface/제약. 추적: R05, R09, R17, R29.
- **검증 등급:** `live_integration`. 환경: `local_python`, `usb_android`.
- **변경 파일:** `src/aiqa/replay/android_runner.py`, `src/aiqa/replay/action_executor.py`, `src/aiqa/environments/usb_android.py`. 시험: `tests/integration/test_w30.py`.
- **입출력 계약:** `ReplayRunner.run(spec: ReplaySpec, sink: EventSink, control: RunControl) -> ReplayOutcome`
- **구현·화면·예외:** host ADB 가 plan 의 원래 행동과 입력 ref 를 신뢰 executor 로 실행한다. Mobile-Agent model loop 는 부르지 않으며 journal/lease/전후 capture·IME 복구를 공통 적용한다. timeout 뒤 같은 명령 재전달은 없다.
- **검증 전제:** 실제 USB tap/type/swipe/back 과 key/endpoint 제거·IME 오류·dispatch 후단절을 확인한다.
- **작업 순서:** `test_w30_03`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w30.py::test_w30_03 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "actor_calls": 0,
  "action_evidence_complete": True,
  "timeout_redispatches": 0,
  "ime_restored_or_quarantined": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w30-04"></a>

## W30-04 — 양 플랫폼 replay 동등 계약 gate

- [ ] **W30-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W30-04.md`(구현 때 생성).
- **직접 선행:** [W30-03](06-replay-packages.md#w30-03), [W29-06](06-replay-packages.md#w29-06)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C07 + 직접 선행 receipt의 interface/제약. 추적: R04, R05, R09, R16, R17, R34.
- **검증 등급:** `live_integration`. 환경: `local_python`, `local_linux_vm`, `usb_android`.
- **변경 파일:** `tests/integration/test_replay_equivalence.py`, `docs/validation/replay-contract.md`. 시험: `tests/integration/test_w30.py`.
- **입출력 계약:** `validate_replay_equivalence(reports: list[ReplayReport]) -> GateDecision`
- **구현·화면·예외:** Web/Android 가 같은 package identity·step/action/check provenance·role call facts·cancel/lease/evidence contract 를 내보내는지 검증한다. 결정적/OFF 에서 credential 과 endpoint 를 제거해 실제 0 호출·매행동증거를 확인한다.
- **검증 전제:** 동일의도 합성케이스를 두 플랫폼에서 각각 새실행하고 성공/위반/증거누락·원본 hash 를 대조한다.
- **작업 순서:** `test_w30_04`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w30.py::test_w30_04 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "platforms": 2,
  "deterministic_off_model_calls": 0,
  "fresh_evidence_each_run": True,
  "original_source_changed": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

## 영역 종료 점검

- 카드·TASK_INDEX·실제 인계 상태를 맞춘다. 과거 완료를 문서 정리로 다시 구현하거나 무효화하지 않는다.
- 부모 W는 소속 leaf와 parent_gate_tasks/원래 통합 조건까지 만족해야 완료다.
- [UI_COVERAGE](UI_COVERAGE.md)·[COVERAGE](COVERAGE.md)의 실제 수용 조건은 그대로 유지한다.
