# 녹화 모델 요청의 서버 설정

Updated: 2026-11-17. 정상 DB 녹화와 원본 Mobile-Agent 운영 접수에 적용한다. 실제 vendor/AVD/VM 수용은 RX-23/24다. 이번 구현에서 설치·서비스 재시작·모델 과금을 실행하지 않았다.

| 설정 | 기본값 | 동작 |
|---|---|---|
| AIQA_MODEL_PRICE_MODE | strict | 운영 가격 quote가 없으면 unknown_price로 전송0. 이 배치에는 운영 tariff quote adapter가 없어 정상 녹화 AI 차단 |
| AIQA_MODEL_PRICE_MODE=estimate | 운영자의 명시 선택 | 저장 호출 수 한도 내에서 전송. 비용/토큰은 null, incomplete=true. USD 예산·청구 hard cap 보장 아님 |

현재 quote가 없으므로 실제 모델 녹화를 선택하려면 관리 서버 프로세스에 estimate를 명시해야 한다. 과금에 동의한 운영자가 설정하는 항목이며 worker 요청의 price_mode/key_present/budget으로 바꿀 수 없다. strict 가격 예약 adapter는 후속이며 없는 가격을0으로 간주하지 않는다. 단가/토큰·월3000건 실측은 RX-29다. 검증/치유 역할의 가격·소유 권한 연결은 RX-87/88에서 다룬다.

모델 연결은 프로젝트 설정의 authoring logical binding 고정 개정과 key ref/revision을 사용한다. 키 원문은 관리 서버 서비스 계정 secret store에만 있고 worker/생성 코드에는 보내지 않는다. 메타데이터 available과 실제 서비스 계정 credential 읽기 성공은 별도다. 실패한 키를 다른 프로젝트/최신 key로 바꾸어 재시도하지 않는다.

관리 서버의 명시 `AIQA_MODEL_PROVIDER_MODE=openai`는 고정 공식 OpenAI Responses 포트를 선택한다. Android 원본 녹화의 authoring binding은 provider=openai·model=gpt-6-luna·공식 origin 또는 Responses endpoint를 사용한다. 설정 화면도 공식 OpenAI endpoint를 저장하면 해당 provider를 보존한다. 기존 custom `/v1/complete` operational provider와 Web/명시 fixture 경로는 별도다. fixture 연결을 실제 OpenAI 성공으로 처리하지 않는다. httpx.MockTransport/MemorySecretBackend 검증은 실제 유료 모델 수용이 아니다.

같은 API 요청 재전송은 저장 receipt만 읽는다. pending/불명은 보수적으로 호출1을 유지하며 자동 재전송/중간 재개하지 않는다. 새 작업은 사용자가 명시 녹화로 시작한다. 키 폐기·취소·만료 후 과거 receipt 읽기는 실행 권한을 주지 않으며 action_allowed=false다. 운영 모델/API 가격·자격증명 수용 전 실제 과금을 실행하지 않는다.

## RX-99 관찰 입력

새 normal recording pin의 모델 요청에는 model_observation_id가 필수다. worker는 정제 PNG를 기존 evidence-commits로 ACK한 뒤 /api/v1/worker/model-observations에 artifact_id·hash·전체 geometry·captured_at·원 관찰 ID와 동일 모델 요청 identity를 등록한다. 모델 요청은 이미지/URL 원문 대신 이 ID를 보낸다. 서버는 ready/ACK된 같은 REC/attempt artifact와 현재 worker/세대/lease/intent/policy를 검증한다. 프레임은30초, 미래 시계 허용5초이며 오래된 관찰은 새 전송/행동에 쓰지 않는다.

custom /v1/complete 공급자 입력에는 images 배열의 image/png·data_base64·hash·geometry가 추가된다. 실제 vendor API와 호환된다는 뜻이 아니며 운영 키를 입력하기 전에 해당 endpoint가 이 프로토콜을 지원해야 한다. PNG bytes는 telemetry에 복제하지 않는다. 대상 SecretRef가 있는 녹화는 신뢰할 픽셀 정제 coverage 구현 전까지 차단한다. 모델 API key의 SecretRef는 대상 화면 SecretRef와 별개다. 서버가 bool sanitized 하나만으로 민감 화면을 허용하지 않는다.

## Android 원본 녹화의 worker 등록과 접수

실행 PC의 `AIQA_WORKER_MODEL_MODE=operational`은 원본 Mobile-Agent handler를 사용한다. 서버 key를 worker 환경변수에 넣지 않는다. worker의 모델 요청은 기존 HTTPS token과 서버에 등록한 프로젝트 authoring secret reference를 사용한다.

worker는 실제 recording route가 준비된 경우에만 현재 authenticated boot/session의 원본 엔진 또는 명시 fixture mode를 inventory에 보고한다. 서버는 recording credential/project/worker/boot/session을 확인해 report identity를 덮어쓰고, selected physical owner가 같은 worker인지 claim 전에도 검사한다. 다른 PC의 같은 `emulator-5554` 이름은 실행 PC 신원이 아니다. probe-only token, 오래된 session, 다른 프로젝트 report, 미지원 source는 원본 녹화 권한이 아니다.

서버 gateway가 실제 OpenAI 포트가 아니거나 가격 정책이 strict unknown이면 원본 녹화 preview와 새 접수가 차단된다. 입력에는 준비 포함 최소 동작2, 민감 target/definition secret refs 제외, 구성된 목표12KB 한도가 적용된다. 값이 아니라 저장된 정의·메타데이터만 검사하며 UI는 모델/가격 문제는 Settings, worker 지원 문제는 Environments로 안내한다. 이미 받은 request receipt의 pin은 설정 변경으로 덮지 않는다.

원본 source나 선택 의존성이 없으면 원본 녹화만 지원 불가로 보고한다. inventory·설치 앱 조회·준비된 재생 등 독립 route의 worker 구성을 함께 막지 않는다. 서버에 ACK된 녹화 증거 조회·사후 승인에는 실행 PC의 현재 엔진 지원 보고가 필요하지 않으며 재녹화/실행 접수에는 준비된 실행 자원이 필요하다.
