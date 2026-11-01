# 탐색·입력 보호·케이스 편집 개선 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자가 프로젝트와 케이스 맥락을 유지하며 내용을 작성·저장·검토한다.
**Architecture:** 기존 페이지를 프로젝트 shell과 케이스 작업 공간으로 연결하고, 공통 폼 상태에 이동 보호와 구조화 편집을 붙인다. 기존 version/readiness/approval 모델을 유지한다.
**Tech Stack:** 기존 FastAPI/Jinja/JavaScript/pytest.
**Spec / Global Constraints / Review Focus:** [전체 계획](../2026-11-01-ui-ux-improvements.md)을 적용한다. 파일 경로는 저장소 루트 기준이며 `web/...`, `api/...` 축약은 `src/aiqa/` 아래다. 모든 단위는 `planned`다.

<a id="ux-03"></a>
## UX-03 — 작성 도중 이동을 통제하고 저장 실패에서 복구

**바꿀 상황:** 지금은 탭 이동으로 입력이 사라진다. 개선 후 사용자는 변경 여부와 저장 상태를 알고, 원래 가려던 목적지로 안전하게 이동한다. 자동 저장을 새로 도입해 충돌/버전 생성을 숨기는 방식은 사용하지 않는다.

### E01 — 하나의 이동 경계와 미저장 선택

**선행:** S01. **파일:** 수정 `web/static/navigation.js`, `api.js`, `base.html`; 새 `templates/components/unsaved_dialog.html`, `tests/acceptance/test_ux_dirty_navigation.py`.
**입출력:** 전체 계획의 `aiqaNavigate(url)`와 form handle `isDirty()/save()`를 사용한다. 기존 `api.js`의 document click→프로젝트 session→`location.assign`과 `navigation.js`의 별도 guard를 한 경로로 연결한다. 링크마다 서로 다른 가드가 동시에 실행되지 않게 한다.

- [ ] 최초 snapshot과 현재 입력 비교로 dirty를 감지한다. 수정 후 원래 값으로 돌아오면 clean, 실패/409는 dirty, 서버 ACK만 clean으로 만든다. 공통 form register가 없는 화면은 보호 완료로 세지 않는다.
- [ ] dialog에 ‘저장 후 이동 / 버리고 이동 / 계속 편집’을 제공하고 원 목적지·현재 입력·focus를 보존한다. 저장 실패 시 이동하지 않고 해당 오류로 안내한다. 저장 중에는 완료 전 중복 이동/제출을 막는다.
- [ ] 탭·목록·프로젝트 전환·브라우저 뒤로/앞으로·새로고침을 각각 다룬다. 브라우저가 제어하는 unload에는 기본 경고를 사용하고 커스텀3버튼이 항상 나온다고 보장하지 않는다. Ctrl/Meta 새 탭 열기는 현재 편집을 버리지 않는다.
- [ ] 입력→탭 이동 취소/버림/저장, 프로젝트 이동 중 session 준비 실패, 저장422/409, 성공 직후 이동을 검증한다. session 코드가 guard보다 먼저 강제 이동하지 않는지 실제 브라우저로 확인해 `docs/validation/ux/E01.md`에 남긴다.

### E02 — 모든 편집 화면에 동일한 보호·저장 피드백 적용

**선행:** E01. **파일:** 수정 `definition_editor.js`, 계획상의 `environment_editor.js/dataset_editor.js/recording_setup.js`, 기존 `settings.html` script, `case_review.html`의 의견·반려 사유 입력; 위 dirty 시험 확장.

- [ ] 정의·환경·데이터·녹화 초안·프로젝트 설정별로 read/persist를 등록한다. 각 폼에 ‘저장하지 않은 변경 / 저장 중 / 저장됨’과 현재 저장 버전을 표시한다. 검토 의견·반려 사유의 미제출 입력도 `saveBeforeLeave:false`로 보호하며, 이동 확인에서 승인/반려를 암묵 제출하지 않고 명시 제출로 돌아가거나 버리기/취소하게 한다.
- [ ] 입력 오류는 현재 값 유지, 충돌은 서버 값과 본인 값 비교 후 명시 재저장, 권한 상실은 읽기/복사 가능한 비밀 아닌 값과 이동 취소를 제공한다. 요청 자체를 자동 반복하지 않는다.
- [ ] 비밀 입력은 메모리/DOM에서만 처리하고 실패 후 비웠다면 정확히 설명한다. 임의 localStorage 자동 복원을 추가하지 않는다. 복원 보장을 요구하지 않는 현재 UI_SPEC을 유지한다.
- [ ] 화면별 수정·취소·실패·저장 후 이동을 하나씩 실제 조작한다. 구현되지 않은 폼은 독립 잔여 단위로 남기고 `E02.md`에 보호 범위 표를 기록한다.

