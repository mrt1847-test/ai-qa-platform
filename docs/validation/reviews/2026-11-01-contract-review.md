# Cursor 구현 계약 검토 — 2026-11-01

> 이 문서는 수정 전의 역사적 검토다. 현재 상태와 검증은 [수정 결과](2026-11-01-remediation-result.md)를 따른다. 아래 source line/재현 출력은 검토 당시 기준이며 현재 코드에 대한 미해결 목록이 아니다.

판정: **완료 표시를 그대로 신뢰하고 다음 기능의 기반으로 삼기 어렵다.** 제품 앱 연결, 편집 보존, 버전 식별, 실행 중복 방지, 증거 불변성에 수정이 필요하다. 구현 전체가 무효라는 뜻은 아니다. 확인된 결함과 영향을 받는 완료 작업을 아래에 구분했다.

## 검토 범위와 실행 결과

- 검토 기준: 현재 작업 트리의 DATA_DESIGN/UI_SPEC, 실행 CONTRACTS C00~C14, 해당 작업 카드와 인계. HEAD는 `master / 0826522`. 제품 구현 대부분이 untracked이므로 커밋 diff 외에 현재 파일도 직접 읽었다.
- TASK_INDEX 상태: 상세 163개 중 complete 53개, blocked 1개, not_started 109개. NEXT_ACTION Current는 W15-01이다.
- 제품 소스·기존 계획·완료 상태는 수정하지 않았다. 검토 산출물만 추가했다. 사용자 런타임 DB·실제 비밀을 열거나 초기화하지 않았다.
- 자동 시험: `.\.venv\Scripts\python.exe -m pytest -q --deselect tests/integration/test_w01.py::test_w01_02`
- 결과: **50 passed, 3 failed, 1 deselected / 26.14초**. 제외한 W01-02는 VM 실환경 게이트이며 PASS로 계산하지 않는다.
- 실패 3개를 같은 이름으로 재실행해 모두 재현했다. 실패는 아래 V01의 시험 fixture 문제다. 이 결과를 verification_digest 구현의 좌표 처리 결함으로 해석하면 안 된다.
- 별도 부정 검증: 새 메모리 SQLite에 실제 migration 적용, 임시 파일, 실제 `create_app` ASGI 라우팅, HTTP handler/도메인 호출, 합성 PNG, 테스트 command/provider를 사용했다. 기기 조작·모델 호출·설치·배포는 하지 않았다.
- 이후 미착수 W11/W15 이후의 native/model/package/replay/review 기능이 아직 없다는 사실 자체를 결함으로 세지 않았다. 이번 지적은 **이미 완료 처리한 범위의 계약 위반**이다.

P1은 후속 구현의 기반·사용자 데이터·실행 안전성에 영향을 주어 먼저 수정해야 하는 항목이다. P2도 관련 작업의 완료 수용 전에 수정해야 한다.

## 확정 발견 사항

### R01 · P1 · 버전 content_hash에 설정과 녹화 절차가 빠짐

- 위치: [src/aiqa/domain/versions.py:298](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/domain/versions.py:298>), `:329`, `:735`.
- 관련: W05-01/02, C02/C07, DATA_DESIGN의 불변 버전 식별.
- `persist_projection`이 정의만 해시하고, 저장 서비스가 그 값을 case_versions.content_hash로 사용한다. settings_json과 recorded_steps_json은 별도로 저장된다.
- 재현: 같은 정의를 Web 설정으로 저장한 뒤 Android/package와 다른 recorded_steps로 새 버전을 저장했다. 두 버전의 content_hash가 같았다. 서로 다른 실행 입력을 같은 hash로 취급하므로 이후 source/trial/approval 비교의 전제가 깨진다.
- 수용 조건: 정의·설정·녹화 절차 및 계약상 포함할 실행 snapshot을 정식 hash body에 포함한다. 설정/절차 변경은 hash를 바꾸고, 이름·태그·비밀 실제 값 등 제외 대상은 바꾸지 않는지 검사한다. 기존 definition projection hash와 버전 전체 hash를 혼동하지 않는다.

