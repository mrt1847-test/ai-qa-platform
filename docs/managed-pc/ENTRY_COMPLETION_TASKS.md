# 정상 실행 경로의 기능 보완

2026-11-05 · [현재 큐](../../NEXT_ACTION.md) · [코드 대조와 재현](../validation/reviews/2026-11-05-feature-entry-gaps.md)

기존 RX-47~62의 개별 계약과 증거를 재사용한다. 이번 카드는 정상 API·프로세스 진입점에서 발견한 공백을 구현한다. 직접 제공한 모의 핸들러의 성공만으로 일반 제품 경로가 연결됐다고 판정하지 않는다. 외부 모델·기기·guest는 테스트 경계에서 대체하고, 앱의 설정·소유·상태 전이를 그대로 검증한다.

<a id="rx-63"></a>
## RX-63 · 기존 UI·API 회귀와 자원 스키마 호환

**직접 선행** RX-62 · RX-28. **공통 계약** C00/C01/C04/C05/C06/C08 및 소유 도메인 절. **환경** `local_python`. **별도 수용** RX-21 · RX-23.

**확인 근거** RX·UX 검사에서 resource_aliases가 5열인데 4개 값을 넣는 기존 등록 화면 시험이 실패했다.

**파일** `tests/acceptance/test_rx_28.py`, `tests/conftest.py`, `tests/worker_presence_support.py`, `src/aiqa/contracts/resources.py`, `tests/integration/test_rx_63.py`.

- [x] RX 등록 UI를 먼저 재현하고 RX·UX 관련 회귀를 실행한다. 기존 acceptance도 실패부터 순차 확인해 각 결함을 해당 제품 소유 코드에서 수정한다. 실패 테스트를 제거하거나 판정을 약화하지 않는다.
- [x] 기존 fixture INSERT에 열 이름을 명시하고 현재·이전 데이터의 조회/등록 호환을 확인한다. 유사한 기존 시험과 실제 스키마·API 충돌을 찾아 필요한 최소 변경만 적용한다.
- [x] `python -m pytest -q tests/integration/test_rx_63.py` 및 카드에 영향받는 기존 시험을 통과시킨다. RX-63은 기존 RX-28 실패를 고치는 범위에서 회귀를 재사용하고 필요하지 않은 새 시험은 생략한다.
- [x] `docs/validation/tasks/RX-63.md`에 정상 진입점·관측 결과·추가/재사용 코드·명령·실환경 제한을 남긴다.

완료 근거: [RX-63.md](../validation/tasks/RX-63.md).

<a id="rx-64"></a>
## RX-64 · 연속 녹화의 시도별 상태와 중단 결과

**직접 선행** RX-48 · RX-38. **공통 계약** C00/C01/C04/C05/C06/C08 및 소유 도메인 절. **환경** `local_python`. **별도 수용** RX-23.

**확인 근거** 같은 핸들러에서 첫 녹화 1회 후 두 번째 1회를 실행하면 actions=2가 반환됐다. 중간 취소도 outcome=completed, evidence_complete=True였다.

**파일** `src/aiqa/worker/android_jobs.py`, `src/aiqa/worker/runtime.py`, `tests/integration/test_rx_48.py`, `tests/integration/test_rx_64.py`.

- [x] 한 워커에 작업 두 건을 정상 entry로 투입해 각 행동 수·서로 다른 증거 owner를 확인한다. 중간 취소와 두 번째 스텝의 timeout/누락을 서버까지 보내 완료·승인 준비를 잘못 올리지 않는지 확인한다.
- [x] 카운터·시간 원점·device 준비·검증 context를 attempt마다 초기화한다. 취소·예산 소진·후 캡처 실패·미확정 dispatch를 성공 완료와 구분하고 앞 스텝의 증거를 보존한다.
- [x] `python -m pytest -q tests/integration/test_rx_64.py` 및 카드에 영향받는 기존 시험을 통과시킨다. RX-63은 기존 RX-28 실패를 고치는 범위에서 회귀를 재사용하고 필요하지 않은 새 시험은 생략한다.
- [x] `docs/validation/tasks/RX-64.md`에 정상 진입점·관측 결과·추가/재사용 코드·명령·실환경 제한을 남긴다.

완료 근거: [RX-64.md](../validation/tasks/RX-64.md).