<a id="ux-04"></a>
## UX-04 — 검색을 업무 범위 안에서 끝내기

**바꿀 상황:** 검색이 샘플 목록으로 이탈한다. 개선 후 사용자는 현재 프로젝트의 케이스를 찾고 결과 범위·0건·필터를 이해한다. 모든 자산을 검색하는 새 검색 서비스를 만들 필요는 없다.

### N01 — 프로젝트 케이스 검색과 결과 복귀

**선행:** E01의 이동 경계. **파일:** 수정 `web/templates/base.html`, `web/routes.py`, `api/cases.py`, `templates/cases.html`, `static/case_list.js`; 새 `tests/acceptance/test_ux_project_search.py`.
**입출력:** 프로젝트 context가 있으면 실제 `/ui/projects/{p}/cases?q=...`를 사용하고 label을 ‘현재 프로젝트 케이스 검색’으로 명시한다. 프로젝트 목록에서는 프로젝트 검색만 제공한다. 프로젝트 검색 없는 generic shell을 제품 목적지로 사용하지 않는다.

- [ ] 검색어 변경 시 이전 cursor와 선택을 초기화하고 필요한 scope만 유지한다. 명시적 저장 보기 안에서 검색하는 경우 scope를 표시한다. 공통 검색과 같은 뜻의 중복 입력을 정리한다.
- [ ] 결과에 검색어·범위·조회 건수/표시 범위·조건 지우기를 표시한다.0건은 오타/필터 해제와 새 케이스 행동을 제시한다. 정확한 전체 건수는 M01이 제공하기 전까지 계산한 척하지 않는다.
- [ ] 다른 프로젝트에 같은 이름이 있어도 섞이지 않음, 한글/특수문자 query escaping,0건, 상세→목록 복귀, 검색 변경 후 선택 초기화를 시험·조작한다.
- [ ] `N01.md`에 실제 결과 URL과 sample `/ui/shell` 비진입 증거를 남긴다. 입력이 dirty이면 E01 이동 보호를 거친다.

<a id="ux-05"></a>
## UX-05 — 검증 의도를 읽고 고치는 편집기

**바꿀 상황:** 사용자는 JSON 문법과 escape를 해석해야 한다. 개선 후 자연어·사전조건·변수·검증을 업무 표현으로 작성하고, 저장 시 기존 canonical 모델로 변환한다. 보기만 예쁘게 바꾸고 뒤에 필수 JSON을 남기는 방식은 채택하지 않는다.

### E03 — 자연어·조건·변수·경로 편집

**선행:** S01, E01. **파일:** 수정 `web/templates/case_definition.html`, `case_detail.html`, `static/definition_editor.js`, `api/cases.py`; 새 `tests/integration/test_ux_definition_roundtrip.py`.
**입출력:** 기존 definition snapshot과 `/ui/projects/{p}/cases/{c}/definition` 저장 계약을 사용한다. `raw_text/objective/preconditions/variables/secret_refs/path_policy`만 이 카드에서 편집하고 나머지 필드를 복사 보존한다. 성공한 version ID를 새 `expected_head`로 사용한다.

- [ ] 자연어 넓은 입력·목적·사전조건 목록·변수 이름/타입/값 표·필수/금지 경로 목록을 제공한다. 읽기 가능한 한글로 렌더하고 원 JSON은 고급 읽기/내보내기용으로 둔다.
- [ ] 변수 key 변경은 연결 검증에 영향을 알린다. secret은 같은 프로젝트 ref 선택이며 값을 미리보기로 풀지 않는다. 기존에 UI가 지원하지 않는 복합 값은 요약/읽기 전용으로 보존하고 파괴적으로 문자열화하지 않는다.
- [ ] 충돌409는 서버본과 본인 수정 비교·취소·명시 새 저장으로 처리한다. ‘저장됨’ 뒤에는 새 초안 버전과 정식 실행에 필요한 절차를 알려 준다. 의미 변경 시 기존 승인을 조용히 계속 쓰지 않는다.
- [ ] 한글 왕복·복합 변수 보존·null/빈 값 구분·secret ref·미편집 steps/recorded_steps/package 관련 필드 보존·409를 검증한다. 사용자에게 JSON 입력을 요구하지 않고 목적/변수 변경을 완료해 `E03.md`에 남긴다.

### E04 — 단계·기대 결과를 연결해 편집

