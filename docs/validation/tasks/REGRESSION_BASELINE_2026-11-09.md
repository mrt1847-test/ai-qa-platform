# 전체 회귀 기준선 · 2026-11-09

기준 commit master 6c95d2e의 git archive를 .review-work/healing-admission/baseline에 추출하여 원본 master/index를 바꾸지 않고 재현했다. 이번 RX-92/93 집중 검사 성공을 저장소 전체 green으로 표시하지 않는다. 원래 구현 완료 이력도 문서만으로 되돌리지 않는다. 제품 기능과 아래 검사 보정/결함 조사를 별도로 진행한다.

첫 전체 명령: `.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider --tb=short`: 9 failed, 494 passed, 1 skipped (340.36s). 새 RX93 검사는 그 이후에 추가했다.

| 실패 node (tests/integration/) | 관측 / 기준 커밋 재현 |
|---|---|
| test_managed_pc_admission.py::test_completed_rerun_receipt_is_readable_after_resource_goes_offline | claim lease=None; 단독 기준 커밋도 실패. worker scope/presence와 새 접수 pin fixture 대조 필요 |
| test_rx_46.py::test_rx_46_operational_mock_https_authoring_and_approved_replay | recording error vs completed; 단독 기준 커밋도 실패. mock provider/recording 경계의 reason 확인 필요 |
| test_w01.py::test_w01_02 | engine capability None vs 기대 bool; 단독 기준 커밋도 실패. 원본 감사 산출물/registry 경로 대조 필요 |
| test_w07.py::test_w07_01 | inventory422 invalid inventory; 단독 기준 커밋도 실패. inventory payload 현 계약 대조 필요 |
| test_w08.py::test_w08_03 | lease45초 대신 과거 고정 시점 차이 약727k초, stale generation200 vs409; 단독 기준 커밋도 실패. 고정 clock/유효 lease 구성 조사 필요 |
| test_w30.py::test_w30_02 | guessed_coordinate_dispatches counter1 vs0, 실제 guessed dispatch는 거절; 단독 기준 커밋도 실패. counter 의미와 무동작 보장 대조 필요 |
| test_rx_12.py::test_adapter_record_replay_and_sanitize_gates | AndroidGeometryError catch 불일치; 단독은 pass, test_android_observation.py를 먼저 실행한 기준 커밋에서 실패 |
| test_rx_34.py::test_rx_34_digest_geometry_cancel_healing_off_and_no_retransmit | 같은 AndroidGeometryError 모듈 reload 이후 실패, 기준 커밋 재현 |
| test_rx_48.py::test_rx_48_ambiguous_and_sanitize_preserve_prior | 같은 AndroidGeometryError 모듈 reload 이후 실패, 기준 커밋 재현 |

기준 standalone 명령: 위 앞6 + 뒤3 총9 node: 6 failed, 3 passed (7.83s). 기준 순서 명령: test_android_observation.py + 뒤3 node: 3 failed, 28 passed (1.32s). 모듈 reload에 따른 예외 class identity 간섭을 제품의 안전 gate 완화로 해결하지 않는다.

기계 출력은 git-ignored .review-work/healing-admission/{full-pytest,baseline-failures,baseline-order,final-pytest}.log에 있다. 실제 모델/기기 수용 SKIP을 PASS로 셈하지 않는다.

최종 리뷰 수정 후 전체 명령도 동일하게 실행: **9 failed, 534 passed, 1 skipped (342.36s)**. 실패 node 집합이 위 기준 재현의 9개와 정확히 일치한다. 새 RX-92/93 검사56개는 이 최종 전체 실행에 포함되어 통과했다. 별도 집중 묶음67개/JS32개도 통과했다. 최종 로그: `.review-work/healing-admission/post-review-pytest.log`.
