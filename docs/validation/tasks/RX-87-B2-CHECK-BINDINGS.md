# RX87 B2.3b1 · 검증 경계 연결의 불변 저장/API

2026-11-15, master 기준e9ea37f. core store/API 완료이며 브라우저 편집 UI(B2.3b2), worker 검증 시점 소비/실제 평가/정규화 결과(b3/c)는 아직 없다. 상위RX87·전체87/99·기능49/53 유지. 이번에 모델·기기·유료 API·실제 사용자 DB를 호출/변경하지 않았다.

## 결과

자연어 step ID→after_action_id, source check ID→선택 앱 resource_id를 저장한다. 원본 native mapping·입력 case version의 목표/기대값·기존 승인·원본 FAIL bytes를 바꾸지 않는다. 각 step 위치를 임의 같은 ordinal로 간주하지 않고 실제 native ID를 선택한다. 원본 step 순서에 따라 boundary가 역전되면 거절하며 같은 boundary/부분 연결은 지원한다. 다른 check/step/action ID·다른 package·shell·expected 치환은 거절한다.

migration0051 recording_check_bindings는 새 derived manifest와 원래 source/hash/input version을 결합한 immutable row다. INSERT trigger가 project/recording/derived manifest/prior/source hash/input version/native bytes/complete 상태를 함께 대조한다. 독립 FK만으로 다른 recording의 manifest를 결합할 수 없다. UPDATE/DELETE는 금지한다. Binding hash는 새 manifest hash에 들어가 package hash에 반영된다. 정식 검증 권한이나 모델 grant가 아니다.

expected_manifest_id/hash CAS와 actor-scoped body fingerprint·request key로 저장한다. ACK 유실 retry는 같은 source를 기준으로 기존 receipt를 먼저 읽고 새 head CAS를 뒤에 검사하므로 같은 후보가 반환된다. 다른 본문이나 새 key+옛 source는409다. 실패 materialization은 savepoint로 candidate/annotation/manifest 전체 rollback한다. 기존 materializer로 새 version/package를 만들며 late branch이면 기존 draft pointer와 approval은 유지된다. 새 후보 생성 시각은 실제 UTC now다. 과거 immutable 이력 날짜는 고치지 않는다.

일반 rebuild_android_package는 annotation이 붙은 source를 암묵 복사/유실시키지 않고 명시 거절한다. 연결 변경은 새 check-bindings API로 해야 한다. v1/불완전 source는 편집 대상이 아니며 원본 v1 bytes는 보존한다.

## API

`GET/POST /api/v1/projects/{project_id}/recordings/{recording_id}/check-bindings`

GET은 세션/project scope를 확인하고 latest complete native source, logical step/check preview, native IDs/ordinal/kind와 현재 binding을 반환한다. native text literal은 응답에 복제하지 않는다. POST 본문은 expected_manifest_id/hash, step_boundaries:[{step_id,after_action_id}], check_targets:[{check_id,resource_id}]만 받는다. body128KiB는 chunk copy 전 검사하고 중복 JSON key/추가 field를 거절한다. CSRF/Origin/Idempotency-Key가 필요하며 DB/auth 작업은 threadpool에서 수행한다. 실행PC online/model key와 독립인 서버 저장본 작업이다. 새 후보는201/retry200, conflict409, wrong input422, unknown source404, no session401/CSRF-Origin403이다.

반환 case_version_id/replay_package_id/manifest_id는 새 후보이며 approved=false다. 옛 기본 승인본을 해제하거나 새 trial/정식 실행/자동 승인을 만들지 않는다. 현재 worker는 이 binding을 아직 소비하지 않으므로 required unknown을 PASS로 바꾸지 않는다.

## 검증·리뷰

pure validation missingmoduleRED→11passed0.04s. store/derived/idempotency/source unchanged→15passed1.84s. API route missingRED2→18passed3.31s, 원본 materialization/schema/bootstrap regression2passed11.15s. 강제 materialization 실패에서도 caller가 예외를 잡고 transaction을 계속할 때 부분 row0을 확인했다.

fresh final review1회: Important2 + Minor2. (1) 잘못 결합된 source/recording row (2) generic rebuild의 binding 유실을 TDD로 재현했다. 날짜 오류는 사용자의 이력/누적 분석에 잘못된 새 시각을 기록하므로 Important, body copy 후 한도 검사는 새 웹 endpoint의 명시 memory budget을 넘기므로 Important로 재분류했다. 4 source tuple negatives + rebuild + timestamp + stream budget RED7→한 수정 배치→27passed10.88s(기존materialization/bootstrap 포함). DB metadata UPDATE를 허용하거나 기존 gate/실패를 숨기지 않았다. 재리뷰/전체 무변경 검사 반복/유료 호출0이다. 기존 전체9개 baseline 결함을 고쳤다거나 전체 green이라고 하지 않는다.

## 판단·후속

- 먼저 store/API를 완결했다. 비용: 이 커밋만으로 브라우저 편집은 없다. 다음 B2.3b2에서 정상 녹화 페이지 UI/키보드/dirty·충돌·정확한 새 후보 검토 링크와 승인 표기를 연결한다.
- v2만 지원한다. 비용: 손실된 v1의 값은 복구하지 못하므로 재녹화가 필요할 수 있다.
- 순서 역전은 금지하고 같은 boundary는 허용한다. 비용: 의도적 역순 흐름은 새 원본/케이스 설계가 필요하다.
- 일반 rebuild의 binding 계승은 아직 구현하지 않고 차단한다. 비용: 기존 범용 rebuild 호출자는 annotation API를 사용해야 한다.
- 새 생성 시각을 실제 now로 고쳤지만 과거 이력 시각은 immutable로 남긴다. 비용: 과거 잘못 찍힌 날짜는 이 커밋으로 보정되지 않는다.
- worker 평가 소비·UI·일반 OpenAI 서버 공급자·정규화 저장·전체 승인 수용은 유보했다. 미룬 Minor 없음. 사용자 dirty metadata-load.md/test_rx_47.py는 수정/복원/커밋하지 않는다.

로그 .review-work/check-binding-storage/{validation-red,validation-green,store-red,store-green,api-red,api-green,review-red,review-green,regression}.log. 다음 구현은 필요 라이브 환경을 기다리지 않는다.
