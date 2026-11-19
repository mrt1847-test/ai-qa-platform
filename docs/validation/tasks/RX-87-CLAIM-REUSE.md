# RX-87 · 다음 API claim의 한도 분리

- 상태: complete (core_contract). 부모 revision e950e1a. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C00/C01/C04/C05/C08/C09/C14. DB migration 없음.
- 상위 RX-87 체크와 실기기 수용은 완료가 아니다.

## 제공 interface

같은 승인 케이스를 OFF로 두 번 접수하고, 첫 claim의 임대를 반환한 뒤 다음 claim을 받는다. 한 `AndroidReplayHandler`가 둘을 순서대로 재생한다. 첫 재생 뒤에 healer 횟수와 dispatch 횟수를 올리고 시계를 크게 옮겨도, 둘째 claim은 행동 1·healer 0·dispatch 1로 끝난다. 두 snapshot의 package hash는 같다. PASS 최종 결과는 만들지 않는다.

첫 job은 같은 케이스의 다음 claim을 막지 않도록 임대 반환 뒤에 `completed`로만 닫는다. 그 상태 변경은 QA PASS가 아니다.

## 검증

```text
.venv/Scripts/python.exe -B -m pytest tests/integration/test_rx87_claim_reuse.py -q -p no:cacheprovider --tb=short
```

**1 passed, 1.30s.** 로컬 fixture 기기이며 AVD 수용은 아니다.

## 보존과 다음

상위 RX-87 체크는 이 증명만으로 닫지 않는다. 실기기 수용은 RX-23이다.
