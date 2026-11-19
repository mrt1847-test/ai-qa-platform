# 정의 화면은 화면 의미 Assertion을 따로 저장한다

- 상태: partial (core_contract). 부모 revision 4c514db. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C14. DB migration 없음.
- 상위 RX-87 완료 수와 RX-23은 유지한다.

## 제공 동작

정의 편집기의 Assertion은 화면 텍스트·상태 비교와 화면 의미 검증 중 하나를 고른다. 화면 의미는 `kind=visual`로 저장된다. 시각 검증 정책이 없으면 그 문장은 `visual_policy_missing`인 unknown이고, 검증 함수는 호출되지 않는다. 정책이 `ai_visual`이면 그 문장만 한 번 검증한다. 성공으로 추정하지 않는다.

## 검증

```text
.venv/Scripts/python.exe -B -m pytest tests/unit/test_bound_check_evaluation.py -q -p no:cacheprovider --tb=short
node --test tests/web/definition_editor_checks.test.cjs
```

평가 **10 passed, 0.11s**. 편집기 **1 passed**. 에뮬레이터와 유료 모델은 사용하지 않았다.

## 보존과 다음

녹화 중 문장을 읽고 `terminate`를 고르는 일은 Mobile-Agent에 둔다. 다음은 저장한 문장이 녹화 목표에 그대로 실리는지다.