### R02 · P1 · 스텝 편집이 Android 설정과 녹화 절차를 버림

- 위치: [src/aiqa/domain/versions.py:408](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/domain/versions.py:408>), 특히 `:421`.
- 관련: W10-07, W05-02, C02.
- `apply_step_edit`이 기존 설정 대신 `CaseSettings(target_kind="web")`를 만들고 recorded_steps를 전달하지 않는다.
- 재현: Android/package=`com.two` 및 녹화 절차가 있는 버전에서 스텝을 추가하면 새 버전은 Web/default 설정과 `recorded_steps=[]`가 된다. 이전 버전은 남지만 사용자가 선택하지 않은 실행 대상 변경과 정보 손실이 생긴다.
- 수용 조건: 편집하지 않은 필드를 snapshot에서 보존한다. 절차 무효화가 필요한 의미 편집은 명시한 정책으로 처리하고 대상·환경·제한·verifier·healing 설정은 유지한다.

### R03 · P1 · 정의 화면에서 목적만 수정해도 나머지 검증 정의가 지워짐

- 위치: [src/aiqa/web/templates/case_definition.html:5](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/web/templates/case_definition.html:5>), `:49`; [src/aiqa/domain/versions.py:614](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/domain/versions.py:614>).
- 관련: W10-06, C02.
- 저장된 사전조건·변수·비밀 참조·단계·기대·필수 경로가 입력에 복원되지 않는다. 화면 스크립트는 빈 입력으로 전체 정의를 다시 만들고 Web 설정과 빈 녹화 절차까지 보낸다.
- 재현: amount=100, 사전조건, 단계/check, 필수 경로가 있는 초안을 열면 변수 입력은 `{}`, 단계는 공백이다. 목적만 바꾼 화면 payload를 저장하면 201이고 새 버전의 해당 필드가 모두 빈 값으로 바뀐다.
- 수용 조건: 실제 화면 왕복에서 변경하지 않은 필드가 유지되어야 한다. 여러 단계·final_expected·forbidden 경로·Android 설정을 포함해 다시 열기→목적만 수정→저장을 검증한다. R02와 별개인 화면 직렬화 문제다.

### R04 · P1 · 오래된 AI/TC 제안이 최신 편집을 덮을 수 있음

- 위치: [src/aiqa/domain/proposals.py:97](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/domain/proposals.py:97>), `:108`, `:118`.
- 관련: W06-09, C02.
- 제안 수락은 현재 head와 요청 expected_head만 비교한다. 제안의 고정 base_version_id/base_hash가 여전히 적용 가능한지 확인하지 않는다.
- 재현: v1 대상 제안을 만든 뒤 별도 편집으로 v2를 저장했다. 기존 제안을 expected_head=v2로 수락하면 성공하고 오래된 제안 정의와 v1 설정이 최신 초안이 된다.
- 수용 조건: stale base는 409 또는 명시적인 재작성/재기반 흐름으로 처리한다. head 새로고침만으로 오래된 제안의 적용 권한이 생기면 안 된다.

### R05 · P1 · 기본 제품 앱에서 프로젝트 관리와 개요 경로가 빠짐

- 위치: [src/aiqa/api/app.py:12](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/api/app.py:12>), `:46`; [src/aiqa/api/catalog.py:53](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/api/catalog.py:53>); [tests/acceptance/test_w10.py:108](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/tests/acceptance/test_w10.py:108>).
- 관련: W10-02/03, C13의 단일 제품 앱 확장.
- create_app은 install_taxonomy만 호출하고 install_catalog를 호출하지 않는다. 제품의 다른 호출부도 없다.
- 재현: 실제 create_app ASGI 라우터에서 GET `/ui/projects`, GET `/api/v1/projects`는 404다. 프로젝트 개요 API도 등록되지 않는다. 시험은 catalog를 따로 설치해 검사한다.
- W10-02 인계가 “catalog를 기본 앱에 올리지 않는다”를 보존 불변식으로 썼지만, 완료된 사용자 기능을 제품 진입점에서 사용할 수 있어야 한다는 계약과 충돌한다.
- 수용 조건: 제품 앱 factory로 실행한 서버에서 프로젝트 생성→목록→개요→케이스 이동이 동작해야 한다. 테스트에서 수동 라우터 설치로 제품 연결 누락을 가리지 않는다. 앱 생성/health가 DB를 열지 않는 조건도 함께 보존한다.

