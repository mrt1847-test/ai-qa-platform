# 원격 워커 구현 계획

> [경계와 공통 검증 규칙](RUNTIME_BOUNDARIES.md) · [직접 선행 및 환경 색인](IMPLEMENTATION_TASKS.json) · [공통 계약](../execution/CONTRACTS.md). NEXT_ACTION의 Current 절 하나만 실행한다. TDD로 실패 조건을 확인하고 기능을 연결한 뒤 같은 검사를 반복한다. 선행 인계와 구현의 필드명이 다르면 계약을 먼저 대조한다. 카드의 파일은 기존 파일과 생성 예정 파일을 함께 지정한다.

<a id="rx-01"></a>
## RX-01 · 워커 세대와 서버 부팅 분리

**입력** PC-04 · PC-02 및 C00/C01/C04. **환경** `local_python`.

**파일** `src/aiqa/worker/service.py`, `src/aiqa/worker/presence.py`, `src/aiqa/store/queue.py`, `src/aiqa/store/models.py`, `src/aiqa/api/worker.py`, `migrations/versions/0038_worker_attempt_incarnation.py`, `tests/integration/test_rx_01.py`.

- [x] 서버만 재시작하면 정상 worker lease 보존, worker만 재시작하면 기존 dispatch 금지, 세대 위조·구 세션 거절, 이전 DB migration 후 기존 이력 보존.
- [x] WorkerIncarnation(worker_id, session_id, boot_id)를 등록 세션에 묶고 claim에서 attempt에 저장한다. ACK·renew·reconcile은 저장된 세대와 현재 등록 세대를 대조한다. 기존 local attempt는 별도 legacy 분기로 해석한다.
- [x] `python -m pytest -q tests/integration/test_rx_01.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-01.md`에 검증 등급·명령·결과와 세대 필드·마이그레이션 revision·ACK 실패 코드를 남긴다.

<a id="rx-02"></a>
## RX-02 · 워커 발급·폐기와 권한 범위

**입력** PC-04 · PC-02 및 C00/C01/C03/C04/C11. **환경** `local_python`.

**파일** `src/aiqa/api/auth.py`, `src/aiqa/api/resources.py`, `src/aiqa/worker/presence.py`, `src/aiqa/security/worker_enrollment.py`, `tests/integration/test_rx_02.py`.

- [x] 재사용·만료·다른 프로젝트·폐기 토큰·비관리자 발급 거절. 원문 토큰 DB/로그 미노출.
- [x] 기존 enroll_worker·worker_scope_from_token을 확장한다. 관리자 1회 enrollment code를 worker_id와 만료에 묶고 POST /api/v1/worker/enrollments/exchange에서 프로젝트·runner 범위의 폐기 가능한 bearer를 발급한다. revoke는 새 claim·renew·업로드를 차단하고 진행 중 작업을 정리 대기로 보낸다.
- [x] `python -m pytest -q tests/integration/test_rx_02.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-02.md`에 검증 등급·명령·결과와 발급·교환·폐기 route와 권한 표를 남긴다.

<a id="rx-03"></a>
## RX-03 · claim 영수증과 실행 스냅샷

**입력** RX-01 · RX-02 및 C00/C01/C04/C07/C09. **환경** `local_python`.

**파일** `src/aiqa/api/worker.py`, `src/aiqa/worker/service.py`, `src/aiqa/store/queue.py`, `src/aiqa/contracts/worker_attempt.py`, `tests/integration/test_rx_03.py`.

- [x] 같은 키 응답 유실 후 attempt 1개, 키 충돌·scope 위조 거절, 설정 변경 후 스냅샷 동일, 만료 receipt로 dispatch 금지.
- [x] claim은 worker 세대와 Idempotency-Key에 결합된 receipt 및 JobSpecSnapshot(job_id, attempt_id, purpose, target_ref, revision_ref, policy_ref, digest)을 반환한다. 응답 유실 시 같은 키로 receipt를 조회한다. 동일 physical scope를 쓰는 복수 등록 별칭은 서버 소유 canonical scope에 묶는다. snapshot·receipt가 준비되기 전에는 ACK 승인하지 않는다.
- [x] `python -m pytest -q tests/integration/test_rx_03.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-03.md`에 검증 등급·명령·결과와 claim DTO·digest·멱등 키 규칙를 남긴다.

<a id="rx-04"></a>
## RX-04 · outbound HTTP 클라이언트

**입력** RX-02 · RX-03 및 C00/C01/C03/C04. **환경** `local_python`.

**파일** `src/aiqa/worker/http_client.py`, `src/aiqa/config.py`, `tests/integration/test_rx_04.py`.

- [x] 잘못된 인증서·다른 origin redirect·폐기 토큰·timeout 거절, 유실 claim은 같은 키로만 조회, 응답/로그에 bearer 미노출.
- [x] WorkerHttpClient는 관리 서버 HTTPS로 heartbeat·inventory·claim·ACK·renew를 호출한다. test transport를 주입할 수 있게 하고 인증·CA 검증·기한·재시도 분류를 한 곳에서 처리한다.
- [x] `python -m pytest -q tests/integration/test_rx_04.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-04.md`에 검증 등급·명령·결과와 설정 키·DTO·재시도와 비재시도 분류를 남긴다.

