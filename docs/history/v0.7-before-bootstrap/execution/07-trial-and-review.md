# G · 시범·사후 검토·승인 · 상세 작업서 v0.7

제품 설계 v0.6 + [공통 보완 계약](CONTRACTS.md). **제품 미착수: 완료0 / 13**.
[전체 색인](README.md) · [인계 양식](HANDOFF.md) · [UI 추적](UI_COVERAGE.md) · [요구/시험 추적](COVERAGE.md).

문서 전체를 한 번에 구현하지 않는다. **카드 한 개**와 직접 선행 근거를 읽는다.
파일/DTO/시험은 향후 산출물이며 현재 존재·통과를 뜻하지 않는다.
검증 projection은 실제 관찰에서 계산한다. [검증 예시 해석](README.md#4-카드의-검증-예시를-해석하는-법)을 따른다.

| 작업 | 선행 | 결과 |
|---|---|---|
| [W17-01](#w17-01) | [W16-07](05b-recording-workflow.md#w16-07), [W16-08](05b-recording-workflow.md#w16-08) | 미승인 trial preview·공통 RUN/ITEM 접수 |
| [W17-02](#w17-02) | [W17-01](07-trial-and-review.md#w17-01) | 결정적 Web·Android check 와 필수 경로 |
| [W17-03](#w17-03) | [W17-02](07-trial-and-review.md#w17-02) | 명시 AI verifier·unknown 보완·실패 latch |
| [W17-04](#w17-04) | [W17-03](07-trial-and-review.md#w17-03) | ITEM seal·trial 현재근거·QA 표시 |
| [W18-01](#w18-01) | [W17-04](07-trial-and-review.md#w17-04) | exact 검토 snapshot·evidence membership |
| [W18-02](#w18-02) | [W18-01](07-trial-and-review.md#w18-01) | 전후 screenshot·로그·단계 탐색 공통 viewer |
| [W18-03](#w18-03) | [W18-02](07-trial-and-review.md#w18-02) | action 별 사후 검토·미검토 이동·counts |
| [W18-04](#w18-04) | [W18-03](07-trial-and-review.md#w18-03) | 검토 입력·시범·버전·후보 diff 패널 |
| [W18-05](#w18-05) | [W18-04](07-trial-and-review.md#w18-04) | 검토 요청 수명·보호 조회·연장 UI |
| [W19-01](#w19-01) | [W18-05](07-trial-and-review.md#w18-05) | 승인·default·보호·audit 원자 CAS |
| [W19-02](#w19-02) | [W19-01](07-trial-and-review.md#w19-01) | 승인·반려 버튼·충돌·사유 UI |
| [W19-03](#w19-03) | [W19-02](07-trial-and-review.md#w19-02) | 명시 철회·queued 차단·running 취소 |
| [W19-04](#w19-04) | [W19-03](07-trial-and-review.md#w19-03) | 과거 승인·새 기본본·suite/RUN 불변 통합 |

<a id="w17-01"></a>

## W17-01 — 미승인 trial preview·공통 RUN/ITEM 접수

- [ ] **W17-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W17-01.md`(완료 시 생성).
- **직접 선행:** [W16-07](05b-recording-workflow.md#w16-07), [W16-08](05b-recording-workflow.md#w16-08)
- **읽기:** CONTRACTS C00 / C01 / C03 / C06 / C07 / C09 + 직접 선행 receipt의 interface/제약. 추적: R06, R09, R10, R28, R34, UI-07.02, UI-09.01.
- **변경 파일:** `src/aiqa/domain/executions.py`, `src/aiqa/api/executions.py`, `src/aiqa/web/templates/execution_setup.html`. 담당 시험: `tests/acceptance/test_w17.py`.
- **입출력 계약:** `preview_execution(actor: Actor, input: ExecutionPreviewInput) -> ExecutionPreview; enqueue_execution(actor: Actor, input: ExecutionCreateInput) -> ExecutionReceipt`
- **구현·화면·예외:** UI04/07 시범 버튼에서 UI09 공통 4 단계로 이동한다. 미승인 ready package trial 을 허용하고 healing OFF 를 서버가 강제한다. exact version/package/data/env·required checks·key/예산을 점검하고 RUN/ITEM/job 을 원자 생성한다.
- **검증 전제:** 미승인 ready·package0·healing ON trial·결정적키없음·AI 검증키없음·중복시작을 요청한다.
- **작업 순서:** `test_w17_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w17.py::test_w17_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "unapproved_ready_trial": True,
  "no_package_trial": False,
  "trial_healing": False,
  "deterministic_keyless": True,
  "ai_required_keyless_blocked": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w17-02"></a>

## W17-02 — 결정적 Web·Android check 와 필수 경로

- [ ] **W17-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W17-02.md`(완료 시 생성).
- **직접 선행:** [W17-01](07-trial-and-review.md#w17-01)
- **읽기:** CONTRACTS C00 / C01 / C03 / C06 / C07 / C09 + 직접 선행 receipt의 interface/제약. 추적: R06, R09, R17.
- **변경 파일:** `src/aiqa/validation/web.py`, `src/aiqa/validation/android.py`, `src/aiqa/validation/paths.py`, `src/aiqa/contracts/checks.py`. 담당 시험: `tests/integration/test_w17.py`.
- **입출력 계약:** `Validator.evaluate(check: CheckSpec, observation: Observation) -> CheckResult`
- **구현·화면·예외:** 관찰가능 locator/state/text/value·Android hierarchy 로 expected 를 현재값과 대조한다. required path 는 실제 action mapping/journal 로 확인하고 API 우회로 목표만달성한 흐름은 위반이다. action 성공/engine done 은 PASS 가 아니다.
- **검증 전제:** 기대값일치/불일치·필수버튼경로누락·조회불가·timeout 과조작성공만있는 흐름을 평가한다.
- **작업 순서:** `test_w17_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w17.py::test_w17_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "equal": "satisfied",
  "mismatch": "violated",
  "missing_observation": "unknown",
  "engine_done_is_pass": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w17-03"></a>

## W17-03 — 명시 AI verifier·unknown 보완·실패 latch

- [ ] **W17-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W17-03.md`(완료 시 생성).
- **직접 선행:** [W17-02](07-trial-and-review.md#w17-02)
- **읽기:** CONTRACTS C00 / C01 / C03 / C06 / C07 / C09 + 직접 선행 receipt의 interface/제약. 추적: R06, R13, R17.
- **변경 파일:** `src/aiqa/validation/visual.py`, `src/aiqa/models/broker.py`, `src/aiqa/domain/verdicts.py`. 담당 시험: `tests/integration/test_w17.py`.
- **입출력 계약:** `evaluate_check_policy(check: CheckSpec, observation: Observation, control: RunControl) -> CheckResult`
- **구현·화면·예외:** deterministic/ai_visual/deterministic_then_ai_unknown 만 허용한다. unknown 보완은 사전허용 check 만, violated 에는 호출해 PASS 로 바꾸지 않는다. parsefail/가림/증거누락/예산부족은 unknown 이며 짧은 관찰/이유/근거를 보존한다.
- **검증 전제:** deterministic satisfied/violated/unknown·AI timeout·잘못된 JSON·가림·필수위반뒤다음 PASS 를 검증한다.
- **작업 순서:** `test_w17_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w17.py::test_w17_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "violated_supplement_calls": 0,
  "undeclared_ai_calls": 0,
  "parse_failure": "unknown",
  "required_violation_final": "FAIL"
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w17-04"></a>

## W17-04 — ITEM seal·trial 현재근거·QA 표시

- [ ] **W17-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W17-04.md`(완료 시 생성).
- **직접 선행:** [W17-03](07-trial-and-review.md#w17-03)
- **읽기:** CONTRACTS C00 / C01 / C03 / C06 / C07 / C09 + 직접 선행 receipt의 interface/제약. 추적: R06, R08, R09, R31, UI-10.01.
- **변경 파일:** `src/aiqa/domain/verdicts.py`, `src/aiqa/worker/runner.py`, `src/aiqa/api/executions.py`, `src/aiqa/web/templates/execution.html`. 담당 시험: `tests/acceptance/test_w17.py`.
- **입출력 계약:** `finalize_item(input: ItemFinishInput) -> CaseRunView`
- **구현·화면·예외:** final_seq/ready evidence/check/path·violation latch·role facts·snapshot/hash 를 봉인한다. 부족증거는 PASS 금지, valid 위반우선 FAIL·preflight BLOCKED·불명 INCONCLUSIVE 다. UI 에 trial/purpose·현재근거·OFF/actor0 와진행을표시하고 자동승인 0 이다.
- **검증 전제:** Web/Android 정상·값불일치·missingafter·prepblocked·late finish·취소와위반을 확인한다.
- **작업 순서:** `test_w17_04`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w17.py::test_w17_04 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "auto_approvals": 0,
  "missing_evidence_pass": False,
  "terminal_rewrite": False,
  "required_violation": "FAIL"
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w18-01"></a>

## W18-01 — exact 검토 snapshot·evidence membership

- [ ] **W18-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W18-01.md`(완료 시 생성).
- **직접 선행:** [W17-04](07-trial-and-review.md#w17-04)
- **읽기:** CONTRACTS C00 / C01 / C03 / C05 / C07 / C08 + 직접 선행 receipt의 interface/제약. 추적: R07, R08, R30, R34, UI-07.03.
- **변경 파일:** `src/aiqa/recording/review_manifest.py`, `src/aiqa/api/cases.py`, `src/aiqa/store/artifacts.py`. 담당 시험: `tests/acceptance/test_w18.py`.
- **입출력 계약:** `POST /api/v1/case-versions/{v}/review-requests -> ReviewSnapshot`
- **구현·화면·예외:** completed/stored source·ready package·sameexact OFF actor0 PASS trial·required evidence ready 를 확인한다. source/trial 의 owner/attempt/action/hash 를 불변 entries 로 고정하고 review30 일보호를 원자 등록한다.
- **검증 전제:** 같은 case 다른 ITEM PNG·같은 A001 다른 attempt·다른 source/hash·storing 중·치유 PASStrial 을 넣는다.
- **작업 순서:** `test_w18_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w18.py::test_w18_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "foreign_item_evidence_rejected": True,
  "same_action_id_mixing_rejected": True,
  "healed_trial_accepted": False,
  "review_pins_created": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w18-02"></a>

## W18-02 — 전후 screenshot·로그·단계 탐색 공통 viewer

- [ ] **W18-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W18-02.md`(완료 시 생성).
- **직접 선행:** [W18-01](07-trial-and-review.md#w18-01)
- **읽기:** CONTRACTS C00 / C01 / C03 / C05 / C07 / C08 + 직접 선행 receipt의 interface/제약. 추적: R07, R14, R21, R27, UI-07.04, UI-11.01.
- **변경 파일:** `src/aiqa/web/templates/components/evidence_viewer.html`, `src/aiqa/web/static/evidence_viewer.js`, `src/aiqa/api/artifacts.py`. 담당 시험: `tests/acceptance/test_w18.py`.
- **입출력 계약:** `EvidenceViewerSelection(owner_kind, owner_id, attempt_id, action_id); GET /api/v1/artifacts/{a}/retention`
- **구현·화면·예외:** UI07/11 용 step→실제 action·전후/이전다음/첫실패·fit/100%/zoom/pan/전체보기·capture 시각/geometry/좌표 swipe·마스킹/ID/log/error/check 를 제공한다. missing/expired/corrupt/delayed 는이미지대신사유이며다른 run PNG 대체 0 이다.
- **검증 전제:** 여러 attempt 의동일 actionID·긴로그·PNG 누락/만료·1024px·키보드이전다음·새로고침 selected 를 확인한다.
- **작업 순서:** `test_w18_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w18.py::test_w18_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "exact_selection_restored": True,
  "missing_image_substituted": False,
  "keyboard_navigation": True,
  "before_after_distinct": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w18-03"></a>

## W18-03 — action 별 사후 검토·미검토 이동·counts

- [ ] **W18-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W18-03.md`(완료 시 생성).
- **직접 선행:** [W18-02](07-trial-and-review.md#w18-02)
- **읽기:** CONTRACTS C00 / C01 / C03 / C05 / C07 / C08 + 직접 선행 receipt의 interface/제약. 추적: R07, R08, R30, UI-07.05.
- **변경 파일:** `src/aiqa/recording/review_manifest.py`, `src/aiqa/api/cases.py`, `src/aiqa/web/templates/case_review.html`. 담당 시험: `tests/acceptance/test_w18.py`.
- **입출력 계약:** `POST /api/v1/case-versions/{v}/action-reviews -> ActionReviewView`
- **구현·화면·예외:** reviewed/needs_change/evidence_missing·comment/actor/time 을 exactentry/digest 에 append 한다. 같은 reviewer 최신의견 projection 과과거이력·source/trial 별 counts·다음미검토이동을구현한다. QA 판정변경 0·녹화중검토금지다.
- **검증 전제:** 미검토 3→2·수정필요→reviewed·증거 digest 변경 409·다른 entry·녹화중요청을 확인한다.
- **작업 순서:** `test_w18_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w18.py::test_w18_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "reviews_append_only": True,
  "qa_unchanged": True,
  "count_uses_full_owner_key": True,
  "recording_review_allowed": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w18-04"></a>

## W18-04 — 검토 입력·시범·버전·후보 diff 패널

- [ ] **W18-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W18-04.md`(완료 시 생성).
- **직접 선행:** [W18-03](07-trial-and-review.md#w18-03)
- **읽기:** CONTRACTS C00 / C01 / C03 / C05 / C07 / C08 + 직접 선행 receipt의 interface/제약. 추적: R08, R24, R27, R30, R34, UI-07.06.
- **변경 파일:** `src/aiqa/web/templates/case_review.html`, `src/aiqa/web/templates/components/case_diff.html`, `src/aiqa/api/cases.py`. 담당 시험: `tests/acceptance/test_w18.py`.
- **입출력 계약:** `GET /api/v1/case-versions/{v}/review-readiness -> ReviewReadiness`
- **구현·화면·예외:** UI07 단계/입력·설정/시범/저장기록/버전탭·base↔candidate 정의/경로/절차/target/설정/오류/근거 diff 를 표시한다. package/lock/mapping·OFF trial·검토누락·evidence 원인별승인차단과새 draft/전체재녹화링크를제공한다.
- **검증 전제:** 원문 expected 변경·절차만변경·partialstored·package0·trial 오래된 hash·미검토 1 건을 확인한다.
- **작업 순서:** `test_w18_04`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w18.py::test_w18_04 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "incomplete_candidate_approve": False,
  "block_reasons_explicit": True,
  "old_review_copied": False,
  "source_trial_tabs_distinct": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w18-05"></a>

## W18-05 — 검토 요청 수명·보호 조회·연장 UI

- [ ] **W18-05 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W18-05.md`(완료 시 생성).
- **직접 선행:** [W18-04](07-trial-and-review.md#w18-04)
- **읽기:** CONTRACTS C00 / C01 / C03 / C05 / C07 / C08 + 직접 선행 receipt의 interface/제약. 추적: R08, R15, R30, UI-07.07.
- **변경 파일:** `src/aiqa/api/cases.py`, `src/aiqa/store/artifacts.py`, `src/aiqa/web/templates/case_review.html`. 담당 시험: `tests/acceptance/test_w18.py`.
- **입출력 계약:** `POST /api/v1/review-requests/{r}/retention-extensions -> ProtectionReceipt`
- **구현·화면·예외:** 열린 review30 일 임시보호·기한/보호사유를표시하고 연장은새보호 event 다. 만료된 artifact 가있으면승인차단+새 REC/trial 안내, 반려 record 는보존하고 영구 pin 으로오인하지않는다.
- **검증 전제:** fakeclock30 일경과·연장·기존 expiryimmutable·파일이미 expired·다른 validapprovalpin 을 검사한다.
- **작업 순서:** `test_w18_05`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w18.py::test_w18_05 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "extension_appends": True,
  "expired_missing_approve": False,
  "rejected_record_retained": True,
  "other_approval_pin_preserved": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w19-01"></a>

## W19-01 — 승인·default·보호·audit 원자 CAS

- [ ] **W19-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W19-01.md`(완료 시 생성).
- **직접 선행:** [W18-05](07-trial-and-review.md#w18-05)
- **읽기:** CONTRACTS C00 / C01 / C03 / C08 / C09 / C10 + 직접 선행 receipt의 interface/제약. 추적: R08, R12, R24, R30, R34.
- **변경 파일:** `src/aiqa/domain/approvals.py`, `src/aiqa/api/cases.py`, `src/aiqa/store/artifacts.py`. 담당 시험: `tests/integration/test_w19.py`.
- **입출력 계약:** `approve_case(actor: Actor, input: ApprovalInput) -> ApprovalReceipt`
- **구현·화면·예외:** exactreview/source/trial/package/check/policy/evidence·필수 action 검토·currentapprovalCAS 를 transaction 에서재검사한다. approved event·requiredscript/source/trialevidence pin·currentpointer·audit 를함께확정한다. 기존승인은유효유지다.
- **검증 전제:** 중간 pin/포인터오류·동시후보승인·GC 경합·hash 불일치·중복 key 를요청한다.
- **작업 순서:** `test_w19_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w19.py::test_w19_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "partial_approval_rows": 0,
  "concurrent_loser_status": 409,
  "old_approval_auto_revoked": False,
  "default_and_pins_atomic": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w19-02"></a>

## W19-02 — 승인·반려 버튼·충돌·사유 UI

- [ ] **W19-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W19-02.md`(완료 시 생성).
- **직접 선행:** [W19-01](07-trial-and-review.md#w19-01)
- **읽기:** CONTRACTS C00 / C01 / C03 / C08 / C09 / C10 + 직접 선행 receipt의 interface/제약. 추적: R08, R21, R24, R30, UI-07.08.
- **변경 파일:** `src/aiqa/web/templates/case_review.html`, `src/aiqa/api/cases.py`, `src/aiqa/domain/approvals.py`. 담당 시험: `tests/acceptance/test_w19.py`.
- **입출력 계약:** `POST /api/v1/case-versions/{v}/approvals; POST /api/v1/case-versions/{v}/rejections -> DecisionReceipt`
- **구현·화면·예외:** 버튼문구는 이 버전 승인 및 기본 실행본으로 사용. 반려사유/actor/time·candidatehash 를저장하고기록/기존 default 유지다. 409 때새 current/diff 와입력보존, 자동반복승인없음. 실패/중단/반려재녹화후보의 default 유지를 UI 에서검증한다.
- **검증 전제:** v2 승인→후보실패/중단/반려→새후보승인·동시 409·사유누락 422 를실행한다.
- **작업 순서:** `test_w19_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w19.py::test_w19_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "failed_candidate_changes_default": False,
  "rejected_record_deleted": False,
  "stale_approval_auto_retried": False,
  "reason_required": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w19-03"></a>

## W19-03 — 명시 철회·queued 차단·running 취소

- [ ] **W19-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W19-03.md`(완료 시 생성).
- **직접 선행:** [W19-02](07-trial-and-review.md#w19-02)
- **읽기:** CONTRACTS C00 / C01 / C03 / C08 / C09 / C10 + 직접 선행 receipt의 interface/제약. 추적: R08, R11, R12, R24, UI-07.09.
- **변경 파일:** `src/aiqa/domain/approvals.py`, `src/aiqa/api/cases.py`, `src/aiqa/store/queue.py`, `src/aiqa/web/templates/components/revoke_confirm.html`. 담당 시험: `tests/acceptance/test_w19.py`.
- **입출력 계약:** `POST /api/v1/approvals/{a}/revoke -> RevokeReceipt`
- **구현·화면·예외:** 철회영향에 exactapproval 의 queued/running·suite 참조를보여주고사유/expectedcurrent 로 append 한다. queuedclaim BLOCKED·runningcancel 영구기록·approvalpin 해제+90 일유예·현재 pointer null 을원자확정한다. 과거본자동 fallback/완료 QA 변경 0 이다.
- **검증 전제:** current/oldapproval 철회·반복철회·claim/approve 경합·진행중위반을검사한다.
- **작업 순서:** `test_w19_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w19.py::test_w19_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "current_default_after_revoke": None,
  "automatic_fallback": False,
  "queued_claim_blocked": True,
  "terminal_qa_changed": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w19-04"></a>

## W19-04 — 과거 승인·새 기본본·suite/RUN 불변 통합

- [ ] **W19-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W19-04.md`(완료 시 생성).
- **직접 선행:** [W19-03](07-trial-and-review.md#w19-03)
- **읽기:** CONTRACTS C00 / C01 / C03 / C08 / C09 / C10 + 직접 선행 receipt의 interface/제약. 추적: R08, R09, R24, R28, R30.
- **변경 파일:** `tests/integration/test_approval_lifecycle.py`, `docs/validation/approval-lifecycle.md`. 담당 시험: `tests/integration/test_w19.py`.
- **입출력 계약:** `validate_approval_lifecycle(fixture: ApprovalLifecycleFixture) -> LifecycleReport`
- **구현·화면·예외:** v2 유효승인/suite/queuedRUN→후보재녹화/새 OFFtrial/검토→v4 승인뒤새기본만 v4 를선택함을검증한다. suite 명시교체는 W21 이고 oldrevoke 별도다. 실제 UI/DB/파일 hash 를근거로남긴다.
- **검증 전제:** 승인전/후기존 suite·queued/running·oldpin·원본 source/export 와 TC 변경을대조한다.
- **작업 순서:** `test_w19_04`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w19.py::test_w19_04 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "old_suite_version_unchanged": True,
  "old_run_snapshot_unchanged": True,
  "old_valid_evidence_pinned": True,
  "tc_changes_block_execution": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

## 영역 종료 점검

- 카드 체크·TASK_INDEX 상태·인계 근거가 일치해야 한다.
- [COVERAGE](COVERAGE.md)·[UI_COVERAGE](UI_COVERAGE.md)에서 담당 항목의 실제 증거를 연결한다.
- 후속 기능을 미리 완료 처리하지 않는다. 실패/계약 변경은 [REVIEW](REVIEW.md)에 기록하고 영향 작업을 재개한다.
