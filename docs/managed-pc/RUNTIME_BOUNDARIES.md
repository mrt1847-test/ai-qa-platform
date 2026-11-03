# 등록 실행 PC와 독립 관리 서버 구현 경계

2026-11-03 · [확정 배치](../superpowers/specs/2026-11-02-managed-pc-execution-design.md) · [실행 큐](../../NEXT_ACTION.md) · [카드 색인](IMPLEMENTATION_TASKS.json)

현재 PC를 첫 실행 자원으로 등록한다. 독립 관리 서버가 로그인, job/lease, DB, 증거, 검토와 승인을 소유한다. 접속 PC는 브라우저에서 이 서버에 접속한다. 실행 PC의 워커는 HTTPS outbound로 제어와 증거를 교환하고 자신에게 연결된 Android 또는 격리 브라우저만 사용한다.

## 기존 코드에서 이어갈 지점

| 경계 | 코드 조사 결과 | 구현 카드 |
| --- | --- | --- |
| 프로세스 | `src/aiqa/launcher.py`의 `main`에서 worker는 sleep loop다. `src/aiqa/config.py`의 `load_settings`는 loopback 개발 배치를 전제한다. | RX-08, RX-16 |
| 제어·세대 | `src/aiqa/api/worker.py`의 `install_worker`가 heartbeat, claim, ACK, renew, event를 제공한다. `src/aiqa/worker/service.py`의 `acknowledge_attempt`와 `reconcile_jobs`는 서버 프로세스가 얻은 boot ID를 사용한다. `src/aiqa/store/queue.py`의 `claim_queued_job`, `reconcile_stored`, `finish_job`은 서버 상태 전이로 재사용한다. `src/aiqa/worker/control.py`의 `RunControl`은 로컬 DB를 참조하므로 원격 모드에 시간 제한과 제어 응답만 넘긴다. | RX-01~05, RX-07 |
| 인증·자원 | `src/aiqa/api/auth.py`의 `enroll_worker`와 `worker_scope_from_token`을 재사용한다. `authorize_page`는 loopback 전제, `authorize_browser`는 세션·Origin·CSRF 경계다. 현재 inventory와 UI는 `src/aiqa/api/resources.py` 및 PC-03 결과에서 이어간다. | RX-02, RX-09, RX-16~17, RX-28 |
| 증거·종료 | `src/aiqa/worker/spool.py`의 `EvidenceSpool.append/acknowledge/purge`, `src/aiqa/store/artifact_ingest.py`의 upload policy, `src/aiqa/store/evidence.py`의 서버 ingest를 유지한다. `src/aiqa/store/artifacts.py`의 `require_ready_artifacts`와 `src/aiqa/recording/service.py`의 `finish_recording`을 승인과 분리된 저장 경로로 사용한다. | RX-06~07, RX-18 |
| Android | `src/aiqa/environments/android_observation.py`의 `AndroidObservationProvider.observe`는 명시 serial을 사용한다. 캡처는 정제 이전 데이터다. `src/aiqa/replay/android_runner.py`의 `AndroidPreflight.dispatch`는 현재 대상을 해석하는 경계다. `src/aiqa/recording/action_executor.py`의 행동 단계와 결합한다. | RX-09~10, RX-12 |
| Web | `src/aiqa/replay/driver.py`의 `TrustedWebDriver.dispatch`는 IPC 파싱 단계다. `src/aiqa/replay/ipc.py`의 `parse_ipc_message`, `src/aiqa/replay/compiler.py`의 패키지 생성, `src/aiqa/worker/isolated_web.py`의 `probe_web_isolation`을 이어 쓴다. 실제 backend와 우회 차단 증거가 필요하다. | RX-13~15, RX-22, RX-30 |
| 모델·비밀·복원 | `src/aiqa/models/broker.py`의 `ModelBroker.admit/meter`를 서버 전송 포트에 연결한다. `src/aiqa/security/secrets.py`의 `resolve_secret`과 `_write_os`는 권한을 검사하고 Windows 자격 증명 저장소를 사용한다. `src/aiqa/store/backup.py`의 `create_backup/validate_restore/activate_restore`가 복구의 시작점이다. | RX-11, RX-19~21, RX-31 |

## 고정 엔진에서 가져올 범위

