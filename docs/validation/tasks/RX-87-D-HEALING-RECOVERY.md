# RX87 D · 허용 실패의 한 번 재동작

- 상태: complete (core_contract). 부모 revision 9f32265. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C04/C05/C06/C14, [RX87 D](../../execution/CONTRACTS.md). DB migration 없음. UI 없음.
- 소비한 선행: [episode 예약](RX-87-C-HEALING-EPISODE.md), RX96의 유일 locator 증명.

## 제공 interface

`healing.recovery.plan_bounded_recovery(...)`는 `RecoveryDecision(dispatch_once, healer_calls, reason, changes_original_result=False)`를 반환한다. `target_not_found`와 `layout_shift`만 후보가 된다. 제품 assertion, ambiguous, 이미 전송됐거나 unknown인 dispatch, 예약 호출 0, 취소된 checkpoint, 다른 action/input/path, 유일하지 않은 대상은 재동작하지 않는다. 통과한 후보는 현재 관찰의 유일한 visible/enabled 대상이고 승인된 action/input/path와 같다.

`AndroidReplayContext.healing_client`가 없으면 ON pin은 `healing_runtime_unavailable`로 재생을 시작하지 않는다. client가 있으면 locator 실패이고 아직 전송되지 않은 action만 `reserve`와 `proposal`을 물어 한 번 더 원래 동작을 보낸다. 두 번째 실패나 전송 후 실패는 다시 시도하지 않는다. `healer_calls`만 늘고 원본 check 결과와 package digest를 성공으로 바꾸지 않는다. 정상 재생의 healer 호출은 0이다.

## 검증

```text
.venv/Scripts/python.exe -B -m pytest tests/unit/test_healing_recovery.py tests/integration/test_rx87_healing_recovery.py tests/integration/test_rx87_replay_control.py::test_valid_server_on_pin_is_explicitly_unavailable_until_episode_ports_exist tests/integration/test_rx87_replay_control.py::test_explicit_off_claim_does_not_inherit_worker_healing_default -q -p no:cacheprovider --tb=line
```

최종 **8 passed 1.30s**. 등급은 core_contract fixture다. 실기기 재동작, 운영 모델 키, 전체 suite green이 아니다. 기존 전체 실패 기준선은 유지한다.

## 보존과 다음

원본 QA와 승인 package는 수정하지 않았다. 다음은 [MA05b2](../../managed-pc/MOBILE_AGENT_REVIEW_JOURNEY_TASKS.md#ma05b2--정상-source검토사후-승인동일-package-ai0)의 저장 원본 검토·사후 승인·같은 package AI0다. 전체 RX87 완료 수는 유지한다.
