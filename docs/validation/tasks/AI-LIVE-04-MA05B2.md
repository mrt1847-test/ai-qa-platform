# MA05b2 · 저장본 승인 후 같은 package AI0

- 상태: complete (core_contract). 부모 revision 5749db8. 이 파일을 포함한 커밋이 완료 revision이다.
- 적용 계약: C05/C08/C14. DB migration 없음. 새 UI 없음.
- 소비한 선행: [MA05b1.3](AI-LIVE-04-MA05B13.md), [경계 평가](RX-87-B2-BOUND-CHECK-EVALUATION.md), [제한 복구](RX-87-D-HEALING-RECOVERY.md).

## 제공 경로

저장본의 package를 바꾸지 않고 `request_review`와 `review_action`, `approve_case`로 검토·승인을 만든다. trial limits는 `actor=0`, `self_healing_enabled=false`이고 package id/hash가 그 버전의 ready package와 같다. 승인 이벤트는 `approved`이며 `current_approval_id`는 그 승인이다. package body hash는 승인 전후가 같다.

같은 package의 native plan을 trial worker가 재생한다. 5개 동작이 전달되고 authoring, healer, verifier 호출은 0이다.

## 검증

```text
.venv/Scripts/python.exe -B -m pytest tests/integration/test_ma05b2_same_package.py -q -p no:cacheprovider --tb=line
```

최종 **1 passed 1.45s**. 등급은 core_contract fixture다. 승인 함수를 SQL pointer 갱신으로 대체하지 않았다. 실제 브라우저 클릭, 운영 기기, 유료 모델 수용은 아니다.

## 보존과 다음

원본 package hash와 AI0 조건을 유지했다. 전체 MA05/RX87 실환경 수용은 미완료다. 다음은 RX-88 Web replay 정책 소비다.
