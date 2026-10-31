# H-1 · 선택 셀프힐링·제안 · 상세 작업서 v0.7

제품 설계 v0.6 + [공통 보완 계약](CONTRACTS.md). **제품 미착수: 완료0 / 6**.
[전체 색인](README.md) · [인계 양식](HANDOFF.md) · [UI 추적](UI_COVERAGE.md) · [요구/시험 추적](COVERAGE.md).

문서 전체를 한 번에 구현하지 않는다. **카드 한 개**와 직접 선행 근거를 읽는다.
파일/DTO/시험은 향후 산출물이며 현재 존재·통과를 뜻하지 않는다.
검증 projection은 실제 관찰에서 계산한다. [검증 예시 해석](README.md#4-카드의-검증-예시를-해석하는-법)을 따른다.

| 작업 | 선행 | 결과 |
|---|---|---|
| [W31-01](#w31-01) | [W19-04](07-trial-and-review.md#w19-04) | 실행별 healing 정책·ON/OFF snapshot |
| [W31-02](#w31-02) | [W31-01](08a-self-healing.md#w31-01) | 미 dispatch eligibility·episode 원자 예약 |
| [W31-03](#w31-03) | [W31-02](08a-self-healing.md#w31-02) | typed AI target 제안·동일 대상 증명 |
| [W31-04](#w31-04) | [W31-03](08a-self-healing.md#w31-03) | 임시 override·원래 동작 1 회·후속 QA |
| [W31-05](#w31-05) | [W31-04](08a-self-healing.md#w31-04) | 불변 repair proposal·전체 재녹화 채택 |
| [W31-06](#w31-06) | [W31-05](08a-self-healing.md#w31-05) | healing 설정·진행·이력 UI 연결 |

<a id="w31-01"></a>

## W31-01 — 실행별 healing 정책·ON/OFF snapshot

- [ ] **W31-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W31-01.md`(완료 시 생성).
- **직접 선행:** [W19-04](07-trial-and-review.md#w19-04)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C06 / C07 / C09 + 직접 선행 receipt의 interface/제약. 추적: R13, R17, R33.
- **변경 파일:** `src/aiqa/healing/policy.py`, `src/aiqa/domain/executions.py`, `src/aiqa/contracts/healing.py`. 담당 시험: `tests/integration/test_w31.py`.
- **입출력 계약:** `resolve_healing_policy(version: CaseVersion, request: HealingRequest, global_limits: Limits) -> ResolvedHealingPolicy`
- **구현·화면·예외:** 기본 OFF·approved capability/scope/binding/예산을검증하고더좁은 global 한도와교집합을 snapshot 한다. trial 은 OFF·진행중토글불가·권한/모델/상한확대는새 version/승인이다.
- **검증 전제:** allowedfalse 에서 ON·scope 확대·healerkey 없음·trialON·접수후 global/버전변경을요청한다.
- **작업 순서:** `test_w31_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w31.py::test_w31_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "default_enabled": False,
  "capability_false_on_rejected": True,
  "trial_enabled": False,
  "running_snapshot_mutated": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w31-02"></a>

## W31-02 — 미 dispatch eligibility·episode 원자 예약

- [ ] **W31-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W31-02.md`(완료 시 생성).
- **직접 선행:** [W31-01](08a-self-healing.md#w31-01)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C06 / C07 / C09 + 직접 선행 receipt의 interface/제약. 추적: R11, R12, R13, R33.
- **변경 파일:** `src/aiqa/healing/service.py`, `src/aiqa/healing/policy.py`, `src/aiqa/store/healing.py`. 담당 시험: `tests/integration/test_w31.py`.
- **입출력 계약:** `reserve_healing_episode(input: HealingTrigger, control: RunControl) -> HealingEpisodeReceipt`
- **구현·화면·예외:** target_not_found/ambiguous/layoutshift 의 read-only lookup 이며 dispatch_started 이력없을때만허용한다. ITEM episode1·모델합계 2 회(전송 retry 포함)·30 초/잔여 job·lease·예산중더엄격한한도를원자예약한다.
- **검증 전제:** 동시 trigger·중복 key·OFF·dispatch 후 timeout·rotation·제품위반·lease 부족을검사한다.
- **작업 순서:** `test_w31_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w31.py::test_w31_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "episodes_per_item_max": 1,
  "post_dispatch_eligible": False,
  "off_model_calls": 0,
  "duplicate_trigger_extra_episodes": 0
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w31-03"></a>

## W31-03 — typed AI target 제안·동일 대상 증명

- [ ] **W31-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W31-03.md`(완료 시 생성).
- **직접 선행:** [W31-02](08a-self-healing.md#w31-02)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C06 / C07 / C09 + 직접 선행 receipt의 interface/제약. 추적: R06, R14, R33, R34.
- **변경 파일:** `src/aiqa/healing/service.py`, `src/aiqa/healing/targets.py`, `src/aiqa/models/broker.py`. 담당 시험: `tests/integration/test_w31.py`.
- **입출력 계약:** `HealingService.propose(input: HealingContext) -> HealingProposal; validate_healing_proposal(proposal: HealingProposal, observation: Observation) -> HealingDecision`
- **구현·화면·예외:** 모델은 target 후보만 typed 반환하고신뢰코드가승인 role/name+container 또는 resource-id/text/context·unique/visible/enabled·동일 action/input/path 를증명한다. 좌표후보는검증된현재 elementbounds 안에서만. visual-only/canvas/newsemanticguess 는 MVP 거부다.
- **검증 전제:** 같은대상 locator 변경·동명이중 target·다른버튼·입력값변경·팝업닫기·canvas·범위밖좌표를제안한다.
- **작업 순서:** `test_w31_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w31.py::test_w31_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "same_target_proven": True,
  "ambiguous_candidate_accepted": False,
  "changed_action_accepted": False,
  "visual_only_accepted": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w31-04"></a>

## W31-04 — 임시 override·원래 동작 1 회·후속 QA

- [ ] **W31-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W31-04.md`(완료 시 생성).
- **직접 선행:** [W31-03](08a-self-healing.md#w31-03)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C06 / C07 / C09 + 직접 선행 receipt의 interface/제약. 추적: R06, R12, R17, R33.
- **변경 파일:** `src/aiqa/healing/service.py`, `src/aiqa/replay/action_executor.py`, `src/aiqa/domain/verdicts.py`. 담당 시험: `tests/integration/test_w31.py`.
- **입출력 계약:** `apply_runtime_override(input: AcceptedHealingProposal, control: RunControl) -> ActionObservation`
- **구현·화면·예외:** accepted target 만해당 ITEM 에 appendoverride 하고원래동작을공통 journal/capture 경로로 1 회 dispatch 한다. 원래 lookup 오류/제안/결정/거부/usage 를보존하고실제 check 를새로수행한다. 필수위반은 FAIL·laterterminal 변경 0 이다.
- **검증 전제:** 치유성공+모든 checkPASS·후속 expected 불일치·정제실패·dispatchtimeout·한도소진을검증한다.
- **작업 순서:** `test_w31_04`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w31.py::test_w31_04 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "original_action_dispatches": 1,
  "success_result": "PASS",
  "healing_used": True,
  "required_violation_result": "FAIL",
  "unassisted_pass": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w31-05"></a>

## W31-05 — 불변 repair proposal·전체 재녹화 채택

- [ ] **W31-05 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W31-05.md`(완료 시 생성).
- **직접 선행:** [W31-04](08a-self-healing.md#w31-04)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C06 / C07 / C09 / C08 + 직접 선행 receipt의 interface/제약. 추적: R08, R24, R33, R34, UI-11.02.
- **변경 파일:** `src/aiqa/healing/proposals.py`, `src/aiqa/api/healing.py`, `src/aiqa/api/recordings.py`, `src/aiqa/web/templates/components/repair_proposal.html`. 담당 시험: `tests/acceptance/test_w31.py`.
- **입출력 계약:** `POST /api/v1/healing-episodes/{e}/repair-proposals -> RepairProposalView; GET /api/v1/repair-proposals/{p}; POST /api/v1/cases/{c}/rerecordings(repair_proposal_id)`
- **구현·화면·예외:** episode/원래 package/acceptedtarget·diff/근거 hash 로불변제안을멱등저장한다. 사용자 diff 확인/사유후새 input/전체 REC 로채택하고 adoptionevent 를 append 한다. 바로 codepatch/승인·부분 merge·기본본수정은없다.
- **검증 전제:** 같은 episode 제안중복·다른 case 제안채택·새 REC 실패·원래 script/default/suite/exporthash 를검사한다.
- **작업 순서:** `test_w31_05`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w31.py::test_w31_05 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "duplicate_proposal_same": True,
  "foreign_proposal_rejected": True,
  "inplace_source_changes": 0,
  "new_full_recording": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w31-06"></a>

## W31-06 — healing 설정·진행·이력 UI 연결

- [ ] **W31-06 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W31-06.md`(완료 시 생성).
- **직접 선행:** [W31-05](08a-self-healing.md#w31-05)
- **읽기:** CONTRACTS C00 / C01 / C04 / C05 / C06 / C07 / C09 + 직접 선행 receipt의 interface/제약. 추적: R21, R27, R33, R34, UI-04.09, UI-09.02, UI-10.02, UI-11.03.
- **변경 파일:** `src/aiqa/web/templates/case_detail.html`, `src/aiqa/web/templates/execution_setup.html`, `src/aiqa/web/templates/execution.html`, `src/aiqa/web/templates/case_run.html`, `src/aiqa/api/healing.py`. 담당 시험: `tests/acceptance/test_w31.py`.
- **입출력 계약:** `GET /api/v1/case-runs/{i}/healing-episodes -> HealingTimeline`
- **구현·화면·예외:** UI04/07 승인 scope·UI09OFF/ON/최대 1episode2 호출 30 초·UI10 phase/counters·UI11 원래 오류→제안→정책/동일 target→override→dispatch→QA 를표시한다. 치유 PASS 는 badge·진행중 toggle 없음·terminal 실패치유는새수행링크다.
- **검증 전제:** 기본 OFF·ON 정상 0 호출·치유성공/거부/실패·제품 FAIL·terminal 후화면을검사한다.
- **작업 순서:** `test_w31_06`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w31.py::test_w31_06 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "default_toggle_off": True,
  "running_toggle_enabled": False,
  "healed_pass_badge": True,
  "original_error_hidden": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

## 영역 종료 점검

- 카드 체크·TASK_INDEX 상태·인계 근거가 일치해야 한다.
- [COVERAGE](COVERAGE.md)·[UI_COVERAGE](UI_COVERAGE.md)에서 담당 항목의 실제 증거를 연결한다.
- 후속 기능을 미리 완료 처리하지 않는다. 실패/계약 변경은 [REVIEW](REVIEW.md)에 기록하고 영향 작업을 재개한다.
