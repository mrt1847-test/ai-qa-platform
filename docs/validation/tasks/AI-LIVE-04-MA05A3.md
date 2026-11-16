# AI-LIVE-04-MA05A3 · 정상 모델 turn 수용 전 실패 진단

2026-11-17 Asia/Seoul. BASE2998b66 original master. 실제 pinned Mobile-Agent main/public API + 모의 OpenAI/ADB/app launch다. 과금·실기기 호출0, RX87 전체 완료 수는 유지한다.

## 동작·인터페이스

`MobileAgentRegisteredObservation`은 현재 ACK/등록된 관찰의 call/action/before artifact ID/hash/observation ID만 보존하는 frozen snapshot이다. model port는 이를 pending turn과 구분하고 정상 evidence release에서 비운다. 모델 호출 전 fence 거절·provider503·HTTP 응답 유실·잘못된 receipt·닫는 tool tag가 없는 응답은 accepted native turn을 만들지 않는다.

별도 `mobile-agent-authoring-failure-v1` log는 stage=authoring, outcome=no_accepted_action, reason=authoring_unavailable, native_calls0/native=None과 same-call before hash만 담는다. raw exception/provider body/키/추론은 포함하지 않는다. action planned/known0, physical events0, source/package/승인0을 유지한다. 서버 실제 model receipts가 비용/usage/dispatch 사실의 유일 근거이며 로그로 청구 여부를 추정하지 않는다.

서버는 exact original engine/policy와 project/worker/attempt/call의 immutable model observation·before ACK를 대조한다. extra/schema/type/다른 call/hash/owner를 거절하고 a2의 same-call role content 불변을 유지한다. 이 진단은 normal step-v1/실행 ACK/history가 아니다. 캐시된 모델 응답도 action_allowed=False다. 모델 호출 전에 막힌 경우 charged receipt가 없어 history만으로 새 호출을 막지 못하므로, 원본 attempt에 ACK diagnostic이 있으면 observation/model authorization에서 후속 호출을 거절한다.

정제 log는 기존 durable packet/pending recovery를 사용한다. ACK 유실은 같은 body/time/key만 확인하며 새 model/capture/native0이다. 과거 source와 승인본을 변경하지 않는다.

## 검증·검토

초기 RED6은 before만 남고 log가 없는 상태를 재현했다. 첫 관련40pass83.55s. schema/scope/log ACK 검사15pass 뒤 before-model 진단 후 live lease에서 새 유효 call을 보내는 경로가 RED였으며 서버 차단을 보완했다. 한 fresh reviewer Important1(원본 parser가 허용하는 닫는 tag 누락 응답)을 RED2로 재현해, process와 같은 single-tool-block 검사를 pending 할당 전에 적용했다. 한 fix pass, re-review 없음. 최종 관련 결과는 아래 추가한다.

## 제한·후속

image upload/observation 등록 자체가 불명인 경우는 frozen snapshot을 추정하지 않는다. 서버 부분 이미지/미ACK spool을 보존하며 source/승인 gate를 완화하지 않는다. worker finish가 없는 server lost/queued cancel은 MA05a4다. 실제 모델 추론 성능/과금·PC 전원 종료·독립 서버 수용은 별도다.

최종 관련9개 파일 검사: **1 failed201 passed338.06s**. 유일 실패는 old before-only 기대 ID4였으며 새 진단 log까지5개 ID로 바꾸고 planned0/실제 before+log ID를 검사했다. 제품 코드 변경 없이 authoring/runtime 영향2개 파일 후속 **40 passed73.13s**. authoring 진단의 PC offline timeline/log 원문 조회 추가 **1 passed2.22s**. 전체 suite green이나 실제 앱 TC 수가 아니며 기존6개 실패 기준선은 유지한다.
