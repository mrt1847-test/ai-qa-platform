# 케이스·설정·Web·복수 워커 구현 계획

> Current에 있는 카드 하나씩 로컬 계약 시험으로 구현한다. 실행 순서는 [NEXT_ACTION](../../NEXT_ACTION.md), 직접 선행과 상태는 [RX 색인](IMPLEMENTATION_TASKS.json)을 따른다. 기존 작업에 동등한 코드와 증거가 있으면 재사용한다.

**목표** Android 핵심 동선과 독립적으로 사용자 기능 및 Web·호스팅의 실행 코드를 구현한다.

**검증 범위** 실제 앱 진입점과 임시 DB·파일을 사용한다. 외부 모델·ADB·guest 응답은 테스트 경계에서만 대체할 수 있다. UI가 바뀌면 로컬 브라우저에서 정상·오류·키보드 동선을 확인한다. 운영 장비·키·독립 호스트가 필요한 최종 검증은 [실환경 카드](ACCEPTANCE_TASKS.md)나 기존 W 검증에 따로 남긴다.

<a id="rx-55"></a>
## RX-55 · 케이스 자연어 구조화와 제안 수락

**입력** W16-01 · W10-07 · RX-45 및 C00/C01/C02/C06/C11/C12. **환경** `local_python` · `local_browser`. **대응 범위** W16-02의 구현. **별도 수용** W16-02.

**파일** `src/aiqa/domain/proposals.py`, `src/aiqa/api/cases.py`, `src/aiqa/worker/runtime.py`, `src/aiqa/web/static/proposals.js`, `tests/acceptance/test_rx_55.py`.

- [x] 모의 모델로 제안→비교→수락과 실패·다른 버전·비밀 원문 차단을 브라우저/API에서 확인한다.
- [x] 저장한 자연어에서 구조화 제안 job을 실행하고 현재 버전과의 변경을 표시한다. 수락 시 새 정의를 만들고 취소·충돌은 원본을 보존한다.
- [x] `python -m pytest -q tests/acceptance/test_rx_55.py`를 실행한다. 실제 로컬 브라우저 확인도 기록한다.
- [x] `docs/validation/tasks/RX-55.md`에 실제 진입점, 검증 명령·결과, 제공 인터페이스와 남은 실환경 범위를 남긴다.

<a id="rx-56"></a>
## RX-56 · Android 설치 앱 조회와 선택

**입력** RX-32 · W11-03 및 C00/C01/C03/C04/C05/C11. **환경** `local_python` · `local_browser`. **대응 범위** W11-04의 구현. **별도 수용** W11-04.

**파일** `src/aiqa/environments/usb_android.py`, `src/aiqa/worker/android_jobs.py`, `src/aiqa/api/resources.py`, `src/aiqa/web/templates/recording_setup.html`, `tests/acceptance/test_rx_56.py`.

- [x] 모의 ADB에 앱 두 개와 offline·다른 serial·권한 거절을 주고 선택과 조회를 확인한다. 조회 중 설치나 reset은 0회다.
- [x] lease가 있는 지정 Android의 읽기 전용 installed_apps 결과를 저장하고 녹화 준비 화면에서 선택한다. 과거 관찰에는 시각을 표시한다.
- [x] `python -m pytest -q tests/acceptance/test_rx_56.py`를 실행한다. 실제 로컬 브라우저 확인도 기록한다.
- [x] `docs/validation/tasks/RX-56.md`에 실제 진입점, 검증 명령·결과, 제공 인터페이스와 남은 실환경 범위를 남긴다.

완료 근거: [RX-56.md](../validation/tasks/RX-56.md).

<a id="rx-57"></a>
## RX-57 · 명시 Android 설치·초기화와 사후 확인

**입력** RX-56 · W11-05 및 C00/C01/C03/C04/C05/C11. **환경** `local_python` · `local_browser`. **대응 범위** W11-06의 구현. **별도 수용** W11-06.

