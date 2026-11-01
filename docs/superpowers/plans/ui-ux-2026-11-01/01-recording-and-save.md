# 녹화 준비·저장·기기 연결 개선 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자가 기기·정보·검증 내용을 입력해 초안을 남기고, 저장 실패나 연결 문제를 이해하며 작업을 이어 간다.
**Architecture:** 기존 케이스 버전·환경/데이터 revision·녹화 접수 API를 공통 폼 상태로 연결한다. native 준비와 초안 작성을 분리한다.
**Tech Stack:** 기존 FastAPI/Jinja/JavaScript/SQLite/pytest.
**Spec / Global Constraints / Review Focus:** [전체 계획](../2026-11-01-ui-ux-improvements.md)의 공통 제약과 인터페이스를 그대로 적용한다. `web/...`, `api/...`, `domain/...`, `store/...` 축약은 `src/aiqa/` 아래이며 migration/test는 루트 기준이다. 모든 단위 상태는 `planned`다.

<a id="ux-01"></a>
## UX-01 — 시작 링크를 넘어 녹화 준비를 완료하는 흐름

**바꿀 상황:** 사용자는 기기 선택 안내를 읽고 멈춘다. 개선 후에는 `기기 선택 → 대상 정보 → 검증 내용 → 저장·준비 확인`으로 진행하고, 실제 실행이 안 되는 상태에서도 작성한 내용을 남긴다.

**화면 결정:** 위에는 현재 단계와 케이스명, 본문에는 해당 단계의 입력, 아래에는 이전·초안 저장·다음을 둔다. 마지막에는 선택 기기/환경/데이터·자연어 요약과 준비 검사 결과를 보여 준다. 기대 결과가 부족한 초안도 저장 가능하며, ‘저장 불가’와 ‘아직 실행 불가’를 혼동시키지 않는다. step만 바꿔 입력을 잃는 링크 이동은 사용하지 않는다.

### R01 — 진입·기기 선택 통합

**파일:** 수정 `src/aiqa/api/catalog.py`, `api/resources.py`, `web/templates/overview.html`, `cases.html`, `environments.html`, `recording_setup.html`. 새 `web/static/recording_setup.js`, `tests/acceptance/test_ux_recording_entry.py`.
**입출력:** 기존 `/recordings/new`는 같은 프로젝트의 `/recordings/wizard`로 안내/리다이렉트한다. 선택 후보는 query `resource_id`로 넘기되 서버가 project 소유와 target을 검증한 뒤 초기값으로 사용한다. query에 비밀/전체 정의를 싣지 않는다. 선택 결과는 공통 draft state의 `resource_id/target_kind`로 R02에 전달한다.

- [ ] 개요·케이스·자원별 진입과 foreign resource 요청의 실패 재현을 먼저 만든다. 올바른 세션에서도 foreign resource는404, 아무 자원도 없으면 선택 방법을 안내한다.
- [ ] 실제 자원을 radio 카드로 선택하고 선택명/상태를 표시한다. 오프라인도 준비 대상으로 고를 수 있지만 실행 가능처럼 표시하지 않는다. 이전/다음은 경계와 현재 단계를 반영한다.
- [ ] 시험 파일을 실행하고 실제 세 진입점·기기 변경·빈 목록을 조작한다. 방문/선택만으로 REC/job/AI 호출이 생기지 않는지 확인한다.
- [ ] `docs/validation/ux/R01.md`에 경로·선택 유지·빈/오프라인 캡처와 미구현 범위를 기록한다.

### R02 — Web 입력·초안 저장·재진입

**선행:** R01, S01, S02의 receipt 기반. **파일:** 수정 위 wizard 파일, `api/cases.py`, `domain/versions.py`의 케이스 생성 경계; 새 `tests/integration/test_ux_recording_draft.py`.
**입출력:** `POST /api/v1/projects/{p}/cases`로 이름을 만들고 `/cases/{c}/versions`로 `CaseRevisionInput`에 맞는 definition/settings·`expected_head`를 저장한다. 두 요청은 하나의 UI 저장 과정이다. 케이스 생성 후 버전 저장 실패 시 기존 `case_id`를 유지해 재제출하고 빈 케이스를 반복 생성하지 않는다. 서버의 wizard 정리 함수가 resource를 요구하는 현 계약을 존중한다.