**선행:** E03. **파일:** 수정 위 정의 파일·기존 단계 편집 UI/`api/cases.py`; 위 roundtrip 시험 확장. 새로운 단계 UI 파일이 필요하면 `templates/components/definition_steps.html`, `static/definition_steps.js`로 분리한다.
**입출력:** `CaseDefinition.steps`의 `StepSpec`과 `CheckSpec(id,kind,expected)`를 기존 canonical serializer로 변환한다. 사용자의 검증 정의 단계와 녹화된 action/compiled package의 연결·불변 규칙은 기존 step-edit 계약을 따른다. 화면의 배열 순서를 ID로 삼지 않는다.

- [ ] 단계 카드마다 수행 의도·검증 목록·기대 값, 마지막에 최종 기대를 제공한다. 지원 kind만 선택하고 미지원/legacy kind는 읽기 전용으로 보존한다.
- [ ] 추가/삭제/순서 변경의 의미와 기존 녹화·검증 binding 영향을 명시한다. 기존 `step-edits` 경계가 필요한 의미 변경은 해당 API를 사용하고 정의 JSON만 고쳐 녹화 절차와 불일치하게 하지 않는다.
- [ ] 필수 기대가 없어도 초안은 저장하고 ‘시범/승인에 필요한 보완’을 표시한다. AI 구조화 제안은 W16-02 계약이 구현된 경우에만 명시 요청·diff·적용으로 연결하고 배경 자동 호출하지 않는다.
- [ ] 단계 순서 변경 후 ID/binding 보존·삭제 영향·미지원 kind·다중 검증·최종 기대·필수 실패 보존을 검증한다. `E04.md`에 일반 사용자 편집과 저장본을 대조한다.

<a id="ux-06"></a>
## UX-06 — 위치와 다음 행동이 드러나는 작업 공간

**바꿀 상황:** ‘목록/상세’만 반복되고 케이스 정보가 여러 얕은 화면에 분산된다. 개선 후 프로젝트에서 어디에 있는지, 어떤 버전을 보고 있는지, 다음에 작성/시범/검토 중 무엇을 해야 하는지 알 수 있다.

### N02 — 공통 프로젝트 탐색·복귀 맥락

**선행:** N01. **파일:** 수정 `web/templates/base.html`, `web/routes.py`, 프로젝트 page context를 만드는 `api/catalog.py/resources.py/cases.py/settings.py/datasets.py/executions.py`; 새 `templates/components/project_navigation.html`, `tests/acceptance/test_ux_project_navigation.py`.
**입출력:** 서버 context의 검증된 project ID/name·현재 section·crumbs·명시 action URL을 소비한다. 클라이언트가 URL 일부만 보고 프로젝트명/권한을 만들어 내지 않는다.

- [ ] 프로젝트 전환과 개요/케이스/묶음/수행/리포트/환경/설정을 일관되게 제공한다. 구현되지 않은 메뉴는 비활성 ‘준비 중’으로 두고 샘플 페이지로 연결하지 않는다. 환경 하위에 기기/앱 빌드/데이터 경로를 노출한다.
- [ ] 케이스명을 breadcrumb·페이지 제목으로 유지하고 범위가 다른 링크를 구체적으로 명명한다. 현재 메뉴/탭에 `aria-current`를 부여한다. 모든 항목을 현재 페이지로 표시하지 않는다.
- [ ] 목록 URL/필터별 scroll과 선택을 복원하고 새 상세는 본문 시작으로 연다. 전역 `aiqa.scroll`을 그대로 다른 페이지에 적용하지 않는다. 프로필 복귀·초안 복귀 URL은 같은 origin/project의 허용 경로만 받는다.
- [ ] 프로젝트 전환·환경 하위 이동·목록2페이지→상세→복귀·새 상세·직접 URL·권한 없는 경로를 시험해 `N02.md`에 남긴다. 화면 간 조회 scope가 서버에서도 유지되어야 한다.

### N03 — 케이스 상태와 탭을 한 작업 공간으로 연결

**선행:** N02, E03. **파일:** 수정 `web/templates/case_detail.html`, `case_definition.html`, `recording_history.html`, `api/cases.py`; 새 `tests/acceptance/test_ux_case_journey.py`.
**입출력:** 기존 readiness의 `saved/recordable/replayable/reviewable/formal_runnable`과 reasons, 선택 version·source REC·trial ITEM·approval을 소비한다. W18/W19 viewer/review/approval 기능을 재사용하며 신규 승인 저장소를 만들지 않는다.

