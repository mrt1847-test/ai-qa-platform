# D-1 · 프로젝트·케이스·설정·선택 TC UI · 상세 작업서 v0.7

제품 설계 v0.6 + [공통 보완 계약](CONTRACTS.md). **제품 미착수: 완료0 / 11**.
[전체 색인](README.md) · [인계 양식](HANDOFF.md) · [UI 추적](UI_COVERAGE.md) · [요구/시험 추적](COVERAGE.md).

문서 전체를 한 번에 구현하지 않는다. **카드 한 개**와 직접 선행 근거를 읽는다.
파일/DTO/시험은 향후 산출물이며 현재 존재·통과를 뜻하지 않는다.
검증 projection은 실제 관찰에서 계산한다. [검증 예시 해석](README.md#4-카드의-검증-예시를-해석하는-법)을 따른다.

| 작업 | 선행 | 결과 |
|---|---|---|
| [W10-01](#w10-01) | [W09-04](03-worker-and-sessions.md#w09-04) | 공통 UI shell·탐색·상태 컴포넌트 |
| [W10-02](#w10-02) | [W10-01](04a-case-management-ui.md#w10-01) | 프로젝트 목록·생성·보관·복구 UI |
| [W10-03](#w10-03) | [W10-02](04a-case-management-ui.md#w10-02) | 프로젝트 개요·실제 counts·빠른 이동 |
| [W10-04](#w10-04) | [W10-03](04a-case-management-ui.md#w10-03) | 케이스 목록·필터·정렬·페이지·복원 |
| [W10-05](#w10-05) | [W10-04](04a-case-management-ui.md#w10-04) | 케이스 선택 조작·복제·보관·진입 연결 |
| [W10-06](#w10-06) | [W10-05](04a-case-management-ui.md#w10-05) | 케이스 검증 정의·변수·기대 편집 |
| [W10-07](#w10-07) | [W10-06](04a-case-management-ui.md#w10-06) | 단계 편집·변수화·명시 diff 수락 |
| [W10-08](#w10-08) | [W10-07](04a-case-management-ui.md#w10-07) | 케이스 통합 탭·최신초안/승인본·diff |
| [W10-11](#w10-11) | [W10-08](04a-case-management-ui.md#w10-08) | 케이스 실행 설정·검증 방식·healing capability 편집 |
| [W10-09](#w10-09) | [W10-11](04a-case-management-ui.md#w10-11) | 기본 설정·role binding·키 일회 입력 UI |
| [W10-10](#w10-10) | [W10-09](04a-case-management-ui.md#w10-09) | 선택 TC 목록·편집·참조·import UI |

<a id="w10-01"></a>

## W10-01 — 공통 UI shell·탐색·상태 컴포넌트

- [ ] **W10-01 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W10-01.md`(완료 시 생성).
- **직접 선행:** [W09-04](03-worker-and-sessions.md#w09-04)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C11 + 직접 선행 receipt의 interface/제약. 추적: R21, R26, R27, UI-COMMON.01, UI-COMMON.02, UI-COMMON.03.
- **변경 파일:** `src/aiqa/web/templates/base.html`, `src/aiqa/web/templates/components/states.html`, `src/aiqa/web/static/navigation.js`, `src/aiqa/web/static/app.css`. 담당 시험: `tests/acceptance/test_w10.py`.
- **입출력 계약:** `render_page(context: PageContext) -> HtmlResponse; UiQueryState(filter, sort, cursor, selected_id, scroll)`
- **구현·화면·예외:** project switch/breadcrumb/이 PC 연결·검색 진입·활성 메뉴를 구현한다. URL query 로 filter/sort/page/selected 를, sessionStorage 에는 비밀 없는 scroll/열설정만 보존한다. loading/empty/403/409/422/stale·미저장 이동 대화상자·focus·1024/1440px 를 공통화한다.
- **검증 전제:** 목록→상세→뒤로/새로고침·422·403·409·통신 끊김·키보드만·1024px 를 실제 browser 에서 확인한다.
- **작업 순서:** `test_w10_01`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w10.py::test_w10_01 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "restored_query": True,
  "duplicate_mutation_on_reload": 0,
  "secret_in_browser_storage": False,
  "keyboard_usable": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w10-02"></a>

## W10-02 — 프로젝트 목록·생성·보관·복구 UI

- [ ] **W10-02 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W10-02.md`(완료 시 생성).
- **직접 선행:** [W10-01](04a-case-management-ui.md#w10-01)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C11 + 직접 선행 receipt의 interface/제약. 추적: R01, R21, R27, UI-01.01, UI-01.02.
- **변경 파일:** `src/aiqa/web/templates/projects.html`, `src/aiqa/api/catalog.py`, `src/aiqa/domain/projects.py`. 담당 시험: `tests/acceptance/test_w10.py`.
- **입출력 계약:** `GET/POST /api/v1/projects; POST /api/v1/projects/{p}/archive; POST /api/v1/projects/{p}/restore -> ProjectView`
- **구현·화면·예외:** UI-01 이름/key/설명/target·검색·활성/보관·counts·생성→환경 준비 이동을 연결한다. 보관 전 진행 REC/RUN·cleanup 을 점검하고 이력은 읽기 가능, 복구 audit 를 남긴다.
- **검증 전제:** 빈 목록·key 중복 409·정상 생성/재접속·진행 REC 보관거부·정리 후 보관/복구를 수행한다.
- **작업 순서:** `test_w10_02`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w10.py::test_w10_02 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "duplicate_key_status": 409,
  "active_job_archive_status": 409,
  "archived_history_readable": True,
  "restore_audited": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w10-03"></a>

## W10-03 — 프로젝트 개요·실제 counts·빠른 이동

- [ ] **W10-03 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W10-03.md`(완료 시 생성).
- **직접 선행:** [W10-02](04a-case-management-ui.md#w10-02)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C11 + 직접 선행 receipt의 interface/제약. 추적: R21, R27, R28, UI-02.01.
- **변경 파일:** `src/aiqa/web/templates/overview.html`, `src/aiqa/api/catalog.py`, `src/aiqa/domain/catalog.py`. 담당 시험: `tests/acceptance/test_w10.py`.
- **입출력 계약:** `GET /api/v1/projects/{p}/overview -> ProjectOverview`
- **구현·화면·예외:** UI-02 미완성 REC/검토대기/미분류 실패·진행/대기 RUN·차단 환경·최근 범위/결과를 실제 query 로 계산한다. 새 녹화·저장 케이스·묶음 버튼은 각 route 로 연결하고 TC 연결률/예시 PASS 를 성과로 표시하지 않는다.
- **검증 전제:** 빈 project 와 실제 draft/approved/REC/ITEM fixture 를 생성해 counts·빠른 이동 대상을 확인한다.
- **작업 순서:** `test_w10_03`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w10.py::test_w10_03 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "counts_match_db": True,
  "empty_fake_passes": 0,
  "new_recording_opens_device_step": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w10-04"></a>

## W10-04 — 케이스 목록·필터·정렬·페이지·복원

- [ ] **W10-04 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W10-04.md`(완료 시 생성).
- **직접 선행:** [W10-03](04a-case-management-ui.md#w10-03)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C11 + 직접 선행 receipt의 interface/제약. 추적: R21, R27, R28, UI-03.01, UI-03.02.
- **변경 파일:** `src/aiqa/web/templates/cases.html`, `src/aiqa/api/cases.py`, `src/aiqa/web/static/case_list.js`. 담당 시험: `tests/acceptance/test_w10.py`.
- **입출력 계약:** `GET /api/v1/projects/{p}/cases -> CursorPage[CaseListRow]`
- **구현·화면·예외:** UI-03 ID/이름/검증요약/target/폴더·태그·우선순위·담당자/latest draft/current approval/action 수/최근결과·환경 build/수정일을 제공한다. 전체/가능/초안/검토/미완성/보관·검색·sort·열설정·선택과 원래 목록 위치를 유지한다.
- **검증 전제:** 26 개 케이스·여러 상태·TC=null 에서 search/filter/sort/25 개 page·뒤로 복원과 타 project 행 누출을 확인한다.
- **작업 순서:** `test_w10_04`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w10.py::test_w10_04 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "default_page_size": 25,
  "query_restore": True,
  "cross_project_rows": 0,
  "null_tc_selectable": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w10-05"></a>

## W10-05 — 케이스 선택 조작·복제·보관·진입 연결

- [ ] **W10-05 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W10-05.md`(완료 시 생성).
- **직접 선행:** [W10-04](04a-case-management-ui.md#w10-04)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C11 + 직접 선행 receipt의 interface/제약. 추적: R21, R24, R27, UI-03.03.
- **변경 파일:** `src/aiqa/web/templates/cases.html`, `src/aiqa/api/cases.py`, `src/aiqa/web/templates/components/bulk_confirm.html`. 담당 시험: `tests/acceptance/test_w10.py`.
- **입출력 계약:** `POST /api/v1/cases/{c}/clone; POST /api/v1/cases/{c}/archive -> CaseView`
- **구현·화면·예외:** 단일/선택 실행→UI09·묶음추가→UI08·새 녹화→UI05·상세→UI04·검토→UI07 을 연결한다. bulk 요청은 각 항목 결과/차단 사유를 보여주고 조용히 제외하지 않는다. clone 은 approval0, 보관은 과거삭제 0 이다.
- **검증 전제:** 승인+미승인 선택·복제·보관·진행 REC 가 포함된 bulk 를 수행한다.
- **작업 순서:** `test_w10_05`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w10.py::test_w10_05 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "silent_exclusions": 0,
  "clone_approvals": 0,
  "history_deleted": 0,
  "blocked_rows_identified": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w10-06"></a>

## W10-06 — 케이스 검증 정의·변수·기대 편집

- [ ] **W10-06 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W10-06.md`(완료 시 생성).
- **직접 선행:** [W10-05](04a-case-management-ui.md#w10-05)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C11 + 직접 선행 receipt의 interface/제약. 추적: R03, R21, R28, UI-04.01.
- **변경 파일:** `src/aiqa/web/templates/case_detail.html`, `src/aiqa/web/templates/case_definition.html`, `src/aiqa/api/cases.py`. 담당 시험: `tests/acceptance/test_w10.py`.
- **입출력 계약:** `POST /api/v1/cases/{c}/versions(input: CaseEditInput) -> CaseVersionView`
- **구현·화면·예외:** UI-04 raw_text/목적/사전조건/변수·secret refs/단계의도/기대·required path 를 직접 편집하고 draft 저장한다. 모호함은 저장허용+readiness 이유, CAS409 입력보존/서버 diff, 타 project ref/secret 원문 반사는 거부한다.
- **검증 전제:** 불완전 자연어·필수 expected 미설정·잘못된 변수·동시편집·재접속을 검사한다.
- **작업 순서:** `test_w10_06`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w10.py::test_w10_06 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "incomplete_draft_saved": True,
  "formal_runnable": False,
  "stale_edit_status": 409,
  "secret_echo": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w10-07"></a>

## W10-07 — 단계 편집·변수화·명시 diff 수락

- [ ] **W10-07 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W10-07.md`(완료 시 생성).
- **직접 선행:** [W10-06](04a-case-management-ui.md#w10-06)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C11 / C12 + 직접 선행 receipt의 interface/제약. 추적: R03, R08, R24, R28, UI-04.02.
- **변경 파일:** `src/aiqa/web/templates/case_steps.html`, `src/aiqa/web/static/step_editor.js`, `src/aiqa/domain/versions.py`. 담당 시험: `tests/acceptance/test_w10.py`.
- **입출력 계약:** `StepEditCommand(add | duplicate | remove | move | bind_variable); accept_case_proposal(proposal_id: UUID, expected_head: UUID) -> CaseVersionView`
- **구현·화면·예외:** 단계/검증 추가·복제·삭제·위아래·변수화를 새 draft 로 저장한다. stable ID 복제는 새 ID, 의미변경은 semantic hash 갱신. AI/TC 제안은 diff 확인 후 명시 수락만 적용하며 raw/approved script inplace editor 는 제공하지 않는다.
- **검증 전제:** 단계복제/정렬/삭제·required check 참조·제안거부/수락·기존 approved version/hash 를 비교한다.
- **작업 순서:** `test_w10_07`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w10.py::test_w10_07 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "duplicate_step_new_id": True,
  "rejected_proposal_versions": 0,
  "accepted_proposal_versions": 1,
  "approved_source_unchanged": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w10-08"></a>

## W10-08 — 케이스 통합 탭·최신초안/승인본·diff

- [ ] **W10-08 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W10-08.md`(완료 시 생성).
- **직접 선행:** [W10-07](04a-case-management-ui.md#w10-07)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C11 + 직접 선행 receipt의 interface/제약. 추적: R08, R21, R24, R27, UI-04.03, UI-04.04.
- **변경 파일:** `src/aiqa/web/templates/case_detail.html`, `src/aiqa/web/templates/components/package_view.html`, `src/aiqa/api/cases.py`. 담당 시험: `tests/acceptance/test_w10.py`.
- **입출력 계약:** `GET /api/v1/cases/{c}; GET /api/v1/cases/{c}/versions; GET /api/v1/case-versions/{v}/diff?base={b} -> CaseDiff`
- **구현·화면·예외:** 검증/단계·code/설정/실행이력/검토·버전 탭을 만들고 latest draft 와 current approved 를 나란히 표시한다. package/REC/trial 없는 상태를 명시하고 읽기 링크만 연결한다. package 내용은 W29-06·history W16-06·review W18·policy W31 에서 실제 완성하며 이 작업만으로 그 기능을 완료 처리하지 않는다.
- **검증 전제:** 최초 draft·과거승인+새후보·package null/ready·철회 default null 에서 tab/URL selected version·diff 를 확인한다.
- **작업 순서:** `test_w10_08`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w10.py::test_w10_08 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "draft_approved_distinct": True,
  "missing_package_reason": True,
  "fabricated_history_rows": 0,
  "snapshot_editable": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w10-11"></a>

## W10-11 — 케이스 실행 설정·검증 방식·healing capability 편집

- [ ] **W10-11 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W10-11.md`(완료 시 생성).
- **직접 선행:** [W10-08](04a-case-management-ui.md#w10-08)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C11 / C06 / C09 + 직접 선행 receipt의 interface/제약. 추적: R13, R17, R21, R33, R34, UI-04.10.
- **변경 파일:** `src/aiqa/web/templates/case_settings.html`, `src/aiqa/api/cases.py`, `src/aiqa/domain/versions.py`. 담당 시험: `tests/acceptance/test_w10.py`.
- **입출력 계약:** `save_case_revision(actor: Actor, case_id: UUID, input: CaseRevisionInput, expected_head: UUID) -> CaseVersionView`
- **구현·화면·예외:** UI04 실행 설정 탭에서 Web URL/Android package·environment/data/secret ref·install/reset/cleanup·limits·검증별 deterministic/ai_visual/unknown 보완과 binding·승인 healing allowed/scope/상한/기본OFF를 편집한다. global 기본값과 case version 값을 구별하고 의미 변경은 새 draft/package=null·새 전체 REC/검토다. 실행 시 ON/OFF는 여기서 즉시 수행하지 않는다.
- **검증 전제:** 승인 case에서 verifier method/binding·healing scope/상한·환경을 수정하고 expected_head 충돌·타 project ref·필수 AI 키 누락·allowed=false를 확인한다.
- **작업 순서:** `test_w10_11`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w10.py::test_w10_11 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "new_case_revision": True,
  "old_approval_scope_changed": False,
  "new_package": None,
  "healing_default_enabled": False,
  "field_errors_preserve_input": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w10-09"></a>

## W10-09 — 기본 설정·role binding·키 일회 입력 UI

- [ ] **W10-09 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W10-09.md`(완료 시 생성).
- **직접 선행:** [W10-11](04a-case-management-ui.md#w10-11)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C11 / C06 + 직접 선행 receipt의 interface/제약. 추적: R13, R14, R21, R33, UI-15.01, UI-15.02.
- **변경 파일:** `src/aiqa/web/templates/settings.html`, `src/aiqa/api/settings.py`, `src/aiqa/api/model_bindings.py`, `src/aiqa/api/secret_refs.py`. 담당 시험: `tests/acceptance/test_w10.py`.
- **입출력 계약:** `GET/PATCH /api/v1/projects/{p}/settings; POST/PATCH /api/v1/model-bindings; GET/POST /api/v1/projects/{p}/folders|tags; PATCH /api/v1/folders/{f}|tags/{t} -> SettingsView | ModelBindingView | CatalogView`
- **구현·화면·예외:** UI-15 project/분류/default limits/보관/failure policy 와 authoring/verification/healing/maintenance binding·endpoint/model/key ref 를 저장한다. 키는 일회 입력 후 clear·read 미반환. 범위 축소는 허용, 승인 capability 확대는 새 version 필요. 실제 모델 검사 버튼 연결은 W15-04 다.
- **검증 전제:** role 별 다른 binding·key 저장/새로고침·설정 동시변경 409·기존 승인 scope 확대 시도를 확인한다.
- **작업 순서:** `test_w10_09`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w10.py::test_w10_09 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "role_bindings_separate": True,
  "read_secret_plaintext": False,
  "browser_saved_key": False,
  "old_approval_expanded": False
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

<a id="w10-10"></a>

## W10-10 — 선택 TC 목록·편집·참조·import UI

- [ ] **W10-10 완료** — 상태: `not_started`. 근거: `docs/validation/tasks/W10-10.md`(완료 시 생성).
- **직접 선행:** [W10-09](04a-case-management-ui.md#w10-09)
- **읽기:** CONTRACTS C00 / C01 / C02 / C03 / C11 + 직접 선행 receipt의 interface/제약. 추적: R21, R24, R28, UI-16.01, UI-16.02.
- **변경 파일:** `src/aiqa/web/templates/tcs.html`, `src/aiqa/web/templates/components/tc_import.html`, `src/aiqa/api/tcs.py`. 담당 시험: `tests/acceptance/test_w10.py`.
- **입출력 계약:** `GET/POST /api/v1/projects/{p}/tcs; POST /api/v1/tcs/{t}/versions; POST /api/v1/tcs/{t}/clone; POST /api/v1/tcs/{t}/archive; PUT/DELETE /api/v1/cases/{c}/tc-reference`
- **구현·화면·예외:** UI-16 선택 메뉴에서 검색/분류/revision·원문/단계/기대·복제/보관을 제공한다. 참조 연결/해제와 내용 가져오기 diff 를 분리하고 TC 새버전 안내는 정보성이다. UI05 에는 필수 TC 단계가 없다.
- **검증 전제:** TC0 개 전체진입·승인 case 참조/해제·TC 수정/보관·import 거부/수락·타 project TC 를 확인한다.
- **작업 순서:** `test_w10_10`에서 위 전제의 미구현 실패 확인 → 지정 범위 구현 → 아래 검사/필요 실제환경 확인 → diff/근거/인계 갱신. 단순 표현 변경은 화면 확인으로 검증한다.
- **검증 명령:** `python -m pytest tests/acceptance/test_w10.py::test_w10_10 -q`. 합격은 해당 함수 PASS + 아래 실제 관찰 projection 일치다. 필요한 live 근거를 모의 PASS로 대체하지 않는다.

```python
assert observed == {
  "tc_required": False,
  "reference_changes_approval": False,
  "import_accept_new_version": True,
  "cross_project_tc_denied": True
}
```

완료 기록은 실제 응답/DB·파일·journal·화면 근거, 실행 명령/결과, 제공 interface, 남은 제한, 다음 준비 ID를 포함한다. 카드 밖 기능은 해당 담당 ID에 남긴다.

## 영역 종료 점검

- 카드 체크·TASK_INDEX 상태·인계 근거가 일치해야 한다.
- [COVERAGE](COVERAGE.md)·[UI_COVERAGE](UI_COVERAGE.md)에서 담당 항목의 실제 증거를 연결한다.
- 후속 기능을 미리 완료 처리하지 않는다. 실패/계약 변경은 [REVIEW](REVIEW.md)에 기록하고 영향 작업을 재개한다.
