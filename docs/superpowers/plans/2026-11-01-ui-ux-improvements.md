# 사용자 작업 흐름을 완성하는 UI 개선 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 실행 방식이 별도로 정해지면 그 방식을 따른다.

**Goal:** 녹화 준비·설정·검증 편집·회귀 대상 관리에서 사용자가 현재 상태를 이해하고 입력 손실 없이 작업을 완료하게 한다.

**Architecture:** 기존 FastAPI/Jinja/일반 JavaScript와 케이스 버전·녹화·승인 계약을 재사용한다. 공통 저장 상태와 이동 보호를 먼저 정하고, 화면별 입력을 기존 API 모델에 연결한다. UI로 해결되지 않는 중복 저장·조회 부족만 해당 도메인의 작은 서버 보완으로 분리한다.

**Tech Stack:** Python/FastAPI, Jinja2, 기존 static CSS/JavaScript, SQLite, pytest. 프런트 프레임워크 전환이나 새 의존성 설치를 전제하지 않는다.

**Spec:** [관찰 보고서](../../validation/reviews/2026-11-01-ui-ux-review.md), [UI_SPEC](../../../UI_SPEC.md), [CONTRACTS](../../execution/CONTRACTS.md), [DATA_DESIGN](../../../DATA_DESIGN.md).

작성일: 2026-11-01. 상태: **수정 계획 추가 완료·구현 미착수**. 이전 검토의 관찰 시점은 보고서에 그대로 남긴다. 이번 소스 대조 시 W18-02~05/W19-01~02 인계와 viewer·검토·승인 코드가 추가되어 있었고, 큐는 완료86/163·Current W19-03이었다. 이 기능을 새로 만들라는 계획이 아니라 기존 기능에 사용자 동선을 연결·보완하는 계획이다. 추가 기능의 실제 브라우저 수용은 아직 확인하지 않았다. NEXT_ACTION/기존 W 완료 상태는 변경하지 않는다.

## 선택한 개선 방식

세 가지 접근을 비교했다. 화면별 오류만 고치면 저장·이동·상태 표시가 계속 달라진다. 프런트를 전면 교체하면 현재 도메인과 증거·승인 구현을 다시 연결하는 비용이 크다. **이번 계획의 제안은 기존 화면·계약을 유지하면서 공통 작업 규칙을 만든 뒤 사용자 여정별로 완성하는 방식**이다. 사용자의 확정 요구는 기존 케이스 통합·AI 호출 정책이며, 아래 레이아웃·단위 구성은 그 요구를 실현하기 위한 설계 제안이다.

## Global Constraints

- 검증 정의·설정·녹화 기록의 관리 단위는 케이스 하나다. TC는 선택 참조다.
- 녹화 시 AI를 호출하고, 반복 테스트는 저장된 코드/동작을 기본 재생한다. 필요한 검증과 명시 ON인 예외 healing만 별도 정책으로 호출한다. 기본 healing OFF·시범 healing OFF를 유지한다.
- 실패·중단 기록도 먼저 보존한다. 사람 승인은 녹화 완료·저장 후 수행하며 저장을 막는 절차로 바꾸지 않는다.
- 재녹화는 새 초안이다. 기존 승인본·REC·과거 결과를 덮지 않는다. 정확한 버전·시도·증거 소유 관계를 유지한다.
- 화면 방문·기기 선택·초안 저장·사전 검사만으로 native 실행·설치·예약·AI 호출을 시작하지 않는다. 시작은 명시 동작과 서버 재검사를 통과해야 한다.
- 세션·CSRF·project scope·기존 receipt/CAS 검사를 유지한다. UI 숨김이나 disabled만으로 권한을 통제하지 않는다.
- 비밀 원문을 URL·local/sessionStorage·증거·로그에 쓰지 않는다. 기본 키 마스킹과 서버의 비밀 보호를 구분한다.
- 모든 사용자 입력 화면에 label·오류 연결·저장 상태·중복 제출 방지·이동 보호를 해당 카드에서 같이 구현한다. 접근성을 마지막 카드까지 미루지 않는다.
- 1440px/1024px를 수용 기준으로 삼는다. native/VM 대기가 독립적인 문서·UI·결정적 시험을 막지 않는다. 실제 환경 미검증을 core/UI 완료 증거로 대체하지 않는다.

