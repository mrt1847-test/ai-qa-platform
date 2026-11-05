# Android 녹화·승인·회귀 구현 계획

> Current에 있는 카드 하나씩 로컬 계약 시험으로 구현한다. 실행 순서는 [NEXT_ACTION](../../NEXT_ACTION.md), 직접 선행과 상태는 [RX 색인](IMPLEMENTATION_TASKS.json)을 따른다. 기존 작업에 동등한 코드와 증거가 있으면 재사용한다.

**목표** 현재 PC에서 저장 케이스의 목표를 사용해 녹화하고, 증거를 검토한 뒤 승인본으로 회귀를 실행한다.

**검증 범위** 실제 앱 진입점과 임시 DB·파일을 사용한다. 외부 모델·ADB·guest 응답은 테스트 경계에서만 대체할 수 있다. UI가 바뀌면 로컬 브라우저에서 정상·오류·키보드 동선을 확인한다. 운영 장비·키·독립 호스트가 필요한 최종 검증은 [실환경 카드](ACCEPTANCE_TASKS.md)나 기존 W 검증에 따로 남긴다.

<a id="rx-47"></a>
## RX-47 · 케이스의 검증 목표를 녹화 작업에 전달

**입력** RX-46 · W16-01 및 C00/C01/C02/C04/C05/C06. **환경** `local_python`. **대응 범위** W16-01/04의 입력과 시작 경계. **별도 수용** RX-23 · RX-24.

**파일** `src/aiqa/recording/service.py`, `src/aiqa/store/queue.py`, `src/aiqa/contracts/worker_attempt.py`, `src/aiqa/api/worker.py`, `src/aiqa/worker/android_jobs.py`, `tests/integration/test_rx_47.py`.

- [x] 브라우저 녹화 접수→claim→모의 모델 요청에서 목표가 전달되는지 확인한다. 접수 이후 케이스 편집과 claim 응답 유실 후에도 동일한 목표인지, 외부 프로젝트·위조 hash·비밀 원문이 차단되는지 검사한다.
- [x] RecordingIntent에 선택 버전 ID와 해시, objective, 허용된 precondition·step·Check, 공개 변수 및 비밀 참조만 담는다. 녹화 접수 시 저장 버전에 고정하고 claim receipt의 snapshot digest에 포함한다. 서버 모델 authoring은 이 목표를 입력으로 받는다.
- [x] `python -m pytest -q tests/integration/test_rx_47.py`를 실행한다.
- [x] `docs/validation/tasks/RX-47.md`에 실제 진입점, 검증 명령·결과, 제공 인터페이스와 남은 실환경 범위를 남긴다.

<a id="rx-48"></a>
## RX-48 · Android 여러 스텝 녹화

**입력** RX-47 · RX-43 · RX-38 및 C00/C01/C04/C05/C06. **환경** `local_python`. **대응 범위** W16-04의 녹화 루프. **별도 수용** RX-23.

**파일** `src/aiqa/worker/android_jobs.py`, `src/aiqa/worker/runtime.py`, `src/aiqa/adapters/mobile_agent_android.py`, `src/aiqa/worker/spool.py`, `tests/integration/test_rx_48.py`.

- [x] 모의 모델의 탭→스와이프→종료를 실행해 실제 전후 파일·로그를 각 스텝에 연결한다. 중간 취소·불명 dispatch·정제 실패에서 앞 스텝 보존과 이후 행동 0회를 확인한다.
- [x] 기존 한 스텝 실행을 반복해 관찰→authoring→typed action→전후 증거를 action_seq별로 처리한다. 모델의 종료 결정, 최대 행동·시간 예산, 취소·임대·watchdog를 적용한다.
- [x] `python -m pytest -q tests/integration/test_rx_48.py`를 실행한다.
- [x] `docs/validation/tasks/RX-48.md`에 실제 진입점, 검증 명령·결과, 제공 인터페이스와 남은 실환경 범위를 남긴다.

