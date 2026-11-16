# MA04b2 · 원본 recording session coordinator

2026-11-16 Asia/Seoul. BASE567cb27 master. 기존 서버 wiring MA04와 C04/C05/C06의 실행 단위. 실제 키/ADB 호출과 runtime/admission default 전환은 하지 않는다.

Goal: 실제 run_mobile_agent_process의 capture/model/native callbacks를 정상 MobileAgentModelPort·AndroidDeterministicDriver·DispatchJournal·mobile StepEvidenceCommitter에 연결한다. source-v2 physical ACK prefix는 after capture/HTTP 전에 atomic write하고 다음 capture에서 같은 turn after/log를 commit한 뒤 다음 model을 허용한다. child는 실제 upstream main을 실행한다. wait/terminal은 native0이며 증거는 저장한다. 녹화 단일 attempt directory 재실행은 거절한다.

- [x] RED 정상 marked API + 실제 upstream subprocess + fake ADB에서 click→terminate, physical source1·model2·각 before/after/log·source ACK·미승인 결과를 확인한다. wait→click→terminate는 model3/native1. before_native checkpoint/capture drift/cancel/unknown runner timeout은 재전송0. after-capture/ACK/prefix 쓰기 실패에도 native ACK 수/기록 보존. 동일 attempt directory 재시작0 model/native. source ACK 실패는 compile-ready mapping0.
- [x] Session은 deep claim/pin/engine 한도를 소비하고 driver serial을 고정한다. 모든 capture는 sanitize/geometry/identity 검증. OS send 전 journal STARTED fsync→최종 gate→parent boundary. known ACK는 parent에 반환하고 post capture는 다음 callback에서 수행한다. persistence 실패는 정지하되 이미 실행한 수를 보존한다.
- [x] Focused prior process/model/evidence regression, fresh review와 단일 TDD fix pass, handoff/contracts/NEXT 업데이트와 로컬 커밋. 실제 runtime target 준비/lease binder와 server admission은 MA04c에서 함께 등록한다. 정상 웹 전체 수용/사람 승인/QA 성공을 이 단위로 주장하지 않는다.

Interfaces: Session owns one fresh directory, local native journal/prefix, model port and metadata journal. Constructor takes trusted client/claim/driver/capture, expected serial, checkpoint(phase)->True, allowed()->True. These callbacks require current runtime/target authority when registered later; helper type is not authority. Result exposes actual native ACK count, process ambiguous bit, server evidence ACK prefix/artifact IDs and source only after clean completion+source ACK.

Ruling: after capture is delayed until parent has counted native ACK. Cost: last turn needs explicit final capture/flush when original main terminates/step-limits; failure retains prefix but has no approval-ready source. Wait/terminal evidence is logical; source-v2 contains physical actions only.

완료 인계: [AI-LIVE-04-MA04B2](../validation/tasks/AI-LIVE-04-MA04B2.md). 새20개 통합 통과, fresh review Important4 단일 RED→GREEN fix pass/재리뷰0. 최종 관련 회귀는 인계를 따른다. 다음 MA04c normal runtime/admission.
