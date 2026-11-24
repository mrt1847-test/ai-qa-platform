# Android Assertion 및 재생 로딩 검증 — 2026-11-24

## 작업 기준

`codex/assertion-readiness-final`은 `master`와 동일한 `1dc66b6`에서 시작했다. master에 남아 있던 문서, hierarchy reader, 녹화 도구 등의 수정은 유지했다. 커밋·병합·push는 수행하지 않았다.

## 반영 내용

- 녹화 준비의 Assertion에 검증 방식과 검증용 AI 연결을 저장한다. 새 Android 케이스는 화면 검증을 기본으로 제시하며 연결을 명시적으로 선택해야 한다. 기존 케이스의 비교 방식은 유지한다. authoring 연결을 대신 사용하지 않는다.
- 재생은 저장된 check의 단계 경계에서 실제 관찰을 비교한다. 화면 검증은 서버가 ACK된 이미지와 고정된 기대 결과를 사용한다. 검증 결과와 최종 ITEM의 PASS·FAIL·INCONCLUSIVE 저장까지 연결했다.
- 후속 동작도 각자의 녹화 당시 대상 조건을 기다린다. 첫 동작 뒤 로딩 화면이 잠시 정지해도 다음 탭의 대상 조건이 충족되지 않으면 입력을 보내지 않는다.
- 입력 ACK 뒤 관찰 중 취소돼도 실제 실행한 입력 수와 ACK를 보존한다. 증거 저장 응답 유실은 동일한 패킷만 재확인하며 기기 입력·관찰·모델 호출을 반복하지 않는다.

## 증거

- `test_assertion_readiness_runtime.py`: 지연된 후속 대상, timeout, 취소 전후, 구 source, 마지막 입력 예산 이후 검증, ACK 응답 유실을 회귀 검증한다. 새로 발견한 세 결함은 수정 전 실패를 확인했다.
- `test_assertion_replay_journey.py`: 로컬 HTTP로 native replay → 증거 ACK → 서버 시각 검증 → finish → 최종 ITEM을 실행한다. satisfied/PASS, violated/FAIL, unknown/INCONCLUSIVE 세 경우와 동일 finish 요청 재확인을 검증한다. 기기와 모델은 fixture다.
- `test_recording_assertion_wizard.py`: verification 역할 연결 목록, 초안 저장 및 재개 시 검증 방식·연결·Assertion 유지를 검증한다.
- 웹 JavaScript 전체 테스트: **59 passed**. 브라우저에서 자연어·Assertion 입력과 검증 방식·연결 선택을 확인했다. 화면 증거: `.review-work/assertion-wait/wizard-verification.jpg`.
- 별도 검토자는 발견한 세 결함 수정 후 owned diff에서 추가 중요 결함이 없음을 확인했다.
- 관련 Python 테스트 **109 passed**: readiness 26, bound check 10, runtime 11, boundary 10, visual evaluation 22, result persistence 26, HTTP journey 3, wizard 1.
- 전체 Python 회귀 테스트: **1,771 passed / 24 failed / 1 skipped**, 총 1,796개. 2026-11-25 KST에 실행을 마쳤다. `.review-work/assertion-wait/full-suite-{1..4}.xml`에 파일 단위 4개 분할 결과를 저장했다. 전체 suite가 통과했다는 의미는 아니다.

## 기존 실패 비교

이번 변경을 제외한 master 소스를 별도 디렉터리에 복사하고, migrations와 고정 third_party 프로토콜 소스를 포함해 실패한 24개 테스트를 실행했다. **24개 모두 master 비교본에서도 실패했다.** 기존의 다른 수정 파일은 비교본에도 유지했고, 원래 작업 파일은 교체하지 않았다. 우선 확인한 6건은 다음과 같다.

| 테스트 | 동일하게 관찰된 실패 |
| --- | --- |
| managed_pc_admission / completed_rerun_receipt | claim이 `None` |
| rx_46 / operational_mock_https_authoring_and_approved_replay | completed 대신 error |
| w01_02 | sandbox 관찰값이 boolean 대신 None |
| w07_01 | inventory validation 422 |
| w08_03 | 고정 lease 시간·stale generation 기대값 불일치 |
| w30_02 | guessed_coordinate_dispatches 기대값 불일치 |

나머지 실패는 다음과 같다. Assertion·로딩 수정과 별도로 남아 있는 검증 부채이며, 이번 작업에서 기대값을 완화하거나 삭제하지 않았다.

| 테스트 | 건수 | 관찰된 실패 |
| --- | ---: | --- |
| ma03b_recording_endpoint / unknown_native_log | 1 | 일부 로그만 commit하는 fixture가 422로 거절됨 |
| w16_01, 03, 05, 06, 08 | 5 | 실시간 화면 버튼 금지·예전 안내 문구 기대 |
| w20_01, 03 및 w31_06 | 3 | 이전 힐링 안내 문구 기대 |
| rx_77 및 rx_71 browser journey | 2 | PASS 기대에 INCONCLUSIVE 또는 pass_count 0 |
| rx94_healing_claim / same_configuration_rerun | 1 | preview confirmation 객체 동일성 기대 |
| rx_54 Android·Web handler | 2 | outcome 및 package digest 기대 불일치 |
| ux_model_settings / explicit_keep | 1 | 이전 설정 안내 문구 기대 |
| managed_pc_availability_ui / server_connection_state | 1 | 이전 연결 안내 문구 기대 |
| rx_58 model_check_modes_and_settings | 1 | 이전 replay 설명 문구 기대 |
| rx_72 finish_writes_item_results_and_advances | 1 | 다른 키로 이미 끝난 attempt를 다시 finish하려다 FinishConflict |

최종 비교 결과: `.review-work/assertion-wait/master-full-failures.xml` (24 failed). 초기 6건 비교: `.review-work/assertion-wait/master-known-failures.xml`. ma03b는 필요한 고정 프로토콜을 포함한 최종 비교에서 현재 실행과 같은 422 실패를 확인했다.

## 범위와 한계

이번 후속 검증은 fixture 기기·모델과 로컬 서버를 사용했다. 새 실제 Android/외부 유료 모델 실행이나 README 영상 재촬영을 수행했다는 의미는 아니다. 과거 영상의 INCONCLUSIVE 근거는 변경하지 않았다.

저장된 대상 조건이 없는 과거 녹화는 화면 안정화만 확인한다. 당시 대상 조건을 소급해서 만들 수 없으므로 동일한 대상 준비 조건이 필요하면 재녹화해야 한다. 화면 정지만으로 로딩 완료나 Assertion 충족을 판단하지 않으며, 필수 검증 누락·관찰 불가·모호함은 PASS가 되지 않는다.