<a id="rx-65"></a>
## RX-65 · 현재 화면을 본 뒤 모델이 다음 행동 결정

**직접 선행** RX-47 · RX-48 · RX-46. **공통 계약** C00/C01/C04/C05/C06/C08 및 소유 도메인 절. **환경** `local_python`. **별도 수용** RX-23.

**확인 근거** 실제 녹화는 model plan 요청을 before=live()보다 먼저 하고, worker 입력은 sanitized 문자열과 intent_hash만 보냈다.

**파일** `src/aiqa/worker/android_jobs.py`, `src/aiqa/models/provider_http.py`, `src/aiqa/api/worker.py`, `src/aiqa/models/broker.py`, `tests/integration/test_rx_65.py`.

- [x] 서로 다른 두 관찰에 대해 모의 공급자가 각 관찰을 보고 다른 행동을 반환하게 한다. 캡처 또는 정제가 실패하면 모델·기기 호출 0, 모델 종료 결정 시 기기 동작 0을 확인한다.
- [x] 관찰→정제→모델 요청→응답 해석→journal→dispatch 순서로 바꾼다. 관찰 ID·geometry·필요한 정제 화면/계층·직전 단계 결과를 서버 broker와 공급자 payload에 연결한다. hash와 원본 화면·비밀 범위를 구분한다.
- [x] `python -m pytest -q tests/integration/test_rx_65.py` 및 카드에 영향받는 기존 시험을 통과시킨다. RX-63은 기존 RX-28 실패를 고치는 범위에서 회귀를 재사용하고 필요하지 않은 새 시험은 생략한다.
- [x] `docs/validation/tasks/RX-65.md`에 정상 진입점·관측 결과·추가/재사용 코드·명령·실환경 제한을 남긴다.

완료 근거: [RX-65.md](../validation/tasks/RX-65.md).

<a id="rx-66"></a>
## RX-66 · 승인된 여러 스텝 실제 재생과 동작 후 검증

**직접 선행** RX-51 · RX-54. **공통 계약** C00/C01/C04/C05/C06/C08 및 소유 도메인 절. **환경** `local_python`. **별도 수용** RX-23.

**확인 근거** 재생 핸들러는 approved_plan을 한 번 replay_step에 넘기고, 실제 builder는 실행 전에 before/after를 둘 다 캡처했다. _QuietVerify는 고정 satisfied를 반환한다.

**파일** `src/aiqa/worker/android_jobs.py`, `src/aiqa/replay/android_plan.py`, `src/aiqa/replay/android_runner.py`, `tests/integration/test_rx_51.py`, `tests/integration/test_rx_66.py`.

- [x] 서버에서 만든 두 스텝 패키지를 정상 claim으로 실행해 순서와 전후 시각·바이트를 확인한다. 실제 기대가 깨진 관찰은 실패로 남고, 잘못된 digest·기한·취소에서 이후 입력 0을 확인한다.
- [x] 패키지의 모든 step을 순서대로 실행하고 각 행동 직후에 새 관찰을 얻는다. 실제 Check는 그 관찰로 계산하고 필요한 AI 검증만 서버 broker로 보낸다. 정상 actor·OFF healer는 0회, trial은 healing OFF를 적용한다.
- [x] `python -m pytest -q tests/integration/test_rx_66.py` 및 카드에 영향받는 기존 시험을 통과시킨다. RX-63은 기존 RX-28 실패를 고치는 범위에서 회귀를 재사용하고 필요하지 않은 새 시험은 생략한다.
- [x] `docs/validation/tasks/RX-66.md`에 정상 진입점·관측 결과·추가/재사용 코드·명령·실환경 제한을 남긴다.

완료 근거: [RX-66.md](../validation/tasks/RX-66.md).

<a id="rx-67"></a>
## RX-67 · 행동별 서버 증거 ACK와 실시간 타임라인

**직접 선행** RX-48 · RX-49 · RX-43. **공통 계약** C00/C01/C04/C05/C06/C08 및 소유 도메인 절. **환경** `local_python` · `local_browser`. **별도 수용** RX-23 · RX-25.

**확인 근거** 녹화 핸들러가 all_events/all_artifacts를 끝까지 메모리에 모으고 반환한 뒤 runtime이 commit한다. 진행 중 서버 타임라인에 새 증거가 도달하지 않는다.