## 이슈별 수정 계획

| 이슈 | 개선 후 사용자가 할 수 있는 일 | 상세 계획 / 작업 단위 |
|---|---|---|
| UX-01 녹화 진입 | 기기를 고르고 정보·검증 내용을 입력해 초안을 저장하고 준비 상태 확인 | [녹화 준비](ui-ux-2026-11-01/01-recording-and-save.md#ux-01), R01~R04 |
| UX-02 저장 실패 | 환경/데이터를 작성·재사용하고 오류를 화면 안에서 수정 | [환경·데이터](ui-ux-2026-11-01/01-recording-and-save.md#ux-02), S01~S04 |
| UX-03 입력 손실 | 저장·버리기·계속 편집을 선택하고 의도한 위치로 이동 | [이동 보호](ui-ux-2026-11-01/02-navigation-and-editing.md#ux-03), E01~E02 |
| UX-04 검색 이탈 | 현재 프로젝트의 실제 케이스를 검색하고 목록 맥락으로 복귀 | [검색](ui-ux-2026-11-01/02-navigation-and-editing.md#ux-04), N01 |
| UX-05 JSON 편집 | 자연어·조건·변수·기대 결과를 사람이 읽는 형식으로 수정 | [검증 편집](ui-ux-2026-11-01/02-navigation-and-editing.md#ux-05), E03~E04 |
| UX-06 탐색 혼란 | 프로젝트와 케이스의 현재 위치·상태·다음 행동을 파악 | [탐색·케이스 작업 공간](ui-ux-2026-11-01/02-navigation-and-editing.md#ux-06), N02~N06 |
| UX-07 대량 관리 | 현재 범위·선택 대상을 확인하고 회귀 대상을 선별 | [목록 관리](ui-ux-2026-11-01/03-management-and-accessibility.md#ux-07), M01~M03 |
| UX-08 배치·가독성 | 작업 단계·핵심 입력·오류·버튼을 두 해상도에서 읽고 조작 | [화면 구성](ui-ux-2026-11-01/03-management-and-accessibility.md#ux-08), V01~V02 |
| UX-09 연결 혼란 | PC 연결과 기기 준비 상태를 구별하고 다음 조치를 선택 | [연결 안내](ui-ux-2026-11-01/01-recording-and-save.md#ux-09), D01~D02 |
| UX-10 AI 설정 | 어떤 호출에 비용이 생기고 healing이 허용되는지 이해하고 설정 | [AI·키·정책](ui-ux-2026-11-01/03-management-and-accessibility.md#ux-10), A01~A02 |
| UX-11 접근성 | 키보드로 대상을 구별하고 입력·오류 수정·저장을 완료 | [접근성 수용](ui-ux-2026-11-01/03-management-and-accessibility.md#ux-11), K01~K02 |

## 공통 파일과 인터페이스 경계

신규 파일·인터페이스명은 **계획상의 제안**이다. 구현 시작 시 동등한 기존 구현이 있으면 재사용하고 이름 차이를 카드 인계에 기록한다. 기존 내부 모델의 이름이나 URL을 임의로 바꾸지 않는다.

파일 표기의 `api/`, `domain/`, `store/`, `web/`는 `src/aiqa/` 아래이며 `templates/`, `static/`는 `src/aiqa/web/` 아래다. `tests/`, `migrations/`, `docs/`는 저장소 루트 기준이다. 이 축약은3개 상세 문서에도 동일하게 적용한다.

| 소유 단위 | 파일 | 책임·다른 단위에 제공할 계약 |
|---|---|---|
| S01 | 새 `src/aiqa/web/static/form_state.js`, `templates/components/form_feedback.html` | `aiqaForms.register(form, {read, persist, onSaved, saveBeforeLeave})`가 `save(): Promise<boolean>`, `isDirty(): boolean`, `markSaved()`를 반환. `read()`는 현재 값을 직렬화하고 `persist(payload, requestKey)`는 `aiqaRequest`를 이용. true는 저장 확인 후에만 반환. `saveBeforeLeave`는 일반 편집에서 true, 의견·반려 사유처럼 명시 제출이 필요한 입력에서는 false |
| E01 | 기존 `navigation.js`, `api.js`, 새 `components/unsaved_dialog.html` | `aiqaNavigate(url): Promise<void>`가 등록 폼의 저장/버리기/취소를 처리한 뒤 기존 프로젝트 세션 부트스트랩과 이동을 호출. 두 스크립트의 클릭 가로채기를 한 흐름으로 통합 |
| S02 | 기존 `api/resources.py`, domain 환경·데이터, 필요한 새 receipt 모듈/마이그레이션 | 같은 actor/project/operation/key와 같은 정규화 payload는 같은 저장 응답. 다른 payload는409. commit과 receipt를 원자 처리. job enqueue receipt를 그대로 가져다 자산 저장으로 위장하지 않음 |
| R01~04 | 기존 `recording_setup.html`, 새 `recording_setup.js`, `api/resources.py`, `api/catalog.py` | 화면 state는 `case_id`, `expected_head`, `step`, `target_kind`, `resource_id`, 정확한 환경/데이터 revision과 definition/settings. 임시 UI state와 저장된 케이스 버전을 구분 |
| E03~04 | 기존 `case_definition.html`, `definition_editor.js`, `contracts/cases.py` | 원 snapshot을 복사해 사용자가 바꾼 필드만 갱신. 검증 단계 ID와 녹화 action ID를 구분. 새 case version과 `expected_head` 충돌 규칙 유지 |
| N02 / V01 | 기존 `base.html`, `web/routes.py`, 각 page context / `app.css` | 서버가 검증한 project/case context와 active navigation을 렌더. 데이터 없는 부분을 임의 ‘연결됨/승인/통과’로 채우지 않음 |
| M01~03 | 기존 `api/cases.py`, `domain/catalog.py`, `cases.html`, `case_list.js`, `case_bulk.js` | 목록 query와 선택 상태를 분리. cursor 기반 이전/다음·전체 건수는 실제 서버 조회로 제공. 화면에서3,000건을 모두 내려받아 정렬하지 않음 |

공통 저장 상태는 `idle → dirty → saving → saved / invalid / conflict / forbidden / unknown`이다. `unknown`은 네트워크 단절로 commit 여부가 불명확한 상태다. 성공 표시나 새 key 재전송으로 바꾸지 않는다. 사용자가 값을 바꾸면 기존 재시도와 구분하고 새 제출 key를 만든다. 에러 코드·필드·request_id는 공통 도구가 해석하되 원시 오류 본문으로 화면을 대체하지 않는다. 키 입력은 에러 후에도 ‘안전을 위해 비웠습니다’라고 정확히 안내한다.

의견·반려 사유의 `saveBeforeLeave:false`에서는 dialog의 저장 후 이동을 제공하지 않고 ‘돌아가서 제출 / 버리고 이동 / 계속 편집’으로 안내한다. 이동 보호가 승인·반려를 암묵적으로 실행하지 않는다.

## 실행 순서와 차단 처리

각 항목은 독립 확인 가능한 단위다. 다음 순서는 권장 의존 순서이며 실행 큐의 Current를 변경하는 명령이 아니다.

1. S01 공통 폼 상태 → S02 자산 저장 재시도 보장. E01 이동 보호는 S01 이후 별도로 진행 가능.
2. S03 환경 편집 / S04 데이터 편집 / N01 검색. 세 작업은 공통 규칙을 소비하되 서로의 완료를 기다릴 필요가 없다.
3. R01 진입·기기 선택 → R02 Web 초안 → R03 Android·전환 → R04 시작 준비. D01은 R01과, D02는 기존 preview와 연결한다.
4. E02 모든 편집 화면 보호 / E03 정의 기본 편집 → E04 단계·검증 편집. N02 공통 탐색 → N03 케이스 작업 공간 → N04 시범 준비 / N05 기존 사후 검토 연결 / N06 재녹화 흐름을 각각 독립 수용한다.
5. M01 목록 모델 → M02 이동·선택 → M03 대량 수용. A01 역할·키 → A02 유효 정책·비용 안내.
6. V01 공통 화면 구성은 앞 카드에 필요한 스타일을 공급하며 진행한다. V02 두 폭 전체 여정 수용은 연결된 화면을 확인한다. K01은 각 카드의 필수 기준, K02는 마지막 통합 수용이다.

VM·키·실기기 미준비는 R04의 실제 녹화/시범 성공과 D02의 실제 캡처 수용만 막는다. 화면 입력·초안 저장·차단 이유·합성 근거 viewer는 계속 검증한다. S02가 미완료이면 S03/S04의 일반 입력·조회 구현은 진행할 수 있으나 ‘안전한 재시도 완료’는 열어 둔다. 미지원 Android 앱 선택은 W11-04/06을 참조하고 기본 빌드 등록/상태 표시와 분리한다.

## Review Focus

다음 다섯 조건은 각 소유 카드의 수용 시험에 포함했다.

| 조건 | 기대 행동 | 소유 단위 |
|---|---|---|
| commit 후 응답 유실 | 저장 여부 확인·동일 key 응답 재사용, 중복 revision0 | S02~S04 |
| 수정 중 탭/프로젝트 이동·409 | 입력 유지·이동 취소·서버본 비교, 조용한 덮어쓰기0 | E01~02, E03 |
| Web↔Android 전환·연결 끊김 | 공통 입력 보존·전용 필드 정리·초안 허용·시작 재검사 | R03~04, D01 |
| 선택 후 필터/프로젝트 변경 | 선택 범위 명시·확인 없는 다른 범위 실행0 | M02~03, N01 |
| 검토 근거/승인본이 바뀌거나 만료 | 정확한 버전/시도 유지·승인 충돌 안내·새 초안과 기본본 분리 | N05~06, V02, K02 |

## 카드별 종료와 증거

- 상태는 모두 `planned`로 시작한다. 구현자는 현재 카드와 이 문서의 공통 제약, 필요한 소유 계약만 읽는다.
- 각 카드의 실패 재현 또는 요구 동작 확인 → 변경 → 지정 시험 → 실제 브라우저 조작 → 인계 순서를 지킨다. 모든 카드에 같은 형식의 형식적 테스트를 늘리지 말고 상태·경계·동작을 검증한다.
- 제안 시험 파일은 아래 상세 계획에 새 파일로 명시했다. Python 검증 명령은 `.\.venv\Scripts\python.exe -m pytest <카드의 시험 파일> -q`. 종료 코드0과 지정 시나리오 통과가 필요하다. 시험 파일이 없으면 먼저 작성하고 존재하지 않는 명령을 통과 증거로 남기지 않는다.
- 브라우저 수용은 실제 제품 라우트·격리 런타임·합성 데이터로 수행한다. API 직접 호출만으로 화면 조작 통과를 대신하지 않는다. 1440/1024, 키보드, before/after·오류·저장 후 재조회 근거를 `docs/validation/ux/<단위ID>.md`에 남긴다.
- API/DB/사용자 의미 변경이 필요한 단위는 같은 작업에서 소유 계약·UI_SPEC·TASK_INDEX 동기화 범위를 인계한다. 계획상의 새 receipt/조회 확장을 이미 지원하는 것으로 표시하지 않는다.
- 진행 큐 편입 시 기존 ID와 중복을 확인해 신규 보완 ID를 명시적으로 연결한다. 문서 추가 자체로 제품 완료 수를 올리지 않는다.

## 계획 자체 검증

- [x] UX-01~11 모두 상세 계획·사용자 변화·작업 단위·판정 기준으로 연결했다.
- [x] 하나의 카드가 다른 카드의 인터페이스를 중복 정의하지 않도록 공통 규칙을 이 문서에 모았다.
- [x] 구현된 viewer/승인과 실제 native 미수용을 구분했다.
- [x] 헤더 검사와 내구성 있는 멱등 저장, 저장과 승인, 검증 정의 단계와 기록 action을 구분했다.
- [x] 미구현 검색 기능·표시 ID·비용 계측을 화면만으로 가짜 구현하지 않도록 서버 보완/미지원 상태를 명시했다.

문서 링크·11개 이슈 연결·29개 단위 ID·필수 계획 구성 확인: [계획 검증 기록](../../validation/reviews/ui-2026-11-01/plan-verification.json). 이 기록은 문서 검증이며 제품 구현/시험 통과 증거가 아니다.
