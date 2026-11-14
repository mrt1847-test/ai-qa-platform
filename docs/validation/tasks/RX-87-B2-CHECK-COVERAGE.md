# RX87 B2.3a · 필수 검증 누락 방지 인계

- 상태: complete(core_contract B2.3a), 최종 전체 기준선 비교 완료. 기준 master d91fe15, 2026-11-15. 상위 B2.3/RX87 미완료, 전체87/99·기능49/53 유지. 유료 모델/native device 실행·배포 없음. 기존 metadata-load.md report는 test_w27이 자동 갱신하며 stage/수동 복원하지 않는다.
- 코드: worker/replay_check_coverage.py, worker/android_jobs.py, 녹화 준비/환경 프로필 template. source cases.CheckSpec에는 deterministic subject가 없고 compiler StepMapping.step_id는 gesture action ID다. 이 값을 logical StepSpec이나 resource_id로 추정하지 않는다.
- required_check_coverage(pin,action_index,total_actions,observed_at)는 frozen RequiredCheckCoverage를 반환한다. 중간 action에서는 final_expected를 평가하지 않는다. 마지막 실제 action의 유효한 후속 관찰에서만 source step/final 체크 ID·expected·kind·version/content/context hash를 보존해 미연결 unknown을 생성한다. logical mapping/subject가 없거나 verifier가 미연결/불명 정책이면 성공이 아니다. 이 함수는 evaluator/model grant가 아니며 실제 check PASS는 아직 제공하지 않는다.
- 공식 require_case_context=True Android builder/handler는 worker-local fixture checks/broker/transport로 고정 source required를 대체하지 않는다. 기존 가짜 verify RoleBinding/OwnedCheck/_NoTransport factory 설정도 제거했다. supplied source가 유효해도 require_case_context=False인 직접 개발 constructor는 기존 fixture verifier를 사용한다. supplied metadata의 파싱/owner 검증은 계속 적용한다. HTTP payload가 이 개발 모드를 선택하지 못한다.
- 마지막 action log의 verification 항목은 source check ID/phase/step, version/hash/context, status/method/reason/time을 저장한다. in-memory expected는 원문 그대로이며 durable 표현에는 expected_snapshot=[source expectation omitted]와 expected_hash만 쓴다. strict replay의 raw stdout/observed text는 로그에 복사하지 않는다. 원문 기대값은 권한 있는 고정 case version에서 읽어야 한다. PNG·기존 gesture event prefix/ITEM 소유는 유지한다. 원본 FAIL/승인 package를 변경하지 않는다.
- 미확정 required가 있으면 handler는 error를 반환하고 정상 finish는 INCONCLUSIVE다. 제품 assertion의 violated/FAIL을 새로 만들거나 모델/치유를 자동 호출하지 않는다. check_results 테이블·정규화 ITEM 분석 저장은 아직 후속이다. 이 배치를 실제 검증 엔진/AI 녹화·재생 전체 완료로 보고하지 않는다.
- coverage source의 steps/총 check는 각각<=256, ID/kind/source metadata 문자열은 UTF8<=256bytes다. 마지막 log의 크기를 보장할 수 없는 source는 앱/gesture/capture 전 check_coverage_limits로 거절한다. 원래 expected 텍스트 자체는 이 제한에 포함하지 않으며 5MB 원문도 hash 표현만 저장한다. 실제 서버 artifact 상한5MB를 넘겨 기존 step prefix가 유실되지 않게 한다.
- strict before와 제공된 after 시각은 dispatch 전, live after 시각은 observed journal ACK 전에 timezone-aware ISO/최대64자로 검증한다. 마지막 live frame이 invalid이면 기존 after_evidence_missing/ambiguous 경로로 돌아가 이미 수행한 앞 step의 prefix/artifact를 반환한다. 마지막 미관찰 native action의 개별 서버 증거 보강은 기존 후속 범위이며 이 로그가 실제 final check 성공을 대체하지 않는다.
- UI: Android 준비1회 포함 전체50/탭·스와이프 최대49를 기존 숫자 입력과 aria-describedby로 연결했다. 입력값과 요청 한도/기존 동작은 바꾸지 않았다. template render/기존 페이지 회귀를 수행했으며 새 상호작용은 없다.

## 검증

- RED9 module 부재→GREEN9. handler RED2 고정 required 무시 후 completed/재사용 상태누락→GREEN. source stable identity RED1→GREEN. 최초 집중120passed93.74s(coverage19 + consumer/replay-control/setup/RX79/W11).
- fresh final review1회: Critical0/Important3/Minor0. 민감 expected/raw stdout 로그 RED1, 5MB expected로 artifact 거절 RED1, 마지막 malformed timestamp의 예외 탈출 RED1을 한 수정 배치로 해결했다. count/ID 표현 불가 전송 전 거절 RED2도 추가했다. 수정 후 coverage24+RX71/RX77 원래 양성 여정2 →26passed39.24s. 재리뷰 없음.
- 최초 전체11failed980passed1skipped573.49s의 새 RX71/RX77 두 건은 공식 strict와 직접 개발 constructor 경계를 혼동한 회귀였다. 원래 expected PASS나 trial/review 검사를 바꾸지 않고 기존 require_case_context 구분을 복구했다. 정상 factory는 계속 strict이며 빈 fixture tuple로 required check를 숨길 수 없다.
- JS32passed204.4831ms. 최종 전체 **9failed987passed1skipped524.25s**. 실패 node9는 B2.2b/기존 기준선과 정확히 같고 신규 실패0이다. 전체 green은 아니다. 로그 .review-work/check-coverage/{focus,review-red,review-green,full,verified-full,js}.log.

## 판단·제약·다음

1. source subject/승인 logical mapping이 없으면 unknown이다. 이 임시 공백의 비용은 B2.3b 실제 mapping/binding이 연결되기 전 assertion PASS를 제공하지 못한다는 점이다.
2. 먼저 action log에 source coverage를 보존하고 normalized check_results/ITEM ingress는 후속으로 둔다. 이 단계로 누적 QA 분석 완료를 주장할 수 없다.
3. 개발 constructor의 기존 fixture 검증은 유지한다. custom live 통합자는 반드시 공식 strict builder를 사용해야 한다.
4. 원문 expected와 raw 관찰 텍스트를 durable replay log에 복제하지 않는다. 원문은 고정 case version으로 이동해 봐야 하며 로그만으로 기대값을 해석할 수 없다.
5. coverage 표현 예산을 실행 전 검사한다. API가 저장 가능한 과대 source도 이 worker에서는 제한/축소가 필요하다.
6. 리뷰가 유보한 mapping/실 hierarchy/모델 권한/정규화 저장·실기기/전체 수용은 미완료다. 기존 legacy/recording formatter의 stdout과 별도 source UI 개인정보 정책을 전부 해결했다는 뜻이 아니다. 마지막 전체 기준선 비교는 작성자가 직접 수행한다.

다음은 CASE_CONTEXT_CONSUMER_TASKS.md B2.3b의 승인 logical 경계/검증 대상 binding과 저장/UI다. 기존 recording_manifests의 prior_manifest_id/package_rebuild 구조를 재사용해 원본 recording/package/FAIL을 보존하는 새 후보를 만든다. C 서버 verifier/episode 권한과 D 제한 healing은 이후다. 운영 키 부재로 독립 구현을 멈추지 않는다.
