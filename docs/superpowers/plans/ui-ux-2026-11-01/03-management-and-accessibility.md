# 목록·화면 구성·AI 설정·접근성 개선 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 월3,000개 회귀 케이스를 이해 가능한 상태와 선택 범위로 관리하고, 두 해상도와 키보드에서 같은 작업을 완료한다.
**Architecture:** 서버 목록 projection·정확한 조회 범위와 기존 설정 계약을 보완하고 공통 UI 구성 요소로 표현한다. 기능별 수용과 전체 여정 수용을 분리한다.
**Tech Stack:** 기존 FastAPI/Jinja/JavaScript/CSS/SQLite/pytest.
**Spec / Global Constraints / Review Focus:** [전체 계획](../2026-11-01-ui-ux-improvements.md)을 적용한다. `web/...`, `api/...` 축약은 `src/aiqa/` 아래다. 모든 단위는 `planned`다.

<a id="ux-07"></a>
## UX-07 — 목록을 실행 대상 선별 작업 공간으로 개선

**바꿀 상황:** UUID와 반복 링크는 많지만 어떤 케이스를 회귀에 넣을지 판단하기 어렵다. 개선 후 사용자는 대상·버전·최근 결과·검토 상태를 보고 검색/필터로 범위를 좁힌 뒤, 선택한 항목만 명확히 실행한다.

### M01 — 목록 데이터와 상태 의미 정리

**파일:** 수정 `domain/catalog.py`, `store/models.py`의 `CaseListRow/CursorPage`, `api/cases.py`, `web/templates/cases.html`; 새 `tests/integration/test_ux_case_projection.py`.
**입출력:** 기존 목록 query/projection에 target·draft/approved version·최근 실행 결과/시각·검토 필요 요약을 추가한다. 합의된 QA/disposition/display_result 모델을 재사용하며 null은 ‘실행 이력 없음’ 등 실제 의미로 표시한다. 조회 범위 total을 지원하려면 동일 필터의 count를 서버가 반환하도록 additive 계약을 소유 문서에 명시한다.

- [ ] 상태 사전을 정리한다. ‘정식 실행 가능 / 초안 / 검토 대기 / 미완성 / 보관’을 화면 표현으로 쓰되, 녹화 저장·시범 결과·승인·최근 회귀 결과는 별도 축이다. frontend가 approval ID 유무 하나로 readiness를 추정하지 않는다.
- [ ] 이름을 주 열로, target·승인/초안·최근 결과·시각을 보조 열로 배치한다. UUID는 축약+전체 복사로 제공한다. AUT 순번 ID가 현재 없으면 존재하는 척 만들지 않고 별도 고유 ID 계약이 생길 때 교체한다. 선택 TC는 기본 필수 열에서 뺀다.
- [ ] 단일/배치 SQL projection과 정확한 total을 검증하고 row별 N+1 조회를 피한다. 직접 입력한 필터와 projection 확장은 `CaseListQuery` 및 API query validation에 같이 반영한다.
- [ ] 이력 없음·초안/승인 병존·승인 철회·최근 실패/재시도·다른 project 데이터를 시험한다.0건/32건의 값과 건수를 실제 화면에서 확인해 `docs/validation/ux/M01.md`에 남긴다.

### M02 — 페이지·선택·일괄 행동의 범위 명확화

**선행:** M01, N01. **파일:** 수정 `cases.html`, `static/case_list.js`, `case_bulk.js`, `api/cases.py`, `domain/catalog.py`; 새 `tests/acceptance/test_ux_case_selection.py`.
**입출력:** 페이지 이동은 기존 cursor 계약을 유지한다. 서버에 이전 cursor가 필요하면 동일 scope/sort의 검증된 cursor로 additive 지원하고, 직링크2페이지에서도 이전/처음 이동이 가능해야 한다. `selected`는 명시적인 case ID 집합이며 단일 문자열 비교·첫 항목만 보존하는 처리를 없앤다.

- [ ] ‘전체32개 중1~25 / 다음 / 이전 / 처음’을 실제 count/cursor로 제공한다. 필터·sort 변경 시 cursor를 초기화하고 범위 변화를 알린다. 저장된 목록 context로 상세에서 돌아오게 한다.
- [ ] 행 선택·현재 페이지 전체 선택·선택 건수·선택 해제를 제공한다. MVP 기본은 현재 페이지 선택으로 명시하고 페이지/필터/프로젝트 변경 시 선택을 해제해 알린다. 검색 결과 전체3,000개 선택 기능은 별도 서버 계약 없이 추가하지 않는다.
- [ ] 선택0개면 일괄 행동을 비활성화한다. 실행/보관 등은 대상명·개수·제외 이유를 확인하고 서버 결과의 성공/차단을 항목별로 표시한다. 상한 초과는 조용히 잘라 실행하지 않는다.
- [ ] 2페이지 직링크·검색 후 cursor 초기화·다중 선택·0개·페이지 전환·foreign ID·같은 이름·부분 차단을 시험·조작한다. `M02.md`에 사용자에게 보인 선택 범위와 실제 요청 ID 집합을 대조한다.

