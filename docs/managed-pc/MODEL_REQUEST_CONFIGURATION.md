# 녹화 모델 요청의 서버 설정

Updated: 2026-11-13. RX-98의 정상 DB 녹화 요청에 적용한다. 실제 vendor/AVD/VM 수용은 RX-23/24다. 이번 구현에서 설치·서비스 재시작·모델 과금을 실행하지 않았다.

| 설정 | 기본값 | 동작 |
|---|---|---|
| AIQA_MODEL_PRICE_MODE | strict | 운영 가격 quote가 없으면 unknown_price로 전송0. 이 배치에는 운영 tariff quote adapter가 없어 정상 녹화 AI 차단 |
| AIQA_MODEL_PRICE_MODE=estimate | 운영자의 명시 선택 | 저장 호출 수 한도 내에서 전송. 비용/토큰은 null, incomplete=true. USD 예산·청구 hard cap 보장 아님 |

현재 quote가 없으므로 실제 모델 녹화를 선택하려면 관리 서버 프로세스에 estimate를 명시해야 한다. 과금에 동의한 운영자가 설정하는 항목이며 worker 요청의 price_mode/key_present/budget으로 바꿀 수 없다. strict 가격 예약 adapter는 후속이며 없는 가격을0으로 간주하지 않는다. 단가/토큰·월3000건 실측은 RX-29다. 검증/치유 역할의 가격·소유 권한 연결은 RX-87/88에서 다룬다.

모델 연결은 프로젝트 설정의 authoring logical binding 고정 개정과 key ref/revision을 사용한다. 키 원문은 관리 서버 서비스 계정 secret store에만 있고 worker/생성 코드에는 보내지 않는다. 메타데이터 available과 실제 서비스 계정 credential 읽기 성공은 별도다. 실패한 키를 다른 프로젝트/최신 key로 바꾸어 재시도하지 않는다.

운영 HTTP provider는 기존 AIQA_MODEL_PROVIDER_* 설정으로 승인한 base endpoint와 binding endpoint가 일치하고 HTTPS 운영 연결일 때만 사용한다. 기본 fixture는 명시 fixture provider+loopback binding만 처리하며 운영 연결에 모의 성공을 반환하지 않는다. 이 배치의 포트는 기존 custom /v1/complete protocol이며 OpenAI 등 vendor별 API 호환을 주장하지 않는다. httpx.MockTransport/MemorySecretBackend 검증은 실제 유료 모델 수용이 아니다.

같은 API 요청 재전송은 저장 receipt만 읽는다. pending/불명은 보수적으로 호출1을 유지하며 자동 재전송/중간 재개하지 않는다. 새 작업은 사용자가 명시 녹화로 시작한다. 키 폐기·취소·만료 후 과거 receipt 읽기는 실행 권한을 주지 않으며 action_allowed=false다. 운영 모델/API 가격·자격증명 수용 전 실제 과금을 실행하지 않는다.

## RX-99 관찰 입력

새 normal recording pin의 모델 요청에는 model_observation_id가 필수다. worker는 정제 PNG를 기존 evidence-commits로 ACK한 뒤 /api/v1/worker/model-observations에 artifact_id·hash·전체 geometry·captured_at·원 관찰 ID와 동일 모델 요청 identity를 등록한다. 모델 요청은 이미지/URL 원문 대신 이 ID를 보낸다. 서버는 ready/ACK된 같은 REC/attempt artifact와 현재 worker/세대/lease/intent/policy를 검증한다. 프레임은30초, 미래 시계 허용5초이며 오래된 관찰은 새 전송/행동에 쓰지 않는다.

custom /v1/complete 공급자 입력에는 images 배열의 image/png·data_base64·hash·geometry가 추가된다. 실제 vendor API와 호환된다는 뜻이 아니며 운영 키를 입력하기 전에 해당 endpoint가 이 프로토콜을 지원해야 한다. PNG bytes는 telemetry에 복제하지 않는다. 대상 SecretRef가 있는 녹화는 신뢰할 픽셀 정제 coverage 구현 전까지 차단한다. 모델 API key의 SecretRef는 대상 화면 SecretRef와 별개다. 서버가 bool sanitized 하나만으로 민감 화면을 허용하지 않는다.
