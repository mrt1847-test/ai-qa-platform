# Android·Web 실행 엔진 구현 계획

> [경계와 공통 검증 규칙](RUNTIME_BOUNDARIES.md) · [직접 선행 및 환경 색인](IMPLEMENTATION_TASKS.json) · [공통 계약](../execution/CONTRACTS.md). NEXT_ACTION의 Current 절 하나만 실행한다. TDD로 실패 조건을 확인하고 기능을 연결한 뒤 같은 검사를 반복한다. 선행 인계와 구현의 필드명이 다르면 계약을 먼저 대조한다. 카드의 파일은 기존 파일과 생성 예정 파일을 함께 지정한다.

<a id="rx-09"></a>
## RX-09 · Android 워커 inventory

**입력** RX-04 · AD-01 · PC-03 및 C00/C01/C03/C05. **환경** `local_python`.

**파일** `src/aiqa/environments/android_observation.py`, `src/aiqa/environments/usb_android.py`, `src/aiqa/worker/resources.py`, `src/aiqa/worker/http_client.py`, `src/aiqa/web/static/recording_setup.js`, `tests/integration/test_rx_09.py`.

- [x] adb unauthorized·연결 끊김·다른 serial·낡은 관찰을 ready로 표시하지 않음. 원본 화면 업로드 0회.
- [x] 전용 adb serial에서 probe한 상태와 크기·회전·관찰 시각만 inventory에 게시한다. 마지막 저장 관찰과 현재 heartbeat를 분리하고 PC-03의 녹화 준비 선택기에 노출한다.
- [x] `python -m pytest -q tests/integration/test_rx_09.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-09.md`에 검증 등급·명령·결과와 inventory 필드와 Android readiness를 남긴다.

<a id="rx-10"></a>
## RX-10 · Android 결정적 입력과 전후 증거

**입력** RX-05 · RX-06 · RX-09 및 C00/C01/C05/C07. **환경** `local_python`.

**파일** `src/aiqa/replay/android_plan.py`, `src/aiqa/replay/android_runner.py`, `src/aiqa/recording/action_executor.py`, `src/aiqa/security/redaction.py`, `tests/integration/test_rx_10.py`.

- [x] ADB 실패·timeout·해상도 변경·민감 문자열·정제 실패를 검증하고 모호한 동작 자동 재전송 및 replay actor AI 호출 0회.
- [x] AndroidPreflight의 target 확인 뒤 검증된 tap/swipe/key/text를 지정 serial에 고정 argv로 실행한다. 화면 크기·회전·대상이 변하면 중단한다. 전후 화면·행동 로그를 정제하고 C05의 dispatch 경계에서 spool에 연결한다.
- [x] `python -m pytest -q tests/integration/test_rx_10.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-10.md`에 검증 등급·명령·결과와 typed action과 좌표계·증거 결측/실패 규칙를 남긴다.

<a id="rx-11"></a>
## RX-11 · 관리 서버 모델 호출과 권한

**입력** RX-02 · RX-03 · RX-19 및 C00/C01/C06/C07. **환경** `local_python`.

**파일** `src/aiqa/models/broker.py`, `src/aiqa/api/worker.py`, `src/aiqa/models/provider_http.py`, `src/aiqa/security/secrets.py`, `tests/integration/test_rx_11.py`.

- [x] OFF healer·일반 replay actor·위조 purpose·quota·중복 키 거절 또는 기존 receipt 반환. 외부 모델 대신 fixture로 호출 수 검증.
- [x] POST /api/v1/worker/model-requests는 서버의 불변 정책에서 purpose·check·attempt budget을 읽고 provider 자격증명은 서버에서만 해석한다. authoring·verifier·healer를 분리해 사용량과 비용 상태를 기록한다.
- [x] `python -m pytest -q tests/integration/test_rx_11.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-11.md`에 검증 등급·명령·결과와 provider port·purpose 권한표·usage와 제한 응답를 남긴다.

<a id="rx-12"></a>
## RX-12 · Mobile-Agent Android 녹화 어댑터

**입력** RX-08 · RX-10 · RX-11 및 C00/C01/C05/C06/C07. **환경** `local_python`.

**파일** `src/aiqa/adapters/mobile_agent_android.py`, `src/aiqa/environments/android_observation.py`, `src/aiqa/replay/android_plan.py`, `tests/integration/test_rx_12.py`.

- [x] 잘못된 geometry·알 수 없는 action·shell payload·정제 실패 거절, replay에서는 authoring provider 호출 0회.
- [x] 고정 upstream 응답을 순수 parser로 해석해 typed action과 화면 좌표를 만든다. 정제 관찰→authoring broker→allowlist parser→Android driver→증거 저장으로 연결한다.
- [x] `python -m pytest -q tests/integration/test_rx_12.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-12.md`에 검증 등급·명령·결과와 parser 입력/출력·좌표 변환 표·지원 동작를 남긴다.

<a id="rx-13"></a>
## RX-13 · Web 격리 게이트와 백엔드 계약

**입력** RX-05 · RX-06 및 C00/C01/C05/C07. **환경** `local_python`.

