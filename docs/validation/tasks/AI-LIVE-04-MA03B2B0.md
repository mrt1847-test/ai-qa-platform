# AI-LIVE-04-MA03B2B0 · 원본 context의 서버 내부 gateway 연결

2026-11-16 Asia/Seoul, 기준 master0e434dd. ServerModelGateway.handle/_admit의 내부 mobile_context를 구현해 B1의 원본 대화를 기존 권한/비밀/쿼터/정산 경로에 연결했다. WorkerModelRequest와 worker HTTP DTO/parser에는 context를 추가하지 않았다. 정상 endpoint의 DB 소유권/engine admission과 실제 native ACK producer는 다음 B2b1이고, 이 내부 포트만으로 정상 원본 녹화를 완료하지 않는다. 유료/API/ADB0, 전체 완료 수 유지.

mobile_context는 정확한 MobileAgentContext 타입이며 별도 observation과 혼합할 수 없다. Context의 immutable JSON SHA를 gateway idempotency에 포함해 같은 key의 다른 대화는 충돌로 처리한다. 기존 ModelBroker는 원래 request의 frozen inputs/role/binding/한도를 검사한다. 실제 transport에만 context 전체와 빈 sanitized_inputs를 전달한다. exact OpenAIServerProvider·recording/authoring·Luna 모드만 지원하며 다른 provider/role/model은 키 해석·전송 전에 거절한다.

서버 resolver의 credential은 기존 포트에만 주며 worker/생성 코드에 보내지 않는다. 실제 before_send의 마지막 권한 검사를 유지하고 준비 중 취소는 모델 카운터/사용량0이다. 성공한 같은 context/key는 기존 receipt를 재사용하며 실제 호출/토큰 정산을 더하지 않는다. 이미 캐시된 응답도 혼합 observation이면 조회 전에 거절한다. 원래 단일 관찰/다른 역할 경로는 바꾸지 않는다.

검증: 새 gateway RED8→GREEN8. fresh review1회 Important1/Minor1. 캐시 후 context+observation이 허용되는 문제 RED1로 재현하고 mutual-exclusion을 cache 앞에 옮겼다. 취소 후 usage0 assertion도 보강했다. 단일 fix pass/재리뷰0. 최종 new gateway/context + 기존 MA01/MA02/RX45 회귀 **42passed19.16s**. 실제 앱 TC/유료 수용 건수가 아니며 기존 전체9실패 기준선을 반복·해결하지 않았다.

Ruling: 내부 transport bridge를 DB producer와 분리한다. 비용: 정상 HTTP는 아직 이 context를 자동 구성하지 않으며 B2b1에서 같은 project/attempt/worker/policy/source와 native ACK를 확인해야 한다. B1 타입/서버 내부 호출을 권한 token으로 간주하지 않는다.

Ruling: ModelBroker admission은 원래 요청을 검사하고 전송만 원본 context로 바꾼다. 비용: producer가 frozen goal/history를 구성할 책임이 있으며 임의 worker conversation을 이 인수로 전달해서는 안 된다. source/실제 ACK 증명 없는 history를 이전 실제 동작으로 표시하지 않는다.

다음 B2b1: DB 완료 모델 receipt와 관찰·같은 action의 before/after/log ACK를 대조하는 producer 및 정상 endpoint의 명시 engine 경로. 이후 MA04 handler/source/journal/spool/ACK/finish, MA05 저장본 검토·테스트용 승격·AI0 실행 여정. 기본 접수/legacy worker를 자동 전환하지 않았다.
