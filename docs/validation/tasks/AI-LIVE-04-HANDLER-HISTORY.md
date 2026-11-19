# 정상 handler는 서버 이력과 journal ACK를 사용한다

- 상태: partial (core_contract). 부모 revision fb7ba3c. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C05. DB migration 없음.
- 상위 RX-87 완료 수와 RX-23은 유지한다.

## 제공 동작

원본 녹화 handler의 첫 모델 요청에는 assistant 이력이 없다. 두 번째 요청에는 서버가 만든 assistant 이력 하나와 첫 click이 들어 있고, worker 파일 경로는 없다. 그 동작의 journal은 planned, dispatch_started, acknowledged, observed다. 승인 행은 없다.

## 검증

```text
.venv/Scripts/python.exe -B -m pytest tests/integration/test_ma04_mobile_runtime_handler.py::test_handler_second_model_uses_server_history_and_journal_ack -q -p no:cacheprovider --tb=short
```

**1 passed, 6.61s.** 실제 기기와 유료 모델은 사용하지 않았다.

## 보존과 다음

live 수용은 시작하지 않았다.