**파일** `src/aiqa/environments/app_builds.py`, `src/aiqa/worker/android_jobs.py`, `src/aiqa/api/app_builds.py`, `src/aiqa/web/templates/app_builds.html`, `tests/acceptance/test_rx_57.py`.

- [x] 모의 driver에서 승인되지 않은 변경 0회, 잘못된 digest와 취소·설치 실패에서 ready 금지, 동일 요청 재전송의 중복 설치 0을 확인한다.
- [x] 사용자가 지정한 build와 serial에 명시 요청을 접수하고 기존 허용·임대 정책 하에서만 설치·reset한다. 사후 관찰과 실패·정리 대기를 저장한다.
- [x] `python -m pytest -q tests/acceptance/test_rx_57.py`를 실행한다. 실제 로컬 브라우저 확인도 기록한다.
- [x] `docs/validation/tasks/RX-57.md`에 실제 진입점, 검증 명령·결과, 제공 인터페이스와 남은 실환경 범위를 남긴다.

완료 근거: [RX-57.md](../validation/tasks/RX-57.md).

<a id="rx-58"></a>
## RX-58 · 모델 연결 검사 화면과 결과 저장

**입력** RX-45 · W15-03 및 C00/C01/C06/C11. **환경** `local_python` · `local_browser`. **대응 범위** W15-04의 구현. **별도 수용** W15-04.

**파일** `src/aiqa/api/model_bindings.py`, `src/aiqa/domain/model_bindings.py`, `src/aiqa/api/worker.py`, `src/aiqa/web/routes.py`, `tests/acceptance/test_rx_58.py`.

- [x] 모의 공급자의 성공·401·429·timeout과 키 없음, 기존 승인 재생이 모델 키 없이 가능한 경우를 UI와 API에서 검사한다.
- [x] 설정의 모델 binding별 검사 요청과 결과를 연결한다. 키 누락·권한·호환·제한을 사용자에게 표시하며 키 원문과 불필요한 호출을 방지한다.
- [x] `python -m pytest -q tests/acceptance/test_rx_58.py`를 실행한다. 실제 로컬 브라우저 확인도 기록한다.
- [x] `docs/validation/tasks/RX-58.md`에 실제 진입점, 검증 명령·결과, 제공 인터페이스와 남은 실환경 범위를 남긴다.

완료 근거: [RX-58.md](../validation/tasks/RX-58.md).

<a id="rx-59"></a>
## RX-59 · 운영 브라우저 OIDC 로그인 연결

**입력** RX-41 및 C00/C01/C01/C08/C11. **환경** `local_python` · `local_browser`. **대응 범위** RX-21의 코드 선행. **별도 수용** RX-21.

**파일** `src/aiqa/security/oidc.py`, `src/aiqa/api/oidc_login.py`, `src/aiqa/api/auth.py`, `src/aiqa/web/routes.py`, `tests/acceptance/test_rx_59.py`.

- [x] 로컬 시험 IdP에서 브라우저 왕복, 잘못된 서명·만료·state 재사용·비회원 거절을 확인한다. 운영 호스트·IdP 등록은 RX-21에 남긴다.
- [x] 브라우저 로그인 시작·등록 redirect URI의 콜백·토큰 교환·세션을 연결한다. 서버에서 state/nonce/PKCE 및 설정된 발급자의 ID 토큰 서명·만료·권한을 검증한다.
- [x] `python -m pytest -q tests/acceptance/test_rx_59.py`를 실행한다. 실제 로컬 브라우저 확인도 기록한다.
- [x] `docs/validation/tasks/RX-59.md`에 실제 진입점, 검증 명령·결과, 제공 인터페이스와 남은 실환경 범위를 남긴다.

완료 근거: [RX-59.md](../validation/tasks/RX-59.md).

<a id="rx-60"></a>
## RX-60 · Web guest·브라우저 실행 설정과 안전한 연결