**Mobile-Agent**는 `81fa28b564ef7a695521500bc15a0e1324b2b394`의 Android 예제를 기준으로 한다. `run_gui_owl_1_5_for_mobile.py:main`은 캡처→`GUIOwlWrapper.predict_mm`→`parse_action`→`rescale_coordinates`→`AdbTools` 호출을 한 루프에서 수행한다. 작업 디렉터리를 교체하고 `utils.py:AdbTools._run`은 문자열 shell 실행을 사용한다. 이 저장소는 응답 해석과 좌표 변환을 검증한 뒤, 관리 서버 broker와 기존 typed driver로 연결한다. 입력과 모델 관찰 사이의 리사이즈 규칙은 실제 화면 fixture로 대조한다. ADB 서버와 지정 serial은 등록 실행 PC에 둔다. [고정 runner](https://github.com/X-PLUG/MobileAgent/blob/81fa28b564ef7a695521500bc15a0e1324b2b394/Mobile-Agent-v3.5/mobile_use/run_gui_owl_1_5_for_mobile.py#L145-L270) · [고정 utils](https://github.com/X-PLUG/MobileAgent/blob/81fa28b564ef7a695521500bc15a0e1324b2b394/Mobile-Agent-v3.5/mobile_use/utils.py) · [Android ADB](https://developer.android.com/tools/adb)

**CUAWright**는 `35dbcf389ce2d9a77eb22f539c79a1274ea53559`의 `LocalBrowserEnvironment._persist_step_code`와 `browser_session._cmd_step`을 Web 녹화 소스 경계로 삼는다. `LocalBrowserEnvironment._run_python_code` 및 `browser_session._run_step_code`는 생성 Python을 실행하며, `LocalWorkspace.execute`는 명령을 실행한다. 따라서 step 보존과 녹화 연결을 재사용하고, raw Playwright/CDP는 신뢰 driver에 남긴다. 생성 코드가 접근할 수 있는 동작은 격리된 typed IPC와 명시된 대상에 한정한다. Playwright context로 세션을 분리하고 VM·권한·네트워크 우회는 별도로 확인한다. [고정 browser 환경](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/src/cuawright/webwright/environments/local_browser.py#L410-L455) · [고정 step 실행기](https://github.com/microsoft/CUAWright/blob/35dbcf389ce2d9a77eb22f539c79a1274ea53559/src/cuawright/webwright/tools/browser_session.py#L706-L839) · [Playwright 연결 API](https://playwright.dev/python/docs/api/class-browsertype)

## 서버 프로필과 보안 결정

- 첫 운영 검증 후보는 **실행 PC와 별개의 Windows 관리 호스트**, 서비스 전용 계정, 로컬 영속 SQLite와 artifact 디스크, HTTPS reverse proxy, OIDC 로그인이다. 첫 버전은 DB writer 프로세스 한 개로 제한한다. 호스팅 상품, 공개 범위, DNS, IdP, 인증서, Web VM 제품은 실환경 확인 때 확정한다.
- 사용자 로그인과 워커 인증을 분리한다. 서버가 사용자 프로젝트 멤버십과 역할을 검사한다. 워커는 짧은 등록 코드와 폐기 가능한 프로젝트·worker 범위의 bearer를 사용한다. worker 프로세스는 공유 DB나 관리 파일 경로 대신 인증 HTTP만 사용한다. [OIDC Core](https://openid.net/specs/openid-connect-core-1_0.html) · [RFC 6750](https://www.rfc-editor.org/rfc/rfc6750)
- 모델 provider 자격증명은 관리 서버 계정에서 해석한다. Android/Web 워커와 생성 코드에는 모델 key를 주지 않는다. 실제 대상의 테스트 비밀 입력이 필요하면 기존 SecretRef·행동 허용 범위와 전후 픽셀 정제 gate를 적용한다. 서비스 재시작 후의 Credential Manager 읽기는 실제 서비스 계정으로 검증한다. [Windows CredWriteW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew)
- SQLite snapshot과 artifact manifest를 같은 백업 세대로 검증한다. 저장 서버를 복원한 뒤 증거 무결성, 검토와 승인, 구 worker 자동 실행 차단을 확인한다. 백업에는 비밀 참조와 재연결 절차를 남긴다. [SQLite Backup API](https://sqlite.org/backup.html)

## 저장·실행 장애의 공통 판정

1. 사용자가 케이스에서 대상과 입력을 선택하고 검증 의도를 입력한다. AI authoring 중 tap, swipe 등 실제 동작별 전후 화면과 로그를 정제해 남긴다. 서버가 연속 증거와 manifest를 commit한 뒤 worker에 ACK한다. 승인은 저장 완료 후 별도의 사람 작업이다. 재녹화는 새 후보이고 기존 승인본은 보존한다.
2. 서버는 등록 세대와 자원 fence를 확인하고 worker는 durable journal의 dispatch 기록을 보존한다. 전송 여부가 불명이면 자동 재전송을 막는다. 늦은 업로드는 복구 증거를 보존하되 terminal verdict나 승인 가능 상태를 덮지 않는다. 정리 증거가 들어오면 동일 fence의 임대를 풀고, 사용자가 명시 요청한 새 실행만 허용한다.
3. 실행 PC offline에도 ACK·필수 OFF trial·권한이 충족된 서버 저장본의 검토와 승인은 가능하다. 재녹화·시범·정식·묶음·재실행과 기기 현재 진단은 UI와 API에서 차단한다. 이전 관찰을 보여줄 때는 관찰 시각을 유지한다.
4. 재생은 승인 코드나 저장 action을 사용한다. 정상 재생 actor의 모델 호출은 0회다. AI 검증은 정책이 필요한 경우에만 사용한다. Self-healing은 기본 OFF이며 명시 ON과 허용된 실패·예산·권한 조건을 충족할 때만 호출한다.

## 카드 선택과 기존 이력

| 영역 | 현재 적용과 인계 |
| --- | --- |
| 원격 워커 | [RX-01~08](WORKER_TASKS.md). 서버 세대·인증·영수증·제어·증거·종료·소비를 각각 검증한다. |
| 엔진 | [RX-09~15, RX-30~31](ENGINE_TASKS.md). AD-01의 명시 serial 관찰을 재사용한다. AD-02의 inventory/선택은 RX-09·RX-23, AD-03의 행동/증거는 RX-10·RX-23, AD-04의 소비는 RX-08·RX-23으로 넘긴다. AD-02~04는 과거 개발 카드로 보존하고 자동 선택에서 제외한다. |
| 서버 | [RX-16~21, RX-28](SERVER_TASKS.md). 로그인·등록 화면·프로필·저장·비밀·복원 구현을 fixture에서 검증한 뒤 별도 호스트에서 수용한다. |
| 실환경 | [RX-22~27, RX-29](ACCEPTANCE_TASKS.md). W01-02의 격리 증거는 RX-13/30/22에, W29-05의 native Web 통합 증거는 RX-24에 대응한다. 이전 Windows Home/VM 차단 이력과 원래 gate를 보존한다. 실제 Web backend 부재 중 Android 수용과 워커/서버 작업은 독립 진행한다. 두 플랫폼의 전원 종료 수용 RX-25는 양쪽 준비 후 수행한다. |
| 선택 범위 | CF-01 상용 공급자 조사는 추후 요청이 있을 때 실행한다. 기존 W 완료 126/163은 local baseline이다. 과거 미완료 native 카드나 상용 공급자 조사를 현재 등록 PC 가지의 기본 선행으로 올리지 않는다. |

## 실행과 완료 기준

- NEXT_ACTION이 순서를 단독 소유한다. 원래 W·AD/UX·PC와 새 RX 색인을 ID로 합쳐 직접 선행이 완료되고 인계 파일이 있는 항목만 고려한다. 알려진 미가용 환경 또는 작업 승인이 필요한 카드는 대기에 둔다. core 작업과 UX 독립 후보를 계속 선택할 수 있다.
- RX-21~27, RX-29의 실제 환경 조건은 색인에 명시한다. 현재 독립 서버/운영 인증, Web VM, 운영 모델 키, 두 워커 경합 환경의 준비는 확인되지 않았다. 설치·배포·실제 모델 과금·전원/네트워크 차단은 해당 카드 실행 시 허용 범위를 확인한다. 운영 검증은 전용 테스트 계정·자원·케이스에만 한정한다.
- core 카드는 임시 DB/fixture/무작동 handler로 시험할 수 있다. UI 카드는 실제 브라우저의 키보드와 오류 경로도 확인한다. 실환경 카드는 필요한 실제 환경 증거가 있어야 완료된다. `docs/validation/tasks/<ID>.md`에 명령, 결과, 수정 파일, 인터페이스, 제약과 다음 소비자가 확인할 증거를 남긴다. 기존 W/AD 상태와 RX 상태는 별도로 추적한다.