<a id="rx-49"></a>
## RX-49 · 녹화 중 타임라인과 스텝별 증거 조회

**입력** RX-43 · W16-03 및 C00/C01/C05/C08/C11. **환경** `local_python` · `local_browser`. **대응 범위** W16-04의 사용자 타임라인. **별도 수용** RX-23 · RX-24.

**파일** `src/aiqa/api/recordings.py`, `src/aiqa/web/templates/recording.html`, `src/aiqa/web/static/evidence_viewer.js`, `tests/acceptance/test_rx_49.py`.

- [x] 임시 서버에 두 스텝을 시간차로 넣고 브라우저에서 순서, 키보드 선택, 오프라인의 서버 저장 증거 조회와 다른 프로젝트 접근 차단을 확인한다.
- [x] 기존 녹화 상세에서 서버에 ACK된 action 순서와 상태, 전후 PNG와 로그, 미수신·오류 상태를 표시한다. 선택 스텝을 유지하며 진행을 갱신한다.
- [x] `python -m pytest -q tests/acceptance/test_rx_49.py`를 실행한다. 실제 로컬 브라우저 확인도 기록한다.
- [x] `docs/validation/tasks/RX-49.md`에 실제 진입점, 검증 명령·결과, 제공 인터페이스와 남은 실환경 범위를 남긴다.

<a id="rx-50"></a>
## RX-50 · 저장 녹화에서 Android 재생 패키지 생성

**입력** RX-48 · W30-02 및 C00/C01/C05/C07/C08. **환경** `local_python`. **대응 범위** W16-07 / W30-03의 패키지 경계. **별도 수용** RX-23.

**파일** `src/aiqa/recording/service.py`, `src/aiqa/recording/manifests.py`, `src/aiqa/replay/android_plan.py`, `src/aiqa/replay/packages.py`, `tests/integration/test_rx_50.py`.

- [x] 같은 소스 재시도 시 같은 결과, 누락·오염·지원하지 않는 action의 재생 차단, 기존 승인 패키지 digest 불변을 확인한다.
- [x] 완료한 manifest에서 typed action·순서·geometry·증거 참조를 읽어 해당 녹화 버전에 불변 재생 패키지를 만든다. 복구나 재녹화 결과는 새 버전으로 보존한다.
- [x] `python -m pytest -q tests/integration/test_rx_50.py`를 실행한다.
- [x] `docs/validation/tasks/RX-50.md`에 실제 진입점, 검증 명령·결과, 제공 인터페이스와 남은 실환경 범위를 남긴다.

<a id="rx-51"></a>
## RX-51 · 서버 고정 패키지로 Android 시범·회귀 실행

**입력** RX-50 · RX-34 · W17-03 및 C00/C01/C04/C07/C08/C09. **환경** `local_python`. **대응 범위** W17-04 / W30-03의 실행 연결. **별도 수용** RX-23.

**파일** `src/aiqa/api/worker.py`, `src/aiqa/store/queue.py`, `src/aiqa/domain/executions.py`, `src/aiqa/worker/runtime.py`, `src/aiqa/worker/android_jobs.py`, `tests/integration/test_rx_51.py`.

- [x] 다른 케이스 두 건을 실행해 각 패키지가 선택되고 일반 replay 모델 호출이 0인지, 위조 digest·다른 프로젝트·없는 package가 차단되는지 확인한다.
- [x] trial은 검토할 후보 버전, regression은 승인 스냅샷에 있는 package ID·digest로 읽는다. 운영 worker가 전역 환경의 재생 계획 대신 claim에 고정된 참조를 사용한다. trial의 healing은 OFF다.
- [x] `python -m pytest -q tests/integration/test_rx_51.py`를 실행한다.
- [x] `docs/validation/tasks/RX-51.md`에 실제 진입점, 검증 명령·결과, 제공 인터페이스와 남은 실환경 범위를 남긴다.

<a id="rx-52"></a>
## RX-52 · 시범 증거를 보고 승인하는 사용자 흐름