**파일** `src/aiqa/worker/android_jobs.py`, `src/aiqa/worker/runtime.py`, `src/aiqa/worker/http_client.py`, `src/aiqa/api/recordings.py`, `tests/acceptance/test_rx_67.py`.

- [ ] 두 번째 스텝을 보류한 상태에서 첫 스텝 PNG·로그를 API/브라우저로 조회한다. commit 응답 유실과 재전송에서 중복 행동 0·파일 bytes 동일·미ACK 삭제 0을 확인한다.
- [ ] 행동별 로컬 spool과 서버 commit·ACK를 연결하고 ACK된 prefix를 유지한다. 다음 스텝에서 프로세스가 종료돼도 이전 증거가 조회되고 녹화는 미완료 상태로 남게 한다.
- [ ] `python -m pytest -q tests/acceptance/test_rx_67.py` 및 카드에 영향받는 기존 시험을 통과시킨다. RX-63은 기존 RX-28 실패를 고치는 범위에서 회귀를 재사용하고 필요하지 않은 새 시험은 생략한다.
- [ ] `docs/validation/tasks/RX-67.md`에 정상 진입점·관측 결과·추가/재사용 코드·명령·실환경 제한을 남긴다.

<a id="rx-68"></a>
## RX-68 · 앱 조회·설치·초기화를 실제 워커에 등록

**직접 선행** RX-56 · RX-57 · RX-62. **공통 계약** C00/C01/C04/C05/C06/C08 및 소유 도메인 절. **환경** `local_python` · `local_browser`. **별도 수용** RX-23.

**확인 근거** InstalledAppsProbeHandler와 AppInstallHandler는 있지만 일반 run_worker_process의 Android 조립에는 등록돼 있지 않다.

**파일** `src/aiqa/worker/runtime.py`, `src/aiqa/worker/android_jobs.py`, `src/aiqa/api/resources.py`, `src/aiqa/api/app_builds.py`, `tests/acceptance/test_rx_68.py`.

- [ ] 사용자 API 요청부터 별도 worker entry·모의 ADB까지 실행해 앱 목록과 설치 결과가 서버에 반영되는지 확인한다. 미허가 변경과 serial 위조는 0회이며 metadata-only 응답을 성공 설치로 표시하지 않는다.
- [ ] 자원 관리 목적을 허용된 등록 scope와 고정 물리 기기로 라우팅한다. claim payload와 결과 저장 경로를 연결해 화면에서 접수한 앱 조회/설치/reset의 진행·결과·정리 상태를 읽을 수 있게 한다.
- [ ] `python -m pytest -q tests/acceptance/test_rx_68.py` 및 카드에 영향받는 기존 시험을 통과시킨다. RX-63은 기존 RX-28 실패를 고치는 범위에서 회귀를 재사용하고 필요하지 않은 새 시험은 생략한다.
- [ ] `docs/validation/tasks/RX-68.md`에 정상 진입점·관측 결과·추가/재사용 코드·명령·실환경 제한을 남긴다.

<a id="rx-69"></a>
## RX-69 · 자연어 구조화를 서버 모델 설정에 연결

**직접 선행** RX-55 · RX-45. **공통 계약** C00/C01/C04/C05/C06/C08 및 소유 도메인 절. **환경** `local_python` · `local_browser`. **별도 수용** W16-02.

**확인 근거** request_structure의 기본 경로가 FixtureProviderHttp와 fixture model·secret을 직접 선택한다.

**파일** `src/aiqa/recording/structure.py`, `src/aiqa/api/cases.py`, `src/aiqa/models/broker.py`, `src/aiqa/models/provider_http.py`, `tests/acceptance/test_rx_69.py`.