<a id="rx-05"></a>
## RX-05 · dispatch watchdog과 정리 확인

**입력** RX-03 · RX-04 및 C00/C01/C04/C05. **환경** `local_python`.

**파일** `src/aiqa/worker/control.py`, `src/aiqa/worker/runner.py`, `src/aiqa/worker/dispatch_journal.py`, `src/aiqa/store/queue.py`, `src/aiqa/api/worker.py`, `tests/integration/test_rx_05.py`.

- [x] 시계 이동·갱신 유실·cancel 후 다음 행동 0회, 늦은 구 세대 정리 거절, ambiguous attempt 중 자원 재할당 금지.
- [x] RemoteLeaseGuard는 로컬 단조 시계와 서버의 남은 유효 기간으로 행동 직전 gate를 건다. C04의 10초 heartbeat·45초 lease·30초 watchdog·행동 전 잔여 10초를 유지한다. STARTED만 남은 행동은 미확정으로 기록한다. 서버는 attempt·세대·자원 fence가 일치하는 정리 확인을 받은 뒤에 임대를 해제한다.
- [x] `python -m pytest -q tests/integration/test_rx_05.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-05.md`에 검증 등급·명령·결과와 watchdog 예산·journal 전이·정리 영수증를 남긴다.

<a id="rx-06"></a>
## RX-06 · 정제 증거 업로드와 commit ACK

**입력** RX-03 · RX-04 및 C00/C01/C05/C08. **환경** `local_python`.

**파일** `src/aiqa/worker/spool.py`, `src/aiqa/worker/http_client.py`, `src/aiqa/api/artifacts.py`, `src/aiqa/api/worker.py`, `src/aiqa/store/evidence.py`, `src/aiqa/store/artifact_ingest.py`, `tests/integration/test_rx_06.py`.

- [x] 정제 실패 전송 0회, commit 응답 유실 후 중복 0건, 틀린 hash·권한 거절, 늦은 ACK가 verdict·승인 가능 상태를 변경하지 않음.
- [x] 서버가 정제 artifact와 연속 event prefix를 commit한 뒤 (attempt_id, contiguous_seq, prefix_hash)를 반환한다. 로컬 spool은 일치하는 ACK 뒤에만 purge한다. 종료 후 유입은 기존 attempt의 복구 증거로만 연결한다.
- [x] `python -m pytest -q tests/integration/test_rx_06.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-06.md`에 검증 등급·명령·결과와 증거 ACK wire format·late 상태·보존/폐기 규칙를 남긴다.

<a id="rx-07"></a>
## RX-07 · worker 종료 결과 제출

**입력** RX-05 · RX-06 및 C00/C01/C05/C07/C08/C09. **환경** `local_python`.

**파일** `src/aiqa/api/worker.py`, `src/aiqa/recording/service.py`, `src/aiqa/domain/executions.py`, `src/aiqa/store/queue.py`, `tests/integration/test_rx_07.py`.

- [x] 증거 누락·미확정 dispatch·다른 worker 제출로 성공 금지, 동일 finish 재전송 1회 처리, worker 승인 불가.
- [x] POST /api/v1/worker/attempt-finishes는 scope와 fence를 검증하고 manifest digest 및 마지막 ACK를 대조한 뒤 기존 recording/run 종료 서비스를 부른다. review와 approve는 기존 사용자 경로에 남긴다.
- [x] `python -m pytest -q tests/integration/test_rx_07.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-07.md`에 검증 등급·명령·결과와 finish DTO와 녹화·시범·정식 실행의 종결 상태 표를 남긴다.

<a id="rx-08"></a>
## RX-08 · 독립 worker 소비 프로세스

**입력** RX-05 · RX-07 및 C00/C01/C03/C04/C05. **환경** `local_python`.

**파일** `src/aiqa/launcher.py`, `src/aiqa/worker/runtime.py`, `src/aiqa/worker/runner.py`, `tests/integration/test_rx_08.py`.

- [x] offline·미등록·지원하지 않는 대상은 행동 0회, 종료 시 새 claim 중단, 연결 복구·재시작에서 과거 job 자동 재개 0회. 접수 후 미claim 상태에서 자원 연결이 끊긴 job도 사용자의 새 명시 접수 없이 실행되지 않는다.
- [x] worker 진입점은 서버 DB 없이 heartbeat·inventory·poll을 수행한다. claim→스냅샷 검증→ACK→runner dispatch→증거/finish 순서를 보장한다. 검증용 inert handler를 주입하고 실제 대상은 준비된 adapter만 선택한다.
- [x] `python -m pytest -q tests/integration/test_rx_08.py`에서 계약이 빠진 실패를 확인하고 구현 후 같은 명령의 통과를 확인한다.
- [x] `docs/validation/tasks/RX-08.md`에 검증 등급·명령·결과와 worker 실행 명령·config·handler와 종료 계약를 남긴다.
