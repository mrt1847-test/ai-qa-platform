# 화면 의미 문장은 녹화 목표에 실린다

- 상태: partial (core_contract). 부모 revision 5fdd8a7. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C05. DB migration 없음. 제품 코드 변경 없음.
- 상위 RX-87 완료 수와 RX-23은 유지한다.

## 제공 동작

`kind=visual`인 최종 문장은 녹화 목표에 `final:{id}:visual:{문장}`으로 들어간다. Mobile-Agent가 그 문장을 읽고 `terminate`를 고른다. 목표 문자열은 PASS나 satisfied가 아니다.

## 검증

```text
.venv/Scripts/python.exe -B -m pytest tests/unit/test_mobile_agent_context.py::test_visual_assertion_sentence_is_in_the_recording_goal_and_is_not_a_pass -q -p no:cacheprovider --tb=short
```

**1 passed, 0.19s.** 유료 모델과 에뮬레이터는 사용하지 않았다.

## 보존과 다음

재생 성공으로 바꾸지 않았다. 다음은 케이스 설정에서 시각 검증 연결이 없을 때 저장을 막는 일이다.