- [ ] 케이스 요약에 최신 초안·현재 승인본·최근 녹화/시범·다음 행동과 차단 이유를 표시한다. ‘기록 저장됨 / 녹화 종료 / 시범 통과 / 사람 승인 / 최근 실행 결과’를 하나의 상태로 합치지 않는다. TC는 접힌 선택 참조로 둔다.
- [ ] 검증·녹화 단계/증거·설정·이력·검토 탭에서 같은 케이스/version context를 유지한다. 저장된 버전·REC·시범 근거가 어디서 왔는지 이동해 확인할 수 있게 한다.
- [ ] 초안만 있음·새 초안/과거 승인본 병존·녹화 실패 보존·근거 없음의 요약과 다음 행동을 시험한다. 실제 링크를 조작해 `N03.md`에 저장본·승인본·선택 version이 섞이지 않는 근거를 남긴다.

### N04 — 시범 준비를 선택·사전 검사·명시 접수로 완성

**선행:** N03, S03/S04의 저장본 선택 계약. **파일:** 수정 `web/templates/execution_setup.html`, `api/executions.py`; 새 `web/static/execution_setup.js`, `tests/acceptance/test_ux_trial_setup.py`.
**입출력:** 기존 W17의 시범 preview/enqueue를 사용한다. exact version/package·환경/data·대상 snapshot과 hash를 접수 시 고정한다. UI에서 최신값으로 조용히 교체하지 않는다.

- [ ] 시범 준비의 문단을 실제 version/package·환경/data/대상·검사 결과 요약과 명시 접수로 바꾼다. package 없음은 생성/재녹화 경로, binding 없음은 설정 복귀를 제시한다. 시범은 승인 없이 가능하지만 healing OFF이며 실행 준비 조건은 그대로 검사한다.
- [ ] 선택→검사→입력 변경 시 검사 무효화→재검사→명시 접수 순서를 구현한다. 점유/한도/AI 검사 key 없음은 해결 가능한 항목별 이유를 보여 준다.
- [ ] 미승인 초안 시범·package 없음·결정적 검사만·AI 검사 미설정·접수 중복·준비 후 자원 변경을 시험·조작한다. `N04.md`에 core 접수와 실제 장치 성공을 분리 기록한다.

### N05 — 기존 증거·검토·승인 기능의 동선과 복구

**선행:** N03, 기존 W18/W19 구현. **파일:** 수정 `web/templates/case_review.html`, `components/evidence_viewer.html`, `api/cases.py`, 필요한 `static/evidence_viewer.js`; 새 `tests/acceptance/test_ux_review_journey.py`.
**입출력:** 정확한 owner/attempt/version·review/evidence hash·expected current approval을 기존 API에 전달한다. 현 approval CAS·근거 pin/만료 규칙을 유지한다.

- [ ] 사후 검토 화면에서 기존 단계 의견·다음 미검토·전후 캡처·로그·diff·승인/반려를 연결한다. 정확한 owner/attempt가 바뀌지 않게 하고 missing/expired를 다른 실행 그림으로 채우지 않는다. 반려 사유와 승인 CAS 충돌은 입력을 유지해 설명한다.
- [ ] 승인/반려 제출 중 중복 행동을 막고 성공/검증 오류/409/권한 상실을 구별한다. 차단 이유와 해당 단계/필요한 새 근거로 이동할 수 있게 한다. 승인으로 QA 결과를 바꾸지 않는다.
- [ ] source REC+trial ITEM 합성 근거로 미검토 탐색·반려 사유 수정·승인 충돌·기한 만료·증거 누락을 시험·조작해 `N05.md`에 남긴다. 실제 키/장치 성공을 수용 조건으로 섞지 않는다.

### N06 — 재녹화에서 이전 기본본과 새 후보 구별

**선행:** N03, R02/R03. **파일:** 수정 `web/templates/case_review.html`, `components/rerecord.html`, `recording_history.html`, `api/cases.py`, wizard 초기화; 새 `tests/acceptance/test_ux_rerecord_journey.py`.
**입출력:** 기존 전체 재녹화 계약과 source/base version을 R01~03에 전달한다. 같은 케이스에 새 REC/produced draft를 만들고 이전 기록을 재작성하지 않는다.

- [ ] 전체 재녹화는 R01에 원 케이스/기준 버전을 넘겨 새 초안으로 시작하고 이전 승인본 유지·이전 검토 불승계를 안내한다. 철회 기능은 W19-03의 최신 구현을 대조하고 없는 동작을 활성화하지 않는다.
- [ ] 새 후보가 실패/중단되면 보존 기록·사유·다시 준비 행동을 보여 준다. 이전/새 버전 비교는 검증 내용·환경·동작·근거 차이를 표시하고 새 승인 전 기존 기본본 유지 상태를 명시한다.
- [ ] 승인본이 있는 케이스에서 재녹화 취소/초안 저장/중단/새 후보 반려를 시험·조작한다. 기존 approval/REC 불변과 새 후보의 별도 ID를 `N06.md`에 남긴다. native 녹화 성공은 준비된 환경의 별도 증거로 기록한다.
