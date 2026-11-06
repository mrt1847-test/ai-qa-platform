# 작업 결과·자원 정리·실제 실행 보완

2026-11-06 · [NEXT_ACTION](../../NEXT_ACTION.md) · [확인 근거](../validation/reviews/2026-11-06-completion-gaps.md)

기존 RX-63~71의 성공 증거를 재사용한다. 아래 카드는 현재 코드와 재현에서 확인한 기능 공백을 처리한다. 외부 서버·운영 모델 키·Web VM은 로컬 구현의 선행이 아니다. 구현은 정상 API·worker entry에 연결하고 실제 환경의 최종 수용은 별도 카드에 기록한다.

<a id="rx-72"></a>
## RX-72 · 실행 종료를 QA 결과와 다음 ITEM으로 연결

**입력** RX-53 · RX-71 · RX-38 및 C00/C01/C03/C04/C05/C08/C09/C10 중 해당 경계. **환경** `local_python`. **별도 수용** RX-23 · RX-24 · RX-25.

**근거** RX-71 정상 흐름을 재실행한 뒤 trial·regression jobs는 completed였지만 item_finalizations는 0건이었다. advance_execution의 제품 호출 지점도 없었다.

**파일** `src/aiqa/store/queue.py`, `src/aiqa/domain/executions.py`, `src/aiqa/domain/execution_scheduler.py`, `src/aiqa/domain/reporting.py`, `src/aiqa/api/reports.py`, `tests/integration/test_rx_72.py`.

- [x] UI/API에서 만든 두 ITEM을 worker로 끝내고 동일 실행의 QA 결과·완료율·다음 항목을 확인한다. 같은 finish 재전송·늦은 이벤트·중간 취소가 결과를 덮거나 중복 생성하지 않는지 확인한다.
- [x] 서버 finish 영수증과 저장된 Check·위반·중단 근거에서 실제 ITEM 결과를 확정한다. 결과 이력을 append하고 기존 scheduler와 보고/분석에 연결한다. completed만으로 PASS를 추정하지 않는다.
- [x] `python -m pytest -q tests/integration/test_rx_72.py`와 관련 기존 시험으로 정상 진입점의 결과를 확인한다. RX-78은 기존 회귀 시험을 먼저 재사용한다.
- [x] `docs/validation/tasks/RX-72.md`에 결과 DB 행·실제 파일·기기/driver 호출·요청 영수증과 재개 조건을 기록한다.

완료 근거: [RX-72.md](../validation/tasks/RX-72.md).

<a id="rx-73"></a>
## RX-73 · 워커의 정리 완료와 자원 재사용 연결

**입력** RX-38 · RX-62 · RX-71 및 C00/C01/C03/C04/C05/C08/C09/C10 중 해당 경계. **환경** `local_python`. **별도 수용** RX-25 · RX-26 · RX-27.

**근거** RX-71은 각 작업 뒤 테스트의 _release_lease가 cleanup-confirmations를 대신 호출했다. 일반 worker runtime에는 이 흐름이 없다.

**파일** `src/aiqa/worker/runtime.py`, `src/aiqa/worker/http_client.py`, `src/aiqa/worker/android_jobs.py`, `src/aiqa/store/queue.py`, `tests/integration/test_rx_73.py`.

- [x] 한 워커 프로세스로 녹화→시범→회귀를 연속 접수해 임대 해제를 확인한다. 테스트에서 cleanup API를 대신 호출하지 않는다. 구 세대와 잘못된 자원·응답 유실을 거절하거나 같은 영수증으로 확인한다.
- [x] 실제 핸들러의 자원·context·IME 정리 포트가 반환한 증명으로 동일 attempt/fence의 cleanup 확인을 보낸다. 증명 전 임대 해제를 막고 timeout·정리 실패는 격리/재개 조건으로 남긴다.
- [x] `python -m pytest -q tests/integration/test_rx_73.py`와 관련 기존 시험으로 정상 진입점의 결과를 확인한다. RX-78은 기존 회귀 시험을 먼저 재사용한다.
- [x] `docs/validation/tasks/RX-73.md`에 결과 DB 행·실제 파일·기기/driver 호출·요청 영수증과 재개 조건을 기록한다.

완료 근거: [RX-73.md](../validation/tasks/RX-73.md).

<a id="rx-74"></a>
## RX-74 · APK 원본과 빌드 정보를 서버에 영속 저장

**입력** RX-57 · RX-68 및 C00/C01/C03/C04/C05/C08/C09/C10 중 해당 경계. **환경** `local_python`. **별도 수용** W11-06.

