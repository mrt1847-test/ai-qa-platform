# 등록 실행 PC와 관리 서버 운영 경로 연결

[실행 큐](../../NEXT_ACTION.md) · [카드 색인](IMPLEMENTATION_TASKS.json) · [구현 경계](RUNTIME_BOUNDARIES.md)

기존 완료는 fixture 계약의 증거로 보존한다. 아래 카드는 실행 명령에서 해당 계약을 소비하도록 연결한다. 현 단계에서는 임시 DB와 시험용 포트로 검증하고 장비·운영 인증·실제 모델 사용은 RX 실환경 카드에서 수용한다. Current 한 건씩 작업하고 완료 인계를 남긴다.

<a id="rx-32"></a>
## RX-32 · Android 워커 시작과 기기 목록 연결

**입력** RX-08 · RX-09 및 C00/C01/C03/C04/C05. **환경** `local_python`.

**파일** `src/aiqa/worker/runtime.py`, `src/aiqa/worker/resources.py`, `src/aiqa/environments/android_observation.py`, `tests/integration/test_rx_32.py`.

- [x] 실제 명령의 조립 경로를 fixture ADB·HTTP로 열어 지정 serial 상태·geometry만 보고하고, 연결 끊김·다른 serial·원본 화면 전송·임의 기기 선택을 확인한다. 원본 화면 전송과 임의 선택은 0회여야 한다.
- [x] `run_worker_process`가 등록 프로젝트와 명시 Android serial 설정으로 `AndroidObservationProvider`와 `android_inventory_payload`를 연결한다. heartbeat 이후 `WorkerRuntime`의 inventory 경로를 사용한다. 설정 누락 또는 probe 실패 때 준비 상태를 제공하지 않는다.
- [x] `python -m pytest -q tests/integration/test_rx_32.py`로 관련 동작과 부정 시험을 확인한다.
- [x] `docs/validation/tasks/RX-32.md`에 명령·결과와 워커 기동 설정과 inventory 제공자 조립 지점를 남긴다.

<a id="rx-33"></a>
## RX-33 · Android 녹화 핸들러 연결

**입력** RX-32 · RX-05 · RX-06 · RX-07 · RX-12 및 C00/C01/C04/C05/C06/C08. **환경** `local_python`.

**파일** `src/aiqa/worker/runtime.py`, `src/aiqa/worker/android_jobs.py`, `src/aiqa/adapters/mobile_agent_android.py`, `tests/integration/test_rx_33.py`.

- [x] 기존 설정·임시 DB·fixture driver/model을 써서 탭 1회와 증거 commit을 확인한다. claim 응답 유실, lease 만료, 잘못된 serial, 후 증거 누락에서 중복 탭과 허위 완료를 막는다.
- [x] 운영 worker의 recording handler가 claim 스냅샷에서 대상과 검증 의도를 읽고 ACK 뒤에만 Mobile-Agent authoring을 호출한다. `RemoteLeaseGuard`와 journal, 정제된 전후 PNG·로그 spool, 서버 ACK·finish를 같은 attempt로 연결한다. 녹화 결과는 검토 대기 상태로 저장한다.
- [x] `python -m pytest -q tests/integration/test_rx_33.py`로 관련 동작과 부정 시험을 확인한다.
- [x] `docs/validation/tasks/RX-33.md`에 명령·결과와 recording handler 등록, 단계·증거·finish 연결과 기기별 fail-closed 조건를 남긴다.

<a id="rx-34"></a>
## RX-34 · Android 승인 계획 재생 핸들러 연결

**입력** RX-33 · RX-10 · RX-31 및 C00/C01/C04/C05/C06/C07/C09. **환경** `local_python`.

**파일** `src/aiqa/worker/runtime.py`, `src/aiqa/worker/android_jobs.py`, `src/aiqa/replay/android_runner.py`, `src/aiqa/worker/runner.py`, `tests/integration/test_rx_34.py`.

- [x] 승인 digest 변경, 잘못된 geometry, ACK 유실, 취소, healing OFF 및 예산 소진을 시험한다. 단절 뒤 동작 재전송 0회와 원래 실패 보존을 확인한다.
- [x] trial·regression을 승인된 불변 계획과 자원으로 연결한다. 일반 actor 호출 0, 결정적 Check 우선, 정책상 필요한 검증만 모델 호출, 명시 ON 실패의 제한된 healing을 연결한다.
- [x] `python -m pytest -q tests/integration/test_rx_34.py`로 관련 동작과 부정 시험을 확인한다.
- [x] `docs/validation/tasks/RX-34.md`에 명령·결과와 실행 목적별 등록 조건, 모델 호출 수와 검증 결과를 남긴다.