- [ ] 이름·Web URL·환경 revision·데이터 revision·reset/한도·자연어/기대 결과를 입력한다. 환경/데이터는 같은 프로젝트의 정확한 저장본을 선택하며 없으면 생성 경로와 되돌아올 위치를 제공한다.
- [ ] 공통 form controller로 저장 중/성공/부분 실패를 보여 주고, 성공한 version ID를 유지한다. 이름만 생성됐으면 ‘케이스 생성됨, 내용 저장 필요’로 정확히 표시한다. 기본 재생 mode는 `recorded_replay`다.
- [ ] 케이스 생성도 헤더 검사만으로 중복 방지가 되지 않는 현재 경로를 S02의 receipt 기반으로 보완한다. 생성 응답 유실 후 같은 key/body로 같은 case ID를 돌려받아 내용 저장을 이어 간다. 이미 저장한 version의 응답 유실도 새 version을 만들지 않고 확인/복구한다.
- [ ] 정상 저장→재진입, 기대 결과 공란 저장, 첫/두 번째 요청 응답 유실과 두 번째 요청 실패 후 재개, 다른 탭 수정409의 시험을 추가·실행한다. UI에서 TC 없이 작성·저장·재조회한다.
- [ ] `R02.md`에 입력→저장본 비교, 실패 복구·case/version 행 수 증거를 남긴다. 서버 CAS 실패는 성공 재시도 receipt와 구별한다.

### R03 — Android 입력과 대상 변경의 영향

**선행:** R02. **파일:** 수정 wizard 파일·`api/resources.py:apply_recording_wizard`; 위 draft 시험에 시나리오 추가.
**입출력:** 현재 서버는 Web 전환 시 `android_package/build/account_ref`, Android 전환 시 `web_url`을 비운다. 이 규칙을 명시하고 UI가 숨긴 전용 값을 이전 대상 설정으로 다시 보내지 않는다.

- [ ] Web↔Android 전환 전에 ‘URL 설정이 해제됩니다’ 등 영향만 알리고 자연어·목적·공통 한도·데이터를 유지한다. 선택 기기가 대상과 다르면 재선택을 요구한다.
- [ ] Android 패키지·등록 빌드·계정 참조를 사용자 선택으로 제공한다. W11-04/06이 미완료면 실제 설치 앱 열거/설치를 흉내 내지 말고 지원 중인 등록 빌드·명시 패키지 입력 범위로 제한한다. 계정은 secret ref 선택이며 비밀번호 직접 보관을 추가하지 않는다.
- [ ] 두 방향 전환·미지원 빌드·다른 프로젝트 ref·연결 해제 후 초안 저장을 시험하고, 동일 입력의 재조회에서 공통값 보존/전용값 제거를 확인한다.
- [ ] `R03.md`에 지원/차단 범위와 Web/Android 각각의 조작 증거를 남긴다.

### R04 — 준비 검사와 시작을 구별

**선행:** R02, 해당 target의 R03. **파일:** 수정 wizard JS/템플릿·`api/recordings.py`, 기존 W16-03 시험; 새 `tests/acceptance/test_ux_recording_preflight.py`.
**입출력:** 기존 W16-03의 시작 검사/접수 계약을 사용하고 `POST /api/v1/projects/{p}/recordings`만 명시 시작으로 연결한다. preview의 현재 hash와 입력 version·선택 revision을 고정하고 enqueue 시 서버가 자원·비용·모델·scope를 재검사한다.

- [ ] 준비 검사 결과를 ‘준비됨 / 수정 필요 / 외부 준비 대기’와 각 원인·해결 링크로 표시한다. 저장 성공이 녹화 성공 또는 시작 예약을 뜻하지 않게 한다.
- [ ] ‘AI 녹화 시작’은 준비 결과와 호출 정책을 확인한 뒤 접수한다. 점유는 해당 작업/대기 안내, 필수 binding 없음은 모델 설정 복귀로 연결한다. 초안 저장은 별도 유지한다.
- [ ] 준비 후 기기 busy 전환·내용 변경·중복 클릭·키 없음·예산 초과를 시험한다. preview가 lease/REC를 만들지 않고 접수 재전송이 같은 REC/job으로 수렴함을 확인한다.
- [ ] `R04.md`에 core/UI와 실제 환경 성공을 분리 기록한다. 실기기 대기 중에도 오류·차단 흐름을 완료할 수 있다.

<a id="ux-02"></a>
## UX-02 — 실패 없는 제출보다 재사용·복구 가능한 설정 작성

**바꿀 상황:** 현재는 저장 버튼이 원시 JSON 오류로 끝난다. 개선 후 환경은 재사용 가능한 프로필이고 데이터는 반복 실행할 행/열 표다. 사용자는 잘못된 칸을 고친 뒤 같은 화면에서 저장하고 정확한 revision을 케이스에 연결한다.

### S01 — 공통 폼 상태·오류·저장 계약

