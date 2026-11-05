# 정상 실행 경로 보완 근거

2026-11-05 (Asia/Seoul) · master 작업 트리 read-only 조사. 제품 코드 수정은 이 검토 범위에 포함하지 않았다.

## 확인한 회귀

RX·UX 카드 시험을 모아 실행한 결과 132 passed, 1 failed였다. RX-28의 등록 UI 시험이 `resource_aliases`의 5열에 4개 값을 넣어 실패했다. 기존 acceptance 전체도 순차 실행했으나 다수 실패가 관찰되어 완료 전 중단했다. 전체 시험의 최종 통과 수를 기록한 결과는 아니다.

## 두 가지 단독 재현

기존 `test_rx_48._handler`를 임시 spool과 모의 ADB로 열고 같은 핸들러의 `handle`에 서로 다른 claim 두 건을 보냈다. 첫 작업의 행동 수는 1, 두 번째 반환 행동 수는 2였으나 두 번째 실제 ADB 호출은 1이었다. 상태가 다음 attempt에 누적됐다.

동일 fixture에서 `context.cancelled`를 첫 행동 후 True로 바꾸자 `stopped_reason=cancelled`, `outcome=completed`, `evidence_complete=True`, `ambiguous_dispatch=False`였다. 기존 RX-48 시험도 이 완료를 기대한다. 취소·미확정 종료는 사용자와 서버에 구분되어야 한다.

## 소스에서 확인한 공백

- `src/aiqa/worker/android_jobs.py:_run_recording_step`은 모델 응답을 얻은 뒤 live 관찰을 캡처한다. `server_model_plan_provider` 입력은 정제 화면 자체 대신 문자열 `sanitized`와 목표 hash다.
- 녹화의 event/artifact는 핸들러가 반환할 때까지 메모리 목록에 모인다. 진행 중 서버 타임라인이 신규 스텝을 받는 경로가 필요하다.
- 재생은 여러 줄 계획을 단일 `replay_step`에 넘긴다. live builder는 기기 동작 전에 before와 after를 캡처하며 `_QuietVerify`가 satisfied를 반환한다.
- 앱 조회/설치 handler의 등록 helper는 있지만 `run_worker_process`의 기본 Android 조립에서는 호출되지 않는다.
- `recording/structure.py:_model_content`는 일반 API 요청에서도 provider가 없으면 `FixtureProviderHttp`와 fixture model/secret을 사용한다.
- `replay/driver.py:TrustedWebDriver.run`은 실제 runner가 없어도 native_calls를 증가시킨다. Web entry는 fixture 관찰·gate를 조립한다.

관련 보완은 [RX-63~71](../../managed-pc/ENTRY_COMPLETION_TASKS.md)에 각각 지정했다. 운영 키·독립 호스트·VM은 이 구현의 선행으로 요구하지 않는다. 기존 실환경 수용은 원래 상태를 유지한다.
