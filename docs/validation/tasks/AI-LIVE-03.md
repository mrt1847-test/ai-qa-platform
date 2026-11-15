# AI-LIVE-03 · 실제 Mobile-Agent/Luna 녹화 → 저장 원본 AI0 재생

2026-11-15 Asia/Seoul. 사용자 지적에 따라 자체 화면 루프 시험 AI-LIVE-02와 구분해 실제 upstream 실행 경로를 구현하고 시험했다. 기준 master f7cb466. **실제 Mobile-Agent v3.5 main 녹화와 같은 4동작의 AI0 재생을 관찰했다. 정상 관리 서버 접수/DB evidence ACK/사람 승인을 완료한 것은 아니다.** RX87 및 전체87/99·기능49/53 완료 수를 올리지 않는다.

## 실제 실행한 코드와 대체 범위

[고정 원본 runner](https://github.com/X-PLUG/MobileAgent/blob/81fa28b564ef7a695521500bc15a0e1324b2b394/Mobile-Agent-v3.5/mobile_use/run_gui_owl_1_5_for_mobile.py), commit81fa28b564ef7a695521500bc15a0e1324b2b394. third_party/mobile_agent/manifest.json에 원본/사용 파일 SHA와 MIT LICENSE를 보존한다. runner/main·packages·LICENSE는 byte-identical, utils는 지연 annotation과 미사용 eager numpy/OpenAI/Qwen import 제거만 했다. main/SYSTEM_PROMPT/build_messages/history/parse_action/rescale/smart_resize/annotation 함수 본문은 그대로 실행했다. source manifest 자체의 SHA와 필수 파일 집합을 어댑터 코드에 고정하고 Git 줄바꿈 변환을 끈다.

src/aiqa/adapters/mobile_agent_upstream.py의 run_upstream은 실제 원본 main을 전용 프로세스에서 호출했다(main_invocations1). GUIOwlWrapper의 모델 I/O를 Luna Responses로, AdbTools의 기기 I/O를 관찰 가능한 typed driver로 대체한다. 자체 계획 루프를 새로 실행한 것이 아니다. 원본의 전역 cwd/상대 디렉터리/출력은 새 전용 실행 디렉터리에 제한한다. 설치 앱 선택/외부 app resolver·임의 shell·IME 교체는 사용하지 않는다.

Luna 모델 호환 변환: 원본 tool의1000×1000 좌표와 일치하도록 전송 PNG를1000×1000으로 변환하고 실제 전송 PNG도 저장한다. 원래1080×2400 스크린샷은 별도 보존한다. Structured Outputs로 한 개의 원본 action만 받고, 짧은 summary+arguments를 원본 Action/tool_call 문법으로 직렬화한다. 원본 parser/main이 그 행동을 실행하며 원래 이력에 넣는다. 원본 rescale 결과는 물리 좌표로 명시 변환해 저장하고 재생 때 다시 rescale하지 않는다.

Responses의 commentary와 final_answer를 합치던 기존 포트 결함을 고쳤다. 최종 행동만 실행/이력에 넣고 다음 요청의 assistant phase도 보존한다. raw response에는 중간 설명/메타데이터를 분리해 남겼다. 근거: [공식 structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [공식 Responses phase](https://developers.openai.com/api/reference/resources/responses/methods/retrieve). 중간 설명의 가상 후속 행동을 실제 동작이나 최종 답으로 평가하지 않는다.

## 목표·기기·실제 행동

기존 전용 Medium_Phone_API_36/emulator-5580, com.ebay.kr.gmarket. 로그인/구매/개인정보/권한 허용 없이 mouse 검색어와 상품 목록을 확인하는 자연어 목표만 주었다. 좌표·순서는 주지 않았다. 검색어/안전 규칙/허용 action 형식은 주었으므로 그 자체의 발견 능력은 평가하지 않았다. 원본 정책 외의 임의 앱/시스템 권한 조작은 차단한다.

| 순서 | AI가 선택한 원본 정규 좌표/행동 | 실제 보존·재생한 물리 동작 |
|---|---|---|
| 1 | click420,56 | tap453,134 · 홈 검색창 열기 |
| 2 | click370,88 | tap399,211 · 검색 입력란 선택 |
| 3 | type mouse | input text mouse |
| 4 | click805,89 | tap869,213 · 검색 실행 |
| 5 | terminate success | native0 · 현재 결과 화면을 보고 종료 |

실제 좌표·명령의 최종 권위는 [녹화 report](../evidence/AI-LIVE-03/recording-run/recording/report.json)와 [native trace](../evidence/AI-LIVE-03/recording-run/recording/native-trace.json)다. 표는 그 원본과 별도로 확인해야 한다. 검색 결과 상품/광고는 녹화와 재생에서 달라지므로 동일 상품/가격을 검증한 것은 아니다.

녹화 최종 [PNG](../evidence/AI-LIVE-03/recording-run/recording/terminal.png)와 재생 최종 [PNG](../evidence/AI-LIVE-03/replay-run/replay/terminal.png)를 assistant가 직접 관찰했고 모두 mouse 검색어와 마우스 상품 목록이 보였다. overlay가 결과를 가리지 않았다. 사람의 사후 승인으로 세지 않는다.

## 실제 재생·저장 증거

녹화 성공 뒤 앱만 force-stop/launch로 다시 시작했다. 앱 데이터/검색 이력은 초기화하지 않았다. 두 실행 모두 setup.json/PNG로 구분한다. source SHA는8c6c7ba26c2ffdc1308619006246f0772966582fd3ed5f39f23991ccde2d3bea, recording-pin SHA는70b6d3c66d240521bab559ffb165f379eb175fc70c39034f29db6780d9638220이다.

기록 pin은 source, 완료 상태, serial/AVD/package, 각 before PNG/hierarchy SHA를 묶는다. CLI는 앱을 건드리기 전에 원본·증거·대상·완료를 검증한다. partial/stopped 원본을 완료본처럼 재생하지 않는다. 실제 재생은 키 인자 없는 **별도 Python 프로세스**이며 키 읽기false/모델 포트 생성false/Python network attempts0/model calls0/healing OFF다. Python socket 연결은 금지했고 ADB native 프로세스만 사용했다. 4개 ADB argv가 녹화와 재생에서 순서·좌표·문자열까지 정확히 같았다. [독립 재생 report](../evidence/AI-LIVE-03/replay-run/replay/report.json), [교차 대조 proof](../evidence/AI-LIVE-03/proof.json).

각 step의 before/after PNG, 전송된 물리 좌표/문자열/argv/상태/geometry, original main log, 모델 raw response/짧은 summary/실제 모델/usage, 실제 모델 입력 PNG를 보존했다. before/planned→dispatch_started→ACK/source fsync→after 저장 순서다. ACK 뒤 캡처가 실패해도 이미 실행한 이벤트를 잃지 않는다. 불명 native는 재전송0이다. foreground 전환은 최대10회 읽기만 재관찰하며 native/모델 재시도가 아니다.

native 직전 geometry/foreground와 화면을 재확인한다. tap은 같은 좌표의 유일한 clickable resource id/package/class/bounds/own text/description을 확인하며, 모호하거나 다른 요소가 덮으면 중단한다. 좌표 이동/치유는 하지 않는다. 안정된 ID가 없으면 tap/swipe의 상호작용 영역, text/key의 전체 프레임을 비교한다(채널 차이20 초과 픽셀1% 이하 및 평균차1.5 이하). 이는 시각/구조 가드이며 모든 업무 의미를 판정하는 QA assertion은 아니다. 광고·caret 변화로 차단될 수 있고 의미가 같은 완전히 다른 layout을 자동 수용하지 않는다.

## 호출·추론·개발 실패를 포함한 비용 기록

성공한 녹화: Luna low5회/native4회, input26122/output244(reasoning37 포함), cached input19551, 녹화137.953초. 재생 calls0. 추론 토큰을 output에 다시 더하지 않는다. 가격/청구 조회와 월3000건 환산은 이번 범위가 아니다.

실제 원본 연결을 바로잡는 이번 개발 과정 전체는 paid14회이며 그중 raw usage를 보존한 것은13회다. 초기 provider_response_invalid1회는 원문 보존 전 결함 때문에 usage를 알 수 없다. 이를0token으로 계산하지 않는다. [시도별 summary](../evidence/AI-LIVE-03/attempt-summary.json)에 실패까지 남겼고, 반복 실패한 요청을 비용에서 숨기지 않는다.

- 준비01은 SystemUI ANR로 모델 호출 전 중단(paid0). 이미 열린 앱 위의 Wait를 수동으로 누른 환경 복구는 setup-recovery.json/PNG에 별도 기록했으며 AI 녹화 동작으로 세지 않는다.
- 02는 provider_response_invalid로 paid1/native0; 이후200 raw 응답 보존 기능을 추가했다. 03은 원본 정규 좌표와 실제 입력 이미지의 불일치로 native 전에 중단했다.
- 04/05는 한 행동 형식과 commentary/final 구분 문제로 native0. 04의 여러 가상 행동은 중간 설명이며 최종 행동으로 인정하지 않는다. 전부 모델 추론 실패로 귀속하지 않는다.
- 06은 native1 ACK 뒤 전환 캡처, 07은 native2 관찰 뒤 전환 캡처에서 중단. partial로 남겼고 재생 성공 근거로 사용하지 않았다. 08은 동적 화면의 pixel guard가 native 전에 중단했다.
- 09는 원본 main/Luna 녹화4동작/5응답 및 별도 AI0 재생4동작이 모두 관찰됐다. 추가 유료 비교·재생 중 AI 보정0.

## 추론 능력 체크리스트의 이번 판정

[공통 체크리스트](../AI_RECORDING_REASONING_CHECKLIST.md)에 AR-00 실제 에이전트 실행/변환 provenance를 추가했다. 아래는 최종 연결을 적용한09의 관찰 범위다. 이전 실패와 연결 구현의 결함은 위 이력에서 보존한다.

| ID | 판정 | 실제 근거·한계 |
|---|---|---|
| AR-00 실제 원본 경로 | PASS | 고정 main1회/원본 prompt·history·parser·rescale 호출, hash·I/O 변환 범위 명시 |
| AR-01 목표 이해 | PASS | 제공한 mouse 검색 목표를 따름. 입력값·안전 규칙 자체는 제공됨 |
| AR-02 화면 파악 | PASS | 홈→검색 입력→문자 입력 후→결과를 실제 PNG와 일치하게 사용 |
| AR-03 행동 선택 | PASS(연결 보완 후) | native4개 전후 PNG/리소스ID·위치/argv 확인. 이전 좌표계 실패는 삭제하지 않음 |
| AR-04 다단계 | PASS | 좌표/순서를 주지 않고4개 의존 행동을 선택 |
| AR-05 상태 갱신 | PASS | 현재 PNG와 원래 실행 이력을 사용, 타이핑 뒤 검색 선택 |
| AR-06 돌발 화면 | NOT_RUN | 최종 run에 OS/차단 팝업 없음. 프레임 전환 복구는 도구 기능이며 모델 추론으로 세지 않음 |
| AR-07 실패 복구 | NOT_RUN | 실제 모델 오류 복구·healing을 평가하지 않음. 전송 불명은 단위 검사와 stopped 이력으로 분리 |
| AR-08 종료 근거 | PASS | 결과 PNG를 받은 뒤 종료, assistant가 검색어와 목록을 대조. 제품 assertion은 별도 |
| AR-09 불확실성 | NOT_RUN | 판단 불가/blocked 목표를 주지 않음 |
| AR-10 허용 범위 | PASS(관찰 범위) | 전용 앱/리터럴, 로그인·구매·권한 허용0 |
| AR-11 사용량 | PASS(성공 run) | 실 모델·effort·5회·input/output/cache/reasoning/elapsed/한도. 개발 중1회 usage unknown 별도 |
| AR-12 기록 완전성 | PASS | 실제 ACK4/source4/replay4, 전후 PNG/XML/log/source hash 저장 |
| AR-13 AI 없는 재생 | PASS | 이번 source를 별도 프로세스에서 재로딩, 실제4argv 동일, AI0/key0/network0 |
| AR-14 사람 사후 승인 | NOT_RUN | 저장 완료/검토 대기, 사용자가 승인한 사실 없음 |

결론 범위: 호환 변환 후 Luna low가 이 공개 검색 경로에서 화면·순서·동작·종료를 선택했다. raw Mobile-Agent protocol에 Luna를 그대로 꽂는 것으로는 충분하지 않았으며 처음 시도의 좌표/응답 처리는 실패했다. 이 결과로 일반 추론 우위/실패 복구/전체 앱 적합성을 보장하지 않는다.

## 코드·검사·남은 작업

주요 구현: adapters/mobile_agent_upstream.py, recording/mobile_agent_session.py 및 mobile_agent_frames.py, replay/mobile_agent_replay.py, models/openai_http.py 및 mobile_action_format.py, tools/android_mobile_agent_record_replay.py, third_party/mobile_agent. Pillow optional/dev dependency만 추가했고 Torch/Qwen/추가 앱 설치/권한 변경/DB 초기화/배포0. 전용 AVD는 기존 데이터를 유지해 시작했고 검사 후 같은 이름을 확인해 종료했다.

TDD: 원본 경로 RED8, conversation RED2, ACK/permission/replay RED4, 리뷰 중요 결함 RED3+4+1+1, 실제 연결에서 드러난 응답 보존/1000frame/단일action codec/phase/읽기 settling/target guard RED를 각각 확인했다. 최종 집중60passed2.78s, native v2 관련 회귀34passed10.38s. fresh final review1회, 필수 수정1배치와 실제 시험에서 드러난 연결 결함의 focused TDD, 재리뷰0. 전체1000여개 검사를 반복하지 않았으며 [기존9실패 기준선](REGRESSION_BASELINE_2026-11-09.md)을 해결하거나 전체 green이라 주장하지 않는다.

리뷰 Critical0/Important5를 수정했다: 안전한 ordinal 파일명/대상+완료+화면 pin/실제 화면 가드/원본 검증 누락·줄바꿈/최종 전송 deadline. 외부 private 화면 전송과 빈 녹화 성공 문제도 필수로 올려 수정했고 native timeout 재전송0 회귀를 추가했다. 미룬 Minor는 일부 parser/driver 실패의 안정된 사유 코드 세분화다. screen_drift/capture_transition은 분리했으나 나머지 recording_failed는 아직 거칠다.

Ruling: 정상 관리 서버 model binding/secretref/admission/worker IPC·evidence ACK·웹 승인 연결은 미완료다. 이번 경로는 실제 원본을 실행하는 재사용 engine과 로컬 CLI이며 웹에서 원본 에이전트가 호출된 근거로 확대하지 않는다. 비용: 서버 경로의 추가 구현/수용이 필요하다. Ruling: 기존 pending binding-editor 및 사용자 dirty2개는 이 배치에 포함하지 않는다. 비용: 화면 편집 기능은 별도 검증/커밋이 필요하다. Ruling: 원본 prompt/main은 유지하고 이미지/응답/기기 I/O만 변환한다. 비용: 무수정 GUI-Owl 서비스와 Luna의 직접 상대 비교는 아니다. Ruling: resource/pixel guard가 맞지 않으면 중단하며 자동 healing하지 않는다. 비용: 동적인 다른 UI는 차단될 수 있다.

전체 hash/길이: [evidence manifest](../evidence/AI-LIVE-03/evidence-manifest.json). 원본 main이 생성한 중복 스크린샷/주석 폴더는 증거 복사에서 생략했으며 전후 원본 PNG·실제 모델 입력 PNG·upstream.log는 보존했다. API 키/Authorization header/hidden reasoning 원문은 보존하지 않는다.

원본 bytes 보존: source/vendor·녹화 증거에만 Git text/whitespace 정규화를 끈다. CRLF 및 upstream의 표/모델 출력 공백을 임의 수정하면 SHA를 깨기 때문이다. 제품 코드의 whitespace 검사는 유지한다. 시도 summary는 실제9개 디렉터리만 집계하고 로그 파일명을 별도 시도로 세지 않는다.