**파일:** 새 `web/static/form_state.js`, `web/templates/components/form_feedback.html`, `tests/acceptance/test_ux_form_feedback.py`; 수정 `web/static/api.js`의 필요한 연결과 `base.html` script 등록. 도메인별 serializer는 해당 화면 파일에 둔다.
**입출력:** 전체 계획의 `aiqaForms.register`를 구현한다. `persist`는 기존 `aiqaRequest`를 호출하며 raw `fetch`로 세션 경계를 복제하지 않는다. request key는 같은 미확인 제출을 재시도할 때만 유지한다.

- [ ] 입력 오류422·저장 충돌409·권한403·네트워크 unknown의 상태와 버튼 규칙을 먼저 정의한다. 오류 요약→해당 필드, `aria-invalid/describedby`, live status, 첫 오류 focus를 제공한다.
- [ ] saving에는 중복 dispatch를 막고 성공 ACK 뒤만 `markSaved()`한다. known validation 실패는 수정 가능, unknown은 저장 여부 확인/동일 요청 재시도를 제공하되 자동 mutation 반복은 하지 않는다.
- [ ] 응답 오류 형식이 필드 정보를 주지 않으면 안전한 요약과 request_id를 표시한다. 필요한 상세 field path 추가는 S03/S04가 서버 parser/domain과 같이 소유한다. 원문 payload/비밀을 오류에 출력하지 않는다.
- [ ] Python 응답 계약 시험과 실제 브라우저 상태 전이를 확인해 `S01.md`에 남긴다. DOM 문자열 검사만으로 버튼 동작 완료를 선언하지 않는다.

### S02 — 환경·데이터 저장의 중복/응답 유실 보완

**파일:** 수정 `api/resources.py`의 `_save_environment/_save_dataset`, `domain/environments.py`, `domain/datasets.py`; 필요 시 새 `store/asset_receipts.py`, `migrations/versions/<다음번호>_asset_receipts.py`; 새 `tests/integration/test_ux_asset_save_receipts.py`. 번호는 구현 시 실제 마지막 migration 뒤로 정한다.
**입출력:** 현재 소스에는 헤더 존재 검사 뒤 매번 새 revision을 만드는 경로가 있다. 공통 저장 receipt가 없다면 `(actor,project,operation,key)`+정규화 payload digest·대상 ID·응답을 원자 저장한다. operation에는 생성/개정과 자산 종류를 구분한다. 기존 transaction/receipt를 먼저 대조하고 동등 기능은 재사용한다.

- [ ] 같은 body/key 두 번, 같은 key/다른 body, commit 직후 응답 유실, 재시작 후 재요청, foreign project를 재현하는 시험을 작성한다.
- [ ] 새 revision과 receipt가 같은 transaction에서 commit/rollback되게 한다. 동시 key 경합도 같은 응답으로 수렴하며 다른 body는409다. 비밀은 ref와 안전한 digest만 다룬다.
- [ ] receipt 재조회가 필요하면 scope 검사된 조회 계약을 C03/해당 자산 계약에 먼저 명시하고 구현한다. 지원 전에는 ‘저장 여부 확인 가능’이라고 UI에 쓰지 않는다.
- [ ] 지정 시험을 실행하고 DB 행 수·반환 revision·rollback을 확인한다. `S02.md`와 변경한 소유 계약에 근거를 기록한다. 승인/queue semantics를 자산 저장에 임의 적용하지 않는다.

### S03 — 환경을 대상별 재사용 프로필로 편집

**선행:** S01. 재시도 수용은 S02. **파일:** 수정 `web/templates/environment_editor.html`, `environments.html`, `api/resources.py`; 새 `web/static/environment_editor.js`, `tests/acceptance/test_ux_environment_editor.py`.
**입출력:** 생성 `POST /api/v1/projects/{p}/environments`, 개정 `/environments/{id}/revisions`, 조회 `/environments/{id}/revisions/{revision}`. payload는 `name,target_kind,allowlist:list,viewport:{width:int,height:int},locale,reset_policy,limits:{budget:str,currency:str,timeout_seconds:int,max_actions:int}`와 지원 profile 값이다. 현재 단일 텍스트 필드값을 그대로 보내지 않는다.

- [ ] 기본(이름·대상·앱/URL) / 실행 조건 / 한도로 그룹화한다. 고정 DPR1·Asia/Seoul·portrait는 현재 지원 범위에 맞춰 읽기 전용 설명으로 표시한다. 지원하지 않는 자유 입력을 허용하지 않는다.
- [ ] Web URL·허용 origin 목록과 Android 패키지·setup/reset/cleanup·계정 ref를 구분한다. budgets/currency 등 필수 API 값 누락도 해결하고 입력 단위를 표시한다. 기본값은 기존 실행 계약에서 가져온다.
- [ ] 저장 결과에 프로필명·revision·‘녹화 준비로 돌아가기’를 제공하고 선택한 revision을 전달한다. 프로필을 개정해도 기존 케이스/RUN의 정확한 revision을 자동 추종하지 않는다.
- [ ] 정상 저장·재조회·유효하지 않은 URL/숫자·hidden 전용필드·응답 유실 재시도를 시험·조작한다. 서버 field error는 `viewport.width` 등 안정된 path로 대응한다. `S03.md`에 작성→재사용 전체 경로를 남긴다.