**입력** RX-49 · RX-51 · W19-03 및 C00/C01/C07/C08/C11. **환경** `local_python` · `local_browser`. **대응 범위** W17-04 / W19-04의 승인 여정. **별도 수용** RX-23 · RX-25.

**파일** `src/aiqa/recording/review_manifest.py`, `src/aiqa/api/recordings.py`, `src/aiqa/web/templates/case_review.html`, `src/aiqa/web/routes.py`, `tests/acceptance/test_rx_52.py`.

- [x] 브라우저에서 녹화→trial→스텝 확인→승인과 다른 버전·누락 증거·치유된 trial 거절을 확인한다. 재녹화에서 기존 승인본은 보존한다.
- [x] 현재 녹화 버전과 같은 패키지의 healing OFF trial과 검토 결과를 사용해 사람이 승인한다. 필수 증거가 이미 서버에 저장됐다면 worker 오프라인에도 조회·승인할 수 있게 기존 gate를 연결한다.
- [x] `python -m pytest -q tests/acceptance/test_rx_52.py`를 실행한다. 실제 로컬 브라우저 확인도 기록한다.
- [x] `docs/validation/tasks/RX-52.md`에 실제 진입점, 검증 명령·결과, 제공 인터페이스와 남은 실환경 범위를 남긴다.

<a id="rx-53"></a>
## RX-53 · 승인 버전을 묶음 회귀에 연결

**입력** RX-52 · UX-03 · W22-03 및 C00/C01/C08/C09/C10. **환경** `local_python` · `local_browser`. **대응 범위** W22-04의 묶음 실행과 결과. **별도 수용** RX-25.

**파일** `src/aiqa/domain/executions.py`, `src/aiqa/domain/execution_scheduler.py`, `src/aiqa/api/executions.py`, `src/aiqa/web/templates/execution.html`, `tests/acceptance/test_rx_53.py`.

- [x] 임시 DB의 두 승인 케이스로 성공·실패·취소를 섞어 확인한다. 중간 편집 이후 기존 RUN의 원본 버전과 결과가 보존되는지 검사한다.
- [x] 선택한 묶음 revision이 가리키는 승인 스냅샷으로 각 ITEM을 실행한다. 케이스별 verdict와 증거, 취소·부분 완료·명시적 재실행을 기존 기록과 연결한다.
- [x] `python -m pytest -q tests/acceptance/test_rx_53.py`를 실행한다. 실제 로컬 브라우저 확인도 기록한다.
- [x] `docs/validation/tasks/RX-53.md`에 실제 진입점, 검증 명령·결과, 제공 인터페이스와 남은 실환경 범위를 남긴다.

<a id="rx-54"></a>
## RX-54 · 실행 Check와 제한된 self-healing 연결

**입력** RX-31 · W31-06 및 C00/C01/C05/C06/C07/C09. **환경** `local_python`. **대응 범위** W31-07에서 실기기 검증 전 필요한 기능. **별도 수용** RX-23 · RX-24.

**파일** `src/aiqa/worker/runner.py`, `src/aiqa/healing/service.py`, `src/aiqa/models/broker.py`, `src/aiqa/domain/executions.py`, `tests/integration/test_rx_54.py`.

- [x] 모의 두 플랫폼에서 actor 0, OFF·예산 초과 호출 0, 허용 ON의 제한된 호출과 원래 실패·복구 결과 분리, timeout 시 실패 보존을 확인한다.
- [x] 실행기는 결정적 Check 우선과 필요 시 AI 검증을 사용한다. 실패 후 healing 명시 ON과 예산·승인 대상 조건이 맞을 때만 시도하고 기존 승인본 및 원래 결과를 보존한다. Android·Web에서 쓰는 공통 포트를 고정한다.
- [x] `python -m pytest -q tests/integration/test_rx_54.py`를 실행한다.
- [x] `docs/validation/tasks/RX-54.md`에 실제 진입점, 검증 명령·결과, 제공 인터페이스와 남은 실환경 범위를 남긴다.