### M03 — 대표 회귀 규모 수용

**선행:** M01~02. **파일:** 새 `tests/performance/test_ux_case_catalog_scale.py`; 필요한 경우 query index migration과 위 catalog query만 수정한다. 새 인프라를 도입하지 않는다.

- [ ] 임시 런타임에 합성3,000개 케이스와 초안/승인/실패/이력 없음 상태를 준비한다. 실제 실행이나 AI 호출을 만들지 않는다.
- [ ] 한글 검색·지원 필터·정렬·중간/마지막 페이지·선택 후 일괄 preview를 측정한다. UI가 전체 케이스/증거를 내려받지 않고 page size와 ITEM 한도를 지키는지 확인한다.
- [ ] 제안 수용 목표는 명시한 로컬 시험 환경에서 warm 목록/검색의 p95 1초 이내, 페이지 이동 누락/중복0, 한 페이지의 row별 SQL 조회0이다. 이는 현재 성능 주장이 아니라 계획의 초기 목표다. hardware/runtime/측정 반복 수를 기록하고 목표 변경 시 이유와 수치를 남긴다.
- [ ] API 성능과 브라우저 응답성을 별도로 확인해 `M03.md`에 남긴다. 목표 미달 시 query/index 보완 단위를 편성하고 기능 수용과 성능 수용을 구분한다.

<a id="ux-08"></a>
## UX-08 — 색상보다 작업의 계층과 읽기 공간 개선

**바꿀 상황:** 작은 기본 입력란과 나열된 안내가 같은 비중을 차지한다. 개선 후 사용자는 핵심 입력·상태·다음 행동을 먼저 보고, 상세 진단/고급 옵션은 필요할 때 연다.

### V01 — 공통 화면 구성과 행동 계층

**파일:** 수정 `web/static/app.css`, `base.html`; 새 `templates/components/page_header.html`, `form_section.html`, `status_summary.html`, `action_bar.html`. 화면별 템플릿은 해당 소유 카드에서 이 구성 요소를 적용한다.
**입출력:** 서버 context의 제목·저장 상태·주 행동·보조 행동을 소비하고 데이터 의미를 CSS로 추정하지 않는다. 새로운 디자인 라이브러리나 전체 프레임워크를 추가하지 않는다.

- [ ] 페이지마다 프로젝트/케이스 제목 → 상태 요약 → 작업 본문 → 행동 순서를 통일한다. 주 행동은 현재 단계의 하나(다음/저장/검토 등)로 강조하고 재녹화/보관 등 영향 큰 행동은 구분한다.
- [ ] label을 입력 위에 두고 관련 입력을 fieldset으로 묶는다. 자연어는 넓은 다중 행, 변수·데이터는 표, 검증 단계는 카드, 진단·원 JSON은 접기 영역으로 구성한다. 저장 성공은 버튼 근처와 version으로 전달한다.
- [ ] 1440에서는 편집 본문과 보조 상태,1024에서는 보조 패널 접기/본문 우선으로 배치한다. table/capture는 전용 overflow 영역에 넣고 body 전체 가로 이동을 요구하지 않는다. 고정 action bar가 필드 오류/키보드 focus를 가리지 않게 한다.
- [ ] 버튼·input/select/textarea·tabs·modal의 focus/disabled/loading·상태 문구를 한 규칙으로 정의한다. 색상 외 텍스트/아이콘을 사용한다. 실제 활성 링크/동작과 모양을 일치시킨다.
- [ ] 긴 한글 제목·긴 변수/로그·다중 오류·0건·busy·오프라인을 각 소유 화면에서 검증한다. `V01.md`에 재사용 구성 요소와 실제 적용 범위를 남긴다. CSS 존재만으로 전체 화면 완료를 선언하지 않는다.

### V02 — 두 폭 전체 여정과 증거 화면 수용

**선행:** 적용할 화면의 각 소유 카드. **파일:** 기존 evidence viewer·case review 템플릿/JS·CSS의 필요한 개선. 새 증거 문서 `docs/validation/ux/V02.md`.

