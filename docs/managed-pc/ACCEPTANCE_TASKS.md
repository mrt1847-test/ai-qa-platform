# 실환경 수용·계측 구현 계획

> [경계와 공통 검증 규칙](RUNTIME_BOUNDARIES.md) · [직접 선행 및 환경 색인](IMPLEMENTATION_TASKS.json) · [공통 계약](../execution/CONTRACTS.md). NEXT_ACTION의 Current 절 하나만 실행한다. TDD로 실패 조건을 확인하고 기능을 연결한 뒤 같은 검사를 반복한다. 선행 인계와 구현의 필드명이 다르면 계약을 먼저 대조한다. 카드의 파일은 기존 파일과 생성 예정 파일을 함께 지정한다.

<a id="rx-22"></a>
## RX-22 · 실제 Web 격리 공격 검증

**입력** RX-15 · RX-30 · RX-35 및 C00/C01/C05/C07. **환경** `local_python` · `verified_web_vm` · `dedicated_web_origin` · `native_test_authorized`.

**파일** `docs/managed-pc/WEB_ISOLATION_RUNBOOK.md`, `docs/validation/tasks/RX-22.md`.

- [ ] 허용된 테스트 origin만 접근하고 차단 대상은 모두 거절, 격리 종료 후 stale proof로 claim 거절.
- [ ] 실행 호스트에서 지원 VM과 전용 브라우저를 띄우고 backend proof를 수집한다. host 파일·프로세스·metadata·관리 API·ADB·CDP 우회 시도에서 실행 경계를 확인한다.
- [ ] `python -m pytest -q tests/integration/test_rx_13.py tests/integration/test_rx_30.py tests/integration/test_rx_35.py`로 core를 먼저 확인하고 실제 guest 안에서 runbook의 deny matrix를 실행한다.
- [ ] `docs/validation/tasks/RX-22.md`에 검증 등급·명령·결과와 backend 버전·테스트 origin과 deny matrix를 남긴다.

<a id="rx-23"></a>
## RX-23 · 실제 Android 녹화와 재생

**입력** RX-12 · RX-21 · RX-31 · RX-34 · RX-39 · RX-44 · RX-45 및 C00/C01/C05/C06/C07/C08. **환경** `local_python` · `dedicated_android` · `actual_model_key` · `native_test_authorized`.

**파일** `tests/operational/test_rx_23.py`, `docs/validation/tasks/RX-23.md`.

- [ ] 녹화 종료 후 증거가 먼저 저장되며, OFF replay actor/healer 0회, 화면 불일치 시 오탭 0회, 명시 ON 실패에서만 제한된 healer.
- [ ] 전용 AVD를 등록 PC에서 선택하고 녹화→정제 증거 ACK→검토→승인→기록 기반 replay를 수행한다. 검증과 healing은 실제 사용량을 목적별로 구분한다.
- [ ] 승인된 격리 환경에서 `python -m pytest -q tests/operational/test_rx_23.py`를 단독 실행한다. 필요한 수동 전환 시각과 fixture ID를 기록한다.
- [ ] `docs/validation/tasks/RX-23.md`에 검증 등급·명령·결과와 동작별 화면·로그 hash·usage·서버 receipt를 남긴다.

<a id="rx-24"></a>
## RX-24 · 실제 Web 녹화와 재생

**입력** RX-21 · RX-22 · RX-31 · RX-36 · RX-42 · RX-45 및 C00/C01/C05/C06/C07/C08. **환경** `local_python` · `verified_web_vm` · `dedicated_web_origin` · `actual_model_key` · `native_test_authorized`.

**파일** `tests/operational/test_rx_24.py`, `docs/validation/tasks/RX-24.md`.

- [ ] 생성본 변경 거절, 승인 버전 불변, OFF replay actor/healer 0회, ON 실패 시 제한된 healer와 별도 이력.
- [ ] 격리 브라우저에서 녹화→step source 및 승인 digest 확인→검토→승인→검증된 코드 재생을 수행한다.
- [ ] 승인된 격리 환경에서 `python -m pytest -q tests/operational/test_rx_24.py`를 단독 실행한다. 필요한 수동 전환 시각과 fixture ID를 기록한다.
- [ ] `docs/validation/tasks/RX-24.md`에 검증 등급·명령·결과와 Web 원본/패키지 digest·스크린샷·로그와 usage를 남긴다.

<a id="rx-25"></a>
## RX-25 · 전원 종료 중 다른 PC에서 검토

**입력** RX-21 · RX-23 · RX-24 · PC-03 및 C00/C01/C03/C08/C09/C11. **환경** `local_python` · `independent_server` · `second_client` · `execution_pc_power_test_authorized`.

