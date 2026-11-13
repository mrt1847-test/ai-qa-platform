# RX-99 · 정제된 관찰의 서버 고정과 실제 모델 이미지 입력

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. 아래 순서대로 RED→GREEN과 ledger를 남긴다. 실행 순서는 NEXT_ACTION.md 하나다.

**Goal:** Android 녹화 모델이 해시만 보지 않고 권한 있는 현재 정제 화면을 실제 입력으로 받게 한다.
**Architecture:** worker의 기존 filter_capture gate→인증 observation 업로드→서버 artifact/관찰 receipt 고정→model request는 observation ID 참조→서버가 원본 bytes/geometry를 provider에 전달한다. 별도 화면 접근 권한이나 worker의 임의 URL fetch는 만들지 않는다.
**Tech Stack:** 기존 Python/FastAPI/SQLite/httpx, 기존 PNG validator/artifact storage. 새 의존성·설치·실제 유료 호출 없음.
**Spec:** docs/superpowers/specs/2026-11-02-managed-pc-execution-design.md, docs/execution/CONTRACTS.md C00/C04/C05/C06/C14.
**선행:** RX-98/RX-65/RX-67. **환경:** local_python. **인계:** docs/validation/tasks/RX-99.md (완료 시).

## 확인한 누락과 보존 범위

observation_authoring_inputs는 observation_id·PNG/hierarchy hash·geometry·previous_result 문자열만 전송한다. OperationalProviderHttp.complete도 sanitized_inputs 문자열만 보내므로 실제 모델은 화면을 볼 수 없다. RX-65의 모의 관찰 분기 및 RX-98의 정상 HTTP 권한/전송 계측은 보존하며 이것을 실 AI 시각 입력 완료로 해석하지 않는다. 운영 키 부재와 별개인 코드 누락이다.

## Global Constraints

- 관리 API만 DB/artifact에 접근한다. worker는 인증 HTTPS와 정제 spool만 사용한다. browser key_present/URL/임의 artifact ID를 provider 입력 권한으로 믿지 않는다.
- 기존 filter_capture의 PNG CRC/크기/geometry 검사를 그대로 사용한다(현재 PNG 상한5,000,000 bytes). 알려진 SecretRef의 픽셀 정제 coverage를 증명하지 못하면 업로드·provider 전송0이다. sensitive capture gate를 bool 하나로 우회하지 않는다.
- 숨은 reasoning은 요구/저장하지 않는다. 최초 범위는 정제 PNG와 전체 CaptureGeometry, 고정 intent/직전 행동 결과다. DOM/XML 원문 추가 전송은 포함하지 않는다.
- worker 관찰 receipt는 REC/attempt 소유이며 가짜 action/check를 만들지 않는다. AI 거절·finish·중단처럼 아직 실제 행동이 없는 경우도 저장본을 보존한다. 기존 단계별 전후 증거·manifest/승인 기준을 완화하지 않는다.
- 같은 observation/모델 요청 재시도는 기존 receipt를 사용하며 수명/세대/소유를 바꾸지 않는다. RX-98의 strict 기본·명시 estimate/미측정 비용, 영속 quota·불명 전송 재시도0을 유지한다.

## Review Focus

다른 attempt/프로젝트의 화면 참조 차단; metadata/PNG 변조와 부분 파일; 모델 좌표계와 physical PNG 크기의 차이; SecretRef가 있는 관찰의 미증명 정제; 취소/만료·응답 유실 이후 동일 요청의 안전한 재조회. 각각 아래 owning test에서 provider0/동일 bytes·receipt를 확인한다.

## 1. 서버 관찰 업로드와 고정 receipt

**Files:** src/aiqa/models/model_observations.py (생성), src/aiqa/api/worker.py, migrations/versions/0050_model_observations.py (필요 시), tests/integration/test_rx99_model_observations.py.
**Interfaces:** POST /api/v1/worker/model-observations → {observation_id, image_hash, geometry_hash, artifact_id, replayed}. 서버 `store_authoring_observation(...)`는 RX-98의 현재 grant/lease/ACK/intent 검사와 기존 artifact storage/PNG gate를 소비한다. worker가 보낸 artifact 경로/URL은 받지 않는다.

