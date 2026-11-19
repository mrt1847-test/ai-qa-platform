# 봉인된 녹화는 논리 검증을 동작으로 바꾸지 않는다

- 상태: partial (core_contract). 부모 revision 5b66c11. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C05. DB migration 없음.
- 상위 RX-87 완료 수와 RX-23은 유지한다.

## 제공 동작

입력 케이스의 단계 `s1`과 검증 `c1`은 source 봉인과 finish 뒤 생성된 버전에 그대로 남는다. native 동작 id는 그 단계 id가 아니다. 승인 행은 없다.

## 검증

```text
.venv/Scripts/python.exe -B -m pytest tests/integration/test_ma04_mobile_recording_session.py::test_sealed_source_keeps_the_logical_check -q -p no:cacheprovider --tb=short
```

**1 passed, 5.46s.** 실제 기기와 유료 모델은 사용하지 않았다.

## 보존과 다음

대화 이력과 증거 ACK를 handler에 묶는 부모 항목과 실환경 수용은 열어둡니다.