### S04 — 데이터를 행/열 단위로 작성·연결

**선행:** S01. 재시도 수용은 S02. **파일:** 수정 `web/templates/datasets.html`, `api/datasets.py`, 필요한 `api/resources.py`; 새 `web/static/dataset_editor.js`, `tests/acceptance/test_ux_dataset_editor.py`.
**입출력:** 기존 생성/개정 API의 `row_schema:{columns:[{name,type}]}`, `rows:[{id,values}]`, 선택 `case_id/secret_ref`를 사용한다. 타입은 실제 지원하는 `string/int/bool`만 제공하며 문자열 숫자/불리언을 잘못 보내지 않는다. 목록/특정 version 조회 계약을 하나의 화면 adapter로 정리한다.

- [ ] 열 추가·이름/타입·행 추가/삭제·cell 입력을 표로 제공하고 안정된 row ID는 자동 생성한다. case는 이름 검색 선택, secret은 허용 ref 선택으로 제공한다. 필수 연결로 바꾸지 않는다.
- [ ] 중복 열/행 ID·필수 cell·int/bool 타입 오류를 해당 칸과 서버 field path에 연결한다. 생성/수정 모드를 구별하고 새 revision의 변경 행을 표시한다.
- [ ] 저장 성공 후 데이터명·revision·행 수·케이스 연결/복귀를 안내한다. 기존 실행의 data snapshot을 바꾸지 않는다.
- [ ] 다중 행·타입 변경 시 값 처리·열 삭제 영향·외부 case/ref 거부·오류 수정·재시작 재조회·응답 유실을 검증해 `S04.md`에 남긴다. CSV 가져오기는 별도 계약이 없으면 추가하지 않는다.

<a id="ux-09"></a>
## UX-09 — 연결 정보를 다음 행동으로 해석

**바꿀 상황:** PC 연결됨과 기기 오프라인이 함께 보이고 같은 녹화 링크가 반복된다. 개선 후 사용자는 어느 연결이 문제인지, 어떤 조치가 필요한지, 지금 가능한 작업이 무엇인지 안다.

### D01 — 연결 상태별 행동·선택 유지

**선행:** R01. **파일:** 수정 `environments.html`, `components/connection.html`, `components/device_preview.html`, `api/resources.py`, `base.html`; 새 `tests/acceptance/test_ux_device_guidance.py`.
**입출력:** inventory의 `offline/unauthorized/busy/ready`와 실제 PC 중계 상태를 각각 표시한다. unknown/stale는 QA 판정이 아니라 관찰 상태다. resource ID 전달은 R01 계약을 재사용한다.

- [ ] offline은 연결 방법+‘이 기기로 초안 준비’, unauthorized는 Android 승인 방법, busy는 점유 작업/지원하는 대기 안내, ready는 ‘이 기기로 녹화 준비’를 제공한다. 준비 링크 자체가 실행을 뜻하지 않게 한다.
- [ ] 관찰이 없는 항목은 ‘확인 전’으로 두고 임의 연결됨을 제거한다. 마지막 시각은 현지 시간·오래됨 표시로 바꾸며 진단 상세는 접는다. PC·기기 상태의 차이를 설명한다.
- [ ] 네 상태·unknown·다른 프로젝트·연결 변화 동안 선택 유지와 시작 재검사를 검증해 `D01.md`에 남긴다. VM 부재가 UI 상태별 시험을 막지 않는다.

### D02 — 최근 관찰 화면의 의미·부재 복구

**선행:** 기존 preview API. **파일:** 수정 `components/device_preview.html`, `api/resources.py`, 필요 시 새 `web/static/device_preview.js`; 위 device 시험 확장.

- [ ] 기존 `/api/v1/resources/{id}/preview?project_id=...`가 허용한 정제 artifact만 표시한다. 캡처 시각·Web/Android·관찰 상태를 제목과 함께 보여 준다.
- [ ] 없음/만료/권한 없음/전송 대기를 구별하고 연결 진단·새 관찰 등 실제 지원되는 다음 행동만 제공한다. ‘실시간 화면’·클릭 제어로 오해시키지 않는다.
- [ ] 합성 캡처의 소유 검사·만료·0건·1024 배치를 검증한다. 실제 장치 캡처 대조는 별도 환경 증거로 남기고 `D02.md`에 그 대기를 분리 기록한다.
