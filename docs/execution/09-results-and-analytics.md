# I · 결과·분석·내보내기 · 상세 작업서 v0.8

제품 설계 v0.6 + [보완 계약](CONTRACTS.md). **완료13 / 13**.
[Current 큐](../../NEXT_ACTION.md) · [전체 색인](README.md) · [차단/선행 수정](SCHEDULING.md) · [인계](HANDOFF.md).

카드 한 개와 직접 선행 근거만 읽는다. 기존 코드/complete/blocked 기록을 재사용한다.
검증 등급·live 수용을 구분한다. core fixture는 실제 native 근거가 아니며 최종 검증을 생략하지 않는다.

| 작업 | 직접 선행 | 결과 | 상태 |
|---|---|---|---|
| [W23-01](#w23-01) | [W06-06](02b-job-evidence-schema.md#w06-06) | 7 결과·진행·분모·세 비율 산식 | complete |
| [W23-02](#w23-02) | [W23-01](09-results-and-analytics.md#w23-01), [W18-02](07-trial-and-review.md#w18-02), [W20-04](08b-execution-and-suites.md#w20-04) | ITEM 근거·첫 실패·attempt·실제 설정 상세 | complete |
| [W23-03](#w23-03) | [W23-02](09-results-and-analytics.md#w23-02) | 분류·담당·issue·분석/이의 append UI | complete |
| [W23-04](#w23-04) | [W23-03](09-results-and-analytics.md#w23-03) | 리포트 목록·단일/묶음 보고·필터 | complete |
| [W23-05](#w23-05) | [W23-04](09-results-and-analytics.md#w23-04), [W31-06](08a-self-healing.md#w31-06) | 치유·unassisted·role usage·측정 범위 표시 | complete |
| [W24-01](#w24-01) | [W23-05](09-results-and-analytics.md#w23-05) | 기간·관측 단위·as_of 분모 facts query | complete |
| [W24-02](#w24-02) | [W24-01](09-results-and-analytics.md#w24-01) | series·strict cohort·최근완료·unknown | complete |
| [W24-03](#w24-03) | [W24-02](09-results-and-analytics.md#w24-02) | 추세·반복 실패·시간·비용·저장량 분석 UI | complete |
| [W24-04](#w24-04) | [W24-03](09-results-and-analytics.md#w24-03) | RUN 비교·케이스 이력·조건 차이 UI | complete |
| [W24-05](#w24-05) | [W24-04](09-results-and-analytics.md#w24-04) | 장기 facts·late ledger·과거 보고 재현 | complete |
| [W25-01](#w25-01) | [W24-05](09-results-and-analytics.md#w24-05) | immutable export snapshot·관리 job 접수 | complete |
| [W25-02](#w25-02) | [W25-01](09-results-and-analytics.md#w25-01) | CSV 안전화·열·원본 추적 | complete |
| [W25-03](#w25-03) | [W25-02](09-results-and-analytics.md#w25-02) | 인쇄용 HTML·다운로드·만료 UI | complete |

<a id="w23-01"></a>

## W23-01 — 7 결과·진행·분모·세 비율 산식

- [x] **W23-01 완료** — 상태: `complete`. 근거: [W23-01 인계](../validation/tasks/W23-01.md).
- **직접 선행:** [W06-06](02b-job-evidence-schema.md#w06-06)
- **읽기:** CONTRACTS C00 / C01 / C03 / C06 / C09 / C10 / C14 + 직접 선행 receipt의 interface/제약. 추적: R06, R31.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/domain/report_math.py`, `src/aiqa/contracts/reports.py`. 시험: `tests/integration/test_w23.py`.
- **입출력 계약:** `derive_display_result(item: CaseRunFacts) -> DisplayResult | None; summarize_execution(items: list[CaseRunFacts]) -> ExecutionSummary`
- **구현·화면·예외:** PASS/FAIL/BLOCKED/INCONCLUSIVE/SKIPPED/CANCELLED/NOT_RUN 은상호배타 terminal, 나머지는진행이다. 완료=terminal/N·검증통과=P/(P+F)·전체통과=P/N·미검증 5 종을계산하고분모 0 은 null 이다. FAIL+cancel 은 FAIL1 회다. 이 순수 계산 kernel은 W09/시범/UI가 처음 쓰기 전에 구현한다. 리포트 화면을 여기서 구현하지 않는다.
- **검증 전제:** N10(P6/F2/B1/NOT_RUN1)·진행포함·N0·위반취소를집계한다.
- **작업 순서:** `test_w23_01`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w23.py::test_w23_01 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "terminal": 10,
  "completion_rate": 1,
  "verified_pass_rate": 0.75,
  "total_pass_rate": 0.6,
  "unverified": 2
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w23-02"></a>

## W23-02 — ITEM 근거·첫 실패·attempt·실제 설정 상세

- [x] **W23-02 완료** — 상태: `complete`. 근거: [W23-02 인계](../validation/tasks/W23-02.md).
- **직접 선행:** [W23-01](09-results-and-analytics.md#w23-01), [W18-02](07-trial-and-review.md#w18-02), [W20-04](08b-execution-and-suites.md#w20-04)
- **읽기:** CONTRACTS C00 / C01 / C03 / C06 / C09 / C10 / C14 + 직접 선행 receipt의 interface/제약. 추적: R06, R07, R21, R27, R31, UI-11.05.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/api/case_runs.py`, `src/aiqa/web/templates/case_run.html`, `src/aiqa/web/templates/components/evidence_viewer.html`. 시험: `tests/acceptance/test_w23.py`.
- **입출력 계약:** `GET /api/v1/case-runs/{i} -> CaseRunDetail; GET /api/v1/case-runs/{i}/attempts -> list[AttemptView]`
- **구현·화면·예외:** UI11 exactcase/version/verification/package/policy·data/env/build/device/engine/model·step/action/check 를고정표시한다. first/latestattempt·첫실패·전후/로그/설정/복구/근거·현재판정이유·evidence 만료/보호를조회한다. 실제대상 PNG 를보여주고모델그림으로대체하지않는다.
- **검증 전제:** 동일 A001 여러 attempt·첫실패후 laterPASS·원본 lookup 치유·missingPNG·권한경계를검사한다.
- **작업 순서:** `test_w23_02`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w23.py::test_w23_02 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "first_failure_preserved": True,
  "exact_attempt_navigation": True,
  "model_render_replaces_capture": False,
  "evidence_expiry_reason": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w23-03"></a>

## W23-03 — 분류·담당·issue·분석/이의 append UI

- [x] **W23-03 완료** — 상태: `complete`. 근거: [W23-03 인계](../validation/tasks/W23-03.md).
- **직접 선행:** [W23-02](09-results-and-analytics.md#w23-02)
- **읽기:** CONTRACTS C00 / C01 / C03 / C06 / C09 / C10 / C14 + 직접 선행 receipt의 interface/제약. 추적: R14, R24, R32, UI-11.06.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/domain/analysis.py`, `src/aiqa/api/case_runs.py`, `src/aiqa/web/templates/components/analysis.html`. 시험: `tests/acceptance/test_w23.py`.
- **입출력 계약:** `GET/POST /api/v1/case-runs/{i}/analysis-records -> CursorPage[AnalysisRecord] | AnalysisRecord`
- **구현·화면·예외:** unclassified/in_progress/resolved 와 product/automation/environment/data/unclassified·담당자/comment/issueURL·정정의견을 append 한다. URL 은 http/https 만·HTMLescape·외부 issue 자동생성 0, QA/finalhash/as_of 원본변경 0 이다.
- **검증 전제:** 분석 2 회·정정의견·잘못된 URL/javascript·XSS 메모·다른 project·완료 FAIL 을확인한다.
- **작업 순서:** `test_w23_03`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w23.py::test_w23_03 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "analysis_records": 2,
  "original_verdict": "FAIL",
  "issue_auto_created": False,
  "unsafe_url_accepted": False,
  "comment_html_escaped": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w23-04"></a>

## W23-04 — 리포트 목록·단일/묶음 보고·필터

- [x] **W23-04 완료** — 상태: `complete`. 근거: `docs/validation/tasks/W23-04.md`.
- **직접 선행:** [W23-03](09-results-and-analytics.md#w23-03)
- **읽기:** CONTRACTS C00 / C01 / C03 / C06 / C09 / C10 / C14 + 직접 선행 receipt의 interface/제약. 추적: R21, R27, R31, UI-12.02, UI-12.03.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/api/reports.py`, `src/aiqa/domain/reporting.py`, `src/aiqa/web/templates/reports.html`, `src/aiqa/web/templates/report.html`. 시험: `tests/acceptance/test_w23.py`.
- **입출력 계약:** `GET /api/v1/projects/{p}/reports; GET /api/v1/executions/{e}/report -> ExecutionReport`
- **구현·화면·예외:** UI12 RUN 범위/source/purpose/설정·7 분포+진행·세비율/미검증·확정전제외·실패/분석/issue·first/latest·원본 rerun·evidence 상태를표시한다. 진행은중간/as_of, REC 없음·trial 기본제외·명시 filter 다.
- **검증 전제:** N10 예시·N1·진행·N0 필터·trial 포함배너·분모/기간·목록뒤로복원을확인한다.
- **작업 순서:** `test_w23_04`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w23.py::test_w23_04 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "n10_rates": [
    1,
    0.75,
    0.6
  ],
  "trial_default_included": False,
  "rec_included": False,
  "interim_report_labeled": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w23-05"></a>

## W23-05 — 치유·unassisted·role usage·측정 범위 표시

- [x] **W23-05 완료** — 상태: `complete`. 근거: `docs/validation/tasks/W23-05.md`.
- **직접 선행:** [W23-04](09-results-and-analytics.md#w23-04), [W31-06](08a-self-healing.md#w31-06)
- **읽기:** CONTRACTS C00 / C01 / C03 / C06 / C09 / C10 / C14 + 직접 선행 receipt의 interface/제약. 추적: R13, R31, R33, R35, UI-12.04.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/domain/reporting.py`, `src/aiqa/web/templates/report.html`, `src/aiqa/web/templates/case_run.html`. 시험: `tests/acceptance/test_w23.py`.
- **입출력 계약:** `summarize_assistance(items: list[CaseRunFacts]) -> AssistanceSummary; summarize_role_usage(calls: list[ModelCallFact]) -> RoleUsageSummary`
- **구현·화면·예외:** PASS 안 healing_used 부분집합·unassisted(동작오류/retry/recovery/healing 없는 PASS)와 verifier 축을별도로표시한다. 원래오류·치유성공/거부/실패·rolecalls/비용/partial/null/not_used 를보존하고 8 번째 terminalbucket 을만들지않는다.
- **검증 전제:** PASS6 중 unassisted4/healed1/동작 retry1·verifier 사용·usage 일부누락을집계한다.
- **작업 순서:** `test_w23_05`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w23.py::test_w23_05 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "pass_bucket": 6,
  "healed_pass": 1,
  "unassisted_pass": 4,
  "terminal_bucket_count": 7,
  "missing_usage_display": "partial"
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w24-01"></a>

## W24-01 — 기간·관측 단위·as_of 분모 facts query

- [x] **W24-01 완료** — 상태: `complete`. 근거: `docs/validation/tasks/W24-01.md`.
- **직접 선행:** [W23-05](09-results-and-analytics.md#w23-05)
- **읽기:** CONTRACTS C00 / C01 / C09 / C10 / C14 + 직접 선행 receipt의 interface/제약. 추적: R09, R31, R32.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/domain/analytics.py`, `src/aiqa/api/reports.py`, `src/aiqa/contracts/reports.py`. 시험: `tests/integration/test_w24.py`.
- **입출력 계약:** `query_observations(input: AnalyticsQuery) -> ObservationPage`
- **구현·화면·예외:** parentrequested_at 기준 KST→UTC[from,to)·projectscope·purpose/REC 제외·trial 기본제외를적용한다. attemptretry1 관측/rerun2 관측·createdseq≤asof 분모·finalizedseq≤asofterminal 을계산한다.
- **검증 전제:** KST 자정경계·미시작 NOT_RUN·접수 seq10/확정 20 와 asof15·원본 FAIL+rerunPASS 를조회한다.
- **작업 순서:** `test_w24_01`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w24.py::test_w24_01 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "attempts_do_not_add_observations": True,
  "rerun_observations": 2,
  "asof15_terminal": False,
  "not_run_in_denominator": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w24-02"></a>

## W24-02 — series·strict cohort·최근완료·unknown

- [x] **W24-02 완료** — 상태: `complete`. 근거: `docs/validation/tasks/W24-02.md`.
- **직접 선행:** [W24-01](09-results-and-analytics.md#w24-01)
- **읽기:** CONTRACTS C00 / C01 / C09 / C10 / C14 + 직접 선행 receipt의 interface/제약. 추적: R17, R31, R32, R35.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/domain/cohorts.py`, `src/aiqa/domain/analytics.py`. 시험: `tests/integration/test_w24.py`.
- **입출력 계약:** `compute_series_key(facts: CaseRunFacts) -> Fingerprint; compute_strict_cohort_key(facts: CaseRunFacts, as_of: int) -> Fingerprint`
- **구현·화면·예외:** C10 의 verification/data/env/oracle series 와 build/device/browser/engine/model/prompt/package/runtime/lock/healingONOFF/policy/verifierstrict 축을고정한다. modelnot_used 와 unknown 분리·관찰 seq 없는 actual 을과거에소급하지않는다. latestterminal 은 strict 별최신 1 개다.
- **검증 전제:** expected 완화·절차변경·model0/unknown·ON/OFF·actualbuild 나중관찰·최신진행이있는경우를비교한다.
- **작업 순서:** `test_w24_02`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w24.py::test_w24_02 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "changed_expected_same_series": False,
  "on_off_same_strict": False,
  "unused_equals_unknown": False,
  "latest_terminal_ignores_newer_running": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w24-03"></a>

## W24-03 — 추세·반복 실패·시간·비용·저장량 분석 UI

- [x] **W24-03 완료** — 상태: `complete`. 근거: `docs/validation/tasks/W24-03.md`.
- **직접 선행:** [W24-02](09-results-and-analytics.md#w24-02)
- **읽기:** CONTRACTS C00 / C01 / C09 / C10 / C14 + 직접 선행 receipt의 interface/제약. 추적: R13, R21, R27, R31, R35, UI-12.05.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/web/templates/analytics.html`, `src/aiqa/api/reports.py`, `src/aiqa/domain/analytics.py`. 시험: `tests/acceptance/test_w24.py`.
- **입출력 계약:** `GET /api/v1/projects/{p}/analytics -> AnalyticsReport`
- **구현·화면·예외:** UI12 누적탭에기간/purpose/case/version/verification/data/env/build/model/release_label·all_observations/latest_terminal·표본수/분모/미검증/asof/criteria 를제공한다. 날짜추세·firstpass/recovery·반복 check/분석·시간 p50/p95/nullable 비용·저장량을실제 facts 로표시한다.
- **검증 전제:** 다른조건·진행포함·null duration·빈표본·늦은 usage 보정·필터 URL 복원을확인한다.
- **작업 순서:** `test_w24_03`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w24.py::test_w24_03 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "no_sample_rates": None,
  "not_run_duration": None,
  "filters_preserved": True,
  "late_usage_asof_respected": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w24-04"></a>

## W24-04 — RUN 비교·케이스 이력·조건 차이 UI

- [x] **W24-04 완료** — 상태: `complete`. 근거: [W24-04 인계](../validation/tasks/W24-04.md).
- **직접 선행:** [W24-03](09-results-and-analytics.md#w24-03)
- **읽기:** CONTRACTS C00 / C01 / C09 / C10 / C14 + 직접 선행 receipt의 interface/제약. 추적: R07, R21, R24, R27, R32, UI-13.01, UI-13.02.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/web/templates/comparison.html`, `src/aiqa/api/reports.py`, `src/aiqa/domain/comparisons.py`. 시험: `tests/acceptance/test_w24.py`.
- **입출력 계약:** `GET /api/v1/projects/{p}/execution-comparisons -> ExecutionComparison`
- **구현·화면·예외:** UI13baseline/candidate 를 case/data/target 으로 align 하고변화/지속실패/추가/제외·정의/조건 diff 를먼저표시한다. step/PNG/expected/observed/시간/비용을나란히비교한다. 다른 strict 병합은명시 mixed 배너/구성표본수이며자동개선·회귀확정 0 이다.
- **검증 전제:** build/env/data/expected 변경·동일의도절차변경·missingPNG·최초 FAIL/새 PASS·ON/OFF 를비교한다.
- **작업 순서:** `test_w24_04`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w24.py::test_w24_04 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "condition_difference_visible": True,
  "changed_verification_separate": True,
  "mixed_banner": True,
  "original_fail_preserved": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w24-05"></a>

## W24-05 — 장기 facts·late ledger·과거 보고 재현

- [x] **W24-05 완료** — 상태: `complete`. 근거: [W24-05 인계](../validation/tasks/W24-05.md).
- **직접 선행:** [W24-04](09-results-and-analytics.md#w24-04)
- **읽기:** CONTRACTS C00 / C01 / C09 / C10 / C14 + 직접 선행 receipt의 interface/제약. 추적: R08, R13, R15, R31, R32.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/domain/analytics.py`, `src/aiqa/store/usage.py`, `tests/integration/test_analytics_asof.py`, `docs/validation/analytics.md`. 시험: `tests/integration/test_w24.py`.
- **입출력 계약:** `resolve_report_snapshot(input: ReportSnapshotQuery) -> ReportSnapshot`
- **구현·화면·예외:** detail90 일/PNG30 일만료뒤에도최소 facts/key/hash/lifecycle/ledger 로이전 asof 분모/진행/확정/비용을재현한다. 새로운산식은 criteriaVersion 으로분리하고 cache 는재생성 projection 이다.
- **검증 전제:** seq10 접수/20 확정/30 비용보정·day91payload 만료후각 asof 와캐시삭제를대조한다.
- **작업 순서:** `test_w24_05`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w24.py::test_w24_05 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "historical_snapshot_equal": True,
  "expired_payload_breaks_stats": False,
  "late_usage_rewrites_export": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w25-01"></a>

## W25-01 — immutable export snapshot·관리 job 접수

- [x] **W25-01 완료** — 상태: `complete`. 근거: [W25-01 인계](../validation/tasks/W25-01.md).
- **직접 선행:** [W24-05](09-results-and-analytics.md#w24-05)
- **읽기:** CONTRACTS C00 / C01 / C03 / C09 / C10 / C14 + 직접 선행 receipt의 interface/제약. 추적: R10, R12, R14, R31.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/domain/exports.py`, `src/aiqa/api/reports.py`, `src/aiqa/store/queue.py`. 시험: `tests/integration/test_w25.py`.
- **입출력 계약:** `POST /api/v1/executions/{e}/exports(input: ExportInput) -> JobReceipt`
- **구현·화면·예외:** CSV/printable_html·asof/criteria/filter/cohort/sourceIDs/생성시각·임시보고여부를 immutablemanifest 에고정한다. scope·멱등 key·exportjobQA=null·readyartifact/receipt·명시만료를적용한다.
- **검증 전제:** 진행 export·중복 key·다른 project·lateusage/final 후원본 export 조회·파일만료를검증한다.
- **작업 순서:** `test_w25_01`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/integration/test_w25.py::test_w25_01 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "export_job_verdict": None,
  "duplicate_exports": 1,
  "asof_fixed": True,
  "expired_reason_visible": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w25-02"></a>

## W25-02 — CSV 안전화·열·원본 추적

- [x] **W25-02 완료** — 상태: `complete`. 근거: [W25-02 인계](../validation/tasks/W25-02.md).
- **직접 선행:** [W25-01](09-results-and-analytics.md#w25-01)
- **읽기:** CONTRACTS C00 / C01 / C03 / C09 / C10 / C14 + 직접 선행 receipt의 interface/제약. 추적: R13, R14, R31, UI-12.06.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/domain/exports.py`, `src/aiqa/web/templates/report.html`. 시험: `tests/acceptance/test_w25.py`.
- **입출력 계약:** `render_report_csv(snapshot: ReportSnapshot) -> SanitizedArtifact`
- **구현·화면·예외:** UTF8 CSV 에원본 RUN/ITEM/caseversion/data/env/build·결과/세비율/미검증·원래오류/치유/roleusage/asof/criteria·evidence 가용성을넣는다. 수식시작문자(=,+,-,@와선행제어공백)를안전화하고 secret/hiddenreasoning·임의 path 를제외한다.
- **검증 전제:** 수식문자·따옴표/줄바꿈/한글·secretref/원문·nullusage·권한없는 artifact 를 export 한다.
- **작업 순서:** `test_w25_02`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w25.py::test_w25_02 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "formula_injection_safe": True,
  "korean_roundtrip": True,
  "secret_plaintext": False,
  "original_ids_present": True
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

<a id="w25-03"></a>

## W25-03 — 인쇄용 HTML·다운로드·만료 UI

- [x] **W25-03 완료** — 상태: `complete`. 근거: [W25-03 인계](../validation/tasks/W25-03.md).
- **직접 선행:** [W25-02](09-results-and-analytics.md#w25-02)
- **읽기:** CONTRACTS C00 / C01 / C03 / C09 / C10 / C14 + 직접 선행 receipt의 interface/제약. 추적: R14, R21, R27, R31, UI-12.07.
- **검증 등급:** `core_contract`. 환경: `local_python`.
- **완료 범위:** 완료 범위는 이 카드의 실제 API/DB/파일/브라우저 계약 구현이다. 장치·모델 관찰 입력은 tests/의 명시된 fixture로 검사할 수 있지만 생산 경로에 fake adapter/관측/PASS를 넣지 않는다. 해당 실제 환경 통과는 W28-02, W28-03에서 별도로 요구한다.
- **실제 통합 담당:** [W28-02](10-retention-and-release-gates.md#w28-02), [W28-03](10-retention-and-release-gates.md#w28-03). core 완료로 이 gate를 올리지 않는다.
- **변경 파일:** `src/aiqa/web/templates/report_print.html`, `src/aiqa/web/templates/report.html`, `src/aiqa/api/reports.py`. 시험: `tests/acceptance/test_w25.py`.
- **입출력 계약:** `render_report_html(snapshot: ReportSnapshot) -> SanitizedArtifact; GET /api/v1/exports/{x} -> ExportView`
- **구현·화면·예외:** UI12CSV/인쇄 HTML 버튼→job 진행/완료/실패/만료와다운로드를연결한다. HTML 은범위/기준/원본 ID/시각/임시·조건차이·정제근거링크/만료를표시하고인쇄시잘림을확인한다. localhost 외부공유나 PDF 생성/예약발송은없다.
- **검증 전제:** 긴한글/넓은표·진행 snapshot·XSS 값·artifact 만료·1024/1440 및 printpreview 를확인한다.
- **작업 순서:** `test_w25_03`의 필요한 실패/오류 조건 확인 → 지정 범위 구현 → 아래 검사/요구 환경 확인 → diff/근거/큐 갱신.
- **검증 명령:** `python -m pytest tests/acceptance/test_w25.py::test_w25_03 -q`. 해당 scope의 함수/명시 회귀 PASS와 실제 관찰 projection을 대조한다. live 등급만 실제 환경 미검증 시 blocked다. core 완료는 후속 live 수용을 대신하지 않는다.

```python
assert observed == {
  "html_escaped": True,
  "print_core_fields_clipped": False,
  "localhost_public_claim": False,
  "automatic_pdf": False
}
```

미완료/차단 이유와 재개 조건을 인계에 남긴다. 외부 차단이면 독립 준비 후보를 골라 NEXT_ACTION의 Current를 전환한다. 제품 경로에 fixture/fake PASS를 넣지 않는다.

## 영역 종료 점검

- 카드·TASK_INDEX·실제 인계 상태를 맞춘다. 과거 완료를 문서 정리로 다시 구현하거나 무효화하지 않는다.
- 부모 W는 소속 leaf와 parent_gate_tasks/원래 통합 조건까지 만족해야 완료다.
- [UI_COVERAGE](UI_COVERAGE.md)·[COVERAGE](COVERAGE.md)의 실제 수용 조건은 그대로 유지한다.
