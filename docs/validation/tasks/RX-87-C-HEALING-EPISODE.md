# RX87 C · 서버 healing episode 예약

- 상태: complete (core_contract). 부모 revision 3185581. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C04/C05/C06/C14, [RX87 C](../../execution/CONTRACTS.md). migration `0053_healing_episode_action`. UI 없음.
- 소비한 선행: [정규화 결과](RX-87-B2-CHECK-RESULTS.md), W31-02의 attempt 전체 dispatch 차단.

## 제공 interface

`store.healing.unsent_action(connection, project_id, attempt_id, action_id)`는 그 action이 `planned` 또는 `lookup_failed`이고 journal에 전송 상태가 없을 때 `None`이다. 행이 없으면 `missing`, 이미 전송됐거나 unknown이면 `sent`다. 같은 attempt의 다른 action은 보지 않는다.

`healing.service.reserve_healing_episode(trigger, control)`는 `trigger.action_id`가 있으면 그 판정만 사용한다. 미전송 증거가 없으면 예약하지 않는다. `action_id`가 없으면 기존처럼 attempt에 `dispatch_started`가 하나라도 있으면 예약하지 않는다. 예약 행은 그 `action_id`를 저장한다.

`healing.claim_reservation.reserve_claimed_healing(...)`와 `POST /api/v1/worker/healing-episodes`는 현재 regression claim, worker lease, package, healing binding, 취소 여부를 서버가 확인한다. 요청의 `episode_id`와 `allowed`는 읽지 않는다. authoring role, trial, 만료 lease, 그 action의 violated check는 거절한다. 예약은 item당 1개이고 호출은 2 이하, 시간은 30초 이하다. 같은 key는 같은 행을 다시 준다.

## 검증

```text
.venv/Scripts/python.exe -B -m pytest tests/integration/test_rx87_healing_episode.py tests/integration/test_w31.py -q -p no:cacheprovider --tb=line
```

최종 **8 passed 2.98s**. 앞선 observed action이 있어도 다음 lookup_failed action은 예약된다. 이미 전송된 action, authoring role, 취소, 기존 violated는 예약되지 않고 승인 package와 FAIL 행은 그대로다. 등급은 core_contract fixture다. 실기기 재동작과 운영 키 수용이 아니다.

## 보존과 다음

원본 FAIL과 승인 package는 수정하지 않았다. Android handler는 아직 ON 치유를 실행하지 않는다. 다음 [D](../../managed-pc/ANDROID_RUNTIME_TASKS.md)가 이 예약을 locator/레이아웃 실패에서만 소비한다. 전체 RX87 완료 수는 유지한다.