<a id="rx-35"></a>
## RX-35 · Web 격리 guest IPC 실제 전송 연결

**입력** RX-13 · RX-30 및 C00/C01/C04/C05/C07. **환경** `local_python`.

**파일** `src/aiqa/worker/web_vm_transport.py`, `src/aiqa/worker/web_isolation_backend.py`, `src/aiqa/worker/isolated_web.py`, `tests/integration/test_rx_35.py`.

- [x] 별도 로컬 테스트 프로세스로 송수신·조기 종료·timeout·과대 메시지·위조 endpoint·proof 교체를 재현한다. 실제 guest 격리와 우회 시험은 RX-22에서 수행한다.
- [x] `WebVmTransport`를 승인된 guest endpoint와 통신하는 transport 포트에 연결한다. 연결·요청·종료 기한, 상대 인증, 메시지 크기와 스키마, 비정상 종료 시 정리를 구현한다. Web ready에는 기존 실제 proof가 계속 필요하다.
- [x] `python -m pytest -q tests/integration/test_rx_35.py`로 관련 동작과 부정 시험을 확인한다.
- [x] `docs/validation/tasks/RX-35.md`에 명령·결과와 guest 통신 인터페이스, 설정, 정리 영수증 및 fixture 한계를 남긴다.

<a id="rx-36"></a>
## RX-36 · Web 워커 녹화·재생 진입점 연결

**입력** RX-15 · RX-31 · RX-35 및 C00/C01/C04/C05/C06/C07/C08. **환경** `local_python`.

**파일** `src/aiqa/worker/runtime.py`, `src/aiqa/worker/web_jobs.py`, `src/aiqa/adapters/cuawright_web.py`, `src/aiqa/replay/driver.py`, `tests/integration/test_rx_36.py`.

- [x] fake guest와 브라우저 포트를 사용해 authoring과 replay를 실행한다. 미검증 proof·다른 origin·승인 코드 변경·직접 CDP를 거절하고 일반 replay actor 0회를 확인한다.
- [x] 운영 worker의 Web 경로에서 녹화는 CUAWright 어댑터와 격리 transport, 승인본 재생은 신뢰 driver와 고정 digest로 연결한다. 정제 증거·finish를 보내고 원본과 승인 패키지를 별도 관리한다.
- [x] `python -m pytest -q tests/integration/test_rx_36.py`로 관련 동작과 부정 시험을 확인한다.
- [x] `docs/validation/tasks/RX-36.md`에 명령·결과와 Web handler 등록과 ready 조건, 승인 코드·증거 대응를 남긴다.

<a id="rx-37"></a>
## RX-37 · 관리 서버의 운영 OIDC 연결

**입력** RX-16 · RX-17 · RX-19 및 C00/C01/C01/C08/C11. **환경** `local_python`.

**파일** `src/aiqa/config.py`, `src/aiqa/api/app.py`, `src/aiqa/api/auth.py`, `src/aiqa/api/oidc_login.py`, `src/aiqa/security/oidc.py`, `tests/integration/test_rx_37.py`.

- [x] 모의 HTTPS IdP로 브라우저 로그인 왕복, 잘못된 발급자·서명·만료·state 재사용·멤버십 없음·키 누락을 확인한다. 실제 IdP와 운영 계정의 수용은 RX-21에서 수행한다.
- [x] hosted 앱 시작 시 승인된 설정과 서버 secret ref에서 운영 IdP 클라이언트를 조립한다. 브라우저 리다이렉트부터 콜백·멤버십 검사까지 하나의 경로로 연결하고 테스트 클라이언트는 주입 경계에 둔다.
- [x] `python -m pytest -q tests/integration/test_rx_37.py`로 관련 동작과 부정 시험을 확인한다.
- [x] `docs/validation/tasks/RX-37.md`에 명령·결과와 hosted 설정, 콜백·세션 경계와 비밀 해석 방식를 남긴다.

<a id="rx-38"></a>
## RX-38 · 원격 워커 종료·재연결 계약 보완

**입력** RX-05 · RX-06 · RX-07 · RX-08 및 C00/C01, C03~C08 중 해당 카드의 경계. **환경** `local_python`.

**파일** `src/aiqa/worker/runtime.py`, `src/aiqa/store/queue.py`, `src/aiqa/api/worker.py`, `tests/integration/test_rx_38.py`.

