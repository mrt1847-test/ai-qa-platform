# 후속 · 실행 항목의 명시 제외와 사유

- 상태: complete (core_contract). 부모 revision 9b40c2c. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C00/C01/C09/C14. migration `0054_execution_exclusions`.
- 소비한 선행: RX-90의 4단계 준비와 preview confirmation.

## 제공 interface

묶음 정식과 선택 정식의 각 항목에 제외 체크와 사유 입력이 있다. 체크와 비어 있지 않은 사유가 함께 있을 때만 `exclusions`에 `confirmed: true`로 들어간다. 사유가 없으면 검사를 보내지 않는다.

서버는 사유가 없는 제외 객체를 422로 거절한다. `silent_exclusions`가 있으면 접수하지 않는다. 확인된 제외는 실행 항목에서 빠지고 `execution_exclusions`에 항목과 사유가 남는다. 선택 정식 접수는 원래 선택과 확정 pin을 함께 보내 제외가 해시에서 빠지지 않게 한다.

수행 화면은 실행 수와 제외 수를 따로 보여 주고, 제외는 실행 성공이 아니라고 쓴다.

## 검증

```text
node --test tests/web/suite_execution.test.cjs tests/web/execution_prep.test.cjs
.venv/Scripts/python.exe -B -m pytest tests/integration/test_rx90_exclusions.py tests/integration/test_rx86_healing_execution.py -q -p no:cacheprovider --tb=short
```

UI 제외 경로를 포함한 suite 검사 **9 passed**. fixture 제외 1건과 healing 회귀를 포함한 **24 passed, 28.40s**. 항목 둘 중 하나를 사유와 함께 제외하면 실행은 1건, 저장 사유는 그 항목 하나, 모델 호출은 0이다. 수행 화면에 `성공 2`는 없다.

## 보존과 다음

시범의 단일 항목 제외는 빈 실행이 되므로 두지 않았다. 실환경 수용은 외부 대기다.
