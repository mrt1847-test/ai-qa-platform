# 저장 package는 봉인된 물리 좌표를 재생한다

- 상태: partial (core_contract). 부모 revision 318e79d. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C08/C14. DB migration 없음.
- 상위 RX-87 완료 수와 RX-23은 유지한다.

## 제공 동작

원본 녹화의 package pin은 `physical:click(50, 100)`이다. 모델 좌표 500은 plan에 없다. trial 재생은 ADB `tap 50 100` 한 번이고 authoring, healer, verifier는 0이다. 승인 행은 없다.

## 검증

```text
.venv/Scripts/python.exe -B -m pytest tests/integration/test_ma04_mobile_runtime_handler.py::test_stored_package_replays_sealed_pixels_without_rewriting -q -p no:cacheprovider --tb=short
```

**1 passed, 6.88s.** 실제 기기와 유료 모델은 사용하지 않았다.

## 보존과 다음

사람 승인 뒤의 같은 package AI0는 [MA05b2](AI-LIVE-04-MA05B2.md)다. live 수용은 시작하지 않았다.