**근거** register_app_build와 get_app_build는 프로세스 전역 _known을 사용한다. 서로 다른 API/worker 프로세스와 재시작에서 APK 원본·metadata 조회가 이어지지 않는다.

**파일** `src/aiqa/environments/app_builds.py`, `src/aiqa/api/app_builds.py`, `src/aiqa/store/models.py`, `src/aiqa/worker/android_jobs.py`, `tests/integration/test_rx_74.py`.

- [x] 업로드→API 재시작→다른 프로세스에서 목록/동일 build 조회·bytes hash를 확인한다. 손상·미완료 업로드·교차 프로젝트·동시 중복 요청을 검증한다.
- [x] 기존 app_builds와 artifact 저장소에 byte hash·파일·검사 결과를 연결한다. worker는 인증 HTTP로 지정 build의 원본과 고정 hash를 얻으며 API 메모리 객체를 공유하지 않는다.
- [x] `python -m pytest -q tests/integration/test_rx_74.py`와 관련 기존 시험으로 정상 진입점의 결과를 확인한다. RX-78은 기존 회귀 시험을 먼저 재사용한다.
- [x] `docs/validation/tasks/RX-74.md`에 결과 DB 행·실제 파일·기기/driver 호출·요청 영수증과 재개 조건을 기록한다.

완료 근거: [RX-74.md](../validation/tasks/RX-74.md).

<a id="rx-75"></a>
## RX-75 · 실제 Android 설치·초기화 driver 연결

**입력** RX-74 · RX-68 및 C00/C01/C03/C04/C05/C08/C09/C10 중 해당 경계. **환경** `local_python`. **별도 수용** RX-23.

**근거** Android worker의 기본 조립은 operational 녹화 모드에서도 FixtureInstallDriver(installed=set())를 사용한다.

**파일** `src/aiqa/environments/app_builds.py`, `src/aiqa/worker/runtime.py`, `src/aiqa/worker/android_jobs.py`, `tests/integration/test_rx_75.py`.

- [x] 로컬 모의 ADB와 별도 worker entry로 명시 요청만 실행되는지 검사한다. 드라이버 없는 실행은 차단하고 설치 실패·기기 변경·hash 변경에서 ready를 올리지 않는다. 실제 APK 설치 수용은 전용 기기의 지정 build에서 수행한다.
- [x] 명시 serial의 ADB 설치·패키지 확인·허용 reset을 실제 driver port로 구현한다. fixture는 테스트 주입에만 둔다. 서버에 고정된 APK를 검증한 후 실행하고 사후 관찰·기한·취소·IME 복원에 따른 상태를 남긴다.
- [x] `python -m pytest -q tests/integration/test_rx_75.py`와 관련 기존 시험으로 정상 진입점의 결과를 확인한다. RX-78은 기존 회귀 시험을 먼저 재사용한다.
- [x] `docs/validation/tasks/RX-75.md`에 결과 DB 행·실제 파일·기기/driver 호출·요청 영수증과 재개 조건을 기록한다.

완료 근거: [RX-75.md](../validation/tasks/RX-75.md).

<a id="rx-76"></a>
## RX-76 · Web 신뢰 driver를 실제 브라우저에 연결

**입력** RX-70 · RX-61 및 C00/C01/C03/C04/C05/C08/C09/C10 중 해당 경계. **환경** `local_python` · `local_browser`. **별도 수용** RX-22 · RX-24.

**근거** RX-70의 LocalPageSession은 Python HTMLParser 노드와 생성 PNG를 사용한다. Chrome/CDP에서 페이지를 실제로 조작하는 실행 포트는 구현되지 않았다.

**파일** `src/aiqa/replay/driver.py`, `src/aiqa/worker/web_jobs.py`, `src/aiqa/worker/local_page.py`, `src/aiqa/environments/web_browser.py`, `tests/integration/test_rx_76.py`.

- [x] 현재 PC의 로컬 테스트 웹과 실제 headless 브라우저에서 DOM 변경·스크린샷·동작 수를 확인한다. 미지원 browser·실행 포트 없음·교차 origin·없는 proof에서 제품 ready나 성공을 반환하지 않는다. VM 격리 수용은 RX-22에 남긴다.
- [x] 실제 전용 브라우저 context를 소유하는 신뢰 driver 포트를 추가해 click/fill/scroll/select와 동작 직후 관찰을 연결한다. LocalPageSession은 테스트 주입으로 둔다. 허용 origin과 격리 proof 경계를 유지한다.
- [x] `python -m pytest -q tests/integration/test_rx_76.py`와 관련 기존 시험으로 정상 진입점의 결과를 확인한다. RX-78은 기존 회귀 시험을 먼저 재사용한다.
- [x] `docs/validation/tasks/RX-76.md`에 결과 DB 행·실제 파일·기기/driver 호출·요청 영수증과 재개 조건을 기록한다.