- [x] ACK 없음, 새 boot, 만료, 취소, commit 전후 503/응답 유실에서 기존 결과 불변, 중복 동작 0회를 임시 DB로 검증한다.
- [x] 현재 세대·서버 시각·유효 임대·시작 ACK를 확인한 뒤에만 성공을 저장한다. 응답을 잃은 종료 요청은 같은 키와 본문으로 확인하고 서버 영수증 전에는 완료로 표시하지 않는다.
- [x] `python -m pytest -q tests/integration/test_rx_38.py` 통과와 검증 범위를 `docs/validation/tasks/RX-38.md`에 남긴다.

<a id="rx-39"></a>
## RX-39 · Android 실제 워커 경로 연결

**입력** RX-32 · RX-33 · RX-34 · RX-38 · RX-40 및 C00/C01, C03~C08 중 해당 카드의 경계. **환경** `local_python`.

**파일** `src/aiqa/worker/runtime.py`, `src/aiqa/worker/android_jobs.py`, `src/aiqa/replay/android_runner.py`, `src/aiqa/api/worker.py`, `tests/integration/test_rx_39.py`.

- [x] 로컬 테스트 서버와 fixture model에서 실명령 경로로 기기 등록→claim→ACK→동작→증거 서버 ACK→검토 대기를 검증한다. AVD는 전용 대상에서만 선택한다.
- [x] 실행 진입점에 준비된 Android 핸들러를 등록한다. 서버 target_ref를 해당 등록 기기에 해석하고, 단계별 전후 캡처를 서버에 commit해 ACK prefix로 종료한다.
- [x] `python -m pytest -q tests/integration/test_rx_39.py` 통과와 검증 범위를 `docs/validation/tasks/RX-39.md`에 남긴다.

<a id="rx-40"></a>
## RX-40 · 모델 응답과 시도별 예산 연결

**입력** RX-11 · RX-31 및 C00/C01, C03~C08 중 해당 카드의 경계. **환경** `local_python`.

**파일** `src/aiqa/models/broker.py`, `src/aiqa/models/provider_http.py`, `src/aiqa/api/app.py`, `src/aiqa/api/worker.py`, `tests/integration/test_rx_40.py`.

- [x] 모의 provider에서 두 시도가 각자 예산을 소비하고, 구 세대·재전송·healing OFF·replay actor·키 누락에 따른 외부 호출 수를 검사한다.
- [x] 운영과 fixture provider를 분리하고 모델 입력과 구조화된 행동·검증 응답을 연결한다. attempt 소유·역할·예산과 호출 영수증을 서버에서 확인한다.
- [x] `python -m pytest -q tests/integration/test_rx_40.py` 통과와 검증 범위를 `docs/validation/tasks/RX-40.md`에 남긴다.

<a id="rx-41"></a>
## RX-41 · 실제 OIDC 교환 연결

**입력** RX-37 및 C00/C01, C03~C08 중 해당 카드의 경계. **환경** `local_python`.

**파일** `src/aiqa/api/oidc_login.py`, `src/aiqa/security/oidc.py`, `src/aiqa/config.py`, `src/aiqa/api/auth.py`, `tests/integration/test_rx_41.py`.

- [x] 로컬 모의 HTTPS IdP에서 브라우저 redirect·code 교환·세션 발급, 만료·서명·발급자·멤버십·재사용 거절을 검증한다.
- [x] 운영 호스트에 등록할 IdP의 code 교환과 검증 가능한 서명 경로를 운영 클라이언트로 연결한다. 모의 IdP는 테스트 주입에 둔다.
- [x] `python -m pytest -q tests/integration/test_rx_41.py` 통과와 검증 범위를 `docs/validation/tasks/RX-41.md`에 남긴다.

<a id="rx-42"></a>
## RX-42 · Web 실제 워커 경로 연결

**입력** RX-35 · RX-36 · RX-38 · RX-40 및 C00/C01, C03~C08 중 해당 카드의 경계. **환경** `local_python`.

**파일** `src/aiqa/worker/runtime.py`, `src/aiqa/worker/web_jobs.py`, `src/aiqa/worker/web_vm_transport.py`, `tests/integration/test_rx_42.py`.

- [x] 별도 fixture guest 프로세스로 실제 워커 명령의 녹화·승인본 재생 경로를 검증하고, 증명 없는 guest에서 동작 0회를 확인한다. 실제 VM의 격리 시험은 RX-22에서 수행한다.
- [x] 실제 실행 진입점에 Web 핸들러와 guest 연결을 등록한다. 신뢰 driver와 정제 증거·서버 ACK·finish를 같은 attempt로 연결한다.
- [x] `python -m pytest -q tests/integration/test_rx_42.py` 통과와 검증 범위를 `docs/validation/tasks/RX-42.md`에 남긴다.

