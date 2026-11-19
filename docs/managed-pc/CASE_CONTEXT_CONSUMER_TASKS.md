# RX87 B2.2 · 고정 metadata의 worker 소비

B2.1 supplier 다음 실제 코드 순서다. 상위 RX87은 미완료다. 외부 기기/키 부재를 구현 선행으로 두지 않는다.

## B2.2a · 신뢰 claim metadata 파싱과 실행 전 gate

Files: worker/case_context.py, worker/android_jobs.py, worker/runtime.py/builder, tests/integration/test_rx87_case_context_consumer.py.

- [x] 실제 API context에서 detached immutable WorkerCaseContext를 만든다. claim project/job/attempt/generation/purpose와 hash/schema, REC/ITEM owner, version·package·타깃 형식을 검사한다. source settings는 model grant가 아니다. mutable dict를 보관하거나 환경변수의 target/check로 덮지 않는다.
- [x] 정상 operational/fixture-live builder는 context를 필수로 요구하고 capture/model/native 전에 잘못된/누락 metadata를 거절한다. 직접 만든 개발 handler의 없는 metadata seam만 명시 호환한다. 새 source context가 있으면 항상 검증한다.
- [x] bool/NaN/다른 scope/hash/버전·package 충돌/response mutation·handler 재사용을 RED→GREEN. 실제 모델/device/DB 접근0인 parser와 정상 API pin→worker를 확인한다.
- [x] actor0/OFF·기존 recording/replay 회귀와 fresh review→필수 수정1회→전체 baseline 비교·인계/큐/master commit.

B2.2a 완료2026-11-14(core_contract): [인계](../validation/tasks/RX-87-B2-CONSUMER.md). 집중93·최종 전체 기존9failed924passed1skipped. 리뷰 Important3 해결, Minor2 후속.

## B2.2b · 선택 앱의 lease 후 준비와 저장 증거

B2.2a에서 builder 생성 시 `prepare()` 호출을 제거하고 검증/현재 fence 뒤의 lazy 준비로 옮겼다. 아래 전체 체크는 선택 앱·journal·저장 증거까지 확인할 때 완료한다. 선택 앱/저장 근거의 구현·검증은 아래와 같다.

- [x] builder 생성 때 실행되는 replay prepare()를 제거한다. 선택된 immutable Android package만 ACK/fresh fence 뒤 시작하고 Settings 기본값으로 대체하지 않는다. 명령은 고정 argv/전용 serial·엄격 package 문법·deadline/no retry, allowlisted Activity Manager 인텐트만 쓴다. 공식 근거: https://developer.android.com/tools/adb#am 및 intent arguments.
- [x] 앱 준비는 gesture plan과 구분된 attempt 소유 operation으로 1회만 허용한다. native 전송 직전 fence/journal, 실패/timeout의 unknown·재시작 차단, source screenshot+정제 log의 durable ACK를 연결한다. 준비 로그/이미지의 이벤트 prefix와 step committer key를 충돌시키지 않는다. 저장된 증거는 worker offline에도 조회한다.
- [x] target secret refs가 있으면 RX99와 같은 pixel-coverage gate를 적용한 뒤에만 upload한다. 정제 성공을 가정하거나 새 경로로 우회하지 않는다. 앱 준비 자체와 최대 gesture 한도를 구분해 제한과 UI 안내를 소유 계약에 기록한다.
- [x] 두 claim 재사용/다른 package·native timeout/ACK 유실/취소·시간/준비 증거 조회를 실제 API+명시 fake ADB에서 검증한다. 실 기기 수용은 RX23이다.

B2.2b core 완료 근거/실제 앱 관찰/리뷰 제약은 [인계](../validation/tasks/RX-87-B2-TARGET.md)를 따른다. 준비1회는 전체 native50에 포함되어 gesture 최대49다. 폼의 한도 설명 문구는 아래 B2.3의 Minor 후속으로 남긴다. 실제 AI/정상 전체 QA 수용은 별도다.

## B2.3 · 검사 시점과 결과 저장

- [x] 리뷰 Minor 후속: Android 녹화/환경 한도 UI에 요청 한도와 준비1회/gesture 최대49의 관계를 안내한다. 50줄 승인 plan은 실행 전 거절되며 앱 기동/gesture가 발생하지 않는다.

B2.3a의 공식 strict 경로에서 고정 required의 누락·중간 final 평가·placeholder verifier를 차단하고 마지막 source coverage/unknown을 반환한다. [세부 구현](PINNED_CHECK_COVERAGE_TASKS.md) · [인계](../validation/tasks/RX-87-B2-CHECK-COVERAGE.md). 직접 개발 constructor의 fixture 검증은 명시 호환이다. binding/evaluator/check_results 저장은 [b3](CHECK_BINDING_RUNTIME_TASKS.md)와 [결과 인계](../validation/tasks/RX-87-B2-CHECK-RESULTS.md)로 완료했다. 실기기 PASS와 healing C/D는 미완료다.

### B2.3b · 승인된 logical 경계와 검증 대상 binding

선행 native 원본 보존/재생을 [B2.3b0](../validation/tasks/RX-87-B2-NATIVE-TRACE.md)로 구현·검증했다. 새 trace의 입력/키/swipe 시간/physical 좌표를 보존하고 compiler pin과 ACK source를 대조한다. 아래 logical mapping 자체와 검토 UI는 계속 미완료다.


저장/API 선행 [B2.3b1](../validation/tasks/RX-87-B2-CHECK-BINDINGS.md)을 완료했다. 원본 보존 새 후보/정확한 source CAS/immutable annotation/API는 구현했으며 편집 UI(b2)·실제 worker 소비(b3)는 아래 상위 체크와 함께 미완료다.

- [ ] 자연어 Step 하나는 여러 gesture가 될 수 있다. logical step 순번을 plan line 순번과 임의로 동일시하지 않는다. 승인된 mapping이 없으면 required step check를 성공 처리하지 않는다. AI recording annotation/사후 검토 mapping의 불변 owner·저장/UI를 별도 구현 단위로 정한다.
b3a exact package annotation 공급·조기 검증은 [인계](../validation/tasks/RX-87-B2-CHECK-BINDING-PIN.md)로 완료했다. typed pin 수신은 평가/PASS가 아니며 worker 경계 평가·hierarchy·normalized 저장은 [다음 구현](CHECK_BINDING_RUNTIME_TASKS.md)의 b3b/c다. 상위 체크와 전체 RX87은 유지한다.

### B2.3c · 실제 평가와 정규화 결과 저장

- [x] final_expected는 마지막 승인 action 이후만, step check는 승인 mapping 시점에만 평가한다. 정상 claim에서 전역 fixture checks/expected로 대체0이다. 평가 불가 required check는 unknown/error이며 AI 보완은 승인된 방법·C 권한/한도에만 따른다. 경계 평가는 [b3b1b](../validation/tasks/RX-87-B2-BOUND-CHECK-EVALUATION.md)다.
- [x] check ID·source hash·source expected·판정·ready artifact를 ITEM finish에 영속화하고 원본 FAIL/승인은 보존한다. [인계](../validation/tasks/RX-87-B2-CHECK-RESULTS.md). 이 저장은 실기기 hierarchy PASS가 아니다. 허용 visual verifier와 healing은 C/D다.

B2.2a 완료가 b/3 또는 C/D의 완성은 아니다. UI/DB 계약 변경은 같은 작업에서 소유 문서를 갱신한다.
