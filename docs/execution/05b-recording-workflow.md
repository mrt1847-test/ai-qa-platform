# E-2 · 녹화 입력·진행·저장·재녹화 · 상세 작업서 v0.8

제품 설계 v0.6 + [보완 계약](CONTRACTS.md). **완료5 / 8**.
[Current 큐](../../NEXT_ACTION.md) · [전체 색인](README.md) · [차단/선행 수정](SCHEDULING.md) · [인계](HANDOFF.md).

카드 한 개와 직접 선행 근거만 읽는다. 기존 코드/complete/blocked 기록을 재사용한다.
검증 등급·live 수용을 구분한다. core fixture는 실제 native 근거가 아니며 최종 검증을 생략하지 않는다.

| 작업 | 직접 선행 | 결과 | 상태 |
|---|---|---|---|
| [W16-01](#w16-01) | [W10-11](04a-case-management-ui.md#w10-11), [W11-03](04b-environments-and-launcher.md#w11-03), [W08-01](03-worker-and-sessions.md#w08-01) | 디바이스 먼저 녹화 마법사·입력 초안 | complete |
| [W16-02](#w16-02) | [W16-01](05b-recording-workflow.md#w16-01), [W15-04](05a-action-evidence-and-models.md#w15-04) | 자연어 구조화 관리 job·diff 수락 | not_started |
| [W16-03](#w16-03) | [W16-01](05b-recording-workflow.md#w16-01), [W15-03](05a-action-evidence-and-models.md#w15-03), [W08-05](03-worker-and-sessions.md#w08-05) | 시작 preflight·REC/job 원자 접수 | complete |
| [W16-04](#w16-04) | [W16-03](05b-recording-workflow.md#w16-03), [W01-03](01-foundation-probes.md#w01-03), [W02-04](01-foundation-probes.md#w02-04), [W07-02](03-worker-and-sessions.md#w07-02), [W07-03](03-worker-and-sessions.md#w07-03), [W13-04](05a-action-evidence-and-models.md#w13-04), [W15-04](05a-action-evidence-and-models.md#w15-04), [W14-03](05a-action-evidence-and-models.md#w14-03) | authoring loop·실시간 action timeline·메모 | not_started |
| [W16-05](#w16-05) | [W16-03](05b-recording-workflow.md#w16-03), [W14-03](05a-action-evidence-and-models.md#w14-03), [W13-04](05a-action-evidence-and-models.md#w13-04) | 완료·중단·오류 seal 과 fallback 초안 | complete |
| [W16-06](#w16-06) | [W16-05](05b-recording-workflow.md#w16-05) | 녹화 이력·미완성·receipt·저장상태 UI | complete |
| [W16-07](#w16-07) | [W16-06](05b-recording-workflow.md#w16-06), [W29-06](06-replay-packages.md#w29-06), [W30-04](06-replay-packages.md#w30-04), [W16-04](05b-recording-workflow.md#w16-04) | finish 컴파일 통합·복구/재컴파일 새 버전 | not_started |
| [W16-08](#w16-08) | [W16-06](05b-recording-workflow.md#w16-06) | 같은 case 전체 재녹화·기준/사유·branch | complete |

<a id="w16-01"></a>

## W16-01 — 디바이스 먼저 녹화 마법사·입력 초안

- [x] **W16-01 완료** — 상태: `complete`. 근거: [W16-01 인계](../validation/tasks/W16-01.md).
- **직접 선행:** [W10-11](04a-case-management-ui.md#w10-11), [W11-03](04b-environments-and-launcher.md#w11-03), [W08-01](03-worker-and-sessions.md#w08-01)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C05 / C07 / C14 + 직접 선행 receipt의 interface/제약. 추적: R03, R21, R27, R28, UI-05.02, UI-05.03.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/web/templates/recording_setup.html`, `src/aiqa/api/cases.py`, `src/aiqa/api/resources.py`. 시험: `tests/integration/test_w16.py`.
- **입출력 계약:** `RecordingWizardState(resource_id, environment_revision_id, definition_buffer); POST /api/v1/cases/{c}/versions -> CaseVersionView`
- **구현·화면·예외:** UI05 의 1 기기→2WebURL/Android 앱·build·accountref/data·reset/limits→3 자연어검증 순서를 구현한다. target 변경시 맞지않는필드 무효화·입력오류보존·불완전초안저장·TC 단계없음을 보장한다.
- **검증 전제:** Web/Android 전환·뒤로/앞으로·기기끊김·불완전 expected·TC0 개로저장/재접속을 확인한다.
- **작업 순서:** `test_w16_01`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w16.py::test_w16_01 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "device_first": True,
  "tc_required": False,
  "incomplete_draft_saved": True,
  "wrong_target_fields_retained": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w16-02"></a>

## W16-02 — 자연어 구조화 관리 job·diff 수락

- [ ] **W16-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W16-02.md`(구현 때 생성).
- **직접 선행:** [W16-01](05b-recording-workflow.md#w16-01), [W15-04](05a-action-evidence-and-models.md#w15-04)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C05 / C07 / C12 + 직접 선행 receipt의 interface/제약. 추적: R03, R13, R28, UI-04.05, UI-05.04.
- **검증 등급:** `live_integration`. 환경: `local_python`, `model_binding`.
- **변경 파일:** `src/aiqa/recording/structure.py`, `src/aiqa/api/cases.py`, `src/aiqa/web/templates/components/structure_proposal.html`. 시험: `tests/integration/test_w16.py`.
- **입출력 계약:** `POST /api/v1/case-versions/{v}/structure -> JobReceipt; structure_case(input: StructureSpec) -> CaseStructureProposal`
- **구현·화면·예외:** authoring binding 으로 원문에서목적/조건/단계/expected/path 제안만 만든다. UI04/05 diff 거부는변경 0·수락은새 version, 모호/unknown 은실행차단과보완질문을표시한다. AI 가 expected 를자동완화하지않는다.
- **검증 전제:** 원문모호·정상제안·timeout·제안실패·현재 head 변경·거부/수락을 수행한다.
- **작업 순서:** `test_w16_02`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w16.py::test_w16_02 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "structure_job_qa": None,
  "auto_applied": False,
  "reject_changes": 0,
  "accept_new_revision": 1
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w16-03"></a>

## W16-03 — 시작 preflight·REC/job 원자 접수

- [x] **W16-03 완료** — 상태: `complete`. 근거: [W16-03 인계](../validation/tasks/W16-03.md).
- **직접 선행:** [W16-01](05b-recording-workflow.md#w16-01), [W15-03](05a-action-evidence-and-models.md#w15-03), [W08-05](03-worker-and-sessions.md#w08-05)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C05 / C07 / C14 + 직접 선행 receipt의 interface/제약. 추적: R10, R12, R28, UI-05.05.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/recording/service.py`, `src/aiqa/api/recordings.py`, `src/aiqa/web/templates/recording_setup.html`. 시험: `tests/integration/test_w16.py`.
- **입출력 계약:** `POST /api/v1/projects/{p}/recordings(input: RecordingStartInput) -> RecordingReceipt`
- **구현·화면·예외:** input_case_version_id/hash·resource 로정의/target/권한/secret·authoringbinding/예산을검사하고 REC/job/receipt 를원자생성한다. busy 는점유링크/queue 선택이며 preflight 가예약은아니다. 같은 key/body 같은 REC·정의변경은새요청이다.
- **검증 전제:** 격리된 API/DB의 test-only resource/binding/definition fixture로 중복 key/hash/TC null·busy·차단을 검사한다. production에 모델/자원이 없으면 preflight 이유를 반환하고 가짜 REC 성공을 만들지 않는다.
- **작업 순서:** `test_w16_03`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w16.py::test_w16_03 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "same_key_rec_count": 1,
  "different_body_status": 409,
  "hash_mismatch_status": 409,
  "tc_null_accepted": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w16-04"></a>

## W16-04 — authoring loop·실시간 action timeline·메모

- [ ] **W16-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W16-04.md`(구현 때 생성).
- **직접 선행:** [W16-03](05b-recording-workflow.md#w16-03), [W01-03](01-foundation-probes.md#w01-03), [W02-04](01-foundation-probes.md#w02-04), [W07-02](03-worker-and-sessions.md#w07-02), [W07-03](03-worker-and-sessions.md#w07-03), [W13-04](05a-action-evidence-and-models.md#w13-04), [W15-04](05a-action-evidence-and-models.md#w15-04), [W14-03](05a-action-evidence-and-models.md#w14-03)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C05 / C07 / C12 + 직접 선행 receipt의 interface/제약. 추적: R04, R05, R07, R13, R29, R30, UI-05.06.
- **검증 등급:** `live_integration`. 환경: `local_python`, `local_linux_vm`, `usb_android`, `model_binding`.
- **변경 파일:** `src/aiqa/recording/authoring.py`, `src/aiqa/adapters/cuawright_web.py`, `src/aiqa/adapters/mobile_agent_android.py`, `src/aiqa/web/templates/recording.html`, `src/aiqa/api/recordings.py`. 시험: `tests/integration/test_w16.py`.
- **입출력 계약:** `run_recording(spec: ExecutionSpec, sink: EventSink, control: RunControl) -> EngineOutcome; POST /api/v1/recordings/{r}/notes`
- **구현·화면·예외:** 두 upstream 제안→정책/전후 capture/dispatch/broker 공통경로로실행하고 rawcode/plan·mapping 을보존한다. UI05 목표·현재화면/시각·action 별전후/log·기록/ACK/대기/오류 count·append 메모를표시한다. 녹화중목표수정·승인·pause 버튼없음이다.
- **검증 전제:** 한 step3action·업로드지연·model 대기취소·메모중복·화면지시 injection 을실행한다.
- **작업 순서:** `test_w16_04`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w16.py::test_w16_04 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "per_action_evidence": True,
  "approval_during_recording": False,
  "pending_count_correct": True,
  "notes_append_only": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w16-05"></a>

## W16-05 — 완료·중단·오류 seal 과 fallback 초안

- [x] **W16-05 완료** — 상태: `complete`. 근거: [W16-05 인계](../validation/tasks/W16-05.md).
- **직접 선행:** [W16-03](05b-recording-workflow.md#w16-03), [W14-03](05a-action-evidence-and-models.md#w14-03), [W13-04](05a-action-evidence-and-models.md#w13-04)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C05 / C07 / C14 + 직접 선행 receipt의 interface/제약. 추적: R12, R15, R30, UI-05.07.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/recording/service.py`, `src/aiqa/recording/manifests.py`, `src/aiqa/api/recordings.py`, `src/aiqa/web/templates/recording.html`. 시험: `tests/integration/test_w16.py`.
- **입출력 계약:** `finish_recording(input: RecordingFinishInput) -> ManifestReceipt; stop_recording(recording_id: UUID) -> RecordingView; materialize_recording(manifest_id: UUID, compiled: CompiledPackage | None) -> MaterializationReceipt`
- **구현·화면·예외:** 완료/중단은새행동중지→flush/final_seq/필수 artifact 최대 30 초대기→cleanup→sealedsource/receipt 다. compiler 미준비/실패때 package=null/사유있는새 draft 를저장한다. 정상/실패/중단모두보존하고 engine done 을 QA/승인으로삼지않는다. W16-07 에서 ready compiler 경로를통합한다.
- **검증 전제:** 테스트용 인증 worker의 manifest/event/artifact를 실제 API/DB에 넣어 completed/interrupted/error·중복/다른 body·compiler 부재·원자 저장을 검사한다. 실제 authoring→finish 증거는 W16-04/07에서 요구한다.
- **작업 순서:** `test_w16_05`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w16.py::test_w16_05 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "unapproved_saved": True,
  "failed_saved": True,
  "duplicate_materializations": 1,
  "missing_compiler_package": None
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w16-06"></a>

## W16-06 — 녹화 이력·미완성·receipt·저장상태 UI

- [x] **W16-06 완료** — 상태: `complete`. 근거: [W16-06 인계](../validation/tasks/W16-06.md).
- **직접 선행:** [W16-05](05b-recording-workflow.md#w16-05)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C05 / C07 / C14 + 직접 선행 receipt의 interface/제약. 추적: R07, R15, R21, R30, UI-06.01, UI-06.02, UI-04.06.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/web/templates/recording_history.html`, `src/aiqa/api/recordings.py`, `src/aiqa/web/templates/case_detail.html`. 시험: `tests/integration/test_w16.py`.
- **입출력 계약:** `GET /api/v1/cases/{c}/recordings; GET /api/v1/recordings/{r}/manifests -> CursorPage[RecordingHistoryRow]`
- **구현·화면·예외:** UI06 REC/input/output/base/대상/시각/action 수와 storage/outcome/procedure/evidence/review 축을분리한다. 미완성/반려도노출하며수집범위·오류·전후증거/receipt 를연다. 재전송대기는저장완료가아니다.
- **검증 전제:** partialstored·failed·rejected·recoverymanifest·local/spooling/stored 를조회하고새로고침/selectedaction 을복원한다.
- **작업 순서:** `test_w16_06`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w16.py::test_w16_06 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "stored_implies_completed": False,
  "rejected_hidden": False,
  "receipt_versions_visible": True,
  "local_as_server_saved": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w16-07"></a>

## W16-07 — finish 컴파일 통합·복구/재컴파일 새 버전

- [ ] **W16-07 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W16-07.md`(구현 때 생성).
- **직접 선행:** [W16-06](05b-recording-workflow.md#w16-06), [W29-06](06-replay-packages.md#w29-06), [W30-04](06-replay-packages.md#w30-04), [W16-04](05b-recording-workflow.md#w16-04)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C05 / C07 + 직접 선행 receipt의 interface/제약. 추적: R08, R12, R30, R34, UI-06.03.
- **검증 등급:** `live_integration`. 환경: `local_python`, `local_linux_vm`, `usb_android`.
- **변경 파일:** `src/aiqa/recording/service.py`, `src/aiqa/recording/recovery.py`, `src/aiqa/api/recordings.py`. 시험: `tests/integration/test_w16.py`.
- **입출력 계약:** `POST /api/v1/recordings/{r}/case-drafts; POST /api/v1/recordings/{r}/package-rebuilds -> MaterializationReceipt | JobReceipt`
- **구현·화면·예외:** compilerready 면 sealedsource→compile/artifactready→version/package/receipt 원자확정으로 finish 를연결한다. 이미 package0receipt 가있으면같은 manifest 재요청은그대로반환, 재시도는 package_rebuild 새 manifest/version 이다. recovery 도새 manifest/version 이며기존 immutable version 에 attach 하지않는다.
- **검증 전제:** 최초 compile 성공/실패·fallbackreceipt 후성공·lock 변경 rebuild·같은 key 다른 body·원자실패를검사한다.
- **작업 순서:** `test_w16_07`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w16.py::test_w16_07 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "inplace_package_attach": 0,
  "rebuild_new_version": True,
  "receipt_replay_same": True,
  "partial_version_package_rows": 0
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w16-08"></a>

## W16-08 — 같은 case 전체 재녹화·기준/사유·branch

- [x] **W16-08 완료** — 상태: `complete`. 근거: [W16-08 인계](../validation/tasks/W16-08.md).
- **직접 선행:** [W16-06](05b-recording-workflow.md#w16-06)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C05 / C07 / C08 / C14 + 직접 선행 receipt의 interface/제약. 추적: R08, R24, R28, R30, UI-04.07, UI-06.04.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/api/recordings.py`, `src/aiqa/recording/service.py`, `src/aiqa/web/templates/components/rerecord.html`. 시험: `tests/integration/test_w16.py`.
- **입출력 계약:** `POST /api/v1/cases/{c}/rerecordings(input: RerecordInput) -> RecordingReceipt`
- **구현·화면·예외:** UI04/06 에서 baseversion/reason·검증의도유지또는명시 diff·device/appURL/data/reset 을확인해새 input/REC 를만든다. 중간재개/partialmerge 없이전체흐름이다. 늦은 finish 는새 head 를덮지않는 branch 이며기존 currentapproval 유지다.
- **검증 전제:** v2 기준재녹화→실패/중단·입력 head 동시편집·목표변경제안·TC0 개를검사한다.
- **작업 순서:** `test_w16_08`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w16.py::test_w16_08 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "same_case": True,
  "base_preserved": True,
  "current_approval_changed": False,
  "late_finish_overwrites_head": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

## 영역 종료 점검

- 카드·TASK_INDEX·실제 인계 상태를 맞춘다. 과거 완료를 문서 정리로 다시 구현하거나 무효화하지 않는다.
- 부모 W는 소속 leaf와 parent_gate_tasks/원래 통합 조건까지 만족해야 완료다.
- [UI_COVERAGE](UI_COVERAGE.md)·[COVERAGE](COVERAGE.md)의 실제 수용 조건은 그대로 유지한다.