- [ ] 일반 API로 서로 다른 자연어 두 건을 요청해 공급자 입력과 제안이 구분되는지 확인한다. API 반복 전송·stale base·401/429에서 중복 모델 호출·자동 적용·원문 노출을 막는다.
- [ ] 구조화 job에서 프로젝트 모델 binding·서버 secret ref·역할 예산을 사용한다. 일반 요청에 고정 구조화 응답을 기본값으로 넣지 않고, 설정 누락/응답 실패를 UI의 재시도 가능한 오류로 돌려준다. 수락은 새 버전으로 남긴다.
- [ ] `python -m pytest -q tests/acceptance/test_rx_69.py` 및 카드에 영향받는 기존 시험을 통과시킨다. RX-63은 기존 RX-28 실패를 고치는 범위에서 회귀를 재사용하고 필요하지 않은 새 시험은 생략한다.
- [ ] `docs/validation/tasks/RX-69.md`에 정상 진입점·관측 결과·추가/재사용 코드·명령·실환경 제한을 남긴다.

<a id="rx-70"></a>
## RX-70 · Web 신뢰 driver의 실제 브라우저 호출 연결

**직접 선행** RX-60 · RX-61. **공통 계약** C00/C01/C04/C05/C06/C08 및 소유 도메인 절. **환경** `local_python`. **별도 수용** RX-22 · RX-24.

**확인 근거** TrustedWebDriver.run은 runner가 없어도 native_calls를 증가시키고, Web entry는 fixture gate·관찰을 조립한다.

**파일** `src/aiqa/replay/driver.py`, `src/aiqa/worker/web_jobs.py`, `src/aiqa/worker/web_vm_transport.py`, `tests/integration/test_rx_70.py`.

- [ ] 로컬 전용 웹을 여는 브라우저 driver에서 click/fill/scroll의 실제 DOM 변화와 전후 capture를 확인한다. VM 부재는 격리 수용 RX-22에 남기고, 검증되지 않은 proof로 제품 ready를 올리지 않는다.
- [ ] 신뢰 영역의 전용 브라우저 session과 allowlist 동작·관찰 포트를 실제 worker에 연결한다. 실행 포트가 없으면 명시 차단하고 성공 count를 올리지 않는다. 생성 코드에는 raw CDP·Playwright 핸들을 넘기지 않는다.
- [ ] `python -m pytest -q tests/integration/test_rx_70.py` 및 카드에 영향받는 기존 시험을 통과시킨다. RX-63은 기존 RX-28 실패를 고치는 범위에서 회귀를 재사용하고 필요하지 않은 새 시험은 생략한다.
- [ ] `docs/validation/tasks/RX-70.md`에 정상 진입점·관측 결과·추가/재사용 코드·명령·실환경 제한을 남긴다.

<a id="rx-71"></a>
## RX-71 · 현재 PC의 브라우저부터 승인·회귀까지 연결

**직접 선행** RX-63 · RX-64 · RX-65 · RX-66 · RX-67 · RX-68 · RX-69. **공통 계약** C00/C01/C04/C05/C06/C08 및 소유 도메인 절. **환경** `local_python` · `local_browser`. **별도 수용** RX-23.

**확인 근거** 기존 증거는 개별 모의 핸들러·DB seed 시험이 중심이어서 실제 화면의 접수부터 승인본 회귀까지 동일한 버전으로 이어진 증거가 없다.

**파일** `tools/validation/probe_same_pc_stage.py`, `src/aiqa/web/templates/recording_setup.html`, `src/aiqa/web/templates/case_review.html`, `src/aiqa/web/templates/execution.html`, `tests/acceptance/test_rx_71.py`.

- [ ] 임시 데이터·로컬 모의 모델 공급자로 브라우저 조작부터 실제 entry를 실행한다. 중간 상태를 SQL로 완료시키거나 승인 gate를 우회하지 않는다. 최종 서버 파일 bytes·버전/패키지 hash·actor 호출 0·결과 조회를 기록한다.
- [ ] 정상 케이스 작성과 대상 선택, 녹화, 시범 실행, 증거 확인과 승인, 묶음 회귀를 현재 PC의 독립 API/worker·브라우저로 연결한다. 진행 중 발견한 API·UI·worker 누락은 해당 기능 코드에서 수정한다.
- [ ] `python -m pytest -q tests/acceptance/test_rx_71.py` 및 카드에 영향받는 기존 시험을 통과시킨다. RX-63은 기존 RX-28 실패를 고치는 범위에서 회귀를 재사용하고 필요하지 않은 새 시험은 생략한다.
- [ ] `docs/validation/tasks/RX-71.md`에 정상 진입점·관측 결과·추가/재사용 코드·명령·실환경 제한을 남긴다.

