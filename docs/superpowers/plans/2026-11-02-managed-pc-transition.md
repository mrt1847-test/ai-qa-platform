# Managed PC Execution Implementation Plan

> **For agentic workers:** 확정된 사용자 요구와 [설계](../specs/2026-11-02-managed-pc-execution-design.md)를 따른다. PC-01~04 전환 카드 완료 후 [RX 구현 색인](../../managed-pc/IMPLEMENTATION_TASKS.json)에서 NEXT_ACTION의 Current 하나에 해당하는 카드만 실행한다.

**Goal:** 서버에 저장한 녹화는 실행 PC 없이 승인하고, online 실행 자원에서만 녹화/테스트한다. 초기 실행 PC 한 대에서 여러 PC/선택 cloud 자원으로 확장한다.

**Architecture:** 관리 API/DB/artifact와 실행 worker를 독립 수명으로 배치한다. 기존 scope/job/lease/spool/ACK·승인 불변성은 재사용한다. 상용 provider는 선택이며 기본 선행이 아니다.

**Tech Stack:** 기존 Python/FastAPI/Jinja2/SQLite 개발 baseline 재사용. 독립 운영 호스팅·인증/secret/artifact backend는 후속 근거와 실제 수용 전 미정이다.

## Global Constraints

- 접속 PC에는 worker/ADB/VM을 요구하지 않는다. 등록된 실행 PC에는 운영 worker/driver를 둔다.
- 서버 저장/ACK된 ready 증거만 offline 검토에 사용한다. 기존 필수 trial/버전/검토/보관 조건을 완화하지 않는다.
- offline 신규 실행은 거부하며 재연결 후 자동 실행 예약을 만들지 않는다. 완료된 멱등 요청 receipt 조회는 유지한다.
- 일반 replay actor0·필요 verifier·healing 기본OFF·재녹화 새 후보·이전본 유지.
- 설치/계정 가입/구매/공개·배포는 이번 PC-01 작업에 포함하지 않는다. DB 초기화/이력 삭제 금지.

## Review Focus

- rerun이 최초 실행과 다른 검사로 offline 자원을 접수하는 경우.
- quarantine인데 inventory는 ready로 남은 자원.
- 사용자 PC·관리 서버·원격 worker의 boot/session identity 혼동.
- spool에만 있는 증거를 서버 저장 완료/승인 가능으로 표시하는 경우.
- PC 단절을 새 trial 강제 조건으로 삼거나 반대로 기존 필수 근거 gate를 없애는 경우.

<a id="pc-01"></a>
## PC-01 — 저장 검토와 명시적 offline 실행 차단의 공통 계약

직접 선행: W16-01/W17-01/W20-01/W22-03/W19-01. 등급 core_contract. 외부 자격/실행 PC가 없어도 임시 서버 DB로 검증한다. 이번 구현은 inventory의 명시 상태와 quarantine에 대한 admission이며 전원 단절 자동 감지는 PC-02다.

**Files / interface**

- Create `src/aiqa/domain/resource_readiness.py`: `resource_readiness(connection, project_id: UUID, resource_id: str, target_kind: str) -> ResourceReadiness`; 결과는 ready/code/message/job_id. project alias 조회 후 target·quarantine·state를 판정하고 DB write/device 호출을 하지 않는다.
- Modify `src/aiqa/recording/service.py:_require_resource`: 공통 판정에서 PreflightRejected/ResourceBusy로 변환. 기존 preview/start/rerecord 모두 소비한다.
- Modify `src/aiqa/domain/executions.py:_one_item`(실제 item resolver), `_rerun_blockers`: trial/formal/rerun에 같은 판정. rerun은 pinned version target·resource를 다시 확인하며 거부 전 RUN/ITEM/job을 만들지 않는다. 완료 receipt 재조회는 앞선 멱등 경로를 유지한다.
- Modify `src/aiqa/web/templates/case_review.html`: 서버 보관 증거는 실행 PC offline이어도 검토/승인 가능하며 실행은 연결 필요하다고 안내한다. 승인 gate 자체는 바꾸지 않는다.
- Test `tests/integration/test_managed_pc_admission.py`, `tests/acceptance/test_managed_pc_review.py`: 임시 DB와 기존 tests-only graph를 사용한다.

**Steps / acceptance**

- [x] offline·unauthorized·busy·quarantine·타 project/target의 최초 녹화·재녹화·trial/formal·rerun 거부와 write0을 검증할 실패 시험을 먼저 실행한다. ready 정상과 기존 멱등 receipt는 유지한다.
- [x] 공통 helper와 소비 경로만 구현한다. 기존 승인/원본/QA를 수정하지 않는다.
- [x] 실제 서버의 review/approval 서비스를 임시 저장소에서 호출해 worker/자원이 없어도 완전한 저장 근거 승인 가능, 부족 근거 거부를 확인한다. fixtures는 제품/운영 DB에 넣지 않는다.
- [x] 새 시험과 영향 W16/W17/W19/W20/W22 회귀를 실행하고 UI 문구는 실제 template 응답에서 확인한다. 이 검증은 실제 원격 배포/PC 종료 수용이 아님을 인계에 쓴다.
- [x] diff 검토·인계 `docs/validation/tasks/PC-01.md`·색인/진행/큐 동기화. 다음 PC-02.

<a id="pc-02"></a>
## PC-02 — 서버 수신 시각 기반 worker 접속 수명

