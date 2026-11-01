# H-1 · 선택 셀프힐링·제안 · 상세 작업서 v0.8

제품 설계 v0.6 + [보완 계약](CONTRACTS.md). **완료6 / 7**.
[Current 큐](../../NEXT_ACTION.md) · [전체 색인](README.md) · [차단/선행 수정](SCHEDULING.md) · [인계](HANDOFF.md).

카드 한 개와 직접 선행 근거만 읽는다. 기존 코드/complete/blocked 기록을 재사용한다.
검증 등급·live 수용을 구분한다. core fixture는 실제 native 근거가 아니며 최종 검증을 생략하지 않는다.

| 작업 | 직접 선행 | 결과 | 상태 |
|---|---|---|---|
| [W31-01](#w31-01) | [W19-01](07-trial-and-review.md#w19-01), [W15-03](05a-action-evidence-and-models.md#w15-03), [W13-03](05a-action-evidence-and-models.md#w13-03) | 실행별 healing 정책·ON/OFF snapshot | complete |
| [W31-02](#w31-02) | [W31-01](08a-self-healing.md#w31-01) | 미 dispatch eligibility·episode 원자 예약 | complete |
| [W31-03](#w31-03) | [W31-02](08a-self-healing.md#w31-02) | typed AI target 제안·동일 대상 증명 | complete |
| [W31-04](#w31-04) | [W31-03](08a-self-healing.md#w31-03) | 임시 override·원래 동작 1 회·후속 QA | complete |
| [W31-05](#w31-05) | [W31-04](08a-self-healing.md#w31-04), [W16-08](05b-recording-workflow.md#w16-08) | 불변 repair proposal·전체 재녹화 채택 | complete |
| [W31-06](#w31-06) | [W31-05](08a-self-healing.md#w31-05) | healing 설정·진행·이력 UI 연결 | complete |
| [W31-07](#w31-07) | [W31-06](08a-self-healing.md#w31-06), [W19-04](07-trial-and-review.md#w19-04), [W29-05](06-replay-packages.md#w29-05), [W30-03](06-replay-packages.md#w30-03), [W15-04](05a-action-evidence-and-models.md#w15-04) | 양 플랫폼 실제 셀프힐링·QA 불변 통합 gate | not_started |

<a id="w31-01"></a>

## W31-01 — 실행별 healing 정책·ON/OFF snapshot

- [x] **W31-01 완료** — 상태: `complete`. 근거: [W31-01 인계](../validation/tasks/W31-01.md).
- **직접 선행:** [W19-01](07-trial-and-review.md#w19-01), [W15-03](05a-action-evidence-and-models.md#w15-03), [W13-03](05a-action-evidence-and-models.md#w13-03)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C06 / C07 / C09 / C14 + 직접 선행 receipt의 interface/제약. 추적: R13, R17, R33.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W31-07에서 별도로 요구한다.
- **실제 통합 담당:** [W31-07](08a-self-healing.md#w31-07). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/healing/policy.py`, `src/aiqa/domain/executions.py`, `src/aiqa/contracts/healing.py`. 시험: `tests/integration/test_w31.py`.
- **입출력 계약:** `resolve_healing_policy(version: CaseVersion, request: HealingRequest, global_limits: Limits) -> ResolvedHealingPolicy`
- **구현·화면·예외:** 기본 OFF·approved capability/scope/binding/예산을검증하고더좁은 global 한도와교집합을 snapshot 한다. trial 은 OFF·진행중토글불가·권한/모델/상한확대는새 version/승인이다. 실제 native/모델 연동 수용은 별도 live gate에 남기고 이 카드의 contract fixture 검증과 구분한다.
- **검증 전제:** allowedfalse 에서 ON·scope 확대·healerkey 없음·trialON·접수후 global/버전변경을요청한다.
- **작업 순서:** `test_w31_01`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w31.py::test_w31_01 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "default_enabled": False,
  "capability_false_on_rejected": True,
  "trial_enabled": False,
  "running_snapshot_mutated": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w31-02"></a>

## W31-02 — 미 dispatch eligibility·episode 원자 예약

- [x] **W31-02 완료** — 상태: `complete`. 근거: [W31-02 인계](../validation/tasks/W31-02.md).
- **직접 선행:** [W31-01](08a-self-healing.md#w31-01)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C06 / C07 / C09 / C14 + 직접 선행 receipt의 interface/제약. 추적: R11, R12, R13, R33.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W31-07에서 별도로 요구한다.
- **실제 통합 담당:** [W31-07](08a-self-healing.md#w31-07). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/healing/service.py`, `src/aiqa/healing/policy.py`, `src/aiqa/store/healing.py`. 시험: `tests/integration/test_w31.py`.
- **입출력 계약:** `reserve_healing_episode(input: HealingTrigger, control: RunControl) -> HealingEpisodeReceipt`
- **구현·화면·예외:** target_not_found/ambiguous/layoutshift 의 read-only lookup 이며 dispatch_started 이력없을때만허용한다. ITEM episode1·모델합계 2 회(전송 retry 포함)·30 초/잔여 job·lease·예산중더엄격한한도를원자예약한다. 실제 native/모델 연동 수용은 별도 live gate에 남기고 이 카드의 contract fixture 검증과 구분한다.
- **검증 전제:** 동시 trigger·중복 key·OFF·dispatch 후 timeout·rotation·제품위반·lease 부족을검사한다.
- **작업 순서:** `test_w31_02`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w31.py::test_w31_02 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "episodes_per_item_max": 1,
  "post_dispatch_eligible": False,
  "off_model_calls": 0,
  "duplicate_trigger_extra_episodes": 0
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w31-03"></a>

## W31-03 — typed AI target 제안·동일 대상 증명

- [x] **W31-03 완료** — 상태: `complete`. 근거: [W31-03 인계](../validation/tasks/W31-03.md).
- **직접 선행:** [W31-02](08a-self-healing.md#w31-02)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C06 / C07 / C09 / C14 + 직접 선행 receipt의 interface/제약. 추적: R06, R14, R33, R34.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W31-07에서 별도로 요구한다.
- **실제 통합 담당:** [W31-07](08a-self-healing.md#w31-07). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/healing/service.py`, `src/aiqa/healing/targets.py`, `src/aiqa/models/broker.py`. 시험: `tests/integration/test_w31.py`.
- **입출력 계약:** `HealingService.propose(input: HealingContext) -> HealingProposal; validate_healing_proposal(proposal: HealingProposal, observation: Observation) -> HealingDecision`
- **구현·화면·예외:** 모델은 target 후보만 typed 반환하고신뢰코드가승인 role/name+container 또는 resource-id/text/context·unique/visible/enabled·동일 action/input/path 를증명한다. 좌표후보는검증된현재 elementbounds 안에서만. visual-only/canvas/newsemanticguess 는 MVP 거부다. 실제 native/모델 연동 수용은 별도 live gate에 남기고 이 카드의 contract fixture 검증과 구분한다.
- **검증 전제:** 같은대상 locator 변경·동명이중 target·다른버튼·입력값변경·팝업닫기·canvas·범위밖좌표를제안한다.
- **작업 순서:** `test_w31_03`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w31.py::test_w31_03 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "same_target_proven": True,
  "ambiguous_candidate_accepted": False,
  "changed_action_accepted": False,
  "visual_only_accepted": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w31-04"></a>

## W31-04 — 임시 override·원래 동작 1 회·후속 QA

- [x] **W31-04 완료** — 상태: `complete`. 근거: [W31-04 인계](../validation/tasks/W31-04.md).
- **직접 선행:** [W31-03](08a-self-healing.md#w31-03)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C06 / C07 / C09 / C14 + 직접 선행 receipt의 interface/제약. 추적: R06, R12, R17, R33.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W31-07에서 별도로 요구한다.
- **실제 통합 담당:** [W31-07](08a-self-healing.md#w31-07). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/healing/service.py`, `src/aiqa/replay/action_executor.py`, `src/aiqa/domain/verdicts.py`. 시험: `tests/integration/test_w31.py`.
- **입출력 계약:** `apply_runtime_override(input: AcceptedHealingProposal, control: RunControl) -> ActionObservation`
- **구현·화면·예외:** accepted target 만해당 ITEM 에 appendoverride 하고원래동작을공통 journal/capture 경로로 1 회 dispatch 한다. 원래 lookup 오류/제안/결정/거부/usage 를보존하고실제 check 를새로수행한다. 필수위반은 FAIL·laterterminal 변경 0 이다. 실제 native/모델 연동 수용은 별도 live gate에 남기고 이 카드의 contract fixture 검증과 구분한다.
- **검증 전제:** 치유성공+모든 checkPASS·후속 expected 불일치·정제실패·dispatchtimeout·한도소진을검증한다.
- **작업 순서:** `test_w31_04`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w31.py::test_w31_04 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "original_action_dispatches": 1,
  "success_result": "PASS",
  "healing_used": True,
  "required_violation_result": "FAIL",
  "unassisted_pass": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w31-05"></a>

## W31-05 — 불변 repair proposal·전체 재녹화 채택

- [x] **W31-05 완료** — 상태: `complete`. 근거: [W31-05 인계](../validation/tasks/W31-05.md).
- **직접 선행:** [W31-04](08a-self-healing.md#w31-04), [W16-08](05b-recording-workflow.md#w16-08)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C06 / C07 / C09 / C08 / C14 + 직접 선행 receipt의 interface/제약. 추적: R08, R24, R33, R34, UI-11.02.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W31-07에서 별도로 요구한다.
- **실제 통합 담당:** [W31-07](08a-self-healing.md#w31-07). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/healing/proposals.py`, `src/aiqa/api/healing.py`, `src/aiqa/api/recordings.py`, `src/aiqa/web/templates/components/repair_proposal.html`. 시험: `tests/acceptance/test_w31.py`.
- **입출력 계약:** `POST /api/v1/healing-episodes/{e}/repair-proposals -> RepairProposalView; GET /api/v1/repair-proposals/{p}; POST /api/v1/cases/{c}/rerecordings(repair_proposal_id)`
- **구현·화면·예외:** episode/원래 package/acceptedtarget·diff/근거 hash 로불변제안을멱등저장한다. 사용자 diff 확인/사유후새 input/전체 REC 로채택하고 adoptionevent 를 append 한다. 바로 codepatch/승인·부분 merge·기본본수정은없다. 실제 native/모델 연동 수용은 별도 live gate에 남기고 이 카드의 contract fixture 검증과 구분한다.
- **검증 전제:** 같은 episode 제안중복·다른 case 제안채택·새 REC 실패·원래 script/default/suite/exporthash 를검사한다.
- **작업 순서:** `test_w31_05`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w31.py::test_w31_05 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "duplicate_proposal_same": True,
  "foreign_proposal_rejected": True,
  "inplace_source_changes": 0,
  "new_full_recording": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w31-06"></a>

## W31-06 — healing 설정·진행·이력 UI 연결

- [x] **W31-06 완료** — 상태: `complete`. 근거: [W31-06 인계](../validation/tasks/W31-06.md).
- **직접 선행:** [W31-05](08a-self-healing.md#w31-05)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C06 / C07 / C09 / C14 + 직접 선행 receipt의 interface/제약. 추적: R21, R27, R33, R34, UI-04.09, UI-09.02, UI-10.02, UI-11.03.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W31-07에서 별도로 요구한다.
- **실제 통합 담당:** [W31-07](08a-self-healing.md#w31-07). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/web/templates/case_detail.html`, `src/aiqa/web/templates/execution_setup.html`, `src/aiqa/web/templates/execution.html`, `src/aiqa/web/templates/case_run.html`, `src/aiqa/api/healing.py`. 시험: `tests/acceptance/test_w31.py`.
- **입출력 계약:** `GET /api/v1/case-runs/{i}/healing-episodes -> HealingTimeline`
- **구현·화면·예외:** UI04/07 승인 scope·UI09OFF/ON/최대 1episode2 호출 30 초·UI10 phase/counters·UI11 원래 오류→제안→정책/동일 target→override→dispatch→QA 를표시한다. 치유 PASS 는 badge·진행중 toggle 없음·terminal 실패치유는새수행링크다. 실제 native/모델 연동 수용은 별도 live gate에 남기고 이 카드의 contract fixture 검증과 구분한다.
- **검증 전제:** 실제 API/브라우저에 격리된 episode/check/usage fixture를 넣어 OFF·ON 정상0호출·복구/거부/FAIL·terminal 표시를 검사한다. 실제 치유 정확성/dispatch/한도는 W31-07에서 검증한다.
- **작업 순서:** `test_w31_06`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w31.py::test_w31_06 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "default_toggle_off": True,
  "running_toggle_enabled": False,
  "healed_pass_badge": True,
  "original_error_hidden": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w31-07"></a>

## W31-07 — 양 플랫폼 실제 셀프힐링·QA 불변 통합 gate

- [ ] **W31-07 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W31-07.md`(구현 때 생성).
- **직접 선행:** [W31-06](08a-self-healing.md#w31-06), [W19-04](07-trial-and-review.md#w19-04), [W29-05](06-replay-packages.md#w29-05), [W30-03](06-replay-packages.md#w30-03), [W15-04](05a-action-evidence-and-models.md#w15-04)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C06 / C07 / C08 / C09 / C14 + 직접 선행 receipt의 interface/제약. 추적: R06, R16, R17, R33, R34.
- **검증 등급:** `live_integration`. 환경: `local_python`, `local_linux_vm`, `usb_android`, `model_binding`.
- **변경 파일:** `tests/integration/test_healing_live.py`, `docs/validation/healing-live.md`. 시험: `tests/integration/test_healing_live.py`.
- **입출력 계약:** `validate_live_healing(input: LiveHealingFixture) -> HealingGateReport`
- **구현·화면·예외:** W31-01–06의 계약/관리 UI 구현과 별도로 실제 Web/Android target 변경을 허용된 모델 binding으로 치유한다. 실제 lookup/dispatch 전후 evidence·원래 오류·동일 target 증명·episode1/전송retry포함2호출/30초·제품 FAIL/불명 재dispatch0·원본 code/default 불변을 검증한다. core fixture PASS는 이 live gate를 대체하지 않는다.
- **검증 전제:** 각 플랫폼의 승인된 합성 case에서 정상/OFF·허용 target 변경/ON·expected 위반·navigation/ADB 결과 불명·예산/lease 소진을 실제 실행하고 사람 oracle과 비교한다. VM/USB/key가 없으면 blocked로 남기고 core 작업을 되돌리지 않는다.
- **작업 순서:** `test_w31_07`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_healing_live.py::test_w31_07 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "platforms": 2,
  "false_passes": 0,
  "unknown_action_redispatches": 0,
  "healer_calls_per_episode_max": 2,
  "source_hash_changed": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

## 영역 종료 점검

- 카드·TASK_INDEX·실제 인계 상태를 맞춘다. 과거 완료를 문서 정리로 다시 구현하거나 무효화하지 않는다.
- 부모 W는 소속 leaf와 parent_gate_tasks/원래 통합 조건까지 만족해야 완료다.
- [UI_COVERAGE](UI_COVERAGE.md)·[COVERAGE](COVERAGE.md)의 실제 수용 조건은 그대로 유지한다.
