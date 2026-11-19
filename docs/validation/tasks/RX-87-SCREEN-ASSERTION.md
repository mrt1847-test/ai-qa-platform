# 화면 의미 문장은 시각 검증으로 판정한다

- 상태: partial (core_contract). 부모 revision ae4c166. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C08/C14. DB migration 없음. 제품 코드 변경 없음.
- 상위 RX-87 완료 수와 RX-23은 유지한다.

## 제공 동작

리소스가 없는 최종 Assertion은 재생에서 텍스트 비교로 추정하지 않는다. 케이스 검증 방식이 `ai_visual`이면 그 문장만 시각 검증 포트로 한 번 보내고, 돌아온 상태를 그 Assertion의 결과로 남긴다. authoring과 healer는 0이고 입력은 추가되지 않는다. 녹화 중 문장을 읽고 `terminate`를 고르는 일은 Mobile-Agent에 둔다.

## 검증

```text
.venv/Scripts/python.exe -B -m pytest tests/integration/test_assertion_readiness_runtime.py -q -p no:cacheprovider --tb=line
```

**8 passed, 2.44s.** 에뮬레이터와 유료 모델은 사용하지 않았다.

## 보존과 다음

`required_check_coverage`는 연결 전 기록용으로 남아 있고 재생 판정 경로가 아니다. 다음은 정의 화면의 문장이 이 시각 검증 방식으로 저장되는지다.
