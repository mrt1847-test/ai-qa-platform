# AI-LIVE-04-MA04A · 원본 worker의 모델 callback·관찰 업로드

2026-11-16 Asia/Seoul, 기준 master5f141d4. parent-side MobileAgentModelPort를 구현해 원본 RPC current frame을 정상 worker HTTPS model API에 연결했다. 아직 실제 native/wait evidence handler와 worker/admission 등록은 MA04b/c 미완료다. 유료 API/ADB 호출0이며 모의 포트 검사를 실제 Mobile-Agent live 수용으로 세지 않는다. RX87/전체87of99·기능49of53 유지.

worker/mobile_agent_models.py는 exact source engine pin과 root/snapshot job·attempt·purpose, 비밀 없는 intent, source/generation/현재 frame·한도를 확인한다. claim을 복사하고 geometry도 parse_geometry로 canonical tuple화해 pending 상태가 caller mutable bounds를 공유하지 않는다. API/model key를 읽지 않고 기존 HTTPS client만 사용한다. child의 messages/system은 전송하지 않는다.

marked upload_authoring_observation은 ma-<call UUID> action의 before PNG를 서버 ACK한 뒤 관찰을 같은 모델 요청에 등록한다. legacy는 기존 model-frame.png/source를 유지한다. model callback의 before_send는 그 이후 실제 request_model 직전에 한 번 호출한다. 반환 allowed/action flag/call·attempt·generation·role/purpose/model/observation/hash를 대조하고 원본 parser의 typed physical action과 content·allowlisted audit receipt를 immutable turn으로 보존한다. model_requests는 HTTP 시도 횟수이며 실제 청구 횟수와 다르다.

실패/불명 모델 HTTP는 stopped로 남기고 재시도하지 않는다. source capture ID 중복·재진입·동시 호출·고정 호출 한도도 차단한다. native/wait의 post evidence가 pending인 동안 다음 모델을 요청할 수 없다. accept_evidence는 같은 pending call/attempt·late=false·canonical distinct after/log UUID와 ordered IDs를 검사하고 이미 소비한 artifact를 재사용하지 않는다. 먼저 받은 fresh ACK를 현재 upload에 연결하는 책임은 MA04b trusted uploader에 있으며 서버는 별도로 source/native proof를 확인한다.

검증: RED5→GREEN5/5.25s, 정상 API/마지막 boundary 취소/한도/pending/소유 receipt/claim-copy/reentrant/민감 intent/unknown HTTP11pass10.99s. typed physical turn RED1을 추가했다. fresh review Important2/Minor2: 이전 genuine ACK가 다음 turn을 해제하는 문제·mutable bounds·UUID(int) uncontrolled error를 RED3으로 확인하고 단일 fix pass. consumed artifact set/canonical ordered IDs/geometry snapshot/string UUID를 적용했다. late ACK fixture도 valid UUID로 실제 late flag를 검사하도록 고쳤다. 재리뷰0.

최종 new port14개 + 정상 endpoint/기존 RX99 관찰 회귀 **51passed46.19s**. 실제 기기TC51건이나 전체 기존9실패 해결이 아니다. normal mocked server receipt의 사용량을 보존하지만 과금 호출을 직접 실행하지 않았다.

Ruling: 모델/관찰 callback을 실제 driver/subprocess handler 등록과 분리한다. 비용: 현재 normal runtime는 아직 기존 default이고 MA04b/c에서 원본 main을 이 callback·driver·journal/source/finish에 연결해야 한다.

Ruling: local ACK release는 trusted uploader의 동일 upload/call 상관관계를 전제로 하고 server source proof가 최종 경계다. 비용: MA04b는 after/log artifact 생성·현재 turn과 receipt의 매핑을 명시 구현해야 하며 arbitrary receipt로 release하면 다음 모델 API에서 거절된다. 이미 소비한 ACK는 local에서도 재사용할 수 없다.

다음 MA04b: 실제 원본 subprocess의 native callback과 journal ACK prefix·post capture/evidence/source seal. native ACK를 받은 뒤 after 캡처/업로드에 실패해도 이미 실행한 동작 원본을 잃지 않으며 불명 전송은 재클릭하지 않는다. wait와 terminal은 native 수를 늘리지 않는다. MA04c에서 지원 handler와 server admission을 함께 등록하고 MA05 승인/AI0 여정을 이어간다.