**입력** RX-35 · RX-42 및 C00/C01/C03/C04/C05/C07. **환경** `local_python`. **대응 범위** W07-02 / W29-03의 실행 연결. **별도 수용** RX-22 · RX-24.

**파일** `src/aiqa/worker/web_vm_transport.py`, `src/aiqa/worker/isolated_web.py`, `src/aiqa/worker/runtime.py`, `src/aiqa/replay/driver.py`, `tests/integration/test_rx_60.py`.

- [x] 별도 로컬 시험 guest 프로세스에서 연결·종료·timeout·다른 origin·잘못된 proof를 검증한다. VM 보안 검증은 RX-22에 남긴다.
- [x] 실행 설정으로 승인된 guest endpoint와 전용 대상 origin을 읽어 실제 worker 명령에 Web handler를 조립한다. guest proof·권한 확인 전 실행 불가 상태를 유지한다.
- [x] `python -m pytest -q tests/integration/test_rx_60.py`를 실행한다.
- [x] `docs/validation/tasks/RX-60.md`에 실제 진입점, 검증 명령·결과, 제공 인터페이스와 남은 실환경 범위를 남긴다.

완료 근거: [RX-60.md](../validation/tasks/RX-60.md).

<a id="rx-61"></a>
## RX-61 · Web 녹화와 승인 패키지 재생의 공통 계약

**입력** RX-60 · RX-47 · RX-54 및 C00/C01/C04/C05/C06/C07/C08. **환경** `local_python`. **대응 범위** W16-04 / W29-05의 Web 구현. **별도 수용** RX-24.

**파일** `src/aiqa/worker/web_jobs.py`, `src/aiqa/adapters/cuawright_web.py`, `src/aiqa/replay/driver.py`, `src/aiqa/api/worker.py`, `tests/integration/test_rx_61.py`.

- [x] 시험 guest와 전용 로컬 웹 fixture에서 두 행동·파일 저장·digest pin·actor 0·미검증 proof 시 0회를 확인한다. 실제 격리와 운영 키는 RX-22/24에서 검증한다.
- [x] Web authoring과 승인본 재생의 입력을 서버 작업에 고정한다. step code와 증거 bytes를 저장하고 같은 패키지로 trial/회귀를 실행하며 공통 Check·healing 포트를 사용한다.
- [x] `python -m pytest -q tests/integration/test_rx_61.py`를 실행한다.
- [x] `docs/validation/tasks/RX-61.md`에 실제 진입점, 검증 명령·결과, 제공 인터페이스와 남은 실환경 범위를 남긴다.

완료 근거: [RX-61.md](../validation/tasks/RX-61.md).

<a id="rx-62"></a>
## RX-62 · 복수 워커의 물리 자원 식별·임대

**입력** RX-03 · RX-05 · RX-38 및 C00/C01/C03/C04/C05. **환경** `local_python`. **대응 범위** RX-27의 코드 선행. **별도 수용** RX-27.

**파일** `src/aiqa/worker/resources.py`, `src/aiqa/store/queue.py`, `src/aiqa/api/resources.py`, `src/aiqa/config.py`, `tests/integration/test_rx_62.py`.

- [x] 임시 DB와 두 워커 fixture로 동시 claim, 동일 자원 중복 제어 차단, 다른 자원 독립, 세대 만료·정리 증거 없는 재할당 거절을 확인한다.
- [x] 등록 별칭과 공통 물리 자원 ID를 분리한다. 초기 슬롯 1을 기본값으로 유지하고 슬롯을 명시한 검증 환경에서 같은 자원은 하나만 임대하고 다른 자원은 독립 처리한다.
- [x] `python -m pytest -q tests/integration/test_rx_62.py`를 실행한다.
- [x] `docs/validation/tasks/RX-62.md`에 실제 진입점, 검증 명령·결과, 제공 인터페이스와 남은 실환경 범위를 남긴다.

완료 근거: [RX-62.md](../validation/tasks/RX-62.md).
