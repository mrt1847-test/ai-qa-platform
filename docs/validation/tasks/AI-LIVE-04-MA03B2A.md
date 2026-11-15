# AI-LIVE-04-MA03B2A · 고정 원본 engine pin과 기존 워커 분리

2026-11-16 Asia/Seoul, 기준 master4ed74fb. MA03b B2a를 구현했다. 새 원본 프로토콜과 기존 자체 parser를 구분하기 위한 계약이며 정상 접수의 기본 engine을 전환한 것은 아니다. 유료/API/ADB 호출0, 전체 RX87/87of99·기능49of53 완료 수 유지.

contracts/mobile_agent_engine.py의 dependency-free ref는 kind=mobile-agent-v3.5, 실제 upstream commit81fa28b564ef7a695521500bc15a0e1324b2b394, 기존 검증 manifest SHA, protocol=mobile-agent-parent-rpc-v1을 정확히 고정한다. 반환값은 새 dict다. adapter도 같은 상수를 사용해 두 source anchor가 어긋나지 않는다. vendor/source manifest bytes는 바꾸지 않았다.

freeze_authoring_limits의 서버 내부 engine_ref를 명시하면 authoring_engine을 detached 복사하고 policy hash에 포함한다. marker가 없는 기존 pin/hash는 원래 계산식 그대로다. null/부분/다른 source·protocol/추가 필드 marker는 hash를 다시 계산해도 validator가 거절한다. marker만 남아도 legacy로 downgrade하지 않는다. validate_authoring_pin은 preserved extension까지 deepcopy해 반환값 변경이 claim을 바꾸지 않게 한다. 이 검사는 일관성 검증이며 request가 자기 pin을 만들어 권한을 얻는 구조가 아니다.

기존 resolve_recording_limits는 marker가 있으면 명시 supported_engine이 정확히 일치해야 한다. 기존 AndroidRecordingHandler는 이 지원을 선언하지 않으므로 다른 원본 프로토콜을 자체 루프로 실행하지 않는다. 기존 server_model_plan_provider도 marker가 있는 요청을 캡처/모델 전송 전에 거절한다. 실제 원본 handler는 MA04에서 별도 등록한다.

검사: engine 계약 RED11/legacy positive1→GREEN30(기존 loader 포함). 기존 consumer가 새 marker를 받아들이는 문제 RED2→GREEN43. fresh review1회 Important1/Minor1: preserved extra dict alias RED1→deepcopy 수정, 미사용 import 제거. 한 수정 pass/재리뷰0. 최종 unit engine_pin/protocol/upstream + integration RX97/RX87 recording_limits/MA02 OpenAI → **77passed24.82s**. 기존 전체9실패 기준선은 재실행/해결했다고 주장하지 않는다.

Ruling: 기존 pin에 marker가 없으면 hash/동작을 유지한다. 비용: 새 원본 engine은 서버 접수에서 명시 선택하고 지원 handler가 준비돼야 한다. marker만으로 새 원본 실행을 완료 처리하지 않는다.

Ruling: 기존 소비자는 새 marker를 전송 전에 거절한다. 비용: 새 engine pin의 작업은 MA04 소비자가 등록되기 전 실행할 수 없지만 다른 프로토콜로 오실행하지 않는다. 기존 default 접수는 marker를 추가하지 않으므로 영향을 받지 않는다.

다음 B2b: 같은 project/attempt/worker/policy의 DB receipt/관찰·실제 native ACK에 묶은 대화 producer와 gateway 연결. 모델 응답만으로 실제 동작이 완료됐다고 간주하지 않는다. 이후 MA04 source/journal/spool/ACK/finish, MA05 저장본 승인·AI0 실행. UI/README의 제품 목표와 개발 현황 구분은 유지한다.
