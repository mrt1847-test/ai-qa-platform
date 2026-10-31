# E-2 · 녹화 입력·진행·저장·재녹화 · 상세 작업서 v0.7

제품 설계 v0.6 + [공통 보완 계약](CONTRACTS.md). **제품 미착수: 완료0 / 8**.
[전체 색인](README.md) · [인계 양식](HANDOFF.md) · [UI 추적](UI_COVERAGE.md) · [요구/시험 추적](COVERAGE.md).

문서 전체를 한 번에 구현하지 않는다. **카드 한 개**와 직접 선행 근거를 읽는다.
파일/DTO/시험은 향후 산출물이며 현재 존재·통과를 뜻하지 않는다.
검증 projection은 실제 관찰에서 계산한다. [검증 예시 해석](README.md#4-카드의-검증-예시를-해석하는-법)을 따른다.

| 작업 | 선행 | 결과 |
|---|---|---|
| [W16-01](#w16-01) | [W15-04](05a-action-evidence-and-models.md#w15-04) | 디바이스 먼저 녹화 마법사·입력 초안 |
| [W16-02](#w16-02) | [W16-01](05b-recording-workflow.md#w16-01) | 자연어 구조화 관리 job·diff 수락 |
| [W16-03](#w16-03) | [W16-02](05b-recording-workflow.md#w16-02) | 시작 preflight·REC/job 원자 접수 |
| [W16-04](#w16-04) | [W16-03](05b-recording-workflow.md#w16-03) | authoring loop·실시간 action timeline·메모 |
| [W16-05](#w16-05) | [W16-04](05b-recording-workflow.md#w16-04) | 완료·중단·오류 seal 과 fallback 초안 |
| [W16-06](#w16-06) | [W16-05](05b-recording-workflow.md#w16-05) | 녹화 이력·미완성·receipt·저장상태 UI |
| [W16-07](#w16-07) | [W16-06](05b-recording-workflow.md#w16-06), [W29-06](06-replay-packages.md#w29-06), [W30-04](06-replay-packages.md#w30-04) | finish 컴파일 통합·복구/재컴파일 새 버전 |
| [W16-08](#w16-08) | [W16-06](05b-recording-workflow.md#w16-06) | 같은 case 전체 재녹화·기준/사유·branch |

<a id="w16-01"></a>

## W16-01 — 디바이스 먼저 녹화 마법사·입력 초안

- [ ] **W16-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W16-01.md`(완료 시 생성).
- **직접 선행:** [W15-04](05a-action-evidence-and-models.md#w15-04)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C05 / C07 + 직접 선행 receipt의 interface/제약. 추적: R03, R21, R27, R28, UI-05.02, UI-05.03.
- **변경 파일:** `src/aiqa/web/templates/recording_setup.html`, `src/aiqa/api/cases.py`, `src/aiqa/api/resources.py`. 담당 시험: `tests/integration/test_w16.py`.
- **입출력 계약:** `RecordingWizardState(resource_id, environment_revision_id, definition_buffer); POST /api/v1/cases/{c}/versions -> CaseVersionView`
- **구현·화면·예외:** UI05 의 1 기기→2WebURL/Android 앱·build·accountref/data·reset/limits→3 자연어검증 순서를 구현한다. target 변경시 맞지않는필드 무효화·입력오류보존·불완전초안저장·TC 단계없음을 보장한다.
- **검증 전제:** Web/Android 전환·뒤로/앞으로·기기끊김·불완전 expected·TC0 개로저장/재접속을 확인한다.
- **작업 순서:** `test_w16_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w16.py::test_w16_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "device_first": True,
  "tc_required": False,
  "incomplete_draft_saved": True,
  "wrong_target_fields_retained": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w16-02"></a>

## W16-02 — 자연어 구조화 관리 job·diff 수락

- [ ] **W16-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W16-02.md`(완료 시 생성).
- **직접 선행:** [W16-01](05b-recording-workflow.md#w16-01)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C05 / C07 / C12 + 직접 선행 receipt의 interface/제약. 추적: R03, R13, R28, UI-04.05, UI-05.04.
- **변경 파일:** `src/aiqa/recording/structure.py`, `src/aiqa/api/cases.py`, `src/aiqa/web/templates/components/structure_proposal.html`. 담당 시험: `tests/integration/test_w16.py`.
- **입출력 계약:** `POST /api/v1/case-versions/{v}/structure -> JobReceipt; structure_case(input: StructureSpec) -> CaseStructureProposal`
- **구현·화면·예외:** authoring binding 으로 원문에서목적/조건/단계/expected/path 제안만 만든다. UI04/05 diff 거부는변경 0·수락은새 version, 모호/unknown 은실행차단과보완질문을표시한다. AI 가 expected 를자동완화하지않는다.
- **검증 전제:** 원문모호·정상제안·timeout·제안실패·현재 head 변경·거부/수락을 수행한다.
- **작업 순서:** `test_w16_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w16.py::test_w16_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "structure_job_qa": None,
  "auto_applied": False,
  "reject_changes": 0,
  "accept_new_revision": 1
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w16-03"></a>

## W16-03 — 시작 preflight·REC/job 원자 접수

- [ ] **W16-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W16-03.md`(완료 시 생성).
- **직접 선행:** [W16-02](05b-recording-workflow.md#w16-02)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C05 / C07 + 직접 선행 receipt의 interface/제약. 추적: R10, R12, R28, UI-05.05.
- **변경 파일:** `src/aiqa/recording/service.py`, `src/aiqa/api/recordings.py`, `src/aiqa/web/templates/recording_setup.html`. 담당 시험: `tests/integration/test_w16.py`.
- **입출력 계약:** `POST /api/v1/projects/{p}/recordings(input: RecordingStartInput) -> RecordingReceipt`
- **구현·화면·예외:** input_case_version_id/hash·resource 로정의/target/권한/secret·authoringbinding/예산을검사하고 REC/job/receipt 를원자생성한다. busy 는점유링크/queue 선택이며 preflight 가예약은아니다. 같은 key/body 같은 REC·정의변경은새요청이다.
- **검증 전제:** 이중클릭·동일 key 다른 body·hash 불일치·TC=null·busy 와 claim 전기기변경을 확인한다.
- **작업 순서:** `test_w16_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w16.py::test_w16_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "same_key_rec_count": 1,
  "different_body_status": 409,
  "hash_mismatch_status": 409,
  "tc_null_accepted": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w16-04"></a>

## W16-04 — authoring loop·실시간 action timeline·메모

- [ ] **W16-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W16-04.md`(완료 시 생성).
- **직접 선행:** [W16-03](05b-recording-workflow.md#w16-03)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C05 / C07 / C12 + 직접 선행 receipt의 interface/제약. 추적: R04, R05, R07, R13, R29, R30, UI-05.06.
- **변경 파일:** `src/aiqa/recording/authoring.py`, `src/aiqa/adapters/cuawright_web.py`, `src/aiqa/adapters/mobile_agent_android.py`, `src/aiqa/web/templates/recording.html`, `src/aiqa/api/recordings.py`. 담당 시험: `tests/integration/test_w16.py`.
- **입출력 계약:** `run_recording(spec: ExecutionSpec, sink: EventSink, control: RunControl) -> EngineOutcome; POST /api/v1/recordings/{r}/notes`
- **구현·화면·예외:** 두 upstream 제안→정책/전후 capture/dispatch/broker 공통경로로실행하고 rawcode/plan·mapping 을보존한다. UI05 목표·현재화면/시각·action 별전후/log·기록/ACK/대기/오류 count·append 메모를표시한다. 녹화중목표수정·승인·pause 버튼없음이다.
- **검증 전제:** 한 step3action·업로드지연·model 대기취소·메모중복·화면지시 injection 을실행한다.
- **작업 순서:** `test_w16_04`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w16.py::test_w16_04 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "per_action_evidence": True,
  "approval_during_recording": False,
  "pending_count_correct": True,
  "notes_append_only": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w16-05"></a>

## W16-05 — 완료·중단·오류 seal 과 fallback 초안

- [ ] **W16-05 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W16-05.md`(완료 시 생성).
- **직접 선행:** [W16-04](05b-recording-workflow.md#w16-04)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C05 / C07 + 직접 선행 receipt의 interface/제약. 추적: R12, R15, R30, UI-05.07.
- **변경 파일:** `src/aiqa/recording/service.py`, `src/aiqa/recording/manifests.py`, `src/aiqa/api/recordings.py`, `src/aiqa/web/templates/recording.html`. 담당 시험: `tests/integration/test_w16.py`.
- **입출력 계약:** `finish_recording(input: RecordingFinishInput) -> ManifestReceipt; stop_recording(recording_id: UUID) -> RecordingView; materialize_recording(manifest_id: UUID, compiled: CompiledPackage | None) -> MaterializationReceipt`
- **구현·화면·예외:** 완료/중단은새행동중지→flush/final_seq/필수 artifact 최대 30 초대기→cleanup→sealedsource/receipt 다. compiler 미준비/실패때 package=null/사유있는새 draft 를저장한다. 정상/실패/중단모두보존하고 engine done 을 QA/승인으로삼지않는다. W16-07 에서 ready compiler 경로를통합한다.
- **검증 전제:** completed/interrupted/error·전송누락·compiler 부재·finish 중복/다른 body·늦은 finish 를확인한다.
- **작업 순서:** `test_w16_05`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w16.py::test_w16_05 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "unapproved_saved": True,
  "failed_saved": True,
  "duplicate_materializations": 1,
  "missing_compiler_package": None
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w16-06"></a>

## W16-06 — 녹화 이력·미완성·receipt·저장상태 UI

- [ ] **W16-06 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W16-06.md`(완료 시 생성).
- **직접 선행:** [W16-05](05b-recording-workflow.md#w16-05)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C05 / C07 + 직접 선행 receipt의 interface/제약. 추적: R07, R15, R21, R30, UI-06.01, UI-06.02, UI-04.06.
- **변경 파일:** `src/aiqa/web/templates/recording_history.html`, `src/aiqa/api/recordings.py`, `src/aiqa/web/templates/case_detail.html`. 담당 시험: `tests/integration/test_w16.py`.
- **입출력 계약:** `GET /api/v1/cases/{c}/recordings; GET /api/v1/recordings/{r}/manifests -> CursorPage[RecordingHistoryRow]`
- **구현·화면·예외:** UI06 REC/input/output/base/대상/시각/action 수와 storage/outcome/procedure/evidence/review 축을분리한다. 미완성/반려도노출하며수집범위·오류·전후증거/receipt 를연다. 재전송대기는저장완료가아니다.
- **검증 전제:** partialstored·failed·rejected·recoverymanifest·local/spooling/stored 를조회하고새로고침/selectedaction 을복원한다.
- **작업 순서:** `test_w16_06`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w16.py::test_w16_06 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "stored_implies_completed": False,
  "rejected_hidden": False,
  "receipt_versions_visible": True,
  "local_as_server_saved": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w16-07"></a>

## W16-07 — finish 컴파일 통합·복구/재컴파일 새 버전

- [ ] **W16-07 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W16-07.md`(완료 시 생성).
- **직접 선행:** [W16-06](05b-recording-workflow.md#w16-06), [W29-06](06-replay-packages.md#w29-06), [W30-04](06-replay-packages.md#w30-04)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C05 / C07 + 직접 선행 receipt의 interface/제약. 추적: R08, R12, R30, R34, UI-06.03.
- **변경 파일:** `src/aiqa/recording/service.py`, `src/aiqa/recording/recovery.py`, `src/aiqa/api/recordings.py`. 담당 시험: `tests/integration/test_w16.py`.
- **입출력 계약:** `POST /api/v1/recordings/{r}/case-drafts; POST /api/v1/recordings/{r}/package-rebuilds -> MaterializationReceipt | JobReceipt`
- **구현·화면·예외:** compilerready 면 sealedsource→compile/artifactready→version/package/receipt 원자확정으로 finish 를연결한다. 이미 package0receipt 가있으면같은 manifest 재요청은그대로반환, 재시도는 package_rebuild 새 manifest/version 이다. recovery 도새 manifest/version 이며기존 immutable version 에 attach 하지않는다.
- **검증 전제:** 최초 compile 성공/실패·fallbackreceipt 후성공·lock 변경 rebuild·같은 key 다른 body·원자실패를검사한다.
- **작업 순서:** `test_w16_07`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w16.py::test_w16_07 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "inplace_package_attach": 0,
  "rebuild_new_version": True,
  "receipt_replay_same": True,
  "partial_version_package_rows": 0
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w16-08"></a>

## W16-08 — 같은 case 전체 재녹화·기준/사유·branch

- [ ] **W16-08 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W16-08.md`(완료 시 생성).
- **직접 선행:** [W16-06](05b-recording-workflow.md#w16-06)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C04 / C05 / C07 / C08 + 직접 선행 receipt의 interface/제약. 추적: R08, R24, R28, R30, UI-04.07, UI-06.04.
- **변경 파일:** `src/aiqa/api/recordings.py`, `src/aiqa/recording/service.py`, `src/aiqa/web/templates/components/rerecord.html`. 담당 시험: `tests/integration/test_w16.py`.
- **입출력 계약:** `POST /api/v1/cases/{c}/rerecordings(input: RerecordInput) -> RecordingReceipt`
- **구현·화면·예외:** UI04/06 에서 baseversion/reason·검증의도유지또는명시 diff·device/appURL/data/reset 을확인해새 input/REC 를만든다. 중간재개/partialmerge 없이전체흐름이다. 늦은 finish 는새 head 를덮지않는 branch 이며기존 currentapproval 유지다.
- **검증 전제:** v2 기준재녹화→실패/중단·입력 head 동시편집·목표변경제안·TC0 개를검사한다.
- **작업 순서:** `test_w16_08`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w16.py::test_w16_08 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "same_case": True,
  "base_preserved": True,
  "current_approval_changed": False,
  "late_finish_overwrites_head": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

## 영역 종료 점검

- 카드 체크·TASK_INDEX 상태·인계 근거가 일치해야 한다.
- [COVERAGE](COVERAGE.md)·[UI_COVERAGE](UI_COVERAGE.md)에서 담당 항목의 실제 증거를 연결한다.
- 후속 기능을 미리 완료 처리하지 않는다. 실패/계약 변경은 [REVIEW](REVIEW.md)에 기록하고 영향 작업을 재개한다.
