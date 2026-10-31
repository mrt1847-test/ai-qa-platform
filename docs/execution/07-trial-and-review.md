# G · 시범·사후 검토·승인 · 상세 작업서 v0.8

제품 설계 v0.6 + [보완 계약](CONTRACTS.md). **완료0 / 13**.
[Current 큐](../../NEXT_ACTION.md) · [전체 색인](README.md) · [차단/선행 수정](SCHEDULING.md) · [인계](HANDOFF.md).

카드 한 개와 직접 선행 근거만 읽는다. 기존 코드/complete/blocked 기록을 재사용한다.
검증 등급·live 수용을 구분한다. core fixture는 실제 native 근거가 아니며 최종 검증을 생략하지 않는다.

| 작업 | 직접 선행 | 결과 | 상태 |
|---|---|---|---|
| [W17-01](#w17-01) | [W29-04](06-replay-packages.md#w29-04), [W08-05](03-worker-and-sessions.md#w08-05), [W15-03](05a-action-evidence-and-models.md#w15-03), [W16-03](05b-recording-workflow.md#w16-03) | 미승인 trial preview·공통 RUN/ITEM 접수 | not_started |
| [W17-02](#w17-02) | [W17-01](07-trial-and-review.md#w17-01), [W13-01](05a-action-evidence-and-models.md#w13-01) | 결정적 Web·Android check 와 필수 경로 | not_started |
| [W17-03](#w17-03) | [W17-02](07-trial-and-review.md#w17-02), [W15-03](05a-action-evidence-and-models.md#w15-03) | 명시 AI verifier·unknown 보완·실패 latch | not_started |
| [W17-04](#w17-04) | [W17-03](07-trial-and-review.md#w17-03), [W16-07](05b-recording-workflow.md#w16-07), [W29-05](06-replay-packages.md#w29-05), [W30-03](06-replay-packages.md#w30-03) | ITEM seal·trial 현재근거·QA 표시 | not_started |
| [W18-01](#w18-01) | [W17-03](07-trial-and-review.md#w17-03), [W29-04](06-replay-packages.md#w29-04), [W14-03](05a-action-evidence-and-models.md#w14-03) | exact 검토 snapshot·evidence membership | not_started |
| [W18-02](#w18-02) | [W18-01](07-trial-and-review.md#w18-01) | 전후 screenshot·로그·단계 탐색 공통 viewer | not_started |
| [W18-03](#w18-03) | [W18-02](07-trial-and-review.md#w18-02) | action 별 사후 검토·미검토 이동·counts | not_started |
| [W18-04](#w18-04) | [W18-03](07-trial-and-review.md#w18-03) | 검토 입력·시범·버전·후보 diff 패널 | not_started |
| [W18-05](#w18-05) | [W18-04](07-trial-and-review.md#w18-04) | 검토 요청 수명·보호 조회·연장 UI | not_started |
| [W19-01](#w19-01) | [W18-05](07-trial-and-review.md#w18-05) | 승인·default·보호·audit 원자 CAS | not_started |
| [W19-02](#w19-02) | [W19-01](07-trial-and-review.md#w19-01) | 승인·반려 버튼·충돌·사유 UI | not_started |
| [W19-03](#w19-03) | [W19-02](07-trial-and-review.md#w19-02) | 명시 철회·queued 차단·running 취소 | not_started |
| [W19-04](#w19-04) | [W19-03](07-trial-and-review.md#w19-03), [W16-08](05b-recording-workflow.md#w16-08), [W16-04](05b-recording-workflow.md#w16-04), [W17-04](07-trial-and-review.md#w17-04) | 과거 승인·새 기본본·suite/RUN 불변 통합 | not_started |

<a id="w17-01"></a>

## W17-01 — 미승인 trial preview·공통 RUN/ITEM 접수

- [ ] **W17-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W17-01.md`(구현 때 생성).
- **직접 선행:** [W29-04](06-replay-packages.md#w29-04), [W08-05](03-worker-and-sessions.md#w08-05), [W15-03](05a-action-evidence-and-models.md#w15-03), [W16-03](05b-recording-workflow.md#w16-03)
- **읽기:** CONTRACTS C00 / C01 / C03 / C06 / C07 / C09 / C14 + 직접 선행 receipt의 interface/제약. 추적: R06, R09, R10, R28, R34, UI-07.02, UI-09.01.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W17-04, W19-04에서 별도로 요구한다.
- **실제 통합 담당:** [W17-04](07-trial-and-review.md#w17-04), [W19-04](07-trial-and-review.md#w19-04). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/domain/executions.py`, `src/aiqa/api/executions.py`, `src/aiqa/web/templates/execution_setup.html`. 시험: `tests/acceptance/test_w17.py`.
- **입출력 계약:** `preview_execution(actor: Actor, input: ExecutionPreviewInput) -> ExecutionPreview; enqueue_execution(actor: Actor, input: ExecutionCreateInput) -> ExecutionReceipt`
- **구현·화면·예외:** UI04/07 시범 버튼에서 UI09 공통 4 단계로 이동한다. 미승인 ready package trial 을 허용하고 healing OFF 를 서버가 강제한다. exact version/package/data/env·required checks·key/예산을 점검하고 RUN/ITEM/job 을 원자 생성한다.
- **검증 전제:** 테스트 DB의 exact package/check/binding fixture로 trial/OFF/키 없음/중복 접수 정책을 검사한다. production의 없는 runtime/키를 준비됨으로 표시하지 않는다.
- **작업 순서:** `test_w17_01`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w17.py::test_w17_01 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "unapproved_ready_trial": True,
  "no_package_trial": False,
  "trial_healing": False,
  "deterministic_keyless": True,
  "ai_required_keyless_blocked": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w17-02"></a>

## W17-02 — 결정적 Web·Android check 와 필수 경로

- [ ] **W17-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W17-02.md`(구현 때 생성).
- **직접 선행:** [W17-01](07-trial-and-review.md#w17-01), [W13-01](05a-action-evidence-and-models.md#w13-01)
- **읽기:** CONTRACTS C00 / C01 / C03 / C06 / C07 / C09 / C14 + 직접 선행 receipt의 interface/제약. 추적: R06, R09, R17.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W17-04, W19-04에서 별도로 요구한다.
- **실제 통합 담당:** [W17-04](07-trial-and-review.md#w17-04), [W19-04](07-trial-and-review.md#w19-04). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/validation/web.py`, `src/aiqa/validation/android.py`, `src/aiqa/validation/paths.py`, `src/aiqa/contracts/checks.py`. 시험: `tests/integration/test_w17.py`.
- **입출력 계약:** `Validator.evaluate(check: CheckSpec, observation: Observation) -> CheckResult`
- **구현·화면·예외:** 관찰가능 locator/state/text/value·Android hierarchy 로 expected 를 현재값과 대조한다. required path 는 실제 action mapping/journal 로 확인하고 API 우회로 목표만달성한 흐름은 위반이다. action 성공/engine done 은 PASS 가 아니다.
- **검증 전제:** 명시된 DOM/UI hierarchy/action journal fixture를 입력해 deterministic equal/violated/unknown·필수 경로를 평가한다. 실제 현재 화면과의 binding은 W17-04에서 검증한다.
- **작업 순서:** `test_w17_02`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w17.py::test_w17_02 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "equal": "satisfied",
  "mismatch": "violated",
  "missing_observation": "unknown",
  "engine_done_is_pass": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w17-03"></a>

## W17-03 — 명시 AI verifier·unknown 보완·실패 latch

- [ ] **W17-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W17-03.md`(구현 때 생성).
- **직접 선행:** [W17-02](07-trial-and-review.md#w17-02), [W15-03](05a-action-evidence-and-models.md#w15-03)
- **읽기:** CONTRACTS C00 / C01 / C03 / C06 / C07 / C09 / C14 + 직접 선행 receipt의 interface/제약. 추적: R06, R13, R17.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W17-04, W19-04에서 별도로 요구한다.
- **실제 통합 담당:** [W17-04](07-trial-and-review.md#w17-04), [W19-04](07-trial-and-review.md#w19-04). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/validation/visual.py`, `src/aiqa/models/broker.py`, `src/aiqa/domain/verdicts.py`. 시험: `tests/integration/test_w17.py`.
- **입출력 계약:** `evaluate_check_policy(check: CheckSpec, observation: Observation, control: RunControl) -> CheckResult`
- **구현·화면·예외:** deterministic/ai_visual/deterministic_then_ai_unknown 만 허용한다. unknown 보완은 사전허용 check 만, violated 에는 호출해 PASS 로 바꾸지 않는다. parsefail/가림/증거누락/예산부족은 unknown 이며 짧은 관찰/이유/근거를 보존한다.
- **검증 전제:** 테스트용 ModelTransport의 응답/timeout/parse 실패로 선언 check의 호출/unknown/FAIL latch를 검사한다. 실제 provider 호환/호출은 W15-04 및 live gate를 따른다.
- **작업 순서:** `test_w17_03`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w17.py::test_w17_03 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "violated_supplement_calls": 0,
  "undeclared_ai_calls": 0,
  "parse_failure": "unknown",
  "required_violation_final": "FAIL"
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w17-04"></a>

## W17-04 — ITEM seal·trial 현재근거·QA 표시

- [ ] **W17-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W17-04.md`(구현 때 생성).
- **직접 선행:** [W17-03](07-trial-and-review.md#w17-03), [W16-07](05b-recording-workflow.md#w16-07), [W29-05](06-replay-packages.md#w29-05), [W30-03](06-replay-packages.md#w30-03)
- **읽기:** CONTRACTS C00 / C01 / C03 / C06 / C07 / C09 + 직접 선행 receipt의 interface/제약. 추적: R06, R08, R09, R31, UI-10.01.
- **검증 등급:** `live_integration`. 환경: `local_python`, `local_linux_vm`, `usb_android`.
- **변경 파일:** `src/aiqa/domain/verdicts.py`, `src/aiqa/worker/runner.py`, `src/aiqa/api/executions.py`, `src/aiqa/web/templates/execution.html`. 시험: `tests/acceptance/test_w17.py`.
- **입출력 계약:** `finalize_item(input: ItemFinishInput) -> CaseRunView`
- **구현·화면·예외:** final_seq/ready evidence/check/path·violation latch·role facts·snapshot/hash 를 봉인한다. 부족증거는 PASS 금지, valid 위반우선 FAIL·preflight BLOCKED·불명 INCONCLUSIVE 다. UI 에 trial/purpose·현재근거·OFF/actor0 와진행을표시하고 자동승인 0 이다.
- **검증 전제:** Web/Android 정상·값불일치·missingafter·prepblocked·late finish·취소와위반을 확인한다.
- **작업 순서:** `test_w17_04`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w17.py::test_w17_04 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "auto_approvals": 0,
  "missing_evidence_pass": False,
  "terminal_rewrite": False,
  "required_violation": "FAIL"
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w18-01"></a>

## W18-01 — exact 검토 snapshot·evidence membership

- [ ] **W18-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W18-01.md`(구현 때 생성).
- **직접 선행:** [W17-03](07-trial-and-review.md#w17-03), [W29-04](06-replay-packages.md#w29-04), [W14-03](05a-action-evidence-and-models.md#w14-03)
- **읽기:** CONTRACTS C00 / C01 / C03 / C05 / C07 / C08 / C14 + 직접 선행 receipt의 interface/제약. 추적: R07, R08, R30, R34, UI-07.03.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W17-04, W19-04에서 별도로 요구한다.
- **실제 통합 담당:** [W17-04](07-trial-and-review.md#w17-04), [W19-04](07-trial-and-review.md#w19-04). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/recording/review_manifest.py`, `src/aiqa/api/cases.py`, `src/aiqa/store/artifacts.py`. 시험: `tests/acceptance/test_w18.py`.
- **입출력 계약:** `POST /api/v1/case-versions/{v}/review-requests -> ReviewSnapshot`
- **구현·화면·예외:** completed/stored source·ready package·sameexact OFF actor0 PASS trial·required evidence ready 를 확인한다. source/trial 의 owner/attempt/action/hash 를 불변 entries 로 고정하고 review30 일보호를 원자 등록한다.
- **검증 전제:** 격리된 DB/정제 파일의 source/trial fact fixture로 exact membership·보호·중복/타 ITEM 거부를 실제 transaction에서 검사한다. 이것은 실제 trial PASS의 근거가 아니다.
- **작업 순서:** `test_w18_01`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w18.py::test_w18_01 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "foreign_item_evidence_rejected": True,
  "same_action_id_mixing_rejected": True,
  "healed_trial_accepted": False,
  "review_pins_created": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w18-02"></a>

## W18-02 — 전후 screenshot·로그·단계 탐색 공통 viewer

- [ ] **W18-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W18-02.md`(구현 때 생성).
- **직접 선행:** [W18-01](07-trial-and-review.md#w18-01)
- **읽기:** CONTRACTS C00 / C01 / C03 / C05 / C07 / C08 / C14 + 직접 선행 receipt의 interface/제약. 추적: R07, R14, R21, R27, UI-07.04, UI-11.01.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W17-04, W19-04에서 별도로 요구한다.
- **실제 통합 담당:** [W17-04](07-trial-and-review.md#w17-04), [W19-04](07-trial-and-review.md#w19-04). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/web/templates/components/evidence_viewer.html`, `src/aiqa/web/static/evidence_viewer.js`, `src/aiqa/api/artifacts.py`. 시험: `tests/acceptance/test_w18.py`.
- **입출력 계약:** `EvidenceViewerSelection(owner_kind, owner_id, attempt_id, action_id); GET /api/v1/artifacts/{a}/retention`
- **구현·화면·예외:** UI07/11 용 step→실제 action·전후/이전다음/첫실패·fit/100%/zoom/pan/전체보기·capture 시각/geometry/좌표 swipe·마스킹/ID/log/error/check 를 제공한다. missing/expired/corrupt/delayed 는이미지대신사유이며다른 run PNG 대체 0 이다.
- **검증 전제:** 여러 attempt 의동일 actionID·긴로그·PNG 누락/만료·1024px·키보드이전다음·새로고침 selected 를 확인한다.
- **작업 순서:** `test_w18_02`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w18.py::test_w18_02 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "exact_selection_restored": True,
  "missing_image_substituted": False,
  "keyboard_navigation": True,
  "before_after_distinct": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w18-03"></a>

## W18-03 — action 별 사후 검토·미검토 이동·counts

- [ ] **W18-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W18-03.md`(구현 때 생성).
- **직접 선행:** [W18-02](07-trial-and-review.md#w18-02)
- **읽기:** CONTRACTS C00 / C01 / C03 / C05 / C07 / C08 / C14 + 직접 선행 receipt의 interface/제약. 추적: R07, R08, R30, UI-07.05.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W17-04, W19-04에서 별도로 요구한다.
- **실제 통합 담당:** [W17-04](07-trial-and-review.md#w17-04), [W19-04](07-trial-and-review.md#w19-04). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/recording/review_manifest.py`, `src/aiqa/api/cases.py`, `src/aiqa/web/templates/case_review.html`. 시험: `tests/acceptance/test_w18.py`.
- **입출력 계약:** `POST /api/v1/case-versions/{v}/action-reviews -> ActionReviewView`
- **구현·화면·예외:** reviewed/needs_change/evidence_missing·comment/actor/time 을 exactentry/digest 에 append 한다. 같은 reviewer 최신의견 projection 과과거이력·source/trial 별 counts·다음미검토이동을구현한다. QA 판정변경 0·녹화중검토금지다.
- **검증 전제:** 미검토 3→2·수정필요→reviewed·증거 digest 변경 409·다른 entry·녹화중요청을 확인한다.
- **작업 순서:** `test_w18_03`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w18.py::test_w18_03 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "reviews_append_only": True,
  "qa_unchanged": True,
  "count_uses_full_owner_key": True,
  "recording_review_allowed": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w18-04"></a>

## W18-04 — 검토 입력·시범·버전·후보 diff 패널

- [ ] **W18-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W18-04.md`(구현 때 생성).
- **직접 선행:** [W18-03](07-trial-and-review.md#w18-03)
- **읽기:** CONTRACTS C00 / C01 / C03 / C05 / C07 / C08 / C14 + 직접 선행 receipt의 interface/제약. 추적: R08, R24, R27, R30, R34, UI-07.06.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W17-04, W19-04에서 별도로 요구한다.
- **실제 통합 담당:** [W17-04](07-trial-and-review.md#w17-04), [W19-04](07-trial-and-review.md#w19-04). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/web/templates/case_review.html`, `src/aiqa/web/templates/components/case_diff.html`, `src/aiqa/api/cases.py`. 시험: `tests/acceptance/test_w18.py`.
- **입출력 계약:** `GET /api/v1/case-versions/{v}/review-readiness -> ReviewReadiness`
- **구현·화면·예외:** UI07 단계/입력·설정/시범/저장기록/버전탭·base↔candidate 정의/경로/절차/target/설정/오류/근거 diff 를 표시한다. package/lock/mapping·OFF trial·검토누락·evidence 원인별승인차단과새 draft/전체재녹화링크를제공한다.
- **검증 전제:** 원문 expected 변경·절차만변경·partialstored·package0·trial 오래된 hash·미검토 1 건을 확인한다.
- **작업 순서:** `test_w18_04`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w18.py::test_w18_04 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "incomplete_candidate_approve": False,
  "block_reasons_explicit": True,
  "old_review_copied": False,
  "source_trial_tabs_distinct": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w18-05"></a>

## W18-05 — 검토 요청 수명·보호 조회·연장 UI

- [ ] **W18-05 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W18-05.md`(구현 때 생성).
- **직접 선행:** [W18-04](07-trial-and-review.md#w18-04)
- **읽기:** CONTRACTS C00 / C01 / C03 / C05 / C07 / C08 / C14 + 직접 선행 receipt의 interface/제약. 추적: R08, R15, R30, UI-07.07.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W17-04, W19-04에서 별도로 요구한다.
- **실제 통합 담당:** [W17-04](07-trial-and-review.md#w17-04), [W19-04](07-trial-and-review.md#w19-04). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/api/cases.py`, `src/aiqa/store/artifacts.py`, `src/aiqa/web/templates/case_review.html`. 시험: `tests/acceptance/test_w18.py`.
- **입출력 계약:** `POST /api/v1/review-requests/{r}/retention-extensions -> ProtectionReceipt`
- **구현·화면·예외:** 열린 review30 일 임시보호·기한/보호사유를표시하고 연장은새보호 event 다. 만료된 artifact 가있으면승인차단+새 REC/trial 안내, 반려 record 는보존하고 영구 pin 으로오인하지않는다.
- **검증 전제:** fakeclock30 일경과·연장·기존 expiryimmutable·파일이미 expired·다른 validapprovalpin 을 검사한다.
- **작업 순서:** `test_w18_05`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w18.py::test_w18_05 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "extension_appends": True,
  "expired_missing_approve": False,
  "rejected_record_retained": True,
  "other_approval_pin_preserved": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w19-01"></a>

## W19-01 — 승인·default·보호·audit 원자 CAS

- [ ] **W19-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W19-01.md`(구현 때 생성).
- **직접 선행:** [W18-05](07-trial-and-review.md#w18-05)
- **읽기:** CONTRACTS C00 / C01 / C03 / C08 / C09 / C10 / C14 + 직접 선행 receipt의 interface/제약. 추적: R08, R12, R24, R30, R34.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/domain/approvals.py`, `src/aiqa/api/cases.py`, `src/aiqa/store/artifacts.py`. 시험: `tests/integration/test_w19.py`.
- **입출력 계약:** `approve_case(actor: Actor, input: ApprovalInput) -> ApprovalReceipt`
- **구현·화면·예외:** exactreview/source/trial/package/check/policy/evidence·필수 action 검토·currentapprovalCAS 를 transaction 에서재검사한다. approved event·requiredscript/source/trialevidence pin·currentpointer·audit 를함께확정한다. 기존승인은유효유지다.
- **검증 전제:** 중간 pin/포인터오류·동시후보승인·GC 경합·hash 불일치·중복 key 를요청한다.
- **작업 순서:** `test_w19_01`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w19.py::test_w19_01 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "partial_approval_rows": 0,
  "concurrent_loser_status": 409,
  "old_approval_auto_revoked": False,
  "default_and_pins_atomic": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w19-02"></a>

## W19-02 — 승인·반려 버튼·충돌·사유 UI

- [ ] **W19-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W19-02.md`(구현 때 생성).
- **직접 선행:** [W19-01](07-trial-and-review.md#w19-01)
- **읽기:** CONTRACTS C00 / C01 / C03 / C08 / C09 / C10 / C14 + 직접 선행 receipt의 interface/제약. 추적: R08, R21, R24, R30, UI-07.08.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/web/templates/case_review.html`, `src/aiqa/api/cases.py`, `src/aiqa/domain/approvals.py`. 시험: `tests/acceptance/test_w19.py`.
- **입출력 계약:** `POST /api/v1/case-versions/{v}/approvals; POST /api/v1/case-versions/{v}/rejections -> DecisionReceipt`
- **구현·화면·예외:** 버튼문구는 이 버전 승인 및 기본 실행본으로 사용. 반려사유/actor/time·candidatehash 를저장하고기록/기존 default 유지다. 409 때새 current/diff 와입력보존, 자동반복승인없음. 실패/중단/반려재녹화후보의 default 유지를 UI 에서검증한다.
- **검증 전제:** test DB와 실제 browser에서 v2/후보 실패/반려/동시409·기본본 유지 UI를 검사한다. 실제 재녹화→새 승인 여정은 W19-04에서 검증한다.
- **작업 순서:** `test_w19_02`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w19.py::test_w19_02 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "failed_candidate_changes_default": False,
  "rejected_record_deleted": False,
  "stale_approval_auto_retried": False,
  "reason_required": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w19-03"></a>

## W19-03 — 명시 철회·queued 차단·running 취소

- [ ] **W19-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W19-03.md`(구현 때 생성).
- **직접 선행:** [W19-02](07-trial-and-review.md#w19-02)
- **읽기:** CONTRACTS C00 / C01 / C03 / C08 / C09 / C10 / C14 + 직접 선행 receipt의 interface/제약. 추적: R08, R11, R12, R24, UI-07.09.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/domain/approvals.py`, `src/aiqa/api/cases.py`, `src/aiqa/store/queue.py`, `src/aiqa/web/templates/components/revoke_confirm.html`. 시험: `tests/acceptance/test_w19.py`.
- **입출력 계약:** `POST /api/v1/approvals/{a}/revoke -> RevokeReceipt`
- **구현·화면·예외:** 철회영향에 exactapproval 의 queued/running·suite 참조를보여주고사유/expectedcurrent 로 append 한다. queuedclaim BLOCKED·runningcancel 영구기록·approvalpin 해제+90 일유예·현재 pointer null 을원자확정한다. 과거본자동 fallback/완료 QA 변경 0 이다.
- **검증 전제:** current/oldapproval 철회·반복철회·claim/approve 경합·진행중위반을검사한다.
- **작업 순서:** `test_w19_03`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w19.py::test_w19_03 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "current_default_after_revoke": None,
  "automatic_fallback": False,
  "queued_claim_blocked": True,
  "terminal_qa_changed": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w19-04"></a>

## W19-04 — 과거 승인·새 기본본·suite/RUN 불변 통합

- [ ] **W19-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W19-04.md`(구현 때 생성).
- **직접 선행:** [W19-03](07-trial-and-review.md#w19-03), [W16-08](05b-recording-workflow.md#w16-08), [W16-04](05b-recording-workflow.md#w16-04), [W17-04](07-trial-and-review.md#w17-04)
- **읽기:** CONTRACTS C00 / C01 / C03 / C08 / C09 / C10 + 직접 선행 receipt의 interface/제약. 추적: R08, R09, R24, R28, R30.
- **검증 등급:** `live_integration`. 환경: `local_python`, `local_linux_vm`, `usb_android`, `model_binding`.
- **변경 파일:** `tests/integration/test_approval_lifecycle.py`, `docs/validation/approval-lifecycle.md`. 시험: `tests/integration/test_w19.py`.
- **입출력 계약:** `validate_approval_lifecycle(fixture: ApprovalLifecycleFixture) -> LifecycleReport`
- **구현·화면·예외:** v2 유효승인/suite/queuedRUN→후보재녹화/새 OFFtrial/검토→v4 승인뒤새기본만 v4 를선택함을검증한다. suite 명시교체는 W21 이고 oldrevoke 별도다. 실제 UI/DB/파일 hash 를근거로남긴다.
- **검증 전제:** 승인전/후기존 suite·queued/running·oldpin·원본 source/export 와 TC 변경을대조한다.
- **작업 순서:** `test_w19_04`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w19.py::test_w19_04 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "old_suite_version_unchanged": True,
  "old_run_snapshot_unchanged": True,
  "old_valid_evidence_pinned": True,
  "tc_changes_block_execution": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

## 영역 종료 점검

- 카드·TASK_INDEX·실제 인계 상태를 맞춘다. 과거 완료를 문서 정리로 다시 구현하거나 무효화하지 않는다.
- 부모 W는 소속 leaf와 parent_gate_tasks/원래 통합 조건까지 만족해야 완료다.
- [UI_COVERAGE](UI_COVERAGE.md)·[COVERAGE](COVERAGE.md)의 실제 수용 조건은 그대로 유지한다.
