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

## b3b0 · bounded Android hierarchy의 명시 대상 관찰

BASE dca71ce. 소유 새 environments/android_hierarchy.py와 tests/unit/test_android_hierarchy.py. 기존 AndroidObservationProvider는 PNG/geometry를 수집하고 validation/android는 fixture JSON을 읽으므로 먼저 실제 UIAutomator XML을 명시 resource 사실로 해석하는 pure 포트를 만든다. native command 실행/AI/저장·QA/승인 변경은 이 leaf가 아니다.

Interface: parse_android_hierarchy(raw:bytes,*,package:str,resource_ids:tuple[str,...],rotation:int)->AndroidHierarchy. frozen snapshot(rotation,targets)와 target(resource_id,status,text,enabled,checked,selected,focused,visible)을 반환한다. status available/missing/ambiguous/redacted/unavailable는 관찰 품질이며 QA 결과가 아니다. text는 local raw/repr 제외, 이 포트가 정제·영속화를 주장하지 않는다. 없는 boolean은 None, visible-to-user가 없으면 visible=None이며 value=text로 추정하지 않는다.

- [x] RED exact selected package/resource만 수집하고 같은 resource가 둘이면 ambiguous로 남긴다. password=true는 text/상태를 노출하지 않고 redacted, password field 없거나 잘못됐으면 unavailable. 다른 앱·비선택 text를 snapshot/오류/repr에 복사하지 않는다. 요청 중복은 dedup 가능하나 원본 node 중복을 숨기지 않는다.
- [x] byte1MiB/UI node4096/depth64/선택 text UTF8 4096bytes/targets256을 제한한다. strict UTF8/단일 hierarchy root·rotation0..3와 요청 degrees(0/90/180/270) 일치, DTD/ENTITY 금지, 비정상 XML/한도/rotation 오류는 고정 reason AndroidHierarchyRejected다. external/network XML0, 자동 ratio/회전 보정0. XMLPullParser chunk 검사로 node/depth를 읽는 중에 제한한다. unknown attributes는 무시하되 임의 text/메타데이터를 보존하지 않는다.
- [x] 정상 nested/UTF8/escaping·missing/duplicate/foreign/password/필드 누락/비정상·폭주 XML·rotation·ID/token 부정과 불변성/부작용0을 검사한다. focused 기존 observation/validator 회귀·fresh review1/한 fix pass·인계/큐/master commit. 실제 기기 XML 수용은 b3b1 native reader에서 별도 확인한다.

Ruling: password flag 없는 node를 안전하다고 추정하지 않는다 — raw local 관찰의 민감값이 검증 로그로 새지 않도록 — 비용: 오래된 dump는 unknown일 수 있다. Ruling: visible/value 의미를 text나 node 존재로 추정하지 않는다 — 실제 field 부재가 PASS가 되지 않도록 — 비용: native 관찰 확장 전 일부 state/value 검증은 unknown이다.

## b3b1a · 기존 실제 XML 수집의 공통 포트 추출

직접 선행 b3b0 인계와 [Mobile-Agent/프로젝트 중복 검토](MOBILE_AGENT_RESPONSIBILITY_AUDIT.md)를 읽는다. tools/android_mobile_agent_record_replay.py의 capture_once가 이미 XML을 수집하고 mobile_agent_frames._anchor가 XML을 해석한다. 수집 알고리즘을 worker에 복제하지 않는다.

- [x] 기존 CLI capture_once/native XML read·focus 검사를 공통 environments 포트로 추출하고 CLI가 그 포트를 소비하도록 전환한다. 기존 AndroidObservationProvider/_run_bounded를 재사용한다. serial/AVD/package·현재 제어·모든 deadline·capture 정제·raw local 데이터 경계를 유지한다. 기본값 fixture 성공/새 AI 루프/새 클릭 실행기0.
- [x] 원문 XML/file/stderr를 remote artifact나 오류에 복사하지 않는다. 선택 resource 대상은 b3b0을 소비한다. 고정 stdout 경로(/proc/self/fd/1) 방법은 실제 probe에서 XML+공식 완료 suffix를 확인했으며 argv/한도/정확한 framing을 테스트한 뒤만 사용한다. 남는 임시 device 파일을 만들지 않는 방향을 우선한다.
- [x] _anchor와 새 parser의 낮은 XML decode/한도 검사가 공유 가능한지 대조한다. frame target 보호와 assertion 의미는 합치지 않는다. CLI/worker가 동일 공통 수집 포트를 사용하는 부정/호출 수·취소·변경 target/rotation 회귀·명시 실제 AVD read를 검증하고 인계/master commit한다.