### R06 · P1 · UI mutation이 Origin/CSRF 검사를 우회함

- 위치: [src/aiqa/api/cases.py:636](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/api/cases.py:636>), `:686`, `:880`, `:1267`; [src/aiqa/api/settings.py:162](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/api/settings.py:162>); 인증 차이는 [src/aiqa/api/auth.py:144](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/api/auth.py:144>), `:173`.
- 관련: W04-03, W10-05/06/07/09/11, C01.
- UI 저장 경로는 조회용 authorize_page를 사용한다. 정식 API가 요구하는 세션 Origin 일치와 X-CSRF-Token 검사가 없다. UI JS도 이에 맞춰 토큰 없이 저장한다.
- 재현: 임시 세션 쿠키 + Idempotency-Key, 외부 Origin, CSRF 토큰 없음으로 UI 정의 저장과 기본 설정 저장은 201이다. 같은 조건의 정식 버전 API는 403이다. 이는 handler/인증 경계 재현이며 실제 브라우저 공격 성립까지 검증했다는 뜻은 아니다.
- 수용 조건: 제품의 모든 browser mutation에 같은 인증 계약을 적용하고 화면도 필요한 토큰을 전달한다. GET navigation과 mutation의 권한 검사를 구분한다.

### R07 · P1 · 실제 PNG 화면의 비밀이 정제되지 않음

- 위치: [src/aiqa/security/redaction.py:38](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/security/redaction.py:38>), `:46`, `:59`.
- 관련: W13-02/04, C05/C06.
- PNG 압축 바이트에서 secret UTF-8 문자열을 replace하는 방식이다. 화면에 그려진 문자열은 압축된 픽셀이므로 이 검사로 발견하거나 가릴 수 없다. PNG 내부 문자열 치환은 파일을 손상시킬 수도 있다.
- 재현: 합성 문자열 PIN123을 픽셀로 그린 유효 PNG를 생성했다. raw bytes에는 해당 문자열이 없고, filter_capture는 원본 PNG를 그대로 반환했다. 실제 사용자 비밀은 사용하지 않았다.
- 수용 조건: 정의한 민감 영역을 디코딩된 이미지에서 가리고 재인코딩하거나, 보장할 수 없으면 저장/전송을 차단해야 한다. 실제 PNG를 이용한 전·후 캡처 시험이 필요하다. `b"PNG secret"` 같은 가짜 bytes만으로 정제 완료를 주장하지 않는다.

### R08 · P1 · 전달 불명 동작을 같은 action으로 다시 dispatch할 수 있음

- 위치: [src/aiqa/recording/action_executor.py:131](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/recording/action_executor.py:131>), `:141`, `:155`; [src/aiqa/worker/dispatch_journal.py:44](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/worker/dispatch_journal.py:44>).
- 관련: W13-03, C04/C05.
- dispatch 전에 기존 journal 상태를 판정하지 않는다. 같은 PreparedAction을 다시 전달하면 planned/dispatch_started를 다시 기록하고 command를 호출한다. journal.states도 attempt가 아닌 action_id만으로 조회한다.
- 재현: command가 매번 TimeoutError를 내는 테스트 경계에서 같은 PreparedAction을 두 번 dispatch했다. native command 대역의 execute 호출은 2회이고 journal은 `planned→dispatch_started→unknown`을 두 번 담았다.
- 수용 조건: 안정적인 attempt/action identity로 전달 상태를 복원하고, dispatch_started 이후에는 uncertain/ACK 누락을 포함해 자동 재전송을 금지한다. 재호출·프로세스 재시작·다른 attempt의 같은 action_id도 검사한다. 현재 post_dispatch_retries 카운터가 0인 것은 중복 방지 증명이 아니다.

### R09 · P1 · lookup 중 취소된 작업이 그대로 실행되고 실행 한도도 우회함

