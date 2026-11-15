# RX87 · 실제 Mobile-Agent의 정상 서버·worker 연결

2026-11-15 Asia/Seoul. 실제 source/main/Luna/4동작 AI0 재생의 로컬 증거는 AI-LIVE-03이며 재실행하지 않는다. 이 카드는 그 재사용 engine을 정상 제품 요청에 연결하는 구현이다. 로컬 증거를 서버 수용으로 승격하지 않는다. 사용자 DB/기존 UI dirty/기존 승인/FAIL을 보존한다.

> Use superpowers:executing-plans, TDD. MA-01은 AI-LIVE-04-MA01 인계로 완료했고 MA02a/b는 AI-LIVE-04-MA02 인계로 완료했고 MA03a는 AI-LIVE-04-MA03A 인계로 완료했고 현재 준비 단위는 MA03b B2b2다. 각 단위에서 소유 계약/인계/큐를 갱신하고 독립 미완료 단위를 이어간다. 실제 키·기기·독립 서버가 없어도 transport/HTTP/ADB fixture로 구현한다. 유료 재시험은 별도 명시 요청/승인 없이는 반복하지 않는다.

## MA-01 · 정상 provider factory에 OpenAI 모드 연결

- [x] config.py ModelProviderSettings/load_settings가 명시 AIQA_MODEL_PROVIDER_MODE=openai를 받고 fixture 기본/operational origin 규칙을 보존한다. OpenAI origin=https://api.openai.com, path=/v1/responses, HTTPX 기본 public CA 검증(trust_env=False)을 고정한다. 임의 base URL/path/TLS 해제를 거절하고 키는 settings/factory에서 읽지 않는다.
- [x] models/provider_http.py build_provider_from_settings에서 새 server OpenAI adapter를 선택한다. adapter.complete는 기존 ProviderHttpPort 인터페이스와 결과를 사용한다. 요청마다 bounded OpenAIProviderHttp(max_calls=1)를 새로 만들어 서버 전체12회 latch를 만들지 않는다. 실패한 호출을 자동 retry/fallback하지 않는다. 지정 timeout을 반영하며 테스트 transport가 정상 요청 경계를 관찰할 수 있어야 한다.
- [x] tests/unit/test_openai_provider_settings.py: 기본 fixture, 명시 openai, 잘못된 URL/path/TLS, 키 로딩0, 13회 독립 호출, 실패 후 다른 요청/동일 요청 retry 책임 분리, phase/observation/실제 모델·usage 전달을 검증한다. 실제 네트워크0.
- [x] 관련 설정·provider·gateway 회귀와 인계 AI-LIVE-04-MA01. factory 연결만으로 upstream worker/웹 녹화 완료라고 쓰지 않는다.

## MA-02 · 실제 사용량·최종 server 권한 경계

MA02a(먼저): recording_requests의 openai endpoint/provider 일치와 실제 send 직전 권한 callback. MA02b(다음): 측정 usage 영속화·중복/재시작 정산. 권한/사용량 receipt를 원자적으로 바꾸기 위해 두 단위를 같은 검증/커밋으로 묶었다. 정상 model API의 OpenAI grant는 연결됐고 원본 worker는 다음이다.

- [x] broker.py ServerModelGateway가 OpenAI 결과의 input/output/reasoning/cache를 정상 정산/영속 usage에 전달한다. usage unknown을0으로 바꾸지 않는다. 서버 receipt/idempotency 경로는 동일 요청 재호출/중복 과금을 막는다.
- [x] 실제 HTTP 전송 직전 callback으로 현 attempt/generation/lease/control/모델 budget·역할 binding을 다시 확인한다. 거절 시 provider_dispatched=false, timeout/전송불명은 true로 구분한다. 테스트에서 client 준비/관찰 파싱 동안 권한 변화·quota·lost ACK를 다룬다.

## MA-03 · 원본 upstream subprocess/IPC 경계

