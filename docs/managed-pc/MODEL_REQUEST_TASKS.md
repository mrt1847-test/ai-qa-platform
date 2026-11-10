# 정상 녹화 모델 요청 연결

Updated: 2026-11-10. 기존 C00/C04/C08/C14의 구현 누락을 나눈 카드다. 실행 순서는 NEXT_ACTION.md다. 운영 키 없이 임시 DB/모의 provider로 구현하고 실제 모델 수용 RX-23/24는 별도로 남긴다.

근거: start_recording은 authoring revision의 존재만 확인하고 timeout만 저장한다. server_model_plan_provider는 revision=1을 기본 전송하며, 실제 API에는 AttemptModelPolicy 등록 호출이 없어 테스트가 직접 등록한 정책만 동작한다.

<a id="rx-97"></a>
## RX-97 · 녹화 시작·재녹화의 모델 및 한도 고정

**선행** RX-91/RX-95. **계약** C00/C01/C04/C08/C14. **환경** local_python.

- [x] 서버가 동일 프로젝트의 현재 authoring binding을 결정적으로 선택하고 정확한 revision/key revision의 available 메타데이터를 확인한다. 선택한 최신 binding이 부적합하면 과거 정상 binding으로 회피하지 않는다. 현재 logical binding의 latest revision만 후보며 role 변경된 과거 revision은 제외한다.
- [x] 시작·재녹화 job limits에 비밀 없는 authoring-admission-v1 pin, 입력 버전/hash, timeout/actions/model calls/budget/USD를 고정한다. 전역 600초/50행동/80호출/2USD보다 넓히지 않고 저장된 좁은 한도는 보존한다. 예산·호출0은 녹화 불가다. 키 원문/endpoint는 worker pin에 보내지 않는다.
- [x] 같은 요청 재전송은 당시 job limits/영수증을 재사용한다. 모델 회전/폐기 이후에도 재조회가 가능하며 새 요청은 새 정책으로만 접수한다. 실패 시 새 버전·head·job·녹화·receipt가 남지 않는다.
- [x] 실제 HTTP→queue claim의 policy_ref에 pin hash를 연결하고 공통 worker gate가 손상된 pin을 행동 전에 거절한다. Android 모델 요청은 pin의 revision을 사용한다. 과거 timeout-only 작업은 기존 계약을 유지한다.
- [x] HTTP/임시 DB로 최신·교차 프로젝트·역할 변경·키 폐기·예산0·재시도·재녹화 rollback·claim 변조를 검증한다. 이 카드는 provider 요청 권한/호출 계측을 완료하지 않는다. 모델 요청 gate는 RX-98, 플랫폼별 행동/시간 한도 소비는 RX-87/88에서 연결한다.

**인계** docs/validation/tasks/RX-97.md (완료).

<a id="rx-98"></a>
## RX-98 · 정상 임대 녹화의 서버 모델 권한 준비

**선행** RX-97/RX-96. **계약** C00/C01/C04/C08/C14. **환경** local_python.

- [ ] worker/model-requests에서 서버 DB의 현재 임대·worker/project/attempt/generation/purpose·동결 intent를 확인하고 RX-97의 정확한 binding/key revision만 해석해 attempt 정책을 준비한다. client actor_id/role/owner/최신 revision 대체를 권한으로 믿지 않는다.
- [ ] 재요청이 메모리 정책 호출량을 초기화하지 않게 하며 만료·취소·키 폐기·한도 초과는 provider 전에 차단한다. 프로세스 재시작 후 quota 복원/영속 계측 경계를 명시하고 해결한다. 비밀은 서버 secret resolver만 읽는다.
- [ ] HTTP 오류에 provider_dispatched의 신뢰 가능한 상태를 전달하고 worker가 정책 거절0/실제 전송 실패1을 구별한다. 자체 provider mock만으로 실제 vendor API 수용이라고 표시하지 않는다.
- [ ] 테스트에서 register_policy를 호출하지 않는 실제 browser 시작→worker claim/ACK→authoring HTTP 요청·응답·한도·재시도·거절 여정을 확인한다. Android/Web healing episode/verifier 권한은 RX-87/88의 별도 소유·예약 계약으로 연결하며 recording 권한을 재사용하지 않는다.

