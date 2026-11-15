# AI-LIVE-04-MA03A · 실제 원본 main의 워커 격리 프로세스

2026-11-15 Asia/Seoul, 기준 master d261fb3. 원본 Mobile-Agent main을 별도 자식 프로세스에서 실행하고 부모의 capture/model/native 포트로 연결하는 MA03a를 구현했다. 실제 upstream main·prompt·history·parser·rescale를 호출한다. 이번 검사는 모의 모델/기기 포트를 사용했으며 실제 API/ADB 호출0이다. 기존 AI-LIVE-03의 Luna 녹화4동작·독립 AI0 재생 증거와 구분한다. 정상 웹/worker handler·DB 증거 ACK·사람 승인은 MA03b/MA04/MA05 미완료다. RX87/전체87/99·기능49/53을 올리지 않는다.

## 실행 경계

worker/mobile_agent_process.py의 run_mobile_agent_process는 새 출력 폴더, 자연어 목표, 필수 secrets tuple, capture/model/dispatch/allowed 콜백과 고정 한도를 받는다. 키·worker token·proxy 환경을 자식에게 전달하지 않는다. 고정 Python 모듈 mobile_agent_child가 원본 main을 실행하며 capture/model/native를 한 번에 하나씩 NDJSON RPC로 위임한다. 부모 cwd/stdout/absolute utils alias를 바꾸지 않는다. 자식은 Python socket 연결을 차단하고 ADB/모델 포트를 갖지 않는다. 이는 신뢰한 고정 원본의 I/O 격리이며 악성 코드에 대한 OS sandbox를 제공한다는 뜻은 아니다.

프로토콜은 최대4MiB·중복 필드 거절·정수 순번과 capture→model→native 또는 wait→capture 단계를 검사한다. 첫 캡처의80자 run tag를 고정하고 screenshot 인덱스가0부터 증가해야 한다. PNG는 실제 치수·CRC·압축 크기·2MB 한도를 확인하며 필수 secrets에 민감 정보가 있으면 픽셀 정제 증명이 없으므로 자식/모델에 보내거나 저장하지 않는다. 모델 콜백에는 검증된 PNG/geometry/관찰ID/시각/platform만 있는 MobileAgentModelFrame을 주며 raw reasoning/DOM/stdout/messages는 전달하지 않는다.

부모는 원본 build_messages와 자신의 관찰·이력으로 요청을 대조하고 모델 최종 답을 원본 parser/rescale로 해석한다. 자식의 native method/인자가 정확히 선택한 동작인지 확인한 뒤 typed 물리 동작을 부모 포트에 전달한다. native는 재전송하지 않으며 ACK된 수와 마지막 불명 전송을 별도로 반환한다. model_requests는 부모 위임 횟수이며 실제 서버 청구 횟수가 아니다.

각 콜백은 실제 전송 직전 before_send를 정확히 한 번 호출해야 한다. 현재 제어·monotonic cutoff·모델/native 한도를 그 시점에도 검사한다. 부모→자식 pipe 쓰기는 감독 가능한 writer thread에서 실행해 자식이 읽기를 멈춰도 cutoff/취소가 cleanup으로 이어진다. 부모는 자신이 시작한 자식만 종료/reap하고 bounded stderr를 drain한다. 진단 로그 저장 실패가 이미 계산한 ACK/불명 결과를 덮어쓰지 않는다.

adapters/mobile_agent_upstream.py의 두 loader는 source manifest와 필수 파일 SHA를 확인한 바로 그 byte buffer를 compile한다. 기존 timestamp pyc나 확인 후 변경된 파일을 실행하지 않는다. 부모 순수 protocol loader는 원본 AST에서 parser/rescale 함수만 추출하며 실제 main은 자식에서 실행한다. vendor 원본 bytes/manifest는 바꾸지 않았다.

## 검증과 실제 시험 구분

초기 원본 subprocess RED5, 필수 secrets 입력/민감 캡처 차단 RED6 뒤 기본 경로6pass. 단계·한도·취소·정리·순수 loader를 포함한16pass 후 fresh final review1회에서 Critical0/Important5/Minor1. 주요5개를11개의 실패 테스트로 재현한 뒤 한 수정 pass로29pass19.91s. 실제 child가 읽지 않는 pipe, 오래된 관찰 재사용/다른 tag/인덱스, raw reasoning sentinel, 잘못된 pyc·검증 뒤 파일 변경, 불명 native 후 disk 실패를 포함한다. 재리뷰0.

최종 집중 명령: `.venv/Scripts/python.exe -B -m pytest tests/unit/test_mobile_agent_protocol.py tests/unit/test_mobile_agent_upstream.py tests/unit/test_mobile_agent_session.py tests/unit/test_openai_http.py tests/integration/test_mobile_agent_process.py -q -p no:cacheprovider --tb=short` → **83passed20.91s**. 전체 기존9실패 기준선을 해결했다거나 앱TC83건을 실행했다는 의미가 아니다.

기존 실제 증거도 별도로 대조했다. AI-LIVE-03 manifest85개 bytes/SHA 모두 일치, 실제4개 argv 녹화/재생 동일, replay 모델0/key 읽기false/모델포트 생성false/Python network0. 최종 PNG에 mouse 검색어와 상품 목록이 보인다. 설명 표의 네 번째 탭은 원본 report에 맞게869,213으로 정정했다. 유료 재시험0이며 사람이 승인한 사실도 없다.

## 결정·보류와 다음

Ruling: 콜백은 기존 bounded worker ports이며 timeout은 새 전송 cutoff이고 실행 중 콜백을 강제 중단하지 않는다. 비용: 등록 handler는 반드시 자체 timeout이 있는 포트만 공급해야 한다. IPC 쓰기 지연은 이 예외에 포함하지 않고 감독 writer로 수정했다.

Ruling: source checkout/Pillow 환경과 신뢰된 고정 자식 I/O 격리만 지원한다. 비용: wheel vendor 패키징·악성 프로세스 OS 격리는 별도 설계/검증이 필요하다.

Ruling: CLI 실제 시험과 이 모의 subprocess 검사를 정상 서버/승인 수용으로 승격하지 않는다. 비용: MA03b 서버 소유 원본 대화·저장 이력/이미지→MA04 정상 handler·journal/spool/ACK/finish→MA05 검토·승인본 AI0 실행 여정이 남는다. 사용자/UI dirty와 기존 DB/승인은 보존한다.

Deferred Minor: 부모/자식이 원본 날짜 prompt를 각각 만들기 때문에 자정을 걸치면 model_context로 보수적으로 중단할 수 있다. 잘못된 동작/호출을 허용하지 않으며 좁은 날짜 허용 검증은 후속이다. 포괄 callback_or_ipc_failed 사유의 세분화도 기존 진단 후속이다.

자동 승인 검토는 처음 제안된 무조건 빈 비밀 목록 전달을 보안 약화로 거절했다. 이를 우회하지 않고 secrets를 필수 입력으로 변경했으며 민감 캡처가 PNG 저장/모델 위임 전에 차단되는 검사를 추가했다. 현재 승인 대기/우회 경로는 없다.
