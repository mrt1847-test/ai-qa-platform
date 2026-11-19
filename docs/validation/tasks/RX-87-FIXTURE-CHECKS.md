# RX-87 · fixture check와 replay 모델 호출

- 상태: complete (core_contract). 부모 revision 5d30899. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C00/C01/C06/C14. DB migration 없음.
- 상위 RX-87 완료 수와 RX-23 실기기 수용은 완료가 아니다.

## 제공 interface

`AndroidReplayHandler._verify_and_heal`은 `require_case_context`가 꺼져 있으면 `context.checks`를 평가하지 않는다. 그 fixture check는 제품 판정, `check_failed`, healer·verifier 호출이 아니다. 서버 check pin 평가는 `require_case_context`가 켜진 replay만 한다.

OFF API claim을 fixture check가 있는 handler로 재생하면 worker의 authoring·verifier·healer 합과 `model_call_facts` 행 수가 같다. 둘 다 0이다.

## 검증

```text
.venv/Scripts/python.exe -B -m pytest tests/integration/test_rx87_fixture_checks.py tests/integration/test_rx_66.py tests/integration/test_rx_34.py -q -p no:cacheprovider --tb=short
```

**8 passed, 1.89s.** 로컬 fixture이며 AVD 수용은 아니다.

## 보존과 다음

로컬 RX-87 체크는 닫혔다. 상위 완료 수와 RX-23은 유지한다.