- 위치: [src/aiqa/recording/action_executor.py:136](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/recording/action_executor.py:136>), `:145`, `:155`; [src/aiqa/worker/control.py:63](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/worker/control.py:63>).
- 관련: W09-01/02, W13-03, C04.
- 제어 검사는 lookup 이전 checkpoint 한 번뿐이다. dispatch 직전 재검사가 없고 lease margin/watchdog/action limit를 확인하는 authorize_next_action도 호출하지 않는다.
- 재현: lookup 대역이 취소 상태를 기록하고 반환하게 했다. 취소 후에도 execute가 1회 호출되며 checkpoint 호출은 1회다.
- 수용 조건: dispatch 직전의 유효 generation/취소/lease 여유/예산 검사를 실제 command 경로에 연결한다. 별도 AttemptRunner 단위 시험의 51번째 동작 차단만으로 통합 경로 완료를 판단하지 않는다.

### R10 · P1 · 새 recovery manifest가 이전 증거 파일을 덮어씀

- 위치: [src/aiqa/recording/recovery.py:134](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/recording/recovery.py:134>), `:137`, `:183`.
- 관련: W14-04, C05/C07, 증거 불변성.
- 파일 키가 recording_id/action_id에만 의존하며 wb 모드로 쓴다. 새 request_key/manifest도 같은 경로를 공유한다.
- 재현: 같은 terminal recording의 A1을 request_key=first, bytes=original로 복구한 뒤, second/replacement로 복구했다. manifest는 2개이고 첫 manifest의 source hash는 original이지만 실제 A1.png는 replacement다.
- 수용 조건: 복구마다 불변 object identity와 hash를 사용하고 기존 manifest가 가리키는 bytes를 유지한다. 동일 key/body 재전송과 새 복구 revision을 구분하고 DB 실패 시 파일 일관성도 검사한다. 기존 version/QA/approval 행이 바뀌지 않았다는 시험만으로 충분하지 않다.

### R11 · P1 · ingest ready/ACK가 증거 owner 및 typed ref를 보장하지 않음

- 위치: [migrations/versions/0020_artifact_objects.py:14](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/migrations/versions/0020_artifact_objects.py:14>), `:18`; [src/aiqa/store/evidence.py:210](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/store/evidence.py:210>), `:296`.
- 관련: W06-04, W14-02, C05/C07, DATA_DESIGN §증거 저장.
- artifact_objects.owner_id는 대상/타입 FK가 없는 문자열이다. ingest는 프로젝트/lease만 확인하고 owner 존재·동일 project/REC/ITEM/attempt 소속을 확인하지 않으며 artifact_refs도 함께 만들지 않는다.
- 확인: W14-02 시험 자체가 존재하지 않는 uuid4 owner로 ready/ACK를 받는다. FK 활성 메모리 DB에서도 임의 owner를 가진 artifact_objects 삽입이 허용된다. 정식 artifact_refs 제약이 있어도 이 별도 저장 경로에서 사용하지 않으면 보호되지 않는다.
- 수용 조건: 파일 상태와 업무 출처의 저장 원천을 확정하고, ready+typed ref를 원자적으로 확정한 후 ACK한다. 타 프로젝트의 실제 owner, 존재하지 않는 owner, 잘못된 attempt/action을 각각 거부하는 API 시험이 필요하다.

### R12 · P2 · 중복 파일 hash 경로가 잘못된 upload metadata를 검증 없이 ACK함

- 위치: [src/aiqa/store/evidence.py:192](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/store/evidence.py:192>), `:193`, `:267`.
- 관련: W14-02, C05.
- 기존 실제 body hash/length만 맞으면 declared_hash/declared_length/filename/MIME/owner 검사 이전에 기존 ready receipt를 반환한다. 예를 들어 이미 저장된 bytes와 같은 body에 잘못된 declared hash·길이·경로를 붙여도 우회한다.
- 재현: 메모리 DB에 기존 ready metadata를 넣어 dedup 분기를 분리했다. 같은 bytes에 `../invalid.exe`/잘못된 MIME/0 hash/음수 길이/다른 owner를 보내도 기존 artifact의 ready=True, acked=True receipt를 받았다. 파일 업로드 전체나 파일 실재 여부를 검증한 시험은 아니다.
- 수용 조건: 모든 요청의 metadata/owner를 검증한 뒤 content dedup과 참조 연결을 처리한다. “새 bytes의 잘못된 hash”뿐 아니라 “기존 bytes의 잘못된 hash”를 검사한다.