- [ ] 프로젝트→환경/데이터→녹화 초안→검증 편집→시범 준비→저장본 검토→목록 복귀를1440/1024에서 각각 조작한다. 실제 native가 없으면 그 구간은 명시 대기하고 합성 근거로 저장/검토 UI만 수용한다.
- [ ] 기존 W18 viewer는 왼쪽 단계/미검토 목록, 전후 캡처, 동작·로그·검증 상세, 현재 owner/attempt/version 맥락을 같은 공간에 둔다. 1024에서 보조 로그/정보를 접어도 선택 action과 전후 구분은 유지한다.
- [ ] fit/100%/확대/이동/전체보기는 mode attribute만 바뀌는 것이 아니라 실제 보이는 이미지 배율/영역이 바뀌어야 한다. 이전/다음/첫 실패·로그 열기와 함께 확인한다. 현재 구현 여부를 먼저 재현하고 누락된 제어만 고친다.
- [ ] 근거 누락·만료·전송 대기는 제자리에 표시하고 다른 시도 캡처로 채우지 않는다. ‘정제된 캡처’와 민감 화면 차단을 구별하고 실제로 검증하지 않은 마스킹을 보장하는 문구를 제거한다. 새 승인/재녹화 시 선택 근거가 몰래 바뀌지 않아야 한다.
- [ ] 전체 페이지 before/after, 선택 단계의 캡처/로그 일치, 핵심 행동 가시성·focus·오류 복구를 기록한다. 임의 캡처 최대1024px 값만으로 반응형 수용을 대신하지 않는다.

<a id="ux-10"></a>
## UX-10 — AI를 언제·얼마나 쓰는지 결정하는 설정

**바꿀 상황:** 역할 이름·policy 문자열·키가 나열돼 사용자가 비용과 동작을 예상하기 어렵다. 개선 후 녹화·필요 검증·예외 복구를 구별하고, 기존 연결을 보존하면서 필요한 부분만 바꾼다.

### A01 — 역할 설명·키 보관 상태·명시 변경

**선행:** S01/E01의 상태·이동 규칙. **파일:** 수정 `web/templates/settings.html`, `api/settings.py`, 기존 model binding 경로; 새 `web/static/settings_editor.js`, `tests/acceptance/test_ux_model_settings.py`.
**입출력:** wire role은 `authoring/verification/healing/maintenance`를 유지한다. 화면 label만 녹화 AI/검증 AI/예외 복구 AI/유지보수 AI로 바꾼다. settings `expected_lock`과 secret ref 계약을 유지한다. 기존 binding 없음·유지·교체·해제를 구분하고 빈 입력을 해제 명령으로 쓰지 않는다.

- [ ] 각 역할에 호출 시점과 필수 여부, 현재 endpoint/model·키 연결 유무를 표시한다. key는 password로 기본 숨김·일시 보기·입력 취소를 제공하며 기존 원문을 재표시하지 않는다.
- [ ] 변경하지 않은 역할은 저장 payload에서 명시 유지하고 키를 다시 요구하지 않는다. 교체는 새 secret/binding revision, 해제는 서버가 지원하는 명시 계약으로 처리한다. 해제 계약이 없으면 버튼을 활성화하지 않고 필요한 API 보완을 별도 완료 조건으로 남긴다.
- [ ] 프로젝트 설정 lock 충돌 때 앞서 일부 키/binding만 바뀌지 않도록 저장 경계를 확인한다. 현재 settings handler의 binding 저장 후 `_write` 경로를 원자 처리하거나 명시 부분 결과와 복구 계약으로 고정한다. ‘설정 실패지만 키만 변경됨’을 조용히 남기지 않는다.
- [ ] 기존 연결 유지·한 역할 교체·빈 키·실패 후 비움 안내·409 rollback·foreign ref를 시험한다. 실제 키 대신 합성 값으로 조작하고 응답/로그/storage 비노출을 확인해 `A01.md`에 남긴다.

### A02 — 유효 정책·셀프힐링·비용 한도 안내

**선행:** A01. **파일:** 수정 settings UI/API, 케이스/시범 준비 summary와 기존 broker/usage 조회 adapter; 새 `tests/acceptance/test_ux_ai_policy_summary.py`.
**입출력:** timeout은 현 API 정수1..600, failure/retention/healing은 소유 계약의 허용값으로 제한한다. UI label만 번역하고 실제 값을 새로 발명하지 않는다. global/project/case 및 접수 snapshot의 설정 출처·유효값을 구분한다.