MA03a(완료; [인계](../validation/tasks/AI-LIVE-04-MA03A.md)) · 원본 main을 격리한 실행 프로세스와 bounded typed RPC. 새 worker/mobile_agent_process.py(부모), mobile_agent_child.py(자식), mobile_agent_ipc.py(프로토콜), integration/test_mobile_agent_process.py. 부모는 capture/model/dispatch/before_send callback을 받고 자식은 원본 main/prompt/history/parser/rescale만 실행한다. 키/worker token을 전달하지 않으며 child network를 막는다. 부모 cwd/stdio를 바꾸지 않는다. 메시지 크기/순서/step/모델·native 건수/monotonic cutoff/중지·정리 경계를 검증한다. callback은 기존 bounded worker ports이며 cutoff 뒤 새 전송을 금지하고 진행 I/O는 자체 timeout으로 drain한다.

MA03b(B1 context/명시 포트 완료; [인계](../validation/tasks/AI-LIVE-04-MA03B1.md), B2a exact engine pin/legacy 거절 완료, B2b0 내부 gateway 완료, B2b1 DB 이력/실제 ACK producer 완료, B2b2 정상 endpoint 선택 다음) · 정상 server의 frozen goal/직전 저장 관찰·완료 model receipt로 원본 대화/최종 단일 행동을 구성한다. 임의 worker conversation/외부 이미지 경로를 신뢰하지 않는다. image1000frame와 final_answer codec, source/claim/call 연결을 유지한다. 원본 child가 정상 모델 응답을 받는 것과 handler/evidence/finish 등록은 별도다.


- [x] 원본 main은 worker API 서버의 thread/cwd에서 실행하지 않는다. worker 전용 subprocess에 원본 engine을 두고 bounded typed capture/model/native IPC를 만든다. 실제 키/비밀 원문을 worker·child argv/환경/로그에 보내지 않는다. 실행 ID·case input/version·target·geometry pin과 부모 승인 callback만 전달한다.
- [ ] MA03b의 서버 소유 원본 대화/이미지/receipt 이력과 MA04의 durable journal/evidence ACK를 정상 handler에 연결한다. MA03a 부모의 현재 allowed/before_send·한도·단계 대조는 완료했다. 중지/timeout/child crash/불명 전송에서 재클릭0, 원본 이전 prefix/전후 증거를 보존한다. fake subprocess/IPC와 원본 main으로 통합 테스트한다.

## MA-04 · 정상 AndroidRecordingHandler에 원본 engine 연결

- [ ] worker/android_jobs.py·runtime.py의 정상 recording handler가 MA03을 호출한다. fixture_response/자체 plan_provider가 정상 요청의 암묵적 성공 경로가 되지 않게 한다. 자연어 목표/선택앱/고정 한도/원본 이력을 소비한다.
- [ ] 기존 before/after spool→서버 commit/ACK·native source seal→finish→검토 대기를 유지한다. source v2의 실제 text/key/swipe/좌표와 logical check binding은 보존하며 승인/QA를 자동 생성하지 않는다.

## MA-05 · 승인본 실행과 정상 웹 여정

- [ ] 정상 REC 접수→claim→원본 main→서버 증거/manifest→저장본 검토를 fixture API+원본 main으로 확인한다. worker offline에 조회/검토가 가능해야 한다. 사람이 실제 승인하기 전 실제 승인됐다고 기록하지 않는다.
- [ ] 승인 package ITEM/trial/regression은 기존 deterministic runner의 AI0/healing OFF 경로를 사용한다. 정상 DB source/package/witness/pin을 검증하고 표시 코드/좌표를 추정 재작성하지 않는다. 검증/치유 호출은 승인 지점·정책·C/D만 허용한다.
- [ ] 실제 live 연결 수용은 구현 뒤 별도 opt-in, 기존 AI-LIVE-03과 새 정상 경로 증거를 구분한다. 월3000건 비용 수용은 마지막이며 선행 구현을 막지 않는다.

## 보존할 독립 작업

B2.3b2 편집 UI는 기존 미커밋 구현과 CHECK_BINDING_EDITOR_TASKS.md를 보존한다. 원본 engine 서버 연결을 우선하고, model/secret/lease 변경과 충돌하지 않는 UI 작업은 독립 수행 가능하다. 이후 b3/c hierarchy·정규화 결과와 C/D, RX88~90를 이어간다. RX 전체 완료 수는 올리지 않는다.

Ruling: 설정의 명시 openai는 해당 서버 프로세스의 선택이고 key/binding은 기존 서버 비밀 참조를 이용한다. 로컬 env 키를 자동 수입하지 않는다. 비용: 정상 제품용 비밀 등록/권한 연결은 별도 수용이 필요하다.