### R13 · P2 · 같은 mutation key/body 재전송으로 복제가 중복됨

- 위치: [src/aiqa/api/cases.py:1252](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/api/cases.py:1252>), `:1270`, `:1492`.
- 관련: W10-05, C01.
- Idempotency-Key 존재만 확인하고 receipt/body hash를 저장·재사용하지 않는다.
- 재현: 같은 key와 body로 bulk clone을 두 번 호출하면 200/200이며 copy 케이스가 2개 생긴다.
- 수용 조건: actor/project/operation/key + body hash 및 원래 receipt를 보존한다. 같은 요청은 1개 결과, 다른 body는 409여야 한다. 수정은 bulk 외 같은 패턴을 쓰는 mutation도 점검한다.

### R14 · P2 · TC 화면 버튼들이 GET 전용 URL에 POST함

- 위치: [src/aiqa/web/templates/tcs.html:21](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/web/templates/tcs.html:21>), [src/aiqa/web/templates/components/tc_import.html:4](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/web/templates/components/tc_import.html:4>); `src/aiqa/api/tcs.py`의 page route.
- 관련: W10-10, UI-16, C01/C02.
- 복제·보관·참조 연결/해제·import 수락/거부가 같은 폼을 제출하지만 대응 POST handler가 없고 동작/대상 식별과 JS 연결도 없다.
- 재현: 실제 제품 앱 POST `/ui/projects/{UUID}/tcs`는 405다. API를 직접 호출하는 시험은 이 버튼들의 동작을 검증하지 않는다.
- 수용 조건: 실제 각 버튼을 눌러 올바른 대상/조작/expected revision/CSRF/key가 전달되고 결과가 화면과 DB에 남는지 검사한다. 미지원 조작은 사유와 함께 비활성화한다.

### R15 · P2 · UI 기본 설정에서 음수 timeout을 저장할 수 있음

- 위치: [src/aiqa/api/settings.py:156](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/api/settings.py:156>), `:162`; 정식 API의 비교 기준은 `:73`.
- 관련: W10-09, C06 Limits.timeout_seconds.
- 정식 PATCH는 1~600을 검사하지만 UI save는 int 변환만 한다.
- 재현: UI 저장으로 timeout_seconds=-123을 보내면 201이고 DB에 음수가 저장된다.
- 수용 조건: API/UI 공통 입력 검증을 사용하고 0/음수/상한 초과/잘못된 타입을 422로 처리하며 입력을 보존한다. R06의 인증을 고쳐도 이 검증 문제는 별도로 남는다.

### R16 · P2 · spool이 같은 seq의 다른 payload도 durable 성공으로 응답함

- 위치: [src/aiqa/worker/spool.py:40](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/worker/spool.py:40>), `:42`; [tests/integration/test_w14.py:40](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/tests/integration/test_w14.py:40>).
- 관련: W14-01, seq/hash 동일성 계약.
- 기존 seq가 있으면 계산한 새 digest와 비교하지 않고 기존 receipt를 돌려준다.
- 재현: seq=1에 first를 저장한 뒤 different를 append해도 durable=True이고 first의 hash를 받는다. 호출자는 different가 저장됐다고 오인할 수 있다. 기존 시험도 다른 body를 넣지만 결과를 검증하지 않는다.
- 수용 조건: 같은 attempt/seq의 동일 body만 재전송으로 허용하고 다른 body는 명시적 충돌로 처리한다. 기존 파일과 journal은 보존한다.

### R17 · P2 · ACK 보관 정리 뒤 같은 attempt의 ACK를 진행할 수 없음