<a id="rx-43"></a>
## RX-43 · Android 녹화의 실제 증거 파일 저장

**입력** RX-38 · RX-39와 C00/C01/C04/C05/C06/C08. **환경** `local_python`.

**파일** `src/aiqa/worker/android_jobs.py`, `src/aiqa/worker/runtime.py`, `src/aiqa/recording/service.py`, `tests/integration/test_rx_39.py`.

- [x] 기존 RX-39 시험에 이벤트 외에 artifact 객체·참조·동작과 실제 다운로드 bytes를 검증한다. 누락/오염/ACK 유실에서 허위 완료 0, 늦은 재전송에서 중복 동작 0을 확인한다.
- [x] 녹화 동작과 전후 PNG·로그를 정제해 증거 commit의 artifact 본문으로 전달한다. 서버가 동작과 실제 파일·해시를 연결하고 전후 증거가 준비된 뒤에만 완료를 기록한다.
- [x] `python -m pytest -q tests/integration/test_rx_39.py`에서 지정 회귀를 검증한다. `docs/validation/tasks/RX-43.md`에 시험 명령과 실제 결과를 남긴다.

<a id="rx-44"></a>
## RX-44 · 현재 PC의 실제 Android 워커 검증

**입력** RX-43와 C00/C01/C04/C05/C06/C08. **환경** `local_python` · `android_emulator`.

**파일** `tools/validation/probe_same_pc_stage.py`, `src/aiqa/launcher.py`, `src/aiqa/worker/runtime.py`, `src/aiqa/worker/android_jobs.py`.

- [x] 실제 HTTPS + ADB로 워커 등록→claim→ACK→동작→스크린샷·로그 서버 조회→검토 대기를 재현하고, 키 호출 0과 워커 종료 후 서버 응답을 확인한다.
- [x] 명시적 로컬 검증 설정에서만 fixture 모델을 선택하고 실제 워커 실행 명령으로 전용 AVD의 설정 화면에서 동작한다. API URL·CA·기기 설정은 독립 프로세스에 전달하고, 등록 워커가 기기 목록과 녹화 권한을 각각 올바르게 사용할 수 있는지 확인한다.
- [x] [동일 PC 검증 명령](SAME_PC_STAGE.md)을 실행한다. `docs/validation/tasks/RX-44.md`에 시험 명령과 실제 결과를 남긴다.

<a id="rx-45"></a>
## RX-45 · 운영 모델 공급자 주소 설정과 전송 검증

**입력** RX-40와 C00/C01/C04/C05/C06/C08. **환경** `local_python`.

**파일** `src/aiqa/config.py`, `src/aiqa/models/provider_http.py`, `src/aiqa/models/broker.py`, `src/aiqa/api/app.py`.

- [x] 모의 HTTPS endpoint에서 요청·응답, 잘못된 CA/주소, 키 누락, quota와 멱등성을 검증한다. 실제 모델 호출은 승인된 RX-23/24에서 수행한다.
- [x] 관리 서버가 승인된 공급자 주소와 secret ref를 읽어 실제 전송과 구조화 응답을 연결한다. fixture는 로컬 검증에서만 명시적으로 선택한다.
- [x] `python -m pytest -q tests/integration/test_rx_40.py`에서 지정 회귀를 검증한다. `docs/validation/tasks/RX-45.md`에 시험 명령과 실제 결과를 남긴다.

<a id="rx-46"></a>
## RX-46 · 현재 PC Android 운영 모델 사전 검증

**입력** RX-44 · RX-45와 C00/C01/C04/C05/C06/C08. **환경** `local_python`.

**파일** `src/aiqa/worker/http_client.py`, `src/aiqa/worker/android_jobs.py`, `src/aiqa/worker/runtime.py`, `src/aiqa/models/broker.py`, `tests/integration/test_rx_46.py`.

- [x] RX-23을 현재 PC 사전 검증(이 카드)과 독립 호스트·운영 키 최종 수용으로 분리한다. 모의 HTTPS 공급자 응답을 실제 워커 `model-requests`→녹화 행동에 연결하고, 승인본 digest·plan으로 trial/regression 재생(actor 0)을 검증한다.
- [x] `AIQA_WORKER_MODEL_MODE=operational`과 `AIQA_WORKER_APPROVED_DIGEST`/`AIQA_WORKER_APPROVED_PLAN`을 워커 진입점에 배선한다. 키 원문은 워커에 두지 않는다.
- [x] `python -m pytest -q tests/integration/test_rx_46.py`로 모의 HTTPS 사전 검증을 남긴다. `docs/validation/tasks/RX-46.md`에 결과와 제약을 기록한다.
