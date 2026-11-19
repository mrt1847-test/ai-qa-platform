# 허용된 입력 문자는 source v2에 그대로 봉인된다

- 상태: partial (core_contract). 부모 revision 0255823. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C05. DB migration 없음.
- 상위 RX-87 완료 수와 RX-23은 유지한다.

## 제공 동작

케이스 변수 `query`가 `mouse`인 녹화는 그 문자를 source v2의 `text`와 ADB `text mouse`에 남긴다. 승인 행은 만들지 않는다. 변수가 없는 같은 문자는 이전과 같이 전송하지 않는다.

## 검증

```text
.venv/Scripts/python.exe -B -m pytest tests/integration/test_ma04_mobile_recording_session.py::test_source_seals_allowed_text_without_approval tests/integration/test_ma04_mobile_recording_session.py::test_unlisted_text_is_not_sent_or_sealed -q -p no:cacheprovider --tb=short
```

**2 passed, 7.47s.** 실제 기기와 유료 모델은 사용하지 않았다.

## 보존과 다음

logical check binding은 이 부모 항목에 남아 있다. 실환경 수용은 시작하지 않았다.