- 위치: [src/aiqa/worker/spool.py:90](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/src/aiqa/worker/spool.py:90>), `:95`, `:109`, `:188`.
- 관련: W14-01, 장기 오프라인/복구·연속 ACK cursor.
- purge는 만료된 ACK 파일뿐 아니라 journal record까지 삭제한다. 연속 seq 판정은 항상 1부터 시작하므로 지운 prefix를 복원할 근거가 없다.
- 재현: seq1 ACK→8일 경과 purge→seq2 저장→서버 seq2 ACK를 보내면 gap으로 거부된다. 오래 대기한 미ACK tail을 나중에 업로드하는 경우도 같은 문제가 있다.
- 수용 조건: 파일 GC와 prefix receipt/cursor 보존을 분리한다. 정리·재시작 뒤 prefix hash와 다음 ACK를 계속 검증할 수 있어야 한다.

### R18 · P2 · 패키지와 버전의 정확한 상호 참조가 DB에서 강제되지 않음

- 위치: [migrations/versions/0007_replay_healing.py:29](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/migrations/versions/0007_replay_healing.py:29>), `:41`; [migrations/versions/0002_cases.py:61](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/migrations/versions/0002_cases.py:61>).
- 관련: 완료 W06-05, C07. 이후 compiler 미구현 지적이 아니다.
- package_version_links의 두 FK는 같은 case 여부만 각각 검사하고 replay_packages.case_version_id와 link.version_id의 일치를 강제하지 않는다. case_versions.replay_package_id도 정확한 FK 관계가 없다.
- 재현: case_version_id=v1인 ready package를 link에서는 v2에 연결해 COMMIT할 수 있다. 양쪽 버전의 replay_package_id가 null이어도 허용된다.
- 수용 조건: 정확한 version/package pair와 ready 상태의 조건을 강제하고 잘못된 조합이 transaction 종료 시 거부되는지 확인한다.

### R19 · P2 · materialization receipt가 없는 produced version을 참조할 수 있음

- 위치: [migrations/versions/0003_recordings.py:62](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/migrations/versions/0003_recordings.py:62>).
- 관련: 완료 W06-01, C07, DATA_DESIGN의 manifest→produced version 원자성.
- produced_version_id에 UNIQUE만 있고 대상 FK/동일 case 제약이 없다.
- 재현: 유효 manifest에 produced_version_id=nonexistent-version인 receipt를 삽입할 수 있고 foreign_key_check도 오류가 없다.
- 수용 조건: 실제 생성된 동일 case 버전과 manifest/receipt의 업무 관계를 transaction에서 보장한다. 존재하지 않는 버전과 다른 case 버전을 각각 거부한다.

### R20 · P2 · append-only 결과·비용 사실을 DELETE할 수 있음

- 위치: [migrations/versions/0008_long_term_facts.py:135](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/migrations/versions/0008_long_term_facts.py:135>)~`:175`.
- 관련: W06-06/07, DATA_DESIGN 불변 사실/누적 분석.
- 불변 trigger가 BEFORE UPDATE만 막고 DELETE는 막지 않는다. finalizations/lifecycle/usage/adjustments/analysis 등이 영향을 받는다.
- 재현: 유효 item_finalizations와 usage_adjustments를 각각 삽입한 뒤 DELETE하면 각각 1행이 삭제되고 FK check는 정상이다.
- 수용 조건: 영구 사실의 UPDATE/DELETE를 거부하고, 만료 가능한 detail payload/운영 상태만 지정 경로로 정리한다. 누적 비용 수정은 adjustment 추가 방식으로 검증한다.

## V01 · 현재 시험·완료 근거의 문제