## b3b1b · 정확한 경계의 deterministic 평가

직접 선행 [공통 reader 인계](../validation/tasks/RX-87-B2-ANDROID-HIERARCHY-READER.md)와 b3a pin/기존 replay_check_coverage를 읽는다. 소유 worker/bound_check_evaluation.py(순수 일정/비교), android_jobs.AndroidReplayHandler._verify_and_heal와 호출부, 관련 focused tests다. actual port는 context.hierarchy_observer(package,resource_ids,checkpoint,timeout)다.

- [x] RED 원본 NativeSource.steps의 현재 action ID와 binding.boundaries를 대조해 그 동작 뒤에만 step checks를 예약한다. logical ordinal=gesture ordinal 추정0. final checks는 마지막 승인 action 뒤만이다. 미연결 required는 마지막에 unknown으로 보존하며 중간 실패/취소 후 성공을 꾸미지 않는다.
- [x] due checks 중 승인된 deterministic 정책/명시 resource만 공통 reader로 묶어1회 읽는다. 현재 claim의 read-only checkpoint와 남은 총 시간/명령 cap을 전달하고 extra PNG/model/입력 한도 차감0이다. 마지막 native 예산을 소진했어도 합법적 조회를 잘못 막지 않는지 검사한다. caller fixture check/expected를 섞지 않는다.
- [x] source CheckSpec id/expected/phase/context/content hash를 보존한 RequiredCheckCoverage를 만든다. text는 실제 text field와 exact 비교, state는 명시 boolean 의미가 지원될 때만 비교한다. 없는 value/visible을 text/존재로 추정하지 않고 missing/ambiguous/redacted/unavailable/지원 안 되는 kind는 unknown이다. AI 정책은 C 연결 전 unknown이며 여기서 호출0이다. assertion 실패는 healing하지 않는다.
- [x] worker 정상 claim→여러 gesture/같은·여러 boundary→마지막 final·미연결/누락/모순/취소/한도·actor AI0를 검증한다. coverage의 기존 원문 생략 log 정책/FAIL/승인/source를 보존한다. actual check_results 영속은 c이며 검증되지 않은 결과를 완료로 세지 않는다. fresh review1/한 fix pass/인계/큐/master commit한다.

## c · 정규화 결과/ITEM 영속 (다음)

check ID·source hash·expected/observed·판정·evidence를 durable commit/normalized check_results/ITEM QA에 연결한다. 원본 FAIL와 승인 보존, 모델/제한 healing grant는 C/D의 별도 구현이다. 이후 MA05b2의 정상 원본→사후 승인→동일 package AI0 여정으로 돌아간다.

b3a 완료: [인계](../validation/tasks/RX-87-B2-CHECK-BINDING-PIN.md), 관련144pass52.20s. NativeSource는 verified manifest_id/hash도 frozen으로 보존한다. 크기는 compact UTF8 문서131072bytes이며 envelope/escaped DB 표현 한도와 구별한다. actual evaluator/normalized 결과/전체 RX87은 미완료다.

b3b0 완료: [인계](../validation/tasks/RX-87-B2-ANDROID-HIERARCHY.md), 관련76pass0.60s. pure selected-resource XML port이며 실제 native reader/경계 평가·QA 저장은 b3b1/c다.

b3b1a 완료: [인계](../validation/tasks/RX-87-B2-ANDROID-HIERARCHY-READER.md), 관련192pass55.45s + 실제 Android launcher read8.594s(앱 QA 아님). XML은 check-time 보조 경로이며 일반 녹화 PNG/원본 main을 유지한다.

b3b1b 완료: [인계](../validation/tasks/RX-87-B2-BOUND-CHECK-EVALUATION.md). 저장 action ID 뒤에서만 deterministic text/명시 state를 평가하고, 미연결·판독 불가는 unknown으로 남겨 재생 완료로 세지 않는다. normalized check_results/ITEM 영속은 c이며 전체 RX87은 미완료다.
