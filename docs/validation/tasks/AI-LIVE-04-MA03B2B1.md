# AI-LIVE-04-MA03B2B1 · DB 이력과 실제 동작 증거 ACK producer

2026-11-16 Asia/Seoul, 기준 master7149d97. 서버 내부 load_mobile_agent_history를 구현했다. 정상 endpoint가 이 producer를 자동 선택하는 연결은 다음 B2b2이며, 아직 기본 worker를 원본 main으로 바꾸지 않았다. 유료 API/ADB 호출0, 전체 RX87/87of99·기능49of53 완료 수 유지.

## 소유권과 실제 동작 구분

현재 recording grant·정제 관찰의 call/worker/lease/TTL, frozen non-sensitive intent, exact engine source/protocol과 OpenAI/Luna를 확인한다. 같은 project/attempt/worker/policy의 charged 완료200 receipt만 과거 응답으로 쓴다. 같은 현재 call의 정확한 pending 예약만 제외하고, 타 call pending/paid error/late/terminal·외부 scope는 거절한다. current source ID와 과거 source ID는 중복될 수 없지만 다른 capture의 동일 pixels는 허용한다.

모델 응답만으로 native 완료를 만들지 않는다. 각 이전 call은 ma-<call UUID> action의 before/after/log ready artifact를 가져야 한다. before는 해당 call의 등록 관찰이고, after/log는 같은 worker·job·generation의 completed evidence commit에 함께 포함돼야 한다. 로그는 mobile-agent-step-v1 exact schema로 call/action·observed·native_calls1(wait0)·원본 parser/rescale에서 얻은 실제 physical typed action·전후 hash를 대조한다. authenticated worker ACK는 실행 증거이며 독립 하드웨어 관찰/사람 QA 승인은 아니다.

artifact PNG/hash/geometry와 로그 bytes를 검증하고 현재+최근4개 이미지만 원본 context에 넣는다. 이전 화면은 과거 context여서 현재30초 TTL을 다시 부여하지 않으며 현재 화면은 끝까지 fresh여야 한다. 파일·PNG·Pillow 작업은 DB writer 밖에서 처리하고 마지막에 grant/metadata snapshot과 현재 관찰의 hash/geometry/time/freshness를 다시 확인한다. 반환 context와 source fingerprint는 detached immutable snapshot이다.

## ACK 시각

evidence_commit_requests.created_at은 staging 시작 시각이므로 완료 ACK로 쓰지 않는다. store/evidence.py가 파일 준비 뒤 metadata transaction 안에서 response_body에 server_committed_at을 저장한다. DB schema와 public EvidenceCommitAck DTO는 바꾸지 않는다. 캐시 재조회는 원래 완료 시각을 보존한다. history는 완료 시각 없는 legacy receipt를 ACK 근거로 쓰지 않는다.

proof 요청 시작은 해당 모델 응답 완료 이후, 현재 캡처 등록은 이전 proof 완료 이후여야 한다. 과거 각 캡처도 바로 앞 proof 완료 이후여야 한다. 등록이 staging과 metadata 완료 사이에 끼어든 경우를 실제 fixture API로 재현해 거절한다.

## 검증과 리뷰

기본 producer RED5→GREEN5. 이력 prefix/ACK-before-proposal 순서 결함 RED2→13pass15.92s. fresh review1회 Critical0/Important3/Minor2와 scope/pending 테스트 보완. staging 시각 오판·최종 snapshot 대기 중 TTL 만료·source ID 재사용·과도한 로그 nesting RED4 및 exact frame identity RED1을 확인한 뒤 한 fix pass. candidate artifact query LIMIT3, malformed log JSON의 controlled refusal, foreign worker/policy와 matching own pending positive도 추가했다. 재리뷰0.

최종 producer22개와 기존 evidence_io/evidence_authority/step_evidence_guards/MA02 정상 OpenAI 회귀 **73passed49.78s**. 과거 이미지 TTL/current 만료, typed native 불일치, missing ACK/legacy missing timestamp, paid failed/pending, disk tamper, 두 단계 prefix, writer 밖 I/O를 포함한다. 실제 앱TC73건이나 전체9실패 기준선 해결이라는 뜻은 아니다.

## 결정과 다음

Ruling: 이미 저장된 evidence commit에 server_committed_at을 추가하고 시간 없는 과거 ACK는 이 새 engine의 이력으로 거절한다. 비용: 과거 generic 증거를 새 원본 engine 이력으로 사후 승격하지 못하지만 기존 generic 조회/승인/DTO는 유지한다.

Ruling: 같은 action의 후속 화면·원본 parser와 일치하는 native 로그·서버 ACK를 모두 요구한다. 비용: MA04 실제 handler는 이 naming/schema와 순서를 구현해야 하며 실행 여부 불명/부분 증거로 다음 모델 호출을 하지 않는다.

Ruling: 여기까지는 내부 producer다. 비용: 다음 B2b2에서 정상 model-requests가 server grant의 engine에 따라 이 context를 선택하고 실제 send 전 fingerprint를 재확인해야 한다. 이후 MA04 source/journal/spool/finish, MA05 검토·사람 승인 후 테스트용 승격·AI0 재생을 이어간다. model success/worker ACK를 사람 승인으로 표시하지 않는다.