직접 선행 PC-01/W07-01/W11-01. 등급 core_contract. 새 파일 `src/aiqa/worker/presence.py`, 수정 `src/aiqa/store/schema.py`, `src/aiqa/store/database.py`, `src/aiqa/api/worker.py`, `src/aiqa/api/resources.py`, `src/aiqa/domain/resource_readiness.py`, `src/aiqa/store/queue.py`. 시험 `tests/integration/test_worker_presence.py`.

**Interface:** `report_presence(connection, worker: WorkerScope, boot_id: str, now: datetime) -> WorkerPresence`; `get_presence(connection, worker_id: str, now: datetime) -> WorkerPresence`. boot_id는 bounded opaque identifier이며 서버가 정하는 UTC received_at·worker/project/purpose·revocation을 신뢰한다. DTO에 endpoint/token을 넣지 않는다. resource observation timestamp와 presence를 별개로 저장한다.

- [x] migration 전 데이터가 보존되고 예전 등록 worker의 접속 상태는 unknown→실제 인증 heartbeat 후 online이 되는 실패 시험 작성.
- [x] 10초 보고/45초 미수신 offline, 경계44.999/45초·미래 observation·timezone 오류·등록 폐기·다른 project/worker 위조 거부를 고정 clock으로 검사.
- [x] resource_readiness 및 최초 접수/rerun/claim이 presence를 소비하고 offline에 write/dispatch0, reconnect는 재검증 전 자동 실행0을 검사. 원래 claim lease/watchdog는 별도 유지.
- [x] 정상 heartbeat·만료·복귀와 approval 무관성을 검사하고 인계 `PC-02.md`; 필요해지는 소비 fixture만 인증 presence를 명시해 수정한다. sleep으로 시험하지 않는다.

<a id="pc-03"></a>
## PC-03 — 실행 PC 연결 상태와 조회/실행 행동 UI

직접 선행 PC-02/W11-01/W20-03. 등급 core_contract. 수정 `src/aiqa/worker/resources.py`, `src/aiqa/api/resources.py`, `src/aiqa/web/templates/environments.html`, `src/aiqa/web/templates/recording_setup.html`, `src/aiqa/web/templates/execution_setup.html`, `src/aiqa/web/static/recording_setup.js`, `src/aiqa/web/static/execution_setup.js`. 시험 `tests/acceptance/test_managed_pc_availability_ui.py` 및 필요한 tests/web.

**Interface:** resources 응답에 worker_id·연결 상태·last_seen·실행 가능/차단 이유를 명시하고 raw endpoint/token은 제외한다. UI는 서버 판정을 소비하며 client 시간으로 online을 확정하지 않는다.

- [x] online/busy/offline/unknown/quarantine에 기기 마지막 이미지와 현재 연결을 분리해 표시하는 실패 시험 작성.
- [x] offline에서도 저장 증거/검토/승인·초안 편집 접근을 유지하고 새 녹화/재녹화/trial/정식/rerun·진단은 연결 필요 사유로 막는다. 서버 차단은 PC-01/02를 유지한다.
- [x] 선택 후 단절·다시 접속·새로고침·키보드/오류·입력 보존을 실제 브라우저에서 검사한다. 자동 새 실행/가짜 online 없이 인계 `PC-03.md`.

<a id="pc-04"></a>
## PC-04 — 원격 실행·독립 서버의 후속 카드 확정

직접 선행 PC-01/W01-01. PC-02/03과 독립 진행 가능. 등급 source_audit_design. 공개 근거가 필요한 선택은 실제 공식 문서·고정 CUAWright/Mobile-Agent source로 대조한다. 설치·과금·배포를 하지 않는다.

**Files:** 생성 `docs/managed-pc/RUNTIME_BOUNDARIES.md`, `docs/managed-pc/IMPLEMENTATION_TASKS.json`, 필요한 영역별 세부 카드. 기존 `launcher.py`, `worker/service.py`, `worker/control.py`, `store/queue.py`, `api/worker.py`, `api/auth.py`, `config.py`, `security/secrets.py`, `store/artifacts.py`, `environments/android_observation.py`, 고정 upstream 두 source를 참고한다.

- [x] 원격 worker boot/session과 server boot 분리·등록/폐기·outbound HTTP transport·실제 소비 loop를 각각 독립 검증 카드로 분리한다.
- [x] Android 관찰/결정적 행동/정제·spool ACK와 Web 생성 code 격리/신뢰 driver/CUAWright·모델 broker의 실제 연결점을 함수 단위로 대조한다. AD-01을 재사용하고 AD-02~04와 미완료 W gate를 목표 배치에 매핑했다.
- [x] 실행 PC와 독립된 server DB/artifact/secret·login/project 권한/HTTPS·backup/restore를 작은 카드로 정의한다. 호스팅/키/도메인은 이를 사용하는 실환경 카드의 조건이다.
- [x] 전원 종료 중 저장본 승인과 live 동작 거부, 불명 dispatch와 늦은 ACK, 두 worker의 동일 자원 경합을 별도 수용 카드로 만든다.
- [x] 후속마다 파일·선행·인터페이스·부정 시험·명령·환경·인계를 지정하고 새 색인 조회 규칙을 등록한다.

완료 근거는 [PC-04 인계](../../validation/tasks/PC-04.md), 소스 조사와 적용 범위는 [구현 경계](../../managed-pc/RUNTIME_BOUNDARIES.md)에 있다.

중앙 서버가 미배치인 상태에서 로컬 core 시험을 operational acceptance로 세지 않는다. 이 계획은 상용 provider 계약을 선행으로 요구하지 않는다. CF-01은 추후 필요할 때 선택 조사한다.
