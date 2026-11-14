# RX87 B2.3a · 고정 필수 검증의 누락 방지

> REQUIRED SUB-SKILL: superpowers:executing-plans inline/TDD. 사용자 즉시 연속 실행 승인, 원본 master 유지. BASE d91fe15. Spec CASE_CONTEXT_CONSUMER_TASKS.md B2.3 / CONTRACTS C04/C05/C08/C14.

Goal: 공식 Android 재생이 고정 case의 required check를 worker fixture tuple로 생략하지 않게 하고, 연결되지 않은 검증을 성공으로 보고하지 않는다. 체크 시점/근거를 마지막 action log에 보존한다. 실제 verifier 모델 권한은 C이며 여기서 모델을 추가 호출하지 않는다.

Architecture: 기존 source CheckSpec에는 subject/gesture 경계 binding이 없다. StepMapping은 gesture action mapping이며 logical StepSpec이 아니다. worker/replay_check_coverage.py의 pure typed coverage 판정은 원본 expected/check ID/method/context hash를 보존해 미연결 이유를 명시한다. final_expected는 마지막 승인 action 뒤만, mapping 없는 logical step check는 마지막에 미평가 unknown으로 보고한다. 현재 PNG만으로 text/value/state assertion PASS를 만들지 않는다. explicit legacy direct handler는 기존 verify seam을 유지하고 공식 require_case_context=True 경로는 fixture check/transport로 대체하지 않는다. require_case_context=False인 직접 개발 constructor는 기존 fixture 검증을 유지하되, supplied metadata 자체의 파싱/owner 검증은 생략하지 않는다. 후속 B2.3b가 승인 mapping/subject binding과 실제 deterministic hierarchy evaluator를 제공하며 B2.3c가 check_results/ITEM 영속·결과 계약을 연결한다. API schema를 임의 확장하지 않는다.

- [x] 1. Create worker/replay_check_coverage.py + test_rx87_check_coverage.py. frozen RequiredCheckCoverage/check_result와 plan-local phase 검증, pinned expected/method/step/check identity, source binding 부재 이유, PNG/engine-done/fixture transport가 성공 증거가 되지 않는 negative를 RED→GREEN. Final 중간평가0, required check 없는 명시 source는 coverage 빈 결과다.
- [x] 2. AndroidReplayHandler가 pin 있는 claim에서는 실제 마지막 action 뒤 coverage를 소비하고 required unknown이면 check_failed/error를 반환한다. legacy _case_context 없는 직접 개발 handler는 유지한다. claim마다 결과 초기화, source context hash와 action/check/result를 구조화 log에 넣고(저장 표현은 원본 expected 대신 hash만, stdout 제외) PNG/gesture prefix/owner를 유지한다. 공식 factory의 가짜 verifier RoleBinding/OwnedCheck/_NoTransport는 제거한다. paid AI0, 실패/불명 dispatch에서 final 검증 성공0. 실제 서버 source 형태의 pin→명시 2gesture fixture→반환된 마지막 log artifact를 검사한다. 실제 normalized check_results와 ITEM 저장은 후속 B2.3c다.
- [x] 3. 녹화 준비/환경 한도에 Android 준비1회 포함 총50/gesture49 안내를 추가한다. 기존 input값/정책을 바꾸지 않는다. 기존 페이지 render 회귀/키보드 접근을 확인한다.
- [x] 4. fresh final review1회, Important/Critical만 한 TDD 수정 배치. 집중/전체 baseline9/JS32·문서/큐·로컬 commit. 원본 dirty metadata-load.md는 성능 테스트 자동 갱신 report이며 stage/수동복원하지 않는다.

Pre-flight: source cases.CheckSpec(id,kind,expected) != runtime checks.CheckSpec(subject/method/step) — binding 없이 번호/id를 subject로 추정하지 않는다. compiler StepMapping.step_id는action_id — 자연어 단계와 혼용0. recording model grants != replay verifier grants — C 전 실제 모델0.
Review focus: pinned check를 전역 fixture로 대체하는 입력; 중간 final_expected/마지막 미실행; handler 재사용/다른 claim; secret/raw observation의 log 누출; unknown이 PASS/승인/기존 FAIL 덮어쓰기로 연결되는 경로. 이 배치는 binding 없는 required를 정직하게 unknown으로 보고하는 부분 구현이며 B2.3/상위 RX87 완료가 아니다.

완료2026-11-15(core B2.3a): source/단위19+리뷰/표현예산5=24, 집중120+리뷰26/JS32, 최종 전체 기존9failed987passed1skipped524.25s. 인계 RX-87-B2-CHECK-COVERAGE.md. Parent B2.3/RX87 미완료.
