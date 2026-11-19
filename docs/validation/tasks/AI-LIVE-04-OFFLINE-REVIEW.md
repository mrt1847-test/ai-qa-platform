# 워커가 꺼진 뒤에도 저장 후보는 검토 화면에 남는다

- 상태: partial (core_contract). 부모 revision 14044d5. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C05/C14. DB migration 없음.
- 상위 RX-87 완료 수와 RX-23은 유지한다.

## 제공 동작

원본 handler가 녹화를 마치고 finish한 뒤 worker 연결을 닫아도, 브라우저 세션은 그 녹화와 `?version=` 검토 화면을 연다. 후보는 승인으로 표시되지 않고, 검토 화면은 방문만으로 승인하지 않는다고 말한다.

## 검증

```text
.venv/Scripts/python.exe -B -m pytest tests/integration/test_ma04_mobile_runtime_handler.py::test_finished_recording_stays_reviewable_after_the_worker_is_offline -q -p no:cacheprovider --tb=short
```

**1 passed, 6.85s.** 실제 기기와 유료 모델은 사용하지 않았다.

## 보존과 다음

승인본 AI0 여정은 기존 인계에 있고, live 수용은 시작하지 않았다.
