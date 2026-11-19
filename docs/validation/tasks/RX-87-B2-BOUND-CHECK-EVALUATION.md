# RX87 B2.3b3b1b · 저장 경계의 deterministic 평가

- 상태: complete (core_contract). 부모 revision 7396d20. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C04/C05/C06/C14, [B2.3b3b1b](../../execution/CONTRACTS.md). DB migration 없음. UI 없음.
- 소비한 선행: [공통 reader](RX-87-B2-ANDROID-HIERARCHY-READER.md), [pin](RX-87-B2-CHECK-BINDING-PIN.md), [required coverage](RX-87-B2-CHECK-COVERAGE.md).

## 제공 interface

`worker.bound_check_evaluation.scheduled_checks(pin,binding,native_source,*,action_index,total_actions)`는 원본 `NativeSource.steps`의 현재 action ID와 `binding.boundaries`가 같을 때만 그 step의 check를 반환한다. logical ordinal로 gesture를 고르지 않는다. 연결이 없는 required는 마지막 action에서 `logical_step_mapping_missing`이다. final check는 마지막 action에서만 반환한다.

`evaluate_bound_checks(pin,binding,native_source,*,action_index,total_actions,observed_at,hierarchy_observer=None,checkpoint,timeout=30,visual=None,clock,pause)`는 `RequiredCheckCoverage`를 만든다. source check id/expected/phase/context/content hash/kind를 보존한다. 승인된 deterministic 정책과 명시 resource만 `hierarchy_observer(package,resource_ids,checkpoint,timeout)`로 한 번에 읽는다. 정책이 없거나 대상이 없으면 읽지 않는다. timeout은 호출자가 넘긴 남은 시간이며, 운영 factory는 그 값과 15초 중 작은 값을 명령 cap으로도 쓴다.

text는 실제 text field와 exact 비교한다. state는 `enabled|checked|selected|focused|visible=true|false`만 비교한다. field가 없으면 unknown이며 text나 node 존재로 추정하지 않는다. ambiguous/redacted/unavailable/지원하지 않는 kind/읽기 실패는 unknown이다. 계속 missing인 대상은 남은 읽기 시간 안에서 같은 resource 묶음을 다시 읽고, 끝나도 unknown이다. 그 재읽기는 입력 gesture가 아니다. violated의 latch는 FAIL이다. 관찰 원문은 reason/sanitized_observed/coverage log에 복사하지 않는다.

`AndroidReplayHandler._verify_and_heal`는 `require_case_context`에서 이 함수를 호출한다. checkpoint는 현재 claim의 read-only gate다. 마지막 입력 예산을 소진해도 이 조회는 `action_budget`으로 막지 않는다. 추가 PNG/모델/입력 차감은 0이다. 호출자 fixture check는 source expected를 대체하지 않는다. unknown은 남은 sealed gesture를 취소하지 않고, 앞선 unknown을 뒤의 satisfied가 지우지 못한다. 하나라도 satisfied가 아니면 outcome은 error/`check_failed`다. violated는 그 동작에서 멈추고 healer 호출은 0이다. deterministic 평가의 verifier/actor 호출은 0이다.

## 검증

검토에서 선행 pin 계약을 재현했다. 첫 구현은 경계의 unknown에서 남은 gesture를 끊어 `유효 pin은 재생을 막지 않고 pass도 주지 않는다`를 깨뜨렸다. unknown은 계획을 계속 실행하고 완료만 거부하도록 한 번 고쳤다. 재검토로 새 결함은 남지 않았다.

```text
.venv/Scripts/python.exe -B -m pytest tests/unit/test_bound_check_evaluation.py tests/integration/test_rx87_bound_check_evaluation.py tests/integration/test_android_hierarchy_reader.py tests/integration/test_rx87_check_coverage.py tests/integration/test_rx87_check_binding_pin.py tests/integration/test_assertion_readiness_runtime.py tests/unit/test_replay_readiness.py -q -p no:cacheprovider --tb=line
```

최종 **128 passed 56.11s**. 등급은 core_contract fixture다. 실제 앱 QA/운영 키/독립 서버 수용이 아니다. 전체 suite green으로 표시하지 않는다. 기존 전체 실패 기준선은 유지한다.

## 보존과 다음

원본 source/승인/FAIL bytes는 바꾸지 않았다. coverage log는 expected 원문 대신 hash만 남긴다. 명시 ai_visual callback은 이미 있는 별도 서버 포트이며 이 리프의 deterministic 승인이 아니다. normalized `check_results`/ITEM QA 영속은 [c](../../managed-pc/CHECK_BINDING_RUNTIME_TASKS.md#c--정규화-결과item-영속-다음)다. `store/replay_check_results.py`가 있어도 c를 완료로 세지 않는다. 전체 RX87과 완료 수는 유지한다.
