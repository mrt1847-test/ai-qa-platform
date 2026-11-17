# RX87 B2.3b3 · 저장 검증 연결의 재생 워커 소비

> REQUIRED SUB-SKILL: superpowers:executing-plans inline/TDD. 각 독립 배치 마지막 fresh review1/필수 수정1pass. master에서 수행한다.

Goal: 저장한 logical step→native boundary/check→resource 연결을 실행하는 exact package에 묶어 소비한다.
Architecture: annotation을 source manifest로 가진 package에만 서버가 case_context의 optional check_bindings를 투영한다. 워커는 원본 native witness와 annotation/derived manifest hash를 대조해 detached typed pin으로 보관한다. 다음 배치가 이 pin의 실제 경계에서 관찰/평가하고 정규화 결과를 저장한다.
Tech: 기존 Python/SQLite/ASGI/runtime. 신규 설치/DB migration 없음.
Spec: CASE_CONTEXT_CONSUMER_TASKS.md B2.3b/c, CONTRACTS C04/C05/C06/C14, 사용자 저장 후 사후 승인 및 기본 AI0 목표.

## Global constraints

- trial은 미승인 후보 검증일 수 있다. metadata 수신은 사람 승인/시범 성공/모델 권한이 아니다.
- 기본 actor AI0, healing OFF 유지. annotation/원본 native/source/기존 승인·FAIL 수정0.
- 없거나 평가하지 못한 required는 unknown/error다. step 순번=gesture 순번 추정0.
- latest annotation fallback0. exact package/source manifest와 불변 candidate를 사용한다.
- 실제 키/기기/외부 호스트를 로컬 구현 선행으로 요구하지 않는다.

## b3a · exact package annotation pin 공급·조기 검증

BASE ed8da99. Owners: recording/check_bindings.py, recording/case_context.py; new worker/check_binding_pin.py; worker/case_context.py optional field 검증; android_jobs.AndroidReplayHandler 조기 소비/초기화. Tests: tests/integration/test_rx87_check_binding_pin.py + 관련 existing context/native/binding tests.

Interface: load_runtime_check_binding_pin(connection,project,package_id)->dict|None. case-context-v1.check_bindings는 annotation이 있을 때만 추가한다. schema recording-check-binding-pin-v1, recording_id/manifest_id/manifest_hash/source_manifest_id/source_manifest_hash/input_case_version_id/source_content_hash/binding_hash/bindings. secret/예상값/source native literal을 복사하지 않는다.

resolve_claim_check_binding_pin(claim,case_context,native_source)->WorkerCheckBindingPin|None. UUID/형태/크기·원본 source IDs/order/선택 package resource·canonical binding hash·derived manifest hash와 resolved native source witness를 검사한다. frozen tuples로 반환, 보관 원문 변경이 pin에 영향을 주지 않는다. 새 claim마다 초기화하고 잘못된 supplied pin은 기기 준비/캡처/native/model 전에 check_bindings_invalid로 거절한다. valid pin만으로 기존 required unknown을 PASS로 바꾸지 않는다.

- [x] RED: 실제 저장 annotation package의 서버 투영/다른 package 미수신·과거 package에 최신 연결 fallback0; detached worker pin과 foreign/source/hash/target/order/null/extra 거절, 부작용0.
- [x] 위 인터페이스와 정상 case_context 공급 및 AndroidReplayHandler 조기 검증을 구현한다. annotation 없는 legacy source는 기존 동작 유지, recording/Web context는 Android annotation을 수용하지 않는다.
- [x] 관련 회귀·fresh review/한 수정 배치·계약/인계/NEXT/진행표/master commit. UI/실제 평가 완료로 세지 않는다.

Review focus: candidate 버전과 입력 버전 혼동; 동일 녹화의 더 최신 annotation으로 오래된 package 치환; typed mutable dict 누수; 원본 witness 없는 foreign annotation 수용; 두 번째 claim에 첫 annotation 잔류. 각 테스트에 포함한다.

## b3b · 경계별 실제 관찰·평가 (다음)

b3a pin의 step boundary에서만 step checks, 마지막 승인 action 후 final checks를 평가한다. 실제 hierarchy read-only 관찰/선택 package resource 대상과 deterministic evaluator를 연결한다. PNG/engine 완료 문구만으로 PASS0, 미연결·누락·실패 required는 unknown/error, source check ID/expected 보존. 세부 leaf는 b3a 인계+실제 ports 조사로 확정한다.

## c · 정규화 결과/ITEM 영속 (다음)

check ID·source hash·expected/observed·판정·evidence를 durable commit/normalized check_results/ITEM QA에 연결한다. 원본 FAIL와 승인 보존, 모델/제한 healing grant는 C/D의 별도 구현이다. 이후 MA05b2의 정상 원본→사후 승인→동일 package AI0 여정으로 돌아간다.

b3a 완료: [인계](../validation/tasks/RX-87-B2-CHECK-BINDING-PIN.md), 관련144pass52.20s. NativeSource는 verified manifest_id/hash도 frozen으로 보존한다. 크기는 compact UTF8 문서131072bytes이며 envelope/escaped DB 표현 한도와 구별한다. actual evaluator/normalized 결과/전체 RX87은 미완료다.
