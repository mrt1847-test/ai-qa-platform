# RX-87 · OFF claim과 검증 실패의 다음 claim

- 상태: complete (core_contract). 부모 revision d19b63a. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C00/C01/C04/C05/C08/C09/C14. DB migration 없음.
- 상위 RX-87 체크와 실기기 수용은 완료가 아니다.

## 제공 interface

OFF로 접수한 regression을 worker claim API로 받으면 healing pin은 꺼져 있다. 그 claim의 승인 동작 1회를 재생하고 actor·healer·verifier 호출은 0이다.

같은 snapshot에서 `text_mismatch`가 나면 재생 호출은 1회에서 끝나고 healer 호출은 0이며 `original_failure`는 그 사유다. 다음 claim이 기기 serial에서 거절되면 이전 실패·healer 횟수·dispatch 횟수는 남지 않는다.

## 검증

```text
.venv/Scripts/python.exe -B -m pytest tests/integration/test_rx87_claim_off.py tests/integration/test_rx87_claim_runtime.py -q -p no:cacheprovider --tb=short
```

**2 passed, 2.87s.** 로컬 fixture 기기이며 AVD 수용은 아니다.

## 보존과 다음

중단·취소·임대 반환은 이 확인에 포함하지 않는다. 상위 RX-87은 계속 열려 있다.
