# RX-87 · 실제 ON claim의 차단과 무치유 재생

- 상태: complete (core_contract). 부모 revision e6b095c. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C00/C01/C04/C05/C08/C09/C14. DB migration 없음.
- 상위 RX-87 체크와 실기기 수용은 완료가 아니다.

## 제공 interface

`healing_claim`은 정상 worker claim API가 돌려준 ON snapshot이다. recovery client가 없으면 Android replay는 `healing_runtime_unavailable`로 멈추고 기기 동작은 0이다. client가 있고 예약 호출이 0이면 승인 plan 한 동작을 재생하며 healer·actor·verifier 호출은 0이다. 같은 snapshot의 `max_actions`를 1로 좁히면 두 번째 승인 동작 앞에서 `action_budget`으로 멈춘다.

## 검증

```text
.venv/Scripts/python.exe -B -m pytest tests/integration/test_rx87_claim_runtime.py -q -p no:cacheprovider --tb=short
```

**1 passed, 2.61s.** 로컬 fixture 기기이며 AVD 수용은 아니다.

## 보존과 다음

OFF claim, 검증 실패의 재시도 금지, 임대 정리를 이 파일의 성공으로 대신하지 않는다. 상위 RX-87은 계속 열려 있다.