**파일** `src/aiqa/worker/isolated_web.py`, `src/aiqa/replay/ipc.py`, `src/aiqa/worker/web_isolation_backend.py`, `tests/integration/test_rx_13.py`.

- [x] 격리 설정 누락·위조 proof·기한 만료 시 실행 0회, fixture에서 IPC 우회 거절. 실제 탈출 시도는 RX-22.
- [x] 격리 경계에 IPC·사전 승인된 입출력만 부여하고 host filesystem·process·ADB·CDP·직접 provider·임의 network 접근을 거부한다. 격리 확인이 없으면 Web ready를 제공하지 않는다.
- [x] `python -m pytest -q tests/integration/test_rx_13.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-13.md`에 검증 등급·명령·결과와 격리 backend 포트·proof 범위와 TTL를 남긴다.

<a id="rx-14"></a>
## RX-14 · Web 승인 코드의 신뢰 driver 실행

**입력** RX-08 · RX-13 및 C00/C01/C05/C07. **환경** `local_python`.

**파일** `src/aiqa/replay/driver.py`, `src/aiqa/replay/compiler.py`, `src/aiqa/replay/ipc.py`, `src/aiqa/recording/action_executor.py`, `tests/integration/test_rx_14.py`.

- [x] 임의 Python/shell·raw Playwright handle·cross-origin·승인 digest 변경·미지원 동작 거절, replay actor AI 0회.
- [x] TrustedWebDriver는 허용된 브라우저 동작만 대상별 격리 context로 번역한다. 승인 digest·revision·origin을 검증하고 locator·navigation·정제 관찰을 기존 executor에 연결한다.
- [x] `python -m pytest -q tests/integration/test_rx_14.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-14.md`에 검증 등급·명령·결과와 지원 IPC verb·selector·승인 digest 계약를 남긴다.

<a id="rx-15"></a>
## RX-15 · CUAWright Web 녹화 어댑터

**입력** RX-11 · RX-13 · RX-14 및 C00/C01/C05/C06/C07. **환경** `local_python`.

**파일** `src/aiqa/adapters/cuawright_web.py`, `src/aiqa/worker/isolated_web.py`, `src/aiqa/replay/compiler.py`, `tests/integration/test_rx_15.py`.

- [x] workspace shell·직접 CDP·생성 코드의 host 읽기와 재생 중 무단 코드 수정 거절. 잘린 trajectory는 승인 가능한 패키지를 만들지 않음.
- [x] 고정 CUAWright hook에서 step 원본과 요약을 분리한다. 격리된 작성 결과 중 allowlist 통과한 step만 신뢰 driver에서 실행하고 검토 가능한 소스·승인 패키지·전후 증거를 저장한다.
- [x] `python -m pytest -q tests/integration/test_rx_15.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-15.md`에 검증 등급·명령·결과와 hook 지점·추출된 source와 승인 패키지 대응를 남긴다.

<a id="rx-30"></a>
## RX-30 · Web 격리 VM 전송 구현

**입력** RX-13 · RX-14 및 C00/C01/C05/C07. **환경** `local_python`.

**파일** `src/aiqa/worker/web_isolation_backend.py`, `src/aiqa/worker/web_vm_transport.py`, `src/aiqa/worker/isolated_web.py`, `tests/integration/test_rx_30.py`.

- [x] fixture의 연결 실패·guest 종료·위조 IPC·guest proof 교체에서 차단 및 정리 확인, 실제 VM 없이는 ready 금지.
- [x] 지원 VM에서 격리 실행기와 신뢰 driver 사이에 allowlist IPC를 연결한다. worker 계정이 승인한 guest endpoint만 사용하며 브라우저 CDP와 모델 key는 생성 코드를 실행하는 guest에 제공하지 않는다. 구체 VM 제품/이미지 준비와 host 수용은 RX-22에서 확인한다.
- [x] `python -m pytest -q tests/integration/test_rx_30.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-30.md`에 검증 등급·명령·결과와 VM transport 설정·guest lifecycle·장애 정리를 남긴다.

<a id="rx-31"></a>
## RX-31 · replay 검증·실패 후 healing 연결

**입력** RX-07 · RX-11 및 C00/C01/C06/C07/C09. **환경** `local_python`.

**파일** `src/aiqa/worker/runner.py`, `src/aiqa/healing/service.py`, `src/aiqa/models/broker.py`, `src/aiqa/domain/executions.py`, `src/aiqa/api/worker.py`, `tests/integration/test_rx_31.py`.

- [x] OFF·예산 없음·비허용 실패·다른 Check에서 healer 0회, 모델 timeout은 성공 금지, 후보가 기존 승인 package를 바꾸지 않음.
- [x] 기존 검증·healing 서비스와 worker 모델 요청을 연결한다. 결정적 Check 우선, AI Check는 등록된 필요 조건에서만, healing은 승인된 실패와 ON 정책에서만 제한한다. 원래 실패와 제안·시도 결과를 별도 저장한다.
- [x] `python -m pytest -q tests/integration/test_rx_31.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-31.md`에 검증 등급·명령·결과와 Check 분기와 오류·호출 횟수·별도 결과 계약를 남긴다.
