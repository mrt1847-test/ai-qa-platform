# source v2는 스와이프 좌표와 Back 키를 봉인한다

- 상태: partial (core_contract). 부모 revision 2781902. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C05. DB migration 없음.
- 상위 RX-87 완료 수와 RX-23은 유지한다.

## 제공 동작

원본 녹화 세션은 모델 좌표 `[100,200]→[300,400]`를 물리 픽셀 `9,40→29,79`, 지속 800ms로 source v2와 ADB swipe에 같이 남긴다. Back은 keycode 4와 `keyevent 4`다. 케이스 변수에 없는 문자 `mouse`는 `authoring_unavailable`이고 전송·source·승인을 만들지 않는다.

## 검증

```text
.venv/Scripts/python.exe -B -m pytest tests/integration/test_ma04_mobile_recording_session.py::test_source_seals_swipe_coordinates_without_approval tests/integration/test_ma04_mobile_recording_session.py::test_unlisted_text_is_not_sent_or_sealed tests/integration/test_ma04_mobile_recording_session.py::test_source_seals_back_key_without_approval -q -p no:cacheprovider --tb=line
```

**3 passed, 11.70s.** 실제 기기와 유료 모델은 사용하지 않았다.

## 보존과 다음

허용된 입력 변수의 문자 봉인과 logical check binding은 이 항목에 남아 있다. 승인은 만들지 않았다.
