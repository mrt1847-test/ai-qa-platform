# H-2 · 정식·선택·묶음·취소·재실행 · 상세 작업서 v0.7

제품 설계 v0.6 + [공통 보완 계약](CONTRACTS.md). **제품 미착수: 완료0 / 13**.
[전체 색인](README.md) · [인계 양식](HANDOFF.md) · [UI 추적](UI_COVERAGE.md) · [요구/시험 추적](COVERAGE.md).

문서 전체를 한 번에 구현하지 않는다. **카드 한 개**와 직접 선행 근거를 읽는다.
파일/DTO/시험은 향후 산출물이며 현재 존재·통과를 뜻하지 않는다.
검증 projection은 실제 관찰에서 계산한다. [검증 예시 해석](README.md#4-카드의-검증-예시를-해석하는-법)을 따른다.

| 작업 | 선행 | 결과 |
|---|---|---|
| [W20-01](#w20-01) | [W31-06](08a-self-healing.md#w31-06) | 정식 preview·exact 승인·명시 제외 |
| [W20-02](#w20-02) | [W20-01](08b-execution-and-suites.md#w20-01) | 정식 접수 원자성·preview hash·claim 재검증 |
| [W20-03](#w20-03) | [W20-02](08b-execution-and-suites.md#w20-02) | 공통 4 단계 수행 마법사·최종확인 |
| [W20-04](#w20-04) | [W20-03](08b-execution-and-suites.md#w20-03) | 수행 목록·진행·ITEM·연결 상태 UI |
| [W21-01](#w21-01) | [W20-04](08b-execution-and-suites.md#w20-04) | 묶음 목록·기본 metadata·복제·보관 |
| [W21-02](#w21-02) | [W21-01](08b-execution-and-suites.md#w21-01) | 묶음 exact 구성·순서·data/env 편집 |
| [W21-03](#w21-03) | [W21-02](08b-execution-and-suites.md#w21-02) | 새 승인본 diff·명시 suite 교체 |
| [W21-04](#w21-04) | [W21-03](08b-execution-and-suites.md#w21-03) | 선택·data 확장·명시 제외·N 상한 |
| [W21-05](#w21-05) | [W21-04](08b-execution-and-suites.md#w21-04) | 순차 continue/stop·NOT_RUN·부모 확정 |
| [W22-01](#w22-01) | [W21-05](08b-execution-and-suites.md#w21-05) | RUN·ITEM 취소와 finish 경합 UI |
| [W22-02](#w22-02) | [W22-01](08b-execution-and-suites.md#w22-01) | 미시작 skip 만 허용·사유·집계 |
| [W22-03](#w22-03) | [W22-02](08b-execution-and-suites.md#w22-02) | 원본 연결 새 rerun·구성 확인·lineage |
| [W22-04](#w22-04) | [W22-03](08b-execution-and-suites.md#w22-03) | 수행 편집·원본·취소·재시작 통합 동선 |

<a id="w20-01"></a>

## W20-01 — 정식 preview·exact 승인·명시 제외

- [ ] **W20-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W20-01.md`(완료 시 생성).
- **직접 선행:** [W31-06](08a-self-healing.md#w31-06)
- **읽기:** CONTRACTS C00 / C01 / C03 / C08 / C09 + 직접 선행 receipt의 interface/제약. 추적: R08, R09, R22, R28, UI-09.03.
- **변경 파일:** `src/aiqa/domain/executions.py`, `src/aiqa/api/executions.py`. 담당 시험: `tests/acceptance/test_w20.py`.
- **입출력 계약:** `preview_execution(actor: Actor, input: ExecutionPreviewInput) -> ExecutionPreview`
- **구현·화면·예외:** 공통 trial 경로에 regression/reverification 승인검사를추가한다. default 또는명시과거유효 approval 을 exactversion 에고정하고 package/data/env/build/role/한도를점검한다. 미승인/불가항목은사유와명시제외확인을요구하고 preview 는예약아니다.
- **검증 전제:** 미승인·철회·유효 oldapproval·일부불가선택·hash/role/key 없음·busy 를 preview 한다.
- **작업 순서:** `test_w20_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w20.py::test_w20_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "unapproved_formal": False,
  "valid_old_approval_allowed": True,
  "silent_exclusions": 0,
  "preview_reserves_resource": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w20-02"></a>

## W20-02 — 정식 접수 원자성·preview hash·claim 재검증

- [ ] **W20-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W20-02.md`(완료 시 생성).
- **직접 선행:** [W20-01](08b-execution-and-suites.md#w20-01)
- **읽기:** CONTRACTS C00 / C01 / C03 / C08 / C09 + 직접 선행 receipt의 interface/제약. 추적: R09, R10, R12, R22.
- **변경 파일:** `src/aiqa/domain/executions.py`, `src/aiqa/store/queue.py`, `src/aiqa/api/executions.py`. 담당 시험: `tests/integration/test_w20.py`.
- **입출력 계약:** `enqueue_execution(actor: Actor, input: ExecutionCreateInput) -> ExecutionReceipt; validate_claim_snapshot(job: JobSpec) -> ClaimDecision`
- **구현·화면·예외:** preview hash 와 request 선택/제외·resolvedapproval/package/policy/data/env/secretrefrevision 을재검증하고 RUN/전체 ITEM/jobs/receipt 를원자생성한다. claim 에서 revoke/실제환경변경을검사한다. 같은 key 같은 RUN·다른 body409 다.
- **검증 전제:** preview 후철회/편집·접수중 crash·이중시작·claim 때앱변경·pastvalidapproval 를검사한다.
- **작업 순서:** `test_w20_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w20.py::test_w20_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "partial_run_rows": 0,
  "duplicate_run_count": 1,
  "revoked_claim": "BLOCKED",
  "snapshot_uses_latest": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w20-03"></a>

## W20-03 — 공통 4 단계 수행 마법사·최종확인

- [ ] **W20-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W20-03.md`(완료 시 생성).
- **직접 선행:** [W20-02](08b-execution-and-suites.md#w20-02)
- **읽기:** CONTRACTS C00 / C01 / C03 / C08 / C09 + 직접 선행 receipt의 interface/제약. 추적: R21, R22, R27, R31, UI-09.04.
- **변경 파일:** `src/aiqa/web/templates/execution_setup.html`, `src/aiqa/web/static/execution_setup.js`. 담당 시험: `tests/acceptance/test_w20.py`.
- **입출력 계약:** `ExecutionWizard(targets, data_environment, preview, confirmation); POST /api/v1/projects/{p}/executions`
- **구현·화면·예외:** UI09 이름/purpose·출처/원본사유·target 확인→env/data/build/reset/limits→preflight/제외사유→최종 N/제외수로구성한다. replay/actor0·필요 verifier·healingOFF/ON·release_label 을표시하고 N0/100 초과는시작불가다.
- **검증 전제:** single/selection/suite/rerun 진입·단계뒤로·422 입력보존·previewstale409·중복클릭·trial 정식혼합을확인한다.
- **작업 순서:** `test_w20_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w20.py::test_w20_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "wizard_steps": 4,
  "empty_execution_allowed": False,
  "over_100_allowed": False,
  "mixed_trial_formal_allowed": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w20-04"></a>

## W20-04 — 수행 목록·진행·ITEM·연결 상태 UI

- [ ] **W20-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W20-04.md`(완료 시 생성).
- **직접 선행:** [W20-03](08b-execution-and-suites.md#w20-03)
- **읽기:** CONTRACTS C00 / C01 / C03 / C08 / C09 + 직접 선행 receipt의 interface/제약. 추적: R07, R10, R21, R26, R31, UI-10.03, UI-10.04.
- **변경 파일:** `src/aiqa/web/templates/executions.html`, `src/aiqa/web/templates/execution.html`, `src/aiqa/api/executions.py`. 담당 시험: `tests/acceptance/test_w20.py`.
- **입출력 계약:** `GET /api/v1/projects/{p}/executions; GET /api/v1/executions/{e}; GET /api/v1/case-runs/{i}`
- **구현·화면·예외:** UI10 대기/진행/완료/전체·RUN 이름/purpose/source/요청자/env/build/종료수/PASS/분포/시각과필터를제공한다. 상세 ITEM 목록/현재화면/이벤트/경과/자원·phase/calls·stale/재접속복원을표시한다. 완료수와 PASS 수는별개다.
- **검증 전제:** 진행중실패포함 RUN·빈목록·필터/page·연결단절/재접속·새로고침 selectedITEM 을확인한다.
- **작업 순서:** `test_w20_04`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w20.py::test_w20_04 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "completed_count_equals_pass_count": False,
  "phase_is_job_status": False,
  "reload_duplicate_jobs": 0,
  "selected_item_restored": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w21-01"></a>

## W21-01 — 묶음 목록·기본 metadata·복제·보관

- [ ] **W21-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W21-01.md`(완료 시 생성).
- **직접 선행:** [W20-04](08b-execution-and-suites.md#w20-04)
- **읽기:** CONTRACTS C00 / C01 / C02 / C09 + 직접 선행 receipt의 interface/제약. 추적: R21, R22, UI-08.01.
- **변경 파일:** `src/aiqa/domain/suites.py`, `src/aiqa/api/suites.py`, `src/aiqa/web/templates/suites.html`. 담당 시험: `tests/acceptance/test_w21.py`.
- **입출력 계약:** `GET/POST /api/v1/projects/{p}/suites; POST /api/v1/suites/{s}/clone; POST /api/v1/suites/{s}/archive -> SuiteView`
- **구현·화면·예외:** UI08ID/이름/설명/target/담당자/구성수/최근수행/수정일·검색/분류·생성/복제/보관/이력을제공한다. 진행 RUNsnapshot 은변경하지않고빈 suite 저장은허용하되실행 N0 차단이다.
- **검증 전제:** 빈 suite·복제/보관·진행 RUN 참조·다른 project 검색을확인한다.
- **작업 순서:** `test_w21_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w21.py::test_w21_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "empty_suite_saved": True,
  "empty_suite_executable": False,
  "existing_run_unchanged": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w21-02"></a>

## W21-02 — 묶음 exact 구성·순서·data/env 편집

- [ ] **W21-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W21-02.md`(완료 시 생성).
- **직접 선행:** [W21-01](08b-execution-and-suites.md#w21-01)
- **읽기:** CONTRACTS C00 / C01 / C02 / C09 + 직접 선행 receipt의 interface/제약. 추적: R22, R32, UI-08.02.
- **변경 파일:** `src/aiqa/domain/suites.py`, `src/aiqa/api/suites.py`, `src/aiqa/web/templates/suite_editor.html`. 담당 시험: `tests/acceptance/test_w21.py`.
- **입출력 계약:** `POST /api/v1/suites/{s}/versions(input: SuiteRevisionInput) -> SuiteVersionView`
- **구현·화면·예외:** 왼쪽승인 AUT 검색→오른쪽 entry 추가/제거/정렬·exactversion/approval·data 행/환경 defaults/reset·continue/stop 을불변 revision 저장한다. 같은 AUT 다른 data 는 entryID/행이름으로구별하고 mixed 는 target 별자원필수·암묵로그인의존금지다.
- **검증 전제:** Web/Androidmixed·동일 AUT2data·순서변경·다른 caseversion·없는자원을검사한다.
- **작업 순서:** `test_w21_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w21.py::test_w21_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "entry_ids_unique": True,
  "data_rows_distinct": True,
  "mixed_resource_required": True,
  "old_suite_revision_unchanged": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w21-03"></a>

## W21-03 — 새 승인본 diff·명시 suite 교체

- [ ] **W21-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W21-03.md`(완료 시 생성).
- **직접 선행:** [W21-02](08b-execution-and-suites.md#w21-02)
- **읽기:** CONTRACTS C00 / C01 / C02 / C09 + 직접 선행 receipt의 interface/제약. 추적: R08, R22, R24, UI-08.03.
- **변경 파일:** `src/aiqa/domain/suites.py`, `src/aiqa/web/templates/suite_editor.html`, `src/aiqa/api/suites.py`. 담당 시험: `tests/acceptance/test_w21.py`.
- **입출력 계약:** `GET /api/v1/suites/{s}/upgrade-proposals; POST /api/v1/suites/{s}/versions -> SuiteVersionView`
- **구현·화면·예외:** 새 approved 는업데이트가능정보와정의/절차/정책 diff·영향 entry 를표시한다. 사용자가명시선택한 entry 만새 revision 으로교체하고 oldapproval/기존 RUN 을자동추종하지않는다.
- **검증 전제:** v2suite→v4approval 생성→제안거부/일부교체·동시 suite 편집 409 를확인한다.
- **작업 순서:** `test_w21_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w21.py::test_w21_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "auto_upgraded_entries": 0,
  "reject_new_revisions": 0,
  "accepted_upgrade_new_revision": 1,
  "old_run_unchanged": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w21-04"></a>

## W21-04 — 선택·data 확장·명시 제외·N 상한

- [ ] **W21-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W21-04.md`(완료 시 생성).
- **직접 선행:** [W21-03](08b-execution-and-suites.md#w21-03)
- **읽기:** CONTRACTS C00 / C01 / C02 / C09 + 직접 선행 receipt의 interface/제약. 추적: R22, R28, R31, R35, UI-03.04, UI-09.05.
- **변경 파일:** `src/aiqa/domain/executions.py`, `src/aiqa/web/templates/execution_setup.html`, `src/aiqa/api/executions.py`. 담당 시험: `tests/acceptance/test_w21.py`.
- **입출력 계약:** `expand_execution_selection(input: ExecutionSelection) -> ExpandedExecutionScope`
- **구현·화면·예외:** single/selection/suite 를공통 ITEM(caseversion×data 행×target)로확장하고 exactentryID·exclusions 이유를고정한다. 중복 entryID 거부·data 행 N·N0/100 초과 422·월 3000 은 release_label 의최소 30RUN 이다. 미승인항목자동제외 0 이다.
- **검증 전제:** 99/100/101expandedITEM·전부제외·중복 entry·TC0·선택일부불가를검사한다.
- **작업 순서:** `test_w21_04`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w21.py::test_w21_04 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "limit_100_accepted": True,
  "limit_101_status": 422,
  "zero_items_status": 422,
  "silent_exclusions": 0
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w21-05"></a>

## W21-05 — 순차 continue/stop·NOT_RUN·부모 확정

- [ ] **W21-05 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W21-05.md`(완료 시 생성).
- **직접 선행:** [W21-04](08b-execution-and-suites.md#w21-04)
- **읽기:** CONTRACTS C00 / C01 / C02 / C09 + 직접 선행 receipt의 interface/제약. 추적: R11, R12, R22, R31, UI-10.05.
- **변경 파일:** `src/aiqa/domain/execution_scheduler.py`, `src/aiqa/store/queue.py`, `src/aiqa/domain/verdicts.py`. 담당 시험: `tests/acceptance/test_w21.py`.
- **입출력 계약:** `advance_execution(execution_id: UUID, completed_item: CaseRunView) -> SchedulingDecision`
- **구현·화면·예외:** slot1·앞 ITEMterminal/cleanup 후다음 claim 한다. continue 는안전한다음항목, stop_on_non_pass 는나머지 NOT_RUN·이유이며사용자취소 CANCELLED 와구별한다. 모든확정 ITEMterminal 후부모 terminal·집계는공통산식이다.
- **검증 전제:** mixed3 항목의중간 FAIL/BLOCKED·continue/stop·cleanupquarantine·중복 finish 를검사한다.
- **작업 순서:** `test_w21_05`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w21.py::test_w21_05 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "parallel_items_max": 1,
  "stop_remaining": "NOT_RUN",
  "cancel_remaining": "CANCELLED",
  "parent_early_terminal": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w22-01"></a>

## W22-01 — RUN·ITEM 취소와 finish 경합 UI

- [ ] **W22-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W22-01.md`(완료 시 생성).
- **직접 선행:** [W21-05](08b-execution-and-suites.md#w21-05)
- **읽기:** CONTRACTS C00 / C01 / C04 / C09 + 직접 선행 receipt의 interface/제약. 추적: R06, R11, R12, R31, UI-10.06.
- **변경 파일:** `src/aiqa/api/executions.py`, `src/aiqa/domain/executions.py`, `src/aiqa/web/templates/execution.html`. 담당 시험: `tests/acceptance/test_w22.py`.
- **입출력 계약:** `POST /api/v1/executions/{e}/cancel; POST /api/v1/case-runs/{i}/cancel -> CancellationReceipt`
- **구현·화면·예외:** 전체/개별취소영향과요청/정지/정리를구분한다. queued 항목 terminal·runningcancel/cleanup·stop 정책을적용하며완료 ITEM/유효위반은덮지않는다. 중복요청은같은 receipt 다.
- **검증 전제:** 취소직전 FAIL·queued/running/done 혼합·finish 동시·단절후재요청을확인한다.
- **작업 순서:** `test_w22_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w22.py::test_w22_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "violation_then_cancel": "FAIL",
  "done_item_changed": False,
  "duplicate_cancel_effects": 1
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w22-02"></a>

## W22-02 — 미시작 skip 만 허용·사유·집계

- [ ] **W22-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W22-02.md`(완료 시 생성).
- **직접 선행:** [W22-01](08b-execution-and-suites.md#w22-01)
- **읽기:** CONTRACTS C00 / C01 / C04 / C09 + 직접 선행 receipt의 interface/제약. 추적: R11, R12, R22, R31, UI-10.07.
- **변경 파일:** `src/aiqa/api/executions.py`, `src/aiqa/domain/executions.py`, `src/aiqa/web/templates/execution.html`. 담당 시험: `tests/acceptance/test_w22.py`.
- **입출력 계약:** `POST /api/v1/case-runs/{i}/skip(input: SkipInput) -> CaseRunView`
- **구현·화면·예외:** 미시작 queued·미 dispatch ITEM 만자원확보없이 completed/disposition skipped 로확정한다. running/claimed 경합은 409·사유/actor 보존·SKIPPED 한번집계, stop 정책영향을보인다.
- **검증 전제:** queuedskip·claim 동시·runningskip·doneFAILskip·중복 skip 을검사한다.
- **작업 순서:** `test_w22_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w22.py::test_w22_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "queued_display_result": "SKIPPED",
  "running_skip_status": 409,
  "skip_physical_sessions": 0,
  "fail_rewritten": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w22-03"></a>

## W22-03 — 원본 연결 새 rerun·구성 확인·lineage

- [ ] **W22-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W22-03.md`(완료 시 생성).
- **직접 선행:** [W22-02](08b-execution-and-suites.md#w22-02)
- **읽기:** CONTRACTS C00 / C01 / C04 / C09 + 직접 선행 receipt의 interface/제약. 추적: R09, R24, R31, R32, UI-10.08, UI-11.04, UI-12.01.
- **변경 파일:** `src/aiqa/domain/executions.py`, `src/aiqa/api/executions.py`, `src/aiqa/web/templates/components/rerun.html`. 담당 시험: `tests/acceptance/test_w22.py`.
- **입출력 계약:** `POST /api/v1/executions/{e}/reruns(input: RerunInput) -> ExecutionPreview`
- **구현·화면·예외:** 선택실패/전체/개별 ITEM·사유·원본 ref/rootlineage 로새 preview→UI09 확인→새 RUN/ITEM 을만든다. 기본 exact 구성이며변경은명시하고 reverification 승인정책을적용한다. 과거 FAIL·attempt 수를새관측으로덮지않는다.
- **검증 전제:** FAIL 원본→새 PASS·철회 oldapproval·다른 env 명시·동일 key 재전송을검사한다.
- **작업 순서:** `test_w22_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w22.py::test_w22_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "original_result": "FAIL",
  "new_result_independent": True,
  "lineage_preserved": True,
  "duplicate_new_runs": 1
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w22-04"></a>

## W22-04 — 수행 편집·원본·취소·재시작 통합 동선

- [ ] **W22-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W22-04.md`(완료 시 생성).
- **직접 선행:** [W22-03](08b-execution-and-suites.md#w22-03)
- **읽기:** CONTRACTS C00 / C01 / C04 / C09 + 직접 선행 receipt의 interface/제약. 추적: R16, R21, R22, R27, R28, R31.
- **변경 파일:** `tests/acceptance/test_execution_lifecycle.py`, `docs/validation/execution-lifecycle.md`. 담당 시험: `tests/integration/test_w22.py`.
- **입출력 계약:** `validate_execution_lifecycle(fixture: ExecutionLifecycleFixture) -> LifecycleReport`
- **구현·화면·예외:** UI03/08→09→10→11/12 의 single/selection/suite/rerun 를 실제 API/DB 로통합확인한다. excluded vs NOT_RUN vs SKIPPED vs CANCELLED·완료와 PASS·한도/slot·현재승인변경과 exactsnapshot 을검증한다.
- **검증 전제:** mixedsuite·일부제외·중간취소/skip·새재실행·탭재접속을 TC0 로실행한다.
- **작업 순서:** `test_w22_04`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/integration/test_w22.py::test_w22_04 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "silent_scope_changes": 0,
  "original_snapshots_changed": 0,
  "result_buckets_exclusive": True,
  "tc_required": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

## 영역 종료 점검

- 카드 체크·TASK_INDEX 상태·인계 근거가 일치해야 한다.
- [COVERAGE](COVERAGE.md)·[UI_COVERAGE](UI_COVERAGE.md)에서 담당 항목의 실제 증거를 연결한다.
- 후속 기능을 미리 완료 처리하지 않는다. 실패/계약 변경은 [REVIEW](REVIEW.md)에 기록하고 영향 작업을 재개한다.