- [x] 정상 current recording request/관찰을 업로드하면 provider0·실제 bytes/hash·REC/attempt 소유 artifact와 receipt가 저장되는 테스트를 먼저 작성한다. 프레임은 raw action/check가 없는 상태에서도 보존한다.
- [x] 단독 테스트 RED 확인 후 최소 구현한다. 같은 key/같은 본문은 동일 receipt, 다른 bytes/geometry는409. 정착 전 실패 파일을 ready로 보이지 않게 한다. 현재 worker/세대/intent·PNG CRC/크기/좌표·SecretRef 정제 부정 경로는0 provider/승인 불가다.
- [x] pytest 새 파일→GREEN. 서버 재조회로 bytes를 대조하고 커밋한다. native device 성공으로 보고하지 않는다.

## 2. worker capture에서 model request까지 연결

**Files:** src/aiqa/worker/model_observations.py (생성), worker/http_client.py, worker/android_jobs.py, tests/integration/test_rx99_model_observations.py.
**Interfaces:** `upload_authoring_observation(client, claim, observation, model_request) -> dict`는 기존 filter_capture를 호출하고 server observation_id를 반환한다. WorkerModelRequest에 optional model_observation_id를 추가한다. 새 normal pin은 참조가 필수며 legacy replay는 그대로다.

- [x] 실제 서버+WorkerHttpClient로 before 관찰이 서버에 ACK된 후만 모델 요청이 전송되는 테스트 RED를 만든다. 정제 실패/업로드 실패/관찰 소유 불일치는 모델/gesture0이다.
- [x] 관찰의 전체 CaptureGeometry(physical/model 크기·transform·rotation·content bounds)와 captured_at을 보존한다. PNG/geometry 해시와 모델 요청 fingerprint를 묶으며 worker 제공 objective로 고정 intent를 바꾸지 않는다.
- [x] 조회→전송→같은 요청 재수신을 GREEN으로 확인하고 커밋한다. 기존 RX-98 fixture도 명시 observation receipt를 준비하도록 보완하며 gate를 완화하지 않는다.

## 3. 서버 원본 bytes의 provider 입력

**Files:** models/broker.py, models/provider_http.py, models/recording_requests.py, tests/integration/test_rx99_model_observations.py 및 기존 RX98 테스트.
**Interfaces:** 기존 provider complete에 서버 전용 optional observation={png bytes, image_hash, geometry, captured_at} 포트를 추가한다. custom /v1/complete payload는 images=[{media_type:"image/png",data_base64,hash,geometry}]로 전달한다. 임의 URL·worker raw model payload를 그대로 전달하지 않는다. vendor별 API 호환은 별도다.

- [x] 동일 intent·서로 다른 정제 이미지의 실제 httpx.MockTransport 요청 body가 다르고 저장 bytes와 일치하는 테스트 RED. 해시 문자열만 넣은 모의 응답으로 대체하지 않는다.
- [x] 서버 관찰 loader가 정확한 소유/ready artifact/declared hash/geometry·수명을 확인한 후만 provider port에 bytes를 준다. unsupported provider는 사전 거절0이며 fixture를 운영 연결로 대체하지 않는다.
- [x] 같은 요청은1회 전송, 다른 관찰은 별개 request identity다. 취소/만료/폐기 이후 새 전송0·늦은 응답 action_allowed=false, 과거 화면/receipt 조회와 사후 승인은 독립 보존한다.
- [x] RX98/RX97/RX65/기존 증거·전체 회귀 후 인계/색인/진행표/큐 동기화. 원래9개 실패는 숨기지 않는다. 실제 Mobile-Agent API 키·토큰·AVD 수용은 RX-23, 비용 계측은 RX-29다.

완료2026-11-13, [인계](../validation/tasks/RX-99.md). core_contract이며 Deferred minor와 실제 모델/기기 미수용은 인계에 보존한다.
