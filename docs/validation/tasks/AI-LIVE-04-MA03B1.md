# AI-LIVE-04-MA03B1 · 서버 소유 원본 대화 구성과 명시 OpenAI 포트

2026-11-16 Asia/Seoul, 기준 master f9ceed7. MA03b의 B1을 구현했다. 서버 producer가 넘긴 frozen RecordingIntent와 관찰·settled 응답으로 고정 원본 SYSTEM_PROMPT/build_messages/history를 실행하고 Responses 대화를 만든다. DB 이력의 실제 소유권/권한 검증은 다음 B2이며 이 helper의 타입을 권한 증명으로 쓰지 않는다. 일반 worker/서버 접수·DB ACK·사람 승인 전체 수용은 미완료다. RX87/전체87/99·기능49/53을 올리지 않는다. 유료 API/ADB 호출0.

## 구현

models/mobile_agent_context.py는 원본 순수 protocol loader를 사용한다. instruction은 서버 고정 목표/조건/단계/검증/변수와 path_policy만 포함한다. worker system/messages·image URL·파일 경로를 받지 않으며 파일을 읽지 않는다. 과거 응답은 최대79개, 마지막4개 이미지는 필수이며 더 오래된 출력은 원본 함수가 요약한다. 현재+과거 최대5개 PNG를1000×1000으로 변환하고 final_answer phase를 보존한다.

입력 PNG의 hash/치수/CRC/크기와 결과 conversation의5이미지/8MB 경계를 확인한다. 새 pixel-only PNG로 재생성해 원본 ICC/text/exif 메타데이터를 보내지 않는다. raw reasoning/DOM/stdout은 입력 타입에 없다. intent secret_refs는 픽셀 coverage가 없으므로 거절하고 변수의 비밀 원문 marker도 거절한다. 응답은 하나의 canonical Action summary·tool block, 중복 JSON 거절, 원본 parser와 typed native validator 일치를 확인한다. terminal 응답 뒤의 이어가기와 허용되지 않은 과거 타이핑을 거절한다.

MobileAgentContext는 JSON snapshot이며 messages()/text_literals()는 새 값을 반환한다. 이후 intent/geometry/조회 결과 변경이 이전 요청을 바꾸지 않는다. 단, 이 helper는 DB 소유권/현재 제어/실제 동작 ACK를 증명하지 않는다.

openai_server.py의 mobile_context는 명시 authoring/gpt-6-luna에서만 사용하며 다른 observation/sanitized_inputs와 혼합하지 않는다. 잘못된 입력은 provider_dispatched=false/counter0이다. 기존 단일 관찰 요청은 유지한다. OpenAIProviderHttp는 기존 phase/usage/최종 before_send를 보존하면서 context를 전달하고 단일 원본 action schema를 사용한다.

기존 mobile_action_format의 mouse-only 제한은 실제 시험 전용 기본값으로 보존했다. 정상 context의 schema는 frozen 변수 중 실제 native text validator가 허용하는 문자열만 type enum으로 사용한다. 공백/한글/256자 초과 등 지원하지 않는 변수는 목표 문맥에는 남지만 타이핑을 허용하지 않는다. 허용 literal이 없으면 type action을 제외한다. 실제 입력 지원 범위를 확대하거나 IME/임의 shell을 허용하지 않는다.

## 검증

기능 RED22→GREEN24. fresh final review1회 Critical0/Important3/Minor1. ICC 잔존, 요약 없는 tool이 오래된 user prompt로 들어가는 문제, schema/native/과거 타이핑의 불일치를 RED6으로 재현해 한 fix pass 후30passed1.58s. Minor 중복 키 fixture도 원본 parser가 인정하는 multiline 형식으로 바로잡았다. 재리뷰0.

최종 집중: unit mobile_agent_context/mobile_agent_protocol/mobile_agent_upstream/openai_http/openai_provider_settings, integration ma03b_openai_context/ma01_openai_factory/ma02_openai_recording → **110passed16.47s**. 실제 공급자/기기 TC 수가 아니다. 기존 전체9실패 기준선을 반복하거나 해결했다고 보고하지 않는다.

## 결정과 다음

Ruling: B1 입력은 서버 내부 helper 타입이고 권한 token이 아니다. B2가 같은 project/attempt/worker/policy의 DB receipt·저장 관찰을 선별하며 현재 관찰·lease·source pin을 다시 검사해야 한다. 비용: B1만으로 정상 원본 녹화를 켤 수 없다.

Ruling: 입력 schema는 frozen nonsecret 변수와 native text validator의 교집합이다. 비용: 타이핑이 필요한 목표는 지원되는 literal 변수를 제공해야 하며 추가 입력원/문자 지원은 별도 기능이다. 변수 없는 경우 fixture mouse를 대신 입력하지 않는다.

Ruling: 기존 단일 화면/CLI smoke 동작을 유지하고 새 context는 명시 경로에서만 사용한다. 비용: B2 engine admission과 gateway 연결, MA04 원본 handler·journal/spool/ACK/finish, MA05 승인본 실행 여정이 남는다. 일반 웹에서 실제 원본이 호출됐다는 완료 주장은 하지 않는다.
