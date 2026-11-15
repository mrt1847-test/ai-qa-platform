# RX87 B2.3b1 · 저장된 녹화와 검증 시점의 불변 연결

2026-11-15 master e9ea37f. NEXT Current/CASE_CONTEXT_CONSUMER_TASKS B2.3b. 사용자 연속 구현 승인. 기존 dirty metadata-load.md/test_rx_47.py 제외, 유료 호출·기기·배포·사용자 DB 변경0(임시 fixture DB만 검증).

설계: 자연어 step ID→native after_action_id, source check ID→Android resource_id를 별도 immutable recording_check_bindings에 저장한다. 원본 native action_mapping/정제 artifact/기존 승인/FAIL은 수정하지 않는다. 저장은 expected manifest ID/hash CAS와 idempotency key를 검사하고 새 package_rebuild manifest/body hash+별도 후보 version/package를 원자적으로 만든다. binding hash는 새 manifest hash에 포함되고 package hash로 전파된다. 원본 case의 기대값/목표/순서/코드·권한은 바꾸지 않는다. 실제 worker 평가 소비는 B2.3b3/c이며 없으면 현재 required unknown을 유지한다.

- [x] 1 pure source-bound validation/TDD: exact schema·불변ID·<=256 labels/steps/checks, 실제 native trace의 action boundary만 허용. 단계 순서는 nondecreasing, 부분 연결 허용, 중복·범위외·다른 package resource ID·shell/expected 치환 거절. source case version은 recording input으로 고정한다.
- [x] 2 migration0051 immutable bindings + transaction service/TDD: same project/recording/source CAS, source shapev2/ready package/complete only, actor scope, source bytes 유지/새 revision·body·version·package, 기존 current approval/기존 draft/FAIL 그대로, retry after lost response가 같은 원래 receipt 반환. 다른본문/낡은source/외부owner는409/거절. definition과순서/expected값은server immutable source에서 읽는다.
- [x] 3 GET context/POST check-bindings API를 정상 auth/CSRF/Origin/idempotency·threadpool에 연결. source/action/logical/check preview와 이전 binding을 조회해 실행PC offline에도 저장본으로 편집가능. POST는 새 candidate/version/package IDs 반환, 승인/trial/실행은 만들지 않는다. API fixture 경로로 검증한다.
- [x] 4 작은 집중 검사/소유계약/인계/NEXT/master commit. fresh finalreview1+중요수정1pass. 다음 B2.3b2에 실제 녹화 페이지의 boundary/target 편집 UI와 새 후보 안내·분기/검토 링크/키보드/충돌·dirty 복귀를 구현한다. 이 카드만으로 UI/평가/정규화 결과 완료로 올리지 않는다.

Ruling: store/API를 먼저 완결하고 UI를 다음 작은 단위로 연결한다 — 기존 immutable package_rebuild를 재사용하고 실행 권한/검증 PASS를 가정하지 않기 위해서 — 비용: 이 커밋만으로 브라우저 편집 UI는 아직 없다. Ruling: 새 v2만 편집대상 — v1의 손실 매개변수를 binding으로 복구할 수 없기 때문 — 비용: 일부 기존 녹화는 재녹화가 필요하다. Ruling: mapping은 같은 boundary를 공유할 수 있으나 source step 순서를 역전할 수 없다 — 여러 logical 검증이 같은 관찰을 쓸 수 있기 때문 — 비용: 의도적인 역순 흐름은 새 원본/케이스 설계가 필요하다.

Core/store/API 완료 근거와 경계: [인계](../validation/tasks/RX-87-B2-CHECK-BINDINGS.md). Important4(리뷰2+재분류2)를 한 TDD 수정 pass로 처리, 최종집중27passed. 다음은 b2 편집 UI다.
