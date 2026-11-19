# RX87 B2.3b2 · 검증 연결 편집의 저장 한계 표시

- 상태: partial (core_contract). 부모 revision 3f4a305. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C00/C14. DB migration 없음.
- 상위 RX-87 완료 수와 RX-23은 유지한다.

## 제공 interface

녹화 페이지의 검증 연결 폼은 후보 저장만 한다. 안내 문구는 실행 적용이 아직 지원되지 않는다고 말한다. 승인된 연결이 없으면 단계 검증을 성공으로 처리하지 않는다고 함께 적는다. 저장 receipt의 manifest hash가 다음 저장의 CAS가 되고, 검토 링크는 `?version=`으로 그 후보를 고정한다. 새 후보는 승인으로 표시하지 않는다.

## 검증

```text
node --test tests/web/recording_check_bindings.test.cjs
.venv/Scripts/python.exe -B -m pytest tests/integration/test_rx87_check_binding_editor.py -q -p no:cacheprovider --tb=short
```

JS **3 passed**. 페이지 **2 passed, 1.99s**. 로컬 브라우저에서 1024·1440 폭의 선택·저장 버튼이 보였고, 저장 뒤 검토 링크는 그 version만 열었다. 승인 버튼은 비활성이고 기본 승인본은 생기지 않았다. Tab은 페이지 처음으로 이동했다.

## 보존과 다음

실행 적용과 자동 승인은 만들지 않았다. 상위 RX-87 완료 수와 RX-23은 유지한다. 다음은 실환경 수용 대기입니다.