- [ ] 일반 재생은 기록 기반, AI 검증은 선택 검사에서, healing은 기본OFF 및 허용 capability 안의 예외에서만 호출됨을 요약한다. 승인 capability 밖 ON 선택은 서버도 거부한다. 시범은 OFF 고정으로 표시한다.
- [ ] 호출/시간/비용 한도·실제 누적 사용량·초과 차단을 각각 보여 준다. 월3,000개는 예상 업무량이며 실행당 토큰/호출 수가 없으면 실제 비용을 확정 금액으로 제시하지 않는다. 아직 계측되지 않은 항목은 ‘계측 전’으로 표시한다.
- [ ] 모델 연결 검사나 검증 실행은 명시 행동으로만 연결하고 유료 호출 여부를 사전에 표시한다. 화면 진입/설정 저장/일반 재생 준비가 자동 연결 검사로 과금되지 않게 한다.
- [ ] key 없음+결정적 검사, key 없음+AI 검사, healing OFF/허용 ON/범위 밖 ON, 시범, 한도 초과, 상속/override를 시험·조작한다. 실제 API 호출 없이 정책과 차단을 확인해 `A02.md`에 남긴다.

<a id="ux-11"></a>
## UX-11 — 키보드·보조 기술로 같은 업무 완료

**바꿀 상황:** 체크박스와 검색의 이름이 없고 상태 변화가 시각 문구에만 의존한다. 개선 후 사용자는 초점과 대상·오류·변경 결과를 인지하며 마우스 없이 작업을 마친다.

### K01 — 구성 요소별 접근성 계약

**파일:** 수정 `base.html`, `cases.html`, 각 폼 feedback/tab/dialog·viewer와 CSS; 새 `tests/acceptance/test_ux_accessible_semantics.py`.
**입출력:** 각 화면은 접근 가능한 name·현재 상태·오류 연결을 제공한다. 이 카드는 앞 카드의 기준을 감사·보완하며 label 제공을 나중 작업으로 미루는 근거가 아니다.

- [ ] 행 checkbox는 ‘<짧은 ID> <케이스명> 선택’, 전체 선택은 ‘현재 페이지25개 선택’ 등 대상을 포함해 같은 이름의 케이스도 구별한다. 검색은 범위 label, table은 caption/header, 입력은 label·설명·필수·오류 연결을 갖춘다.
- [ ] 저장 상태는 status, 필요한 오류 요약은 alert로 알리고 오류 위치로 이동한다. disabled 사유는 읽을 수 있게 제공한다. 탭은 실제 링크 탐색 또는 완전한 tab keyboard 중 한 패턴을 일관되게 구현한다.
- [ ] modal은 제목·focus 진입/순환/취소·원 위치 복귀를 제공한다. 키보드 동작이 입력을 가로채지 않게 한다. 특히 viewer 방향키는 textarea/input/select/contenteditable의 커서 이동을 침범하지 않는다.
- [ ] DOM 의미 시험과 실제 Tab/Shift+Tab/Enter/Space/Escape/방향키 조작을 대조해 `K01.md`에 남긴다. 스크린리더 실제 시험을 하지 않았다면 했다고 쓰지 않는다.

### K02 — 사용자 목적 기반 통합 수용

**선행:** 검증할 해당 소유 카드, K01. **파일:** 새 `docs/validation/ux/K02.md`와 사용성 수용 시나리오. 독립 사용자 관찰은 실제 참여자가 준비된 경우에만 별도로 기록한다.

- [ ] 처음 방문자가 ‘TC 등록 없이 Web/Android 초안 저장’을 키보드로 수행하고 재조회한다. 실기기가 없어도 왜 녹화를 시작할 수 없는지와 다음 조치를 찾을 수 있어야 한다.
- [ ] ‘조건 수정 중 다른 프로젝트로 이동’을 수행해 저장/버리기/취소를 구분하고, 오류가 나면 입력 유지·수정·복귀를 완료한다.
- [ ] ‘32개 중 실패 대상 찾기→선택→범위 확인→실행 준비’와3,000개 규모의 동일 범위 규칙을 확인한다. 화면 선택과 서버 요청 대상이 일치해야 한다.
- [ ] ‘저장된 스와이프/탭의 전후 캡처·로그 확인→다음 미검토→승인 또는 반려→재녹화 초안’을 수행한다. 새 녹화 도중 승인을 요구하지 않고 기존 승인본과 새 후보가 구분돼야 한다. 근거 만료/기본본 변경409도 다룬다.
- [ ] 각 목적의 완료/막힘·혼란 지점·1440/1024와 키보드 증거를 남긴다. 기능 시험·전문가 UI 확인·독립 사용자 수용·실제 native 성공을 별도 결과로 기록하고 미실시 항목을 완료 처리하지 않는다.