완료 근거: [RX-76.md](../validation/tasks/RX-76.md).

<a id="rx-77"></a>
## RX-77 · 브라우저에서 결과·자원 복귀까지 사용자 여정 검증

**입력** RX-72 · RX-73 · RX-75 · RX-71 및 C00/C01/C03/C04/C05/C08/C09/C10 중 해당 경계. **환경** `local_python` · `local_browser`. **별도 수용** RX-23 · RX-25.

**근거** RX-71은 httpx ASGI로 폼 API를 직접 호출하고 HTML 파일 스크린샷만 선택적으로 찍는다. 회귀 QA 결과와 worker 정리를 확인하지 않고 종료한다.

**파일** `tools/validation/probe_same_pc_stage.py`, `tests/acceptance/test_rx_71.py`, `src/aiqa/web/static/recording_setup.js`, `src/aiqa/web/static/execution_setup.js`, `src/aiqa/web/templates/execution.html`, `tests/acceptance/test_rx_77.py`.

- [x] 브라우저에서 녹화→trial→검토/승인→두 케이스 묶음 회귀→결과/증거 조회를 실행한다. 중간 SQL 완료·테스트의 cleanup 대행·가짜 PASS를 사용하지 않는다. 전용 AVD는 별도 옵션으로 실행할 수 있게 한다.
- [x] 정상 웹 UI의 입력·버튼·JavaScript로 작업을 접수하는 동일 PC 테스트 모드를 연결한다. 별도 API/worker와 설정된 모의 모델을 사용하고 결과 리포트·증거 원본·자원 재사용까지 확인한다. 발견한 UI/API 누락은 해당 소유 코드에서 수정한다.
- [x] `python -m pytest -q tests/acceptance/test_rx_77.py`와 관련 기존 시험으로 정상 진입점의 결과를 확인한다. RX-78은 기존 회귀 시험을 먼저 재사용한다.
- [x] `docs/validation/tasks/RX-77.md`에 결과 DB 행·실제 파일·기기/driver 호출·요청 영수증과 재개 조건을 기록한다.

완료 근거: [RX-77.md](../validation/tasks/RX-77.md). 한계: JS와 동일 HTTP 계약·실 WorkerRuntime(DOM 클릭·AVD는 별도). execution wizard `items: []`는 인계에 기록.

<a id="rx-78"></a>
## RX-78 · 기존 관리 UI와 로컬 launcher 회귀 정리

**입력** RX-63 · RX-71 및 C00/C01/C03/C04/C05/C08/C09/C10 중 해당 경계. **환경** `local_python` · `local_browser`. **별도 수용** RX-21.

**근거** 전체 pytest를 --maxfail=3으로 실행해 76 passed, 3 failed였다. W11 두 건의 버튼 전면 금지 가정이 새 등록 화면과 충돌했고 W12 launcher의 /ui/local 접속도 실패했다.

**파일** `tests/acceptance/test_w11.py`, `tests/acceptance/test_w12.py`, `src/aiqa/launcher.py`, `src/aiqa/api/lifecycle.py`, `tests/acceptance/test_rx_78.py`.

- [x] W11 두 실패와 W12 로컬 실행부터 재현한다. 잘못된 준비 상태를 통과시키거나 테스트를 삭제하지 않고 관련 구·신 시험을 통과시킨다.
- [x] 기존 화면 계약과 새 기능의 차이를 대조해 정상 사용자 기능을 보존하며 구체 요소를 검사한다. 로컬 launcher는 유효한 서버/워커 설정으로 시작·상태 확인·종료하고 설정 누락을 화면에서 설명한다.
- [x] `python -m pytest -q tests/acceptance/test_rx_78.py`와 관련 기존 시험으로 정상 진입점의 결과를 확인한다. RX-78은 기존 회귀 시험을 먼저 재사용한다.
- [x] `docs/validation/tasks/RX-78.md`에 결과 DB 행·실제 파일·기기/driver 호출·요청 영수증과 재개 조건을 기록한다.

완료 근거: [RX-78.md](../validation/tasks/RX-78.md).

