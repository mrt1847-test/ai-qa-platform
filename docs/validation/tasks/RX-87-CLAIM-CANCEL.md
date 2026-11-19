# RX-87 · 취소와 임대 반환이 승인본과 실패를 유지

- 상태: complete (core_contract). 부모 revision 6ea0fef. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C00/C01/C04/C05/C08/C09/C14. DB migration 없음.
- 상위 RX-87 체크와 실기기 수용은 완료가 아니다.

## 제공 interface

OFF regression을 claim한 뒤 저장한 항목 결과가 FAIL이면 실행 취소는 409이고 그 FAIL과 job limits의 package hash는 유지된다. worker cleanup은 임대를 반환하고 격리하지 않으며 package hash를 바꾸지 않는다.

같은 snapshot에 `cancel_requested`가 있으면 재생 동작은 0이다. 남은 임대가 0이면 `lease_margin`으로 멈추고 healer 호출은 0이다. 두 경로 모두 snapshot의 `replay_package_hash`를 바꾸지 않는다.

## 검증

```text
.venv/Scripts/python.exe -B -m pytest tests/integration/test_rx87_claim_cancel.py tests/integration/test_rx87_claim_off.py -q -p no:cacheprovider --tb=short
```

**2 passed, 1.74s.** 로컬 fixture이며 AVD 수용은 아니다.

## 보존과 다음

상위 RX-87의 나머지 체크와 실기기 수용은 열려 있다. 한 handler가 두 API claim을 이어서 받을 때 행동 한도가 누적되지 않는지는 다음이다.
