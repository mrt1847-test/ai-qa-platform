# AI-LIVE-04-MA05A2 · 원본 행동 실패 로그·상태·증거 ACK 복구

2026-11-17 Asia/Seoul, BASE2a1d717 original master. 실제 upstream main/public API + mock OpenAI/ADB/app launch 등급이며 유료·실기기 호출0. RX87 전체/87/99·49/53 완료 수는 유지한다.

## 인터페이스·동작

`recording.mobile_agent_evidence`는 reserved ma-call의 bounded strict packet을 검사한다. before ACK는 planned/known0이다. observed step-v1은 같은 authenticated model receipt/call/worker/attempt/generation/geometry/before hash/원본 parser의 typed native와 전후 PNG/hash·이벤트 쌍을 대조한다. failure-v1은 log만 저장하고 unknown/known native ACK/known not-sent를 구분한다. native timeout에는 after를 조작하거나 다시 캡처하지 않는다. unknown0, acknowledged1, not_sent→lookup_failed1이다. wait/terminal 미관찰은 control_unobserved이며 physical native0이다.

서버는 같은 call/role의 ACK 파일 hash 변경을409로 막고, planned에서 검증된 상태로만 전환한다. failure에는 physical events0, 성공 history release0, source/package/승인0이다. raw 예외/stdout/키/hidden reasoning을 포함하지 않고 enum reason과 typed 동작·이미지 hash만 저장한다. PC offline에서도 기존 timeline과 artifact API로 unknown 상태·before·로그를 읽는다.

`MobileAgentRecordingSession`은 실패 시 별도 진단 log를 durable StepEvidenceCommitter에 넣는다. normal after/log packet이 이미 시작됐으면 그 packet만 재확인하며 실패 payload로 교체하지 않는다. `pending_sequence/confirm_turn`은 owner/checksum/고정 packet을 검증하고 ACK된 원 receipt도 재사용한다.

`MobileAgentRecordingResult.evidence_pending` → 내부 `HandlerResult.evidence_recovery` callback → runtime pending_evidence로 미확인 ACK를 전달한다. unresolved packet이 있으면 finish body/key를 동결하지 않고 새 claim도 하지 않는다. metadata ACK를 얻은 뒤 실제 contiguous seq/hash·known action 수·artifact ID로 error/incomplete finish와 cleanup을 진행한다. 복구에 native/model/capture0, counts는 한 번만 합산한다. helper는 worker HTTP에 노출하지 않으며 재시작한 handler를 자동 재실행하지 않는다.

## 검증·검토

초기 RED4→관련34pass98.77s. 실제 API 변조/ACK 유실 테스트에서 strict type RED2를 확인하고 reason enum·native 숫자 타입을 고쳤다. 한 fresh reviewer Important4를 exact pair/after geometry/role bytes/미확인 ACK cursor RED9로 재현한 뒤 한 fix pass로 보완했다. 새 집중25pass80.06s. 최종 관련 회귀 결과는 아래 추가한다.

## 제한·다음

모델 turn을 수신하기 전 오류는 before planned만 보존하며 별도 진단 로그는 MA05a3다. worker finish가 오지 않는 watchdog/lost 경로는 MA05a4에서 조사한다. 역사적으로 잘못 저장된 observed row를 일괄 수정하지 않는다. 승인/새 모델 history는 여전히 exact same-call source proof를 요구한다. 실행 PC 실제 전원 종료·유료 모델·독립 호스트 수용을 이 검사로 대체하지 않는다. generated metadata-load.md는 변경을 보존하고 commit에서 제외한다.

확대 회귀의 첫 실행은14failed142passed256.28s였다. 기존 history fixture의 events=[]12개와 journal fixture의 빈 events1개를 실제 전후 pair로 수정했고, teardown은 새 terminal failure log까지8개 ID를 검사한다. wrong-native/premature-proof는 서버 ingest422를 검사하도록 앞당겼다. 후속46pass66.34s. ACK receipt의 지속 로컬 fsync 실패에 대해 추가 RED를 확인해, durable ACK 저장 전에는 메모리 pending/cursor를 되돌려 보존하도록 수정했다. 이 동작 변경 뒤 관련 suite를 다시 실행했다.

최종: 위13개 관련 파일을 실행해 **157 passed263.30s**. 그 뒤 visible receipt rename 후 local error도 RED1로 확인해, session이 normal turn의 `confirm_turn`에서 이미 저장된 receipt를 재사용하게 보완했다. 변경 영향4개 파일(`test_ma05_failure_evidence.py`, `test_ma04_mobile_recording_session.py`, `test_ma04_mobile_runtime_handler.py`, `test_ma04_mobile_evidence_delivery.py`)의 최종 검사 **73 passed193.48s**. 한 전체 suite의 green 주장/실제 앱 TC 수가 아니며 기존6개 실패는 이전 기준선에 남아 있다.
