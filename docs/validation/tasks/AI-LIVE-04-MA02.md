# AI-LIVE-04-MA02 · 정상 OpenAI 녹화 요청·최종 권한·실측 정산

2026-11-15 Asia/Seoul, 기준mastere86a168. **정상 REC 접수/claim/ACK/저장 이미지의 OpenAI 요청과 실제 token receipt 저장을 모의 HTTP로 검증했다.** 실제 모델·기기 호출0, 기존 AI-LIVE-03 live 증거 재실행0. 원본 main을 정상 worker에서 호출하는 MA03~05는 미완료이며 RX87/전체 완료 수를 올리지 않는다.

## 실제 구현과 권한

recording_requests.py는 frozen binding이 provider=openai/endpoint_kind=https이며 origin 또는 canonical Responses endpoint가 일치할 때만 정확한 OpenAIServerProvider를 승인한다. 최초 승인한 객체를 gateway.handle(provider_pin=...)로 끝까지 고정한다. OpenAI pin을 operational adapter로 우회하지 못하며 기존 non-OpenAI operational labels는 보존한다.

openai_server.py는 supports_send_boundary를 선언한다. broker.py는 그 포트에 실제 before_send callback을 전달하고 OpenAI HTTP client/request 준비가 끝난 뒤 현재 관찰/lease/키/정책·provider identity를 재확인한다. DB writer transaction을 모델 HTTP 동안 유지하지 않는다. 준비 중 취소/lease 만료/키 폐기/관찰 만료는 실제 전송0/charged0. 전송 뒤 취소는 charged1이며 action content를 반환하지 않는다.

동일 키의 동시 요청은 예약 transaction 안에서 기존 receipt를 다시 확인한다. 이미 pending이면 provider_dispatched=null의 unknown 응답, completed이면 기존 결과를 재사용한다. 새로운 요청처럼 미전송409로 오판하지 않는다. 다른 fingerprint/다른 worker는 여전히 충돌/거절한다. crash로 pending이 남으면 재시작 뒤에도 재전송하지 않는 기존 계약을 유지한다.

## 실측과 저장

measurements.py는 실제 provider의 input/output/cache/reasoning만 정수로 읽는다. 누락/잘못된 값은 null이고 실측0과 구분한다. total=input+output이며 reasoning/cache를 더하지 않는다. 숫자는 호출별(token_scope=call)이고 역할별 calls는 attempt 누적이다. 비용/tariff가 없으면 cost_status=unknown/reserved_cost=null을 유지한다. 실제 토큰을 얻었다고 청구 금액이나 월3000건 비용을 안다고 쓰지 않는다.

정상 model_request_receipts.response_json에 같은 호출의 input/output/cached_input/reasoning/total/측정 상태를 저장한다. 기존 relational project/attempt/call/request-key/charged로 연결되므로 새 schema migration 없이 재시작/같은 키 재조회에서 그대로 읽힌다. 정상 성공뿐 아니라 이미 측정한 뒤 권한이 만료된403 receipt에도 사용량을 저장하고 content는 제거한다. usable provider 응답이 없는 실패는 usage를 생략하고 charged1/null-token으로 남긴다. 생략/unknown을 실측0으로 바꾸지 않는다.

gateway의 in-memory UsageLedger도 프로젝트별로 분리했다. 같은 worker call UUID를 두 프로젝트에서 써도 각 프로젝트의 token이 섞이지 않는다. call_tokens(project_id,call_id)는 해당 프로젝트의 immutable count tuple만 읽는다. input/output/cache는 기존 ledger에, reasoning은 영속 response JSON에 보존한다. 월간 집계 UI/정규화 analytics schema·가격 확정은 후속이며 구현됐다고 쓰지 않는다.

## 검사·리뷰

정상 접수 fixture로 OpenAI fixed origin/서버 key/실제 PNG, source pin, gateway restart/중복 요청, 양방향 provider mismatch, HTTP 준비 중·응답 뒤 취소, lease/key/frame 변경을 검사했다. 초기3 RED(provider unavailable)→endpoint 연결 뒤 최종 전송 경계 RED1→GREEN. metadata의 실제 API RED1/정규화 helper RED5→GREEN15/13.26s.

fresh final review1회 Critical0/Important4/Minor3. 중요4개와 관련 하위 조건을 RED로 재현했다: operational 역방향 fallback, 준비 중 provider 교체, 늦은403의 측정 유실, 동일 키 동시 race, 프로젝트별 ledger 격리 getter 부재. SQLite transaction 안에 barrier를 둔 첫 동시 테스트는 setup 결함이어서 transaction 밖 이미지 읽기 완료 시점으로 고쳤고 실제409/false 오판을 다시 RED로 확인했다. 단일 수정 pass 뒤24passed23.65s, canonical full path positive 포함 최종 집중71passed24.37s. 기존 RX98/RX99 호환 검사는 완료 로그를 아래에 기록한다. 전체 기존9실패 기준선을 재실행/해결하거나 전체 green으로 보고하지 않는다.

## 결정·보류와 다음

Ruling: MA02a/b는 같은 receipt·권한·정산 계약을 바꾸므로 한 검증/한 atomic commit으로 합친다. 비용: 원래 두 commit보다 bisection 단위가 크지만 정상 호출을 열고 사용량을 유실하는 중간 상태를 남기지 않는다.

Ruling: 이미 보낸 요청의 비용/사용량은 권한이 나중에 만료돼도 저장하고 action은 차단한다. 비용: 오류 응답에도 사용량 metadata가 추가되므로 API 소비자는 error 여부와 별개로 이를 보존해야 한다.

Ruling: usable 응답 없는 오류의 usage 생략은 unknown을 뜻한다. 비용: 집계자는 charged row의 누락 값을0으로 합산하지 말고 unknown 건수/부분 합계를 표시해야 한다. 이 의미는 테스트에서 필드 부재 자체와 charged1로 확인한다.

Deferred Minor: endpoint rstrip 때문에 임의 trailing slash가 진단상 허용될 수 있으나 physical URL은 고정이다. gateway의 최초 receipt/receipts_for mutable usage dict alias는 in-process 소비자가 바꾸면 memory cache에 영향을 줄 수 있다. 정상 HTTP 경로는 자체 scalar response를 만들며 DB 영속 metadata는 별도로 보존한다. 별도 immutable receipt 후속으로 남긴다. 오류 usage 생략 검사 Minor는 위 계약 명시로 처리했다. 재리뷰/유료시험0.

다음 MA03: 원본 Mobile-Agent main의 subprocess/IPC 경계를 구현한다. 현재 OpenAI 정상 authoring model API가 열린 것과 정상 worker에서 원본 main이 호출되는 것은 다르다. MA03~04에서 사용자 key를 child/argv/env에 넘기지 않고 모델·native·증거를 부모의 현재 권한/한도/ACK로 묶는다. MA05에서 저장본 검토·사람 승인·정식 AI0 실행 여정을 확인한다. 기존 UI dirty/user metadata/test_rx47은 이 배치와 분리해 보존한다.

최종 호환 회귀: 기존 정상 녹화 요청 RX98와 이미지 관찰 RX99 **68passed81.95s**. 새 focused71passed24.37s와 별도이며 실제 앱 TC 건수로 세지 않는다.