1. [tests/integration/test_w05.py:20](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/tests/integration/test_w05.py:20>)의 `_definition(expected, point)`가 `:611`의 같은 이름 함수에 의해 덮인다. test_w05_01은 좌표를 넘긴다고 생각하지만 실제로 expected에 tuple을 넣는다. 이 때문에 verification_digest 비교가 실패한다. **제품의 정상 계약을 바꾸어 이 시험을 맞추면 안 된다.**
2. test_w05_04(`:473`)와 test_w05_06(`:1015`)은 실제 approval row 없이 current_approval_id를 UPDATE한다. 이후 추가한 소속 trigger가 이를 거부한다. 시험 fixture를 유효 관계로 갱신하고 의도한 보존 검증까지 도달시켜야 한다.
3. [tests/acceptance/test_w10.py:108](<C:/Users/cease/OneDrive/문서/ChatGPT/AI test/tests/acceptance/test_w10.py:108>)~`:110`의 catalog 수동 설치, API 직접 호출만으로 UI 제안 수락/TC 버튼을 판정하는 방식은 제품 경로의 연결 누락을 가린다.
4. W13/W14의 post_dispatch_retries·unacked_deleted·duplicate_actions_from_upload 등 카운터 중 일부는 초기값만 비교한다. 값이 0이라는 결과보다 실제 호출 횟수·파일 bytes·DB 행 수·재전송 결과를 검사해야 한다.
5. W10-02 인계처럼 제품 경로 누락을 “보존 불변식”으로 적은 것은 설계 변경 승인 근거가 아니다. 작업 카드·계약과 충돌하면 검토 대상으로 올려야 한다.

## 수정 순서와 완료 재검증

아래는 수정 요청에 사용할 순서이며 NEXT_ACTION의 Current를 이번 검토에서 변경한 것은 아니다. 동일 범위의 결함은 묶어서 고칠 수 있지만, 각 재현/수용 조건은 남겨야 한다.

| 순서 | 수정 묶음 | 관련 발견 | 다시 확인할 완료 작업 |
|---|---|---|---|
| 1 | 시험 fixture 정정과 제품 앱 실제 경로 | V01, R05 | W05-01/04/06, W10-02/03 |
| 2 | 버전 전체 hash·편집 roundtrip·제안 stale base | R01~04 | W05-01/02, W06-09, W10-06/07/11 |
| 3 | UI mutation 인증·동일 요청 receipt·설정 검증 | R06, R13, R15 | W04-03 및 관련 W10 mutation |
| 4 | PNG 정제와 dispatch 제어·재전송 차단 | R07~09 | W09-01/02, W13-02/03/04 |
| 5 | 불변 증거·typed owner/ref·upload 검증·spool 지속성 | R10~12, R16/17 | W06-04, W14-01~04 |
| 6 | DB 패키지·materialization·영구 사실 제약 | R18~20 | W06-01/05/06/07 |
| 7 | TC 실제 버튼과 영향받은 사용자 여정 | R14 및 수정 영향 | W10-10, W10 상위 |

- 수정 뒤 해당 작업의 부정 재현과 영향 회귀를 통과시키고 인계·작업 상태를 동기화한다. 기존 53개를 일괄 미완료로 돌리거나, 일부 함수 시험만으로 관련 상위를 다시 완료 처리하지 않는다.
- 마지막에는 테스트에서 추가 router를 설치하지 않은 create_app으로 프로젝트→케이스 생성→정의/스텝/설정 수정→재접속→TC 조작을 실제 브라우저에서 확인한다. 저장된 hash/설정/관계/증거 bytes도 함께 비교한다.
- VM/기기/모델 환경이 없으면 해당 live gate만 차단 상태를 유지한다. 독립적인 위 수정까지 같이 막을 이유는 없다.
- 이번 검토는 모든 미래 기능의 안전성 보증이 아니다. 실제 녹화→trial→사후 승인→기록 기반 replay→FAIL latch/healing 전체 수용은 아직 해당 후속 작업과 실제 gate가 남아 있다.

## 재현 보조 파일

같은 폴더의 `reproduce_core_review.py`는 실제 사용자 데이터 없이 핵심 경계의 관찰 결과를 JSON으로 출력한다. 현재 결함을 보여 주는 진단 도구이며 정상 동작을 보증하는 PASS 시험이 아니다. 수정 후에는 기대 결과를 정식 회귀 시험으로 바꿔야 한다. 이번 실행 출력은 `core-observations.json`에 보존했다.

실행: `.\.venv\Scripts\python.exe docs/validation/reviews/reproduce_core_review.py`
