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

2026-11-10 RX-86/94/95 후 전체 회귀: 9 failed,603 passed,1 skipped (339.79s). 실패 node 집합은 기존9개와 정확히 같다. `.review-work/healing-execution/verified-pytest.log`에 최종 출력이 있다. 새 모델/장치 수용은 수행하지 않았다.

2026-11-10 RX96 후 전체:9 failed,635 passed,1 skipped (315.44s). 실패 node 집합은 동일9개다. 최종 로그 `.review-work/healing-provider/verified-full.log`; 실제 AI 토큰/기기 수용은 수행하지 않았다.

2026-11-10 RX97 후 최종 전체: **9 failed, 652 passed, 1 skipped in 382.05s (0:06:22)**. 실패 node 집합은 기존9개와 정확히 같다. 집중31/JS32 passed. `.review-work/recording-model-pin/verified-full.log`. 새 실제 AI/장치 수용은 수행하지 않았다.

2026-11-13 RX98 최종 전체: **9 failed, 696 passed, 1 skipped in 487.17s (0:08:07)**. 기존9개 failure node와 정확히 같다. 집중105/JS32 passed. 최초 새2개 RX45/RX47은 실제 전송 수와 정상 admission/ACK/generation fixture 계약 보완 후 해소했다. `.review-work/recording-model-requests/final-full.log`. 실제 모델/기기 수용 없음.

## 2026-11-17 원본 녹화 연결 후 재검사

C2 첫 전체 실행은15failed1393passed1skipped였다. 기존9외6개는 [C2 인계](AI-LIVE-04-MA04C2.md)의 후속53pass와 순서32pass에서 해소했다. AD-01 import 부작용 검사가 canonical android_observation을 reload해 guard 예외 class identity를 바꾸던 test isolation을 수정했다. production guard catch/geometry/sanitize 기준은 바꾸지 않았다.

기존9 중 `test_rx_12.py::test_adapter_record_replay_and_sanitize_gates`, `test_rx_34.py::test_rx_34_digest_geometry_cancel_healing_off_and_no_retransmit`, `test_rx_48.py::test_rx_48_ambiguous_and_sanitize_preserve_prior`는 `test_android_observation.py` 뒤 순서 회귀에서 통과한다. 같은 원인의 새 `test_rx87_native_trace.py::test_native_physical_normalization_cannot_hide_invalid_original_frame`도 통과했다. 나머지 기존6(managed_pc_admission/RX46/W01/W07/W08/W30)은 이번 전체 실행에서도 실패했으며 미해소다. 전체를 다시 실행하지 않았으므로 새 전체 통과 수를 합산해 만들지 않는다. 로그는 .review-work/mobile-agent-engine-admission/{full,full-followup,ordered-followup}.log다.

## 2026-11-27 hosted 변경과 기준 커밋 대조

HS-2~6 작업 시작 커밋 `3525226`을 `.review-work/hosted-runtime/baseline`의 git archive 복제본으로 대조했다. 원본 master/index/사용자 DB는 되돌리지 않았다. 아래 여덟 실패는 이번 hosted 변경 전에도 같은 node/지점에서 재현된다. 따라서 이들을 새로운 Postgres/Storage 회귀로 표시하지 않지만, 해결된 것으로도 표시하지 않는다.

| node | 기준 커밋 관측 |
|---|---|
| acceptance/test_managed_pc_availability_ui.py::test_resource_response_and_environment_show_server_connection_state | 기존 `PC 마지막 응답` 문구 기대 불일치 |
| acceptance/test_rx_58.py::test_rx_58_model_check_modes_and_settings | `page_replay_note` 기대 불일치 |
| acceptance/test_rx_71.py::test_rx_71_browser_recording_trial_approve_suite_regression | finished1/pass0과 PASS 기대 불일치 |
| acceptance/test_rx_77.py::test_rx_77_browser_contract_journey_results_and_resource_reuse | trial-A가 INCONCLUSIVE, 기대 PASS |
| acceptance/test_w20.py::test_w20_01 | 기존 승인 상태 문구 기대 불일치 |
| acceptance/test_w20.py::test_w20_03 | 같은 문구 기대 불일치 |
| acceptance/test_w31.py::test_w31_06 | 고정 healing 한도 문구 기대 불일치 |
| integration/test_ma03b_recording_endpoint.py::test_unknown_native_log_disables_cached_action_without_a_second_send | unknown-native evidence commit이422로 거절됨 |

기준 실행: 앞7개를 포함한 선택 파일 묶음 **7 failed,1 passed in23.66s**, 마지막 node 별도 **1 failed in4.18s**. 현재 작업본에서도 앞7개는 같은 묶음 **7 failed,1 passed in21.38s**다. 로그 `.review-work/hosted-runtime/{acceptance-failures,baseline-acceptance}.log`. 마지막 기준 node는 도구 출력에 실패 stack을 보존했다. 이 비교는 후속 원인 조사의 기준이며 UI 문구나 PASS guard를 테스트에 맞춰 되돌리는 수정 승인이 아니다. 기존 여섯 실패도 별도 보존한다.

추가로 기존6 node 전부를 같은 BASE `3525226` archive에서 다시 실행해 **6 failed in7.71s**를 확인했다(`.review-work/hosted-runtime/baseline-six.log`). 예전 커밋의 실패 기록만으로 이번 변경과 무관하다고 가정하지 않고 작업 시작 revision에서 직접 대조했다.

전체 회귀 후반의 다음3개도 같은 BASE에서 **3 failed in4.34s**로 재현했다(`.review-work/hosted-runtime/baseline-additional.log`):

- `integration/test_rx94_healing_claim.py::test_same_configuration_rerun_keeps_on_pins_and_stored_receipt`: 재접수 preview의 confirmation 내용 불일치.
- `integration/test_rx_54.py::test_rx_54_android_handler_off_and_actor_zero`: 기대 error에 대해 completed.
- `integration/test_rx_54.py::test_rx_54_web_handler_off_budget_on_timeout`: 기대 package digest에 대해 빈 값.

이3개도 새 hosted 코드가 만든 것으로 분류하지 않으며, 구체 원인/계약 보정은 미해결로 유지한다. 전체 최종 결과와 이 대조 집합의 일치 여부는 hosted 구현 계획 ledger에 기록한다.

마지막6개도 BASE에서 **6 failed in18.69s**로 재현했다(`baseline-last.log`): `integration/test_rx_72.py::test_rx_72_finish_writes_item_results_and_advances`의 ITEM 판정 기대 불일치, `integration/test_w16.py`의 `test_w16_08/06/05/03/01`의 기존 무버튼/문구 기대 불일치다. live-video UI가 있는 전체 페이지에 `<button`이 없다고 가정하는 검사도 포함되어 있다. 제품 동작과 기존 검사 계약의 대조가 필요하며 실패 assertion을 단순 삭제하지 않는다.

최종 전체 명령 `python -B -m pytest -q -p no:cacheprovider --tb=short`: **23 failed,1982 passed,1 skipped in2151.02s**. 전체의 실패 node 집합은 위 BASE에서 각각 재현한23개와 정확히 일치한다(집합 대조 unmatched0). 전체 BASE 회귀를 실행했다는 의미는 아니며, 현재 전체에서 실패한 node를 BASE의 여러 선택 묶음으로 직접 대조했다. 전체 로그 `.review-work/hosted-runtime/final-pytest.log`. 이후 추가한 first-admin/Postgres 연결 검사1개와 Git checkout 검사1개는 별도 통과이며 이 전체 수에 더하지 않는다. 기존 미해결을 완료로 바꾸지 않는다.
