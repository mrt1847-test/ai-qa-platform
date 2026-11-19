# 녹화 세션은 자식 종료를 원본으로 봉인하지 않는다

- 상태: partial (core_contract). 부모 revision a70fa44. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C05. DB migration 없음.
- 상위 RX-87 완료 수와 RX-23은 유지한다.

## 제공 동작

정상 녹화 세션이 원본 자식을 띄운 뒤, 모델 응답 다음에 자식이 종료되면 결과는 `failed`와 `child_closed`다. ADB 전송과 native 수는 0이고, source 행과 승인 행은 생기지 않는다. 불명 전송으로 바꾸지 않는다.

## 검증

```text
.venv/Scripts/python.exe -B -m pytest tests/integration/test_ma04_mobile_recording_session.py::test_child_closed_after_model_does_not_send_or_seal -q -p no:cacheprovider --tb=short
```

**1 passed, 2.39s.** 실제 기기와 유료 모델은 사용하지 않았다.

## 보존과 다음

대화 이력과 증거 ACK를 handler에 묶는 부모 항목의 나머지와 live 수용은 열어둡니다.
