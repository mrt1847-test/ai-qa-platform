# AI-LIVE-04-MA03B2B2 · 정상 녹화 모델 API의 원본 context 연결

2026-11-16 Asia/Seoul, 기준 master47855f7. 검증된 DB authoring pin의 engine_kind를 기준으로 정상 model-requests가 원본 context producer와 gateway를 선택하도록 연결했다. worker system/messages/engine bool을 신뢰하지 않는다. 기본 녹화 접수는 아직 marker를 선택하지 않고 기존 worker도 전환하지 않았으며, 그 부분은 MA04다. 유료 API/ADB 호출0, 전체 RX87/87of99·기능49of53 완료 수 유지.

## 실제 정상 경로

recording_authorization.py는 이미 검증한 frozen pin에서만 내부 engine_kind를 만든다. recording_requests.py는 표시된 engine에 대해 B2b1의 DB/source/native ACK 이력 producer를 사용하고 gateway에 context를 전달한다. generic observation과 섞지 않고 ModelBroker는 기존 frozen request를 계속 검증한다. producer/이미지 처리는 DB writer 밖이다. HTTP 준비가 끝난 실제 send 직전에 현재 관찰/lease/key/provider/policy와 history source fingerprint를 다시 확인한다. 변경/불명/부분 native 증거에서는 추가 전송0이다.

응답은 단일 원본 tool·허용 physical action·frozen literal로 검증하고 current terminate는 허용하되 사람 승인이나 finish를 자동 생성하지 않는다. provider가 보고한 실제 model도 사용자 지정 Luna와 같아야 한다. invalid response/model mismatch는 consumed502로 저장하며 실제 측정 usage를 보존하고 content를 반환하지 않는다. 검증 도중 현재 관찰이 만료되면 consumed403/usage 보존이다. 사용량을 dispatch_unknown으로 잃거나0token으로 표시하지 않는다.

같은 call의 receipt는 캐시/재시작 후에도 읽을 수 있다. 아직 실행 증거가 없으면 기존의 허용된 response retry를 재사용하고, after/log ready 증거가 있으면 action_allowed=false다. unknown native 로그도 재실행 권한을 주지 않는다. 조회 자체로 모델 재호출·중복 정산은 없다. marker 없는 기존 모델 API는 기존 단일 관찰/문법을 유지한다.

## 검증

정상 API original prompt/history/schema·missing ACK·준비 중 log tamper·semantic failure/usage·캐시 소비 상태 RED6(terminal 승인0 positive1)→GREEN7. 응답 검증 중 TTL 만료 RED1을 추가해 마지막 관찰 재검사를 연결했다. restart/history·unknown log cache도 확인했다.

fresh review1회 Important2/Minor0. terminate status array/dict가 TypeError로 usage를 잃는 문제와 다른 actual_model이 허용되는 문제를 RED3으로 재현했다. shared original codec에서 status string을 엄격히 검사하고 현재 model identity를 먼저 확인해 measured502로 남겼다. 단일 fix pass/재리뷰0.

첫 회귀는124pass/producer fixture1fail이었다. 새 정상 endpoint가 잘못된 두 번째 제안을 미리 거절해 이전 negative fixture가 구성되지 않은 것이었다. temporary fixture의 reserve/settle storage primitives로 불일치 완료 제안을 만들어 기존 producer 순서 거절을 그대로 검사했다. 제품 gate/검증 조건은 완화하지 않았다. 수정 단일 검사1pass 뒤 최종 new endpoint/history + 기존 MA02/RX98 + unit context/upstream **125passed82.42s**. 실제 앱 TC/유료 수용125건이 아니며 기존 전체9실패 기준선은 반복/해결하지 않았다.

## 결정과 다음

Ruling: server grant가 고정 engine을 선택한 경우에만 원본 context를 쓰고 기존 marker 없는 요청은 유지한다. 비용: 실제 default admission/지원 worker handler는 MA04에서 함께 전환해야 한다. 이 정상 model API 증거를 원본 main의 전체 웹 녹화·승인 수용으로 확대하지 않는다.

Ruling: 잘못된 응답이나 다른 모델도 이미 전송했다면 사용량을 저장하고 action만 차단한다. 비용: 오류 응답의 usage/actual_model을 소비자는 보존해야 하고 해당 녹화는 자동 재시도하지 않는다.

Ruling: native after/log 증거가 있으면 캐시된 action은 조회 전용이다. 비용: 불명/부분 상태를 같은 action 재전송으로 복구하지 못하며 명시 새 녹화/검토 흐름을 이용한다.

다음 MA04a: worker의 원본용 model callback와 ma-call before 관찰 업로드·서버 receipt 대조·post evidence ACK 대기를 연결한다. MA04b/c에서 실제 원본 subprocess handler와 journal/spool/source/finish 및 admission을 등록한다. MA05에서 저장본 검토·사람 승인 후 테스트용 승격·AI0 실행·offline 조회를 확인한다. 추가 모델 키·독립 서버·비용 계측을 코드 선행으로 삼지 않는다.