**인계** docs/validation/tasks/RX-98.md (완료 시 작성).

### RX-98의 실행 순서와 중간 확인

한 번에 handler·DB·provider를 통째로 바꾸지 않고 아래 순서로 구현한다. ID 완료는 모든 필수 단계가 끝난 뒤 한 번만 한다.

1. **소유 gate** (`models/recording_authorization.py`, 테스트 새 RX98 파일): 현재 attempt→job→lease→incarnation/worker presence를 서버에서 읽는다. project/worker/purpose=recording/authoring owner_id=attempt/generation/ACK 이후 active 상태·취소·만료·600초 및 저장 timeout을 확인한다. 타 worker·같은 프로젝트의 타 attempt·지난 generation·ACK 전·취소·만료를 provider0으로 재현한다. timestamp는 서버 시각이며 client deadline=2099를 작업 수명으로 쓰지 않는다.
2. **고정 정책 준비**: stored job limits의 authoring pin/hash와 해당 recording_intent/version을 대조한다. DB의 정확한 binding/key revision·role/compatibility/availability를 재검사한다. model은 고정 revision에서, actor는 서버 접수 이력에서 얻는다. 최신 모델·worker actor_id·client key_present로 대체하지 않는다. OS resolver 실패와 메타데이터 실패를 구분한다. 이 단계만으로 provider를 호출하지 않는다.
3. **영속 예약** (`migrations/versions`/`store`): worker가 재사용한 idempotency key와 실제 normalized request fingerprint를 scoped project/attempt/role에 고정한다. provider 전에 SQLite 원자 예약하고 전송 중 DB transaction을 유지하지 않는다. 프로세스 재시작/두 요청 경합/미정착 요청도 호출 quota를 복구하거나 보수적으로 차감한다. 기존 model_call_facts는 action/check FK를 요구하므로 authoring을 위해 가짜 action/check를 만들지 않는다.
4. **provider와 정착** (`models/broker.py`와 HTTP API): 준비된 정책을 한 번 등록하고 새 요청이 ledger를 초기화하지 않게 한다. key 원문은 서버 resolver 내부에서만 사용한다. 사전 거절은0, 성공·전송 이후 실패/불명은1로 정착하고 idempotent 재수신이 같은 요청을 다시 provider에 보내지 않도록 한다. 미정착/타임아웃은 명시 unknown으로 남기며 자동 성공·재전송을 하지 않는다.
5. **HTTP 오류·worker 연결** (`api/worker.py`,`worker/http_client.py`,`worker/android_jobs.py`): reason/provider_dispatched를 typed 데이터로 전하고 provider 미전송·전송 실패·관리 API 응답 유실을 구별한다. 임의 오류 원문/토큰을 노출하지 않는다. claim generation과 고정 revision을 실제 authoring 요청에 전달한다. 다른 worker API 오류 계약은 유지한다.
6. **통합 증거와 인계**: 테스트의 register_policy 호출 없이 browser start→claim→ACK→model 요청을 실제 ASGI/MockTransport/MemorySecretBackend로 수행한다. 한도/재시도/키 회전·폐기/서버 gateway 재생성·정리/거절·원본 기록 보존을 확인한다. binding endpoint와 실제 provider port의 대상이 일치해야 하며 무조건 다른 global endpoint로 보내지 않는다. vendor protocol 지원은 실제 어댑터 근거로만 주장하고 현재 custom /v1/complete fixture로 대체하지 않는다.

금액은 호출 수와 별개다. tariff 기반 사전 비용 상한을 적용하거나 미측정/추정 모드를 명시적으로 모델링해야 한다. max_calls만으로 budget USD를 지켰다고 보고하지 않는다. RX-29는 구현 후 실제 모델 토큰·비용·처리량 계측이다.
