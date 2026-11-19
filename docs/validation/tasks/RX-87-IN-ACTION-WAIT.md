# 탭·입력 안의 대기

- 상태: partial (core_contract). 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C08. DB migration 없음. 새 동작 종류 없음.
- 상위 RX-87 완료 수와 RX-23은 유지한다.

## 제공 동작

재생의 탭·스와이프·입력·키는 wait라는 별도 동작을 추가하지 않는다. 저장된 대상 조건이 있으면 그 조건이 맞을 때까지, 없으면 화면이 잠깐 잠잠해질 때까지 본 뒤에 입력을 한 번 보낸다. 기다리는 동안 같은 탭을 다시 보내지 않는다.

## 검증

```text
.venv/Scripts/python.exe -B -m pytest tests/integration/test_assertion_readiness_runtime.py -q -p no:cacheprovider --tb=short
```

**7 passed, 2.02s.** 에뮬레이터와 유료 모델은 사용하지 않았다.

## 보존과 다음

Mobile-Agent의 녹화 중 화면 판단은 바꾸지 않았다. 다음은 재생 Assertion이 unknown으로만 남는 경로다.
