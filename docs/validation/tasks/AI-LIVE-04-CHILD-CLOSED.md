# 원본 자식이 모델 응답 뒤에 종료되면 동작을 보내지 않는다

- 상태: partial (core_contract). 부모 revision d4845ce. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C05. DB migration 없음.
- 상위 RX-87 완료 수와 RX-23은 유지한다.

## 제공 동작

부모는 자식 파이프가 닫히면 `child_closed`로 멈춘다. 모델 응답을 한 번 받은 뒤 자식이 종료되면 native 전송은 0이고, 불명 전송으로 표시하지 않는다. 같은 자식을 다시 띄워 재클릭하지 않는다.

## 검증

```text
.venv/Scripts/python.exe -B -m pytest tests/integration/test_mobile_agent_process.py::test_child_crash_after_model_never_dispatches -q -p no:cacheprovider --tb=short
```

**1 passed, 0.77s.** 같은 파일의 취소와 native timeout 검사는 직전 실행에서 통과했다. 실제 기기와 유료 모델은 사용하지 않았다.

## 보존과 다음

handler에 대화 이력과 증거 ACK를 묶는 부모 항목과 live 수용은 열어둡니다. 다음은 실환경 수용 대기입니다.
