# RX87 B2.3b3c · 정규화 결과와 ITEM QA

- 상태: complete (core_contract). 부모 revision d9d181d. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C04/C05/C06/C08/C14, [B2.3b3c](../../execution/CONTRACTS.md). DB migration 없음. UI 없음.
- 소비한 선행: [경계 평가](RX-87-B2-BOUND-CHECK-EVALUATION.md).

## 제공 interface

`store.replay_check_results.persist_replay_check_results(connection, finish)`는 finish 트랜잭션 안에서 호출된다. native trial/regression package가 아니면 빈 행은 legacy `None`이고, 행이 있으면 거절한다. 반환은 required check 집계 `FAIL` | `PASS` | `INCONCLUSIVE`다.

저장 조건은 서버 source의 check ID/kind/phase/step, context hash, case version, content hash, 그리고 그 action의 observed ACK와 ready ITEM `after`/`log` artifact다. `expected_snapshot`은 source expected다. worker가 보낸 expected와 `sanitized_observed` 원문은 저장하지 않는다. source hash는 저장 action의 case version `content_hash`와 같아야 한다. deterministic satisfied/violated는 명시 resource와 지원되는 text/state reason이 있을 때만 받는다. `ai_visual`의 satisfied/violated는 서버가 먼저 쓴 행이 아니면 거절한다.

`finish_worker_attempt`는 이 집계로 ITEM `core_result`를 쓴다. violated가 하나라도 있으면 FAIL이고 같은 check를 이후 satisfied로 바꾸지 않는다. unknown이거나 required가 빠지면 INCONCLUSIVE다. required가 모두 satisfied이고 worker outcome이 completed일 때만 PASS다. worker의 `required_violation` 플래그는 판정이 아니다. receipt.approved는 false다.

## 검증

기존 저장 모듈이 worker 모양의 행과 ITEM 판정까지 연결되는지를 재현했다. 제품 코드를 완화하지 않았고, 누락돼 있던 finish→ITEM 계약 검사를 추가했다.

```text
.venv/Scripts/python.exe -B -m pytest tests/integration/test_replay_check_results.py -q -p no:cacheprovider --tb=line
```

최종 **26 passed 17.72s**. 등급은 core_contract fixture다. 실기기 hierarchy PASS, 운영 키, 독립 서버 수용이 아니다. 전체 suite green으로 표시하지 않는다.

## 보존과 다음

원본 승인 행과 기존 violated 상태는 유지한다. 모델/제한 healing grant는 [RX87 C](../../managed-pc/ANDROID_RUNTIME_TASKS.md)다. 그 다음 D, 이후 MA05b2다. 전체 RX87 완료 수는 유지한다.
