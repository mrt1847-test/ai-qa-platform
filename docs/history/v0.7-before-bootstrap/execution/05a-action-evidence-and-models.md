# E-1 · 행동·증거·spool·모델 계측 · 상세 작업서 v0.7

제품 설계 v0.6 + [공통 보완 계약](CONTRACTS.md). **제품 미착수: 완료0 / 12**.
[전체 색인](README.md) · [인계 양식](HANDOFF.md) · [UI 추적](UI_COVERAGE.md) · [요구/시험 추적](COVERAGE.md).

문서 전체를 한 번에 구현하지 않는다. **카드 한 개**와 직접 선행 근거를 읽는다.
파일/DTO/시험은 향후 산출물이며 현재 존재·통과를 뜻하지 않는다.
검증 projection은 실제 관찰에서 계산한다. [검증 예시 해석](README.md#4-카드의-검증-예시를-해석하는-법)을 따른다.

| 작업 | 선행 | 결과 |
|---|---|---|
| [W13-01](#w13-01) | [W12-03](04b-environments-and-launcher.md#w12-03) | 행동 제안 schema·대상·도구 정책 gate |
| [W13-02](#w13-02) | [W13-01](05a-action-evidence-and-models.md#w13-01) | 메모리 정제·전 캡처와 실제 하위 행동 |
| [W13-03](#w13-03) | [W13-02](05a-action-evidence-and-models.md#w13-02) | durable dispatch journal·명령 ACK 경계 |
| [W13-04](#w13-04) | [W13-03](05a-action-evidence-and-models.md#w13-03) | 후 캡처·검증 연결·결과불명 보존 |
| [W14-01](#w14-01) | [W13-04](05a-action-evidence-and-models.md#w13-04) | 정제 spool·seq·hash·ACK journal |
| [W14-02](#w14-02) | [W14-01](05a-action-evidence-and-models.md#w14-01) | staging→rename→ready·ingest ACK |
| [W14-03](#w14-03) | [W14-02](05a-action-evidence-and-models.md#w14-02) | 파일 reconcile·missing/corruption 조회 |
| [W14-04](#w14-04) | [W14-03](05a-action-evidence-and-models.md#w14-03) | terminal 뒤 read-only 증거 복구 |
| [W15-01](#w15-01) | [W14-04](05a-action-evidence-and-models.md#w14-04) | 공통 model broker·role/check/episode 권한 |
| [W15-02](#w15-02) | [W15-01](05a-action-evidence-and-models.md#w15-01) | usage·retry·late settlement ledger |
| [W15-03](#w15-03) | [W15-02](05a-action-evidence-and-models.md#w15-02) | 호출 전 예산 예약·deadline·취소 |
| [W15-04](#w15-04) | [W15-03](05a-action-evidence-and-models.md#w15-03) | 모델 연결 검사·비용·무키 replay 안내 UI |

<a id="w13-01"></a>

## W13-01 — 행동 제안 schema·대상·도구 정책 gate

- [ ] **W13-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W13-01.md`(완료 시 생성).
- **직접 선행:** [W12-03](04b-environments-and-launcher.md#w12-03)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 + 직접 선행 receipt의 interface/제약. 추적: R06, R14, R29.
- **변경 파일:** `src/aiqa/recording/action_executor.py`, `src/aiqa/security/action_policy.py`, `src/aiqa/contracts/actions.py`. 담당 시험: `tests/integration/test_w13.py`.
- **입출력 계약:** `PolicyGate.authorize(proposal: ActionProposal, context: StepContext) -> ActionDecision`
- **구현·화면·예외:** tap/type/swipe/back 와 Web 지원 action 을 typed schema 로 제한하고 URL redirect/package/allowlist·승인입력·required path 를 검사한다. 화면/DOM 속 지시는 실행권한이 아니며 raw shell/code 는 거부한다.
- **검증 전제:** 화면 prompt injection·범위밖 URL/package·unknownaction·입력변경·helper rawcommand 를 제안한다.
- **작업 순서:** `test_w13_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w13.py::test_w13_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "out_of_scope_dispatches": 0,
  "raw_shell_allowed": False,
  "screen_instruction_authoritative": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w13-02"></a>

## W13-02 — 메모리 정제·전 캡처와 실제 하위 행동

- [ ] **W13-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W13-02.md`(완료 시 생성).
- **직접 선행:** [W13-01](05a-action-evidence-and-models.md#w13-01)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 + 직접 선행 receipt의 interface/제약. 추적: R07, R14, R29.
- **변경 파일:** `src/aiqa/security/redaction.py`, `src/aiqa/recording/action_executor.py`, `src/aiqa/adapters/cuawright_web.py`, `src/aiqa/adapters/mobile_agent_android.py`. 담당 시험: `tests/integration/test_w13.py`.
- **입출력 계약:** `prepare_action(proposal: ActionProposal, observation: Observation) -> PreparedAction`
- **구현·화면·예외:** 원본 PNG/DOM/stdout/messages 는 메모리에서 필터 후 보관본만 spool 로 보낸다. compound step 을 각 actual action 으로 분해하고 각각 전캡처를 얻는다. 필터/전캡처 실패는 command 금지, 원본 reasoning debug 저장도금지다.
- **검증 전제:** 3 행동 step 과 secret 화면/DOM/예외 stdout·redactor failure·FLAG_SECURE 를 재현한다.
- **작업 순서:** `test_w13_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w13.py::test_w13_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "actions": 3,
  "before_artifacts": 3,
  "raw_secret_on_disk": False,
  "pre_capture_failure_dispatches": 0
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w13-03"></a>

## W13-03 — durable dispatch journal·명령 ACK 경계

- [ ] **W13-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W13-03.md`(완료 시 생성).
- **직접 선행:** [W13-02](05a-action-evidence-and-models.md#w13-02)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 + 직접 선행 receipt의 interface/제약. 추적: R11, R12, R17, R33.
- **변경 파일:** `src/aiqa/recording/action_executor.py`, `src/aiqa/worker/dispatch_journal.py`, `src/aiqa/replay/action_executor.py`. 담당 시험: `tests/integration/test_w13.py`.
- **입출력 계약:** `dispatch_action(prepared: PreparedAction, control: RunControl) -> DispatchReceipt`
- **구현·화면·예외:** planned→lookup_failed 또는 dispatch_started 를 로컬 durable journal 에 flush 한 뒤 native API 를 한 번 호출한다. 이후 acknowledged/observed/unknown 을 append 하며 ACK 미수신을 lookup_failed 로 되돌리지 않는다. journal writefail 이면 dispatch0 이다.
- **검증 전제:** journal flushfail·Playwright click navigation timeout·ADB timeout·ACK 유실을 주입해 명령전송 횟수를 계수한다.
- **작업 순서:** `test_w13_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w13.py::test_w13_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "journal_failure_dispatches": 0,
  "post_dispatch_retries": 0,
  "timeout_reclassified_lookup": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w13-04"></a>

## W13-04 — 후 캡처·검증 연결·결과불명 보존

- [ ] **W13-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W13-04.md`(완료 시 생성).
- **직접 선행:** [W13-03](05a-action-evidence-and-models.md#w13-03)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 + 직접 선행 receipt의 interface/제약. 추적: R06, R07, R12, R29.
- **변경 파일:** `src/aiqa/recording/action_executor.py`, `src/aiqa/contracts/evidence.py`, `src/aiqa/validation/observations.py`. 담당 시험: `tests/integration/test_w13.py`.
- **입출력 계약:** `observe_action(receipt: DispatchReceipt, control: RunControl) -> ActionObservation`
- **구현·화면·예외:** 즉시 후 PNG·capture 시각/geometry·실제명령결과·error/check refs 를 동일 action 에 연결한다. 후캡처 누락/정제실패/rotation 은 incomplete/unknown 이며 재탭 0 이다. read-only 재관찰은 delayed 로 구별한다.
- **검증 전제:** 3 행동 정상·후 PNG 실패·회전·나중 재관찰을 수집해 action/evidence mapping 을 대조한다.
- **작업 순서:** `test_w13_04`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w13.py::test_w13_04 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "normal_before_after_png": 6,
  "missing_after_redispatches": 0,
  "delayed_as_immediate": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w14-01"></a>

## W14-01 — 정제 spool·seq·hash·ACK journal

- [ ] **W14-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W14-01.md`(완료 시 생성).
- **직접 선행:** [W13-04](05a-action-evidence-and-models.md#w13-04)
- **읽기:** CONTRACTS C00 / C01 / C03 / C05 / C07 + 직접 선행 receipt의 interface/제약. 추적: R07, R12, R14, R15.
- **변경 파일:** `src/aiqa/worker/spool.py`, `src/aiqa/worker/service.py`, `src/aiqa/contracts/evidence.py`. 담당 시험: `tests/integration/test_w14.py`.
- **입출력 계약:** `append_evidence(envelope: EvidenceEnvelope) -> LocalReceipt; acknowledge_spool(receipt: IngestReceipt) -> AckState`
- **구현·화면·예외:** attempt/local_seq/hash·정제 PNG/log 를 durable spool 에 append 한다. 서버 contiguous ACK/hash 가 검증된 파일만 정리 가능하다. 최대 7 일은 ACK 된 spool 정책이고 미 ACK 자료는 자동폐기하지 않으며 한도압박시 새행동을 멈춘다.
- **검증 전제:** 전송전/후 crash·중복전송·seq gap·7 일 경과 미 ACK·disk full 을 주입한다.
- **작업 순서:** `test_w14_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w14.py::test_w14_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "unacked_deleted": 0,
  "ack_hash_required": True,
  "duplicate_actions_from_upload": 0,
  "pressure_stops_actions": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w14-02"></a>

## W14-02 — staging→rename→ready·ingest ACK

- [ ] **W14-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W14-02.md`(완료 시 생성).
- **직접 선행:** [W14-01](05a-action-evidence-and-models.md#w14-01)
- **읽기:** CONTRACTS C00 / C01 / C03 / C05 / C07 + 직접 선행 receipt의 interface/제약. 추적: R07, R12, R14, R29.
- **변경 파일:** `src/aiqa/store/evidence.py`, `src/aiqa/store/artifacts.py`, `src/aiqa/api/artifacts.py`. 담당 시험: `tests/integration/test_w14.py`.
- **입출력 계약:** `ingest_artifact(lease: LeaseToken, input: ArtifactUpload) -> ArtifactReceipt`
- **구현·화면·예외:** generated object key·길이/hash·같은볼륨 tmp flush/rename 뒤 DBready+ref/ACK 를 확정한다. project/owner/lease/size 를 검사하고 임의 path·확장자 MIME 불일치·hash 오류는 quarantine/거부다.
- **검증 전제:** rename 뒤 DBfail·중복 hash 업로드·다른 project owner·잘못된 hash/길이·path traversal 을 요청한다.
- **작업 순서:** `test_w14_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w14.py::test_w14_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "ack_before_ready": False,
  "hash_mismatch_ready": False,
  "path_escape": False,
  "duplicate_receipt_same": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w14-03"></a>

## W14-03 — 파일 reconcile·missing/corruption 조회

- [ ] **W14-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W14-03.md`(완료 시 생성).
- **직접 선행:** [W14-02](05a-action-evidence-and-models.md#w14-02)
- **읽기:** CONTRACTS C00 / C01 / C03 / C05 / C07 + 직접 선행 receipt의 interface/제약. 추적: R07, R14, R15.
- **변경 파일:** `src/aiqa/store/artifacts.py`, `src/aiqa/api/artifacts.py`, `src/aiqa/web/templates/components/evidence_state.html`. 담당 시험: `tests/integration/test_w14.py`.
- **입출력 계약:** `reconcile_artifacts() -> ArtifactReconcileReport; GET /api/v1/artifacts/{a} -> ArtifactStream | EvidenceUnavailable`
- **구현·화면·예외:** orphan tmp/rename-after-crash·DBready 파일없음/hash 변경을 점검하고 운영보관상태를 갱신한다. 원본 result/hash 를 새파일로 대체하지 않으며 missing/expired/corruption 을 UI 에서 구별한다.
- **검증 전제:** 각 파일상태를 실제저장소에 만들고 권한내 image/log GET·ready 조건·기존 finalhash 를 확인한다.
- **작업 순서:** `test_w14_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w14.py::test_w14_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "missing_file_returned_success": False,
  "corruption_detected": True,
  "original_result_hash_changed": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w14-04"></a>

## W14-04 — terminal 뒤 read-only 증거 복구

- [ ] **W14-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W14-04.md`(완료 시 생성).
- **직접 선행:** [W14-03](05a-action-evidence-and-models.md#w14-03)
- **읽기:** CONTRACTS C00 / C01 / C03 / C05 / C07 + 직접 선행 receipt의 interface/제약. 추적: R12, R15, R30.
- **변경 파일:** `src/aiqa/recording/recovery.py`, `src/aiqa/api/recordings.py`, `src/aiqa/worker/service.py`. 담당 시험: `tests/integration/test_w14.py`.
- **입출력 계약:** `POST /api/v1/recordings/{r}/evidence-recoveries -> JobReceipt; recover_evidence(input: EvidenceRecoverySpec) -> ManifestReceipt`
- **구현·화면·예외:** evidence_sync 는 제어권한없는 관리 job·owner null/source ref 다. 실제 미전송 capture 만 새 recovery manifest 로 보존하고 같은 key 같은 receipt/다른 body409. 늦은사진은 delayed, 기존 version/QA/승인변경 0 이며 새 materialization 은 W16-07 이다.
- **검증 전제:** lost REC 의 원래 미전송후 PNG 와 나중찍은 PNG 를 업로드하고 중복/변경 body 를 보낸다.
- **작업 순서:** `test_w14_04`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w14.py::test_w14_04 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "recovery_new_manifest": True,
  "old_result_unchanged": True,
  "delayed_satisfies_immediate": False,
  "recovery_dispatches": 0
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w15-01"></a>

## W15-01 — 공통 model broker·role/check/episode 권한

- [ ] **W15-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W15-01.md`(완료 시 생성).
- **직접 선행:** [W14-04](05a-action-evidence-and-models.md#w14-04)
- **읽기:** CONTRACTS C00 / C01 / C04 / C06 + 직접 선행 receipt의 interface/제약. 추적: R13, R14, R17, R33.
- **변경 파일:** `src/aiqa/models/client.py`, `src/aiqa/models/broker.py`, `src/aiqa/contracts/models.py`. 담당 시험: `tests/integration/test_w15.py`.
- **입출력 계약:** `ModelClient.invoke(request: ModelRequest, control: RunControl) -> ModelResponse`
- **구현·화면·예외:** authoring/verification/healing/maintenance 요청을 broker 한곳으로 모으고 role binding·check/episode owner·actualmodel·callID 를 검사한다. replay script 에는 key/modelnetwork 를 주지 않고 일반 action actor0 를 강제한다.
- **검증 전제:** 등록하지않은 check·잘못된 role·다른 ITEM episode·script 직접 model 호출·정상 authoring 을 대조한다.
- **작업 순서:** `test_w15_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w15.py::test_w15_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "unowned_call_allowed": False,
  "cross_item_call_allowed": False,
  "script_has_key": False,
  "authoring_metered": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w15-02"></a>

## W15-02 — usage·retry·late settlement ledger

- [ ] **W15-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W15-02.md`(완료 시 생성).
- **직접 선행:** [W15-01](05a-action-evidence-and-models.md#w15-01)
- **읽기:** CONTRACTS C00 / C01 / C04 / C06 + 직접 선행 receipt의 interface/제약. 추적: R13, R35.
- **변경 파일:** `src/aiqa/models/usage.py`, `src/aiqa/store/usage.py`, `src/aiqa/models/client.py`. 담당 시험: `tests/integration/test_w15.py`.
- **입출력 계약:** `record_model_usage(input: ModelCallSettlement) -> UsageReceipt; append_usage_adjustment(input: UsageAdjustmentInput) -> UsageLedgerView`
- **구현·화면·예외:** 모든 실제 전송/retry 를 call 로 세고 nullableinput/output/cache/image·measured/estimated/unreported·actualmodel·tariff/currency 를 기록한다. 미사용 0/not_used 와 계측누락 null/unknown 을 분리하고 늦은정산은 appendseq 다.
- **검증 전제:** usage 미보고·일부 role 누락·429 재전송·latebill·중복 providerrequest 를 계수한다.
- **작업 순서:** `test_w15_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w15.py::test_w15_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "unreported_tokens": None,
  "unused_role_calls": 0,
  "partial_total": "partial",
  "late_rewrites_original": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w15-03"></a>

## W15-03 — 호출 전 예산 예약·deadline·취소

- [ ] **W15-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W15-03.md`(완료 시 생성).
- **직접 선행:** [W15-02](05a-action-evidence-and-models.md#w15-02)
- **읽기:** CONTRACTS C00 / C01 / C04 / C06 + 직접 선행 receipt의 interface/제약. 추적: R11, R13, R33.
- **변경 파일:** `src/aiqa/models/budget.py`, `src/aiqa/models/broker.py`, `src/aiqa/worker/control.py`. 담당 시험: `tests/integration/test_w15.py`.
- **입출력 계약:** `reserve_model_call(input: ModelReservation, control: RunControl) -> Reservation; settle_model_call(reservation: Reservation, response: ModelResponse) -> Settlement`
- **구현·화면·예외:** 호출전최대비용/시간/호출수를 원자예약하고 응답후정산한다. strict 가격불명은차단·estimate 명시시불완전표시, 늦은응답은행동불가다. healer 합계 2 회는전송 retry 포함이며 일반 retry2 보다 우선한다.
- **검증 전제:** 동시예산예약·가격누락·호출 80/81·취소응답·healer2 회후 retry 를 주입한다.
- **작업 순서:** `test_w15_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w15.py::test_w15_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "overbooked_reservations": 0,
  "strict_unknown_price_allowed": False,
  "healer_third_call": False,
  "late_action_dispatched": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w15-04"></a>

## W15-04 — 모델 연결 검사·비용·무키 replay 안내 UI

- [ ] **W15-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W15-04.md`(완료 시 생성).
- **직접 선행:** [W15-03](05a-action-evidence-and-models.md#w15-03)
- **읽기:** CONTRACTS C00 / C01 / C04 / C06 + 직접 선행 receipt의 interface/제약. 추적: R13, R14, R17, UI-15.05.
- **변경 파일:** `src/aiqa/api/model_bindings.py`, `src/aiqa/web/templates/settings.html`, `src/aiqa/worker/model_check.py`. 담당 시험: `tests/integration/test_w15.py`.
- **입출력 계약:** `POST /api/v1/model-bindings/{b}/checks -> JobReceipt; GET /api/v1/model-bindings/{b}/compatibility -> CompatibilityReport`
- **구현·화면·예외:** UI15 에 role 별호환·마지막검사/actualmodel·usage 상태/비용·key 가용성을 표시한다. 검사실행은 명시 model_check 관리 job·QA=null, 비용안내후요청한다. 결정적/OFFreplay 는 모델연결검사없이도 허용한다.
- **검증 전제:** key 없는 binding·검사 timeout·호환실패·실제허용최소호출·결정적 replay 의 preflight 를 확인한다.
- **작업 순서:** `test_w15_04`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w15.py::test_w15_04 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "check_job_verdict": None,
  "replay_requires_model_check": False,
  "key_plaintext_echo": False,
  "test_calls_metered": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

## 영역 종료 점검

- 카드 체크·TASK_INDEX 상태·인계 근거가 일치해야 한다.
- [COVERAGE](COVERAGE.md)·[UI_COVERAGE](UI_COVERAGE.md)에서 담당 항목의 실제 증거를 연결한다.
- 후속 기능을 미리 완료 처리하지 않는다. 실패/계약 변경은 [REVIEW](REVIEW.md)에 기록하고 영향 작업을 재개한다.
