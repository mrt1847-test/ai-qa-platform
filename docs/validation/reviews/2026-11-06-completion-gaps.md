# 2026-11-06 완료 경로의 기능 공백

master 작업 트리의 소스와 RX-71 통합 시험을 대조했다. 이 검토에서는 제품 코드를 수정하지 않았다.

## 단독 재현

기존 `test_rx_71_browser_recording_trial_approve_suite_regression`을 임시 DB에서 그대로 실행했다. 각 `_release_lease` 직전 임대는 1건이었고, 테스트가 직접 cleanup-confirmations를 호출한 뒤 다음 작업이 진행됐다. 최종 DB에서 trial과 regression jobs는 completed였지만 `item_finalizations`는 0건이었다. `execution_scheduler.advance_execution`은 정의 외의 제품 호출 지점이 없었다.

## 기존 회귀 실행

`python -B -m pytest -q -p no:cacheprovider --tb=short --maxfail=3` 결과는 76 passed, 3 failed다. 중단된 전체 실행이며 전체 통과 주장으로 사용하지 않는다.

- `tests/acceptance/test_w11.py::test_w11_07`
- `tests/acceptance/test_w11.py::test_w11_01`
- `tests/acceptance/test_w12.py::test_w12_03`

W11은 페이지 전체의 button 금지 가정과 새 PC 등록 UI가 충돌한다. W12는 launcher 이후 `/ui/local` 접속에 실패한다. 오류 근거를 사용자 기능과 대조해 수정해야 한다.

## 남은 제품 연결

- `store/queue.py:finish_worker_attempt`의 정상 trial/regression은 ITEM 결과를 저장하는 경로 없이 job만 completed로 바꾼다.
- `worker/runtime.py`에는 handler가 정리 증명을 만들고 cleanup 확인을 제출하는 경로가 없다.
- `environments/app_builds.py`는 APK 조회와 검사 결과를 프로세스 전역 `_known`에 둔다. `worker/runtime.py`는 실제 Android 분기에도 `FixtureInstallDriver`를 조립한다.
- `worker/local_page.py`는 HTMLParser 기반 메모리 DOM이며 실제 브라우저 실행 포트가 아니다.
- RX-71 사용자 흐름은 ASGI API 호출이고 실제 화면의 JavaScript 입력/접수·결과 표시를 관찰한 증거는 아니다.

[RX-72~78](../../managed-pc/RESULTS_AND_NATIVE_TASKS.md)에 각 구현과 검증 단위를 지정했다. 실환경 수용 RX-21~27과 비용 RX-29의 기존 상태는 별도로 추적한다.