**파일** `tests/operational/test_rx_25.py`, `docs/validation/tasks/RX-25.md`.

- [ ] 재녹화·시범·정식·묶음·재실행·진단 거절, 미ACK 녹화 승인 거절, 전원 복구 후 명시 접수 전 자동 job/행동 0건.
- [ ] Android와 Web의 승인 전 ACK 저장본을 만든 뒤 실행 PC 전원을 끈다. 다른 PC에서 목록·상세·step 증거·승인을 확인하고 live 요청을 UI와 API로 각각 시험한다.
- [ ] 승인된 격리 환경에서 `python -m pytest -q tests/operational/test_rx_25.py`를 단독 실행한다. 필요한 수동 전환 시각과 fixture ID를 기록한다.
- [ ] `docs/validation/tasks/RX-25.md`에 검증 등급·명령·결과와 세 호스트 역할·단절 타임라인·승인/audit·API 상태를 남긴다.

<a id="rx-26"></a>
## RX-26 · 재연결의 미확정 행동과 늦은 ACK

**입력** RX-21 · RX-23 · RX-38 및 C00/C01/C04/C05/C08. **환경** `local_python` · `independent_server` · `dedicated_android` · `fault_injection_authorized`.

**파일** `tests/operational/test_rx_26.py`, `docs/validation/tasks/RX-26.md`.

- [ ] 행동 재전송 0회, 미확정 자원 격리 유지, 늦은 ACK는 증거만 추가, 정리 확인 뒤에만 명시 재실행 가능.
- [ ] 실제 worker에서 STARTED 직후와 서버 commit 직후 각각 통신을 끊어 journal·lease·spool·서버 verdict를 대조한다.
- [ ] 승인된 격리 환경에서 `python -m pytest -q tests/operational/test_rx_26.py`를 단독 실행한다. 필요한 수동 전환 시각과 fixture ID를 기록한다.
- [ ] `docs/validation/tasks/RX-26.md`에 검증 등급·명령·결과와 두 단절 위치의 ledger·정리 receipt·복구 상태를 남긴다.

<a id="rx-27"></a>
## RX-27 · 두 워커의 동일 물리 자원 경합

**입력** RX-21 · RX-23 및 C00/C01/C03/C04/C05. **환경** `local_python` · `independent_server` · `two_registered_workers` · `shared_test_physical_scope` · `native_test_authorized`.

**파일** `tests/operational/test_rx_27.py`, `docs/validation/tasks/RX-27.md`.

- [ ] 동시 승인 lease 하나, 다른 세대의 ACK/renew/release 거절, 정리 확인 전 새 dispatch 0회, 독립 physical scope는 동시 수행 가능.
- [ ] 등록된 두 worker를 하나의 승인된 physical scope에 경합시키고 전원이 켜진 worker의 lease, 중단 worker의 stale fence, 정리 영수증을 비교한다.
- [ ] 승인된 격리 환경에서 `python -m pytest -q tests/operational/test_rx_27.py`를 단독 실행한다. 필요한 수동 전환 시각과 fixture ID를 기록한다.
- [ ] `docs/validation/tasks/RX-27.md`에 검증 등급·명령·결과와 두 worker의 claim/lease/attempt 수·경합 시간과 release 근거를 남긴다.

<a id="rx-29"></a>
## RX-29 · 3000건 회귀 용량과 비용 계측

**입력** RX-23 · RX-24 및 C00/C01/C06/C09/C10. **환경** `local_python` · `actual_model_key` · `cost_sample_authorized`.

**파일** `tests/operational/test_rx_29.py`, `docs/validation/tasks/RX-29.md`.

- [ ] actor 0회 및 OFF/ON 구분, 측정 누락을 0원으로 계산하지 않음, 표본 한계와 처리 가능 시간 검증. 실제 3000건 부하나 구매는 별도 승인.
- [ ] 승인된 작은 표본으로 두 플랫폼의 점유 시간·대기 시간·목적별 모델 토큰·보관량을 측정한다. 월 3000건의 대상 비중·동시 슬롯·모델 단가 가정을 명시해 범위로 환산한다.
- [ ] 승인된 격리 환경에서 `python -m pytest -q tests/operational/test_rx_29.py`를 단독 실행한다. 필요한 수동 전환 시각과 fixture ID를 기록한다.
- [ ] `docs/validation/tasks/RX-29.md`에 검증 등급·명령·결과와 표본 수·측정식·단가 기준일·확장 시 필요한 실행 PC 수 추정를 남긴다.
