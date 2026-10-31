# Web·Android AI QA 플랫폼 Implementation Plan

문서 버전: **0.2**, 2026-10-30. 추가 프롬프트의 관리 UI·회귀 묶음·앱 빌드 요구를 반영했다. [v0.1 계획](docs/history/v0.1/IMPLEMENTATION_PLAN.md)은 보관한다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **현재는 준비 문서만 작성했다. 이 문서는 구현·설치·실행·배포 지시가 아니다.** 후속 구현을 명시적으로 요청받은 뒤 실행 방식을 정한다. 아래 모든 단계는 미착수다.

**Goal:** Windows PC의 실제 웹 관리 UI에서 Web·직접 연결 Android 테스트를 작성·축적·편집·검토/승인하고 정확한 승인 버전을 회귀 묶음으로 실행·분석하는 QA 도구를 만든다.

**Architecture:** A안인 Mobile-Agent Web/Android 에이전트 adapter와 로컬 Chromium/USB Android 환경 adapter를 분리한다. 관리 API가 영구 상태·묶음 snapshot·작업 큐를 소유하고, 별도 worker/runner가 자원 session·모델·증거를 처리한다. UI 탭 수명과 실행 수명은 분리하고 PASS는 현재 증거로 집계한다.

**Tech Stack:** Python 3.11 잠정, FastAPI, Jinja2/HTMX, SQLAlchemy/Alembic, SQLite, 로컬 파일 artifact, Python worker/runner, Playwright Chromium, ADB, 호환성 검증된 모델 API. dependency 버전은 P0에서 고정한다.

**Spec:** [DESIGN.md](DESIGN.md), [UI_SPEC.md](UI_SPEC.md), upstream 근거는 [RESEARCH.md](RESEARCH.md). 계획에 쓰는 모듈·함수는 모두 **신규 플랫폼의 제안 인터페이스**이며 upstream API가 아니다.

## Global Constraints

- Web·Android 둘 다 MVP이며 한 플랫폼 성공만으로 완료하지 않는다.
- UI의 목록/검색·작성/편집/복제·앱 빌드·실행·반려/승인·회귀 묶음·비교/내보내기가 필수다. API/CLI 성공만으로 UI MVP를 완료하지 않는다.
- 초기 브라우저/USB 실행은 로컬이며 클라우드 가입은 필요 없다. 모델 API는 별개이고 원격/클라우드 구현은 후속이다.
- 실행 중 탭을 닫아도 PC API/worker가 살아 있으면 계속한다. PC 종료/절전 중 지속 실행이나 복귀 후 자동 중간 재개는 보장하지 않는다.
- MobileAgent upstream SHA `81fa28b564ef7a695521500bc15a0e1324b2b394`를 시작 기준으로 고정한다.
- 최대 run 시간 600초, actions 50, model calls 80, action retry 1, model retry 2, 초기 제안 예산 USD 2.00.
- heartbeat 10초, server lease TTL 45초, worker 갱신 실패 watchdog 30초, 행동 전 lease 여유 10초 이상.
- API/UI는 127.0.0.1, DB·artifact는 동기화되지 않는 `%LOCALAPPDATA%/AIQA/` 아래; repo/OneDrive DB 금지.
- 실행은 API request/메모리 background task가 아닌 worker/runner에서 수행한다.
- 승인 content/terminal 결과는 불변이며 변경 시 새 revision/run을 만든다.
- 현재 증거의 필수 assertion/path 검증 없이 PASS 금지. usage 미제공은 null.
- 무모델 replay/Skill Factory·중앙형·영상·API/DB oracle은 P1 후속이며 MVP에 몰래 추가하지 않는다.
- target scope·secret ref·policy gate를 거치지 않는 raw shell/모델 생성 코드는 허용하지 않는다.

## Review Focus

아래 다섯 조건은 demo 정상 흐름으로 드러나지 않으므로 소유 task에 부정 시험을 넣었다.

1. 한국어·공백·따옴표가 있는 경로/입력: 이미지 URI와 ADB 입력이 깨지거나 shell 명령으로 해석되지 않아야 한다(T0, T6).
2. 모델 응답 도착과 취소/lease 만료의 race: 이미 받은 행동도 다시 권한을 검사해 실행하지 않아야 한다(T3, T5, T8).
3. 오래된 worker의 finish와 같은 seq의 다른 payload: 확정 결과를 덮거나 증거를 섞지 않아야 한다(T3–T4, T8).
4. 경로 위반·잘못된 값 뒤 AI 자동 복구: 성공한 화면이 원래 위반을 지우지 않아야 한다(T5, T7, T9).
5. usage 미제공·disk full·secret 화면: 0 비용/빈 증거로 PASS하지 않고 null·차단·정리 상태를 보여야 한다(T4–T6, T8).

## 1. 단계·의존관계·중단 기준

| 단계 | 작업 | 선행 | 관찰 가능한 완료 기준 |
|---|---|---|---|
| P0 기술 검증 | T0–T1 | 후속 구현 요청, 합성 대상·모델 접근권 | 두 엔진 경로의 실제 호출/행동/캡처/좌표·한글·종료 가능성, SHA/lock/patch/비용 계측 근거 |
| P1 영구 기반·관리 UI | T2, T2A | P0 gate | project/env/test CRUD·검색/복제·버전/설정 UI와 영구 기록·권한·오류/복원 |
| P2 작업/증거 | T3–T4 | T2 | fake runner로 queue/lease/cancel/event/artifact 멱등성·null usage 입증 |
| P3 최소 수직 기능 | T5 | T0–T4, T2A | 웹 UI 작성→시범→현재 검증→전후 화면·결과 조회, 잘못된 값은 FAIL |
| P4 Web·Android 통합 | T6, T6A | T5, Android P0 gate | Android도 동일 UI/API/판정, 설치 앱·APK/명시 설치·USB/IME/session 정리 |
| P5 승인 회귀 운영 | T7, T7A | T5–T6A | 반려·새 버전·재승인·묶음 고정/순차·child/전체 결과·비교/export |
| P6 장애/품질 gate | T8–T9 | T7A | UI 양 플랫폼 §13 동선·묶음/fault matrix, 거짓 PASS0·탭/PC 수명·복원 |
| P7 후속 확장 | T10(선택) | P6, 별도 요청 | 중앙형 또는 생성 code replay를 새 ADR과 gate로 검토 |

P0가 실패하면 설치 범위를 계속 늘리지 않는다. 각 플랫폼 경로에 engineer 2일 이내의 제한된 spike를 제안하고, 그 안에 해결 방향·필요 patch·미확인 항목을 보고한다. 이는 일정 보장이 아니라 탐색 한도다. Web이 막히면 CUAWright local_launch + 격리 VM 비용을 포함해 A/B 결정을 다시 검토한다. Android를 먼저 성공시켜도 최종 범위를 Android 전용으로 축소하지 않는다.

## 2. 제안 파일 구조

다음은 **향후 생성할 제품 파일**이다. 이번 산출물은 루트 설계 문서 네 개와 v0.1 문서 보관본뿐이다. upstream 파일을 복사/실행하거나 제품 파일을 생성하지 않았다.

```text
src/aiqa/
  contracts.py                 # ID, spec, event, check, usage 공통 DTO
  config.py                    # 비밀 참조·환경 설정, runtime root
  api/app.py                   # API/HTML 부팅과 인증 연결
  api/auth.py                  # session/CSRF, worker enrollment/token
  api/runs.py                  # run 요청/취소/조회와 worker routes
  api/tests.py                 # version/structure/approval routes
  api/artifacts.py             # manifest/upload/content 권한
  api/catalog.py               # project/env/test CRUD·검색·settings
  api/app_builds.py            # APK 등록·검사·명시 설치 job
  api/suites.py                # suite version·suite run·취소
  api/results.py               # 비교·export
  domain/versions.py           # immutable manifest·승인·revocation
  domain/verdicts.py           # check/path 집계와 violation latch
  domain/policy.py             # 대상·도구·단계·예산 권한 검사
  domain/suites.py             # immutable 묶음·snapshot·순차·집계
  store/db.py                  # engine·transaction, local SQLite
  store/models.py              # 관계/unique constraints
  store/queue.py               # claim/lease/terminal 상태 전이
  store/evidence.py            # event/hash/check ingest
  store/artifacts.py           # staging/ready·hash·retention
  models/client.py             # 역할별 호출·usage·예약 예산
  models/compatibility.py      # protocol/image/action 검증 기록
  worker/service.py            # inventory·poll·heartbeat·spool·watchdog
  worker/runner.py             # 1 attempt의 실행과 IPC
  worker/processes.py          # Windows Job Object·정지/정리
  worker/resources.py          # 기기/slot 소유·IME·quarantine
  environments/base.py        # inspect/acquire/prepare/release
  environments/local_chromium.py
  environments/usb_android.py
  environments/app_builds.py  # trusted APK metadata·설치/초기화 policy
  launcher.py                  # API/worker 지속 프로세스 시작·정상 종료 안내
  adapters/base.py             # DESIGN §8.1 계약
  adapters/mobile_agent_web.py # pinned Web 경로 연동
  adapters/mobile_agent_android.py
  validation/web.py            # 승인 locator 기반 oracle
  validation/android.py        # 승인 관찰/visual oracle
  validation/visual.py         # 근거·unknown 처리
  web/templates/              # UI_SPEC 12개 영역, 필수5개 wireframe 구현
  web/static/                 # 고정 HTMX·작은 polling JS/CSS
migrations/                   # 데이터 schema revision
patches/mobile-agent/         # 적용 대상 SHA·작은 patch와 출처/라이선스
tests/unit/                   # 정책/집계/계약
tests/integration/            # queue·spool·ingest·API
tests/acceptance/             # 실제 Web·Android·장애 gate
docs/validation/              # 측정 원자료 인덱스·판정·패치 보고
```

## P0 — 기술 검증

### T0: pinned upstream의 실행 가능성과 프로토콜 gate

**Files (향후):** `docs/validation/upstream-spike.md`, `patches/mobile-agent/README.md`, `tests/integration/test_upstream_contracts.py`, `src/aiqa/models/compatibility.py`, dependency lock.

**Interfaces:** consumes RESEARCH의 고정 SHA/불일치 목록. Produces `check_binding(binding: ModelBinding, fixture: CompatibilityFixture) -> CompatibilityReport`와 engine/patch/lock hash manifest. `ModelBinding/CompatibilityFixture/CompatibilityReport`는 이 task에서 정의하고 T2 `contracts.py`로 승격한다.

- [ ] 합성 screenshot/response fixture로 image URI·JSON action 형식·지원 action·좌표 범위를 확인하는 실패 시험을 작성한다. `test_file_uri_and_korean_path`, `test_unknown_action_rejected`, `test_web_provider_normalized`, `test_go_back_mapping`, `test_usage_absent_is_null`을 명시한다.
- [ ] 향후 `pytest tests/integration/test_upstream_contracts.py -q`를 실행해 예상 실패를 기록한다. 실제 모델 없이 fixture 단계부터 시작한다.
- [ ] 승인 후 read-only 검토한 source를 별도 실행 환경에 준비하고 필요한 dependency만 설치·lock한다. root 라이선스와 사용한 하위 파일 출처를 기록한다. API key를 argv/config artifact에 넣지 않는다.
- [ ] Mobile-Agent Web의 provider/endpoint/action enum·unknown success 문제, Android file URI·resize/좌표/ADB 반환값·instruction 디렉터리를 작은 patch로 해결한다. 원본과 patch hash를 기록하고 전체 프레임워크를 새로 쓰지 않는다.
- [ ] 승인한 모델 endpoint로 이미지/응답 형식 최소 호출을 시험한다. 실제 role별 model ID, endpoint 종류, image 전달, usage 유무, timeout, 호출 비용을 기록한다. arbitrary OpenAI compatible 모델을 자동 허용하지 않는다.
- [ ] 위 시험 재실행과 Web/Android 각 1회 실제 캡처→행동→후 관찰 결과를 기록한다. 이 1회 성공을 회귀 안정성 증거로 사용하지 않는다. 두 경로가 안 되면 ADR D01을 다시 결정한다.
- [ ] 검증 기록과 patch만 검토 후 commit한다. 이후 task는 이 manifest를 입력으로 사용한다.

**Gate:** fixture 통과, 두 플랫폼 실제 제어 근거, 모델 정책/라이선스·lock 이슈 목록, 남은 patch 범위가 명확할 것. 미해결이면 P1에서 UI만 확장하지 않는다.

### T1: Windows·ADB·Chromium 환경/정리 실험

**Files (향후):** `docs/validation/environment-matrix.md`, `tests/integration/test_environment_preflight.py`, `src/aiqa/worker/resources.py`, `src/aiqa/worker/processes.py`, `environments/base.py`, `environments/local_chromium.py`, `environments/usb_android.py`.

**Interfaces:** `probe_resource(resource_ref: ResourceRef) -> ResourceInventory`, `terminate_tree(attempt_id: UUID, grace_seconds: int=5) -> StopAcknowledgement`, `restore_resource(snapshot: ResourceSnapshot) -> CleanupReport`. DTO는 T2 공통 계약으로 옮긴다.

- [ ] offline/unauthorized/locked/secure capture/rotation mismatch, 브라우저 시작 실패에 대한 preflight 차단 시험을 작성·실행해 실패를 확인한다.
- [ ] Android 원본 화면→모델 resize→normalized→실제 touch transform을 중앙·모서리 fixture와 실기기로 대조한다. 한글·공백·따옴표·줄바꿈 입력을 확인하며 OS shell로 해석되면 gate 실패다.
- [ ] Chromium headless 새 context·viewport/DPR·locale/timezone 격리와 종료 후 자식 process 잔존 여부를 확인한다. 앱/IME snapshot·복구 실패는 quarantine으로 만든다.
- [ ] 관리 UI 브라우저와 테스트 브라우저가 별도 process/context임을 확인한다. Windows native를 기준으로 하고 WSL/컨테이너가 필요하면 USB 전달·ADB 경계·화면 접근·경로/종료를 별도 검증한다. APK 검사에 필요한 SDK 도구와 ADB의 사전 조건을 구분한다.
- [ ] `pytest tests/integration/test_environment_preflight.py -q` 결과와 수동 장치 확인을 문서화한다. PC/OS·ADB·device/app/browser version과 승인할 환경 범위를 고정한다.
- [ ] 프로세스 tree 종료/자원 probe 도구와 측정 기록을 검토 후 commit한다.

## P1 — 영구 계약과 권한

### T2: 데이터·불변 버전·로컬 API 기반

**Files:** `contracts.py`, `config.py`, `store/db.py`, `store/models.py`, `domain/versions.py`, `api/app.py`, `api/auth.py`, `api/tests.py`, `migrations/`; `tests/unit/test_versions.py`, `tests/integration/test_local_auth.py`, `tests/integration/test_persistence.py`.

**Interfaces:** `create_revision(test_id: UUID, definition: TestDefinition, actor: Actor) -> VersionManifest`; `approve_version(version_id: UUID, digest: str, basis_run_ids: list[UUID], actor: Actor) -> Approval`; `create_app(settings: Settings) -> FastAPI`. `contracts.py`이 ExecutionSpec, EventEnvelope, CheckSpec/Result, Observation, CapabilitySet, RunControl DTO, ModelRequest/Response와 T0/T1 DTO의 단일 소유자다.

- [ ] 불변 revision UPDATE 거부, 모호한 기대 결과 `needs_review`, 필수 검사 0개 거부, hash mismatch 승인 거부, 재시작 후 보존 시험을 먼저 작성하고 실패를 확인한다.
- [ ] DESIGN §8.2 관계·unique constraint·migration을 구현한다. raw_text와 구조화 계획을 함께 저장하고 environment/run snapshot을 나눈다.
- [ ] API/HTML은 loopback 인증 session·CSRF·Origin을 적용한다. worker enrollment는 single-use 10분, bearer token hash 저장. secret value는 OS store에 두고 reference만 계약에 남긴다.
- [ ] 구조화 작업은 기존 draft revision을 source로 하는 `purpose=structure` job으로 등록한다. 모델은 제안 revision만 반환하고 기기 권한은 부여하지 않는다.
- [ ] `pytest tests/unit/test_versions.py tests/integration/test_local_auth.py tests/integration/test_persistence.py -q`를 실행한다. version hash 변경/secret 로그 노출/DB 재시작 손실이 없음을 확인하고 commit한다.

**Gate:** 생성·조회·revision·승인 전 검증과 로컬 접근 통제 완료. 아직 실제 실행 UI가 없어도 독립 검증 가능하다.

### T2A: 관리 UI 자산·편집·검색·설정 기반

**Files:** `api/catalog.py`, `api/tests.py`, `api/auth.py`, `web/templates/{projects,environments,connections,tests,test_edit,settings}.html`, `web/static/editor.js`, `launcher.py`; `tests/integration/test_catalog_api.py`, `tests/acceptance/test_management_ui.py`.

**Interfaces:** `list_tests(project_id: UUID, query: TestListQuery) -> CursorPage[TestSummary]`; `clone_test(test_id: UUID, actor: Actor) -> TestSummary`; `archive_asset(kind: AssetKind, asset_id: UUID, actor: Actor) -> ArchiveReceipt`; `save_draft(test_id: UUID, definition: TestDefinition, expected_revision: int, actor: Actor) -> VersionManifest`. DTO는 T2 contracts.py에 정의하고 version 저장은 T2 create_revision을 사용한다.

- [ ] UI-01/02/04/05/12의 빈 상태·입력 오류·403·연결 단절·미저장·409를 먼저 시험한다. 검색/필터/정렬/cursor, 새 test·복제 시 승인 미복제, 참조 자산 삭제 금지/보관을 실패 시험으로 작성한다.
- [ ] DESIGN §8.3 CRUD/list/error 계약과 UI_SPEC 버튼을 HTML+HTMX에 연결한다. 이름·태그·우선순위·원문·step/check/path 편집/추가/삭제/순서를 저장하고 새 revision/hash·변경 diff를 보여준다. 실행/승인 snapshot은 읽기 전용이다.
- [ ] 구조화/모델 연결 확인은 T3/T4 queue가 준비될 때 연결하는 관리 job이며 버튼만 눌러 성공한 것처럼 표시하지 않는다. secret 등록은 write-only로 구현하고 값 반환/브라우저 저장을 금지한다.
- [ ] 로컬 시작 도구의 API/worker 지속 프로세스와 상태 URL·정상 종료 안내를 구현한다. 브라우저를 닫는 동작이 worker 종료로 이어지지 않도록 부모 관계를 분리한다. P2 연결 전에는 엔진 작업 미준비 상태를 정확히 표시한다.
- [ ] `pytest tests/integration/test_catalog_api.py tests/acceptance/test_management_ui.py -q`로 실제 브라우저 UI에서 생성·검색·복제·단계 편집·revision 저장·보관·새로고침 복원을 확인하고 검토 후 commit한다.

**Gate:** 일상 자산 관리가 터미널 없이 UI/API/DB로 연결된다. 실행 기능 완료와는 구분하며 실제 Web 실행은 T5에서 연결한다.

## P2 — queue·lease·증거

### T3: 작업 배정·worker·취소·fencing

**Files:** `store/queue.py`, `api/runs.py`, `worker/service.py`, `worker/runner.py`, T1 process/resource 연결; `tests/integration/test_queue_leases.py`, `tests/integration/test_cancellation.py`.

**Interfaces:** `enqueue_run(request: RunRequest, key: str, actor: Actor) -> RunReceipt`; `claim_job(worker_id: UUID, capability: CapabilitySet) -> ExecutionSpec | None`; `renew_lease(attempt_id: UUID, generation: int) -> Lease`; `request_cancel(run_id: UUID, actor: Actor) -> RunSnapshot`; `finalize_attempt(report: AttemptReport) -> FinishReceipt`.

- [ ] 같은 idempotency key/본문은 같은 run, 다른 본문 409, 한 resource에 동시 claim 1개, 중복 ack에 runner 1개, terminal 전이 거부 시험을 먼저 작성하고 실패를 확인한다.
- [ ] DB transaction과 generation으로 DESIGN §6 상태를 구현한다. fake runner부터 연결하고 heartbeat 10/TTL45/watchdog30/행동여유10초를 fake clock으로 시험한다.
- [ ] T2A 시작 도구에 실제 worker service를 연결하고 구조화/진단/모델 확인/앱 검사·설치/export 목적별 허용 payload·물리 lease·verdict=null을 구현한다. 모델 key·기기 권한을 목적 외 작업에 주지 않는다.
- [ ] queued/preparing/running 취소, finalizing 취소 409, 완료/취소 race, 모델 응답 뒤 cancel 재확인 시험을 구현한다. 정지 grace 5초 후 Job Object 종료, cleanup 30초 내 ready 또는 quarantine을 기록한다.
- [ ] API 재시작/worker 사망/lease 만료 뒤 늦은 finish·새 claim을 시험한다. lease 만료 자원은 자동 재배정하지 않고 recover 근거를 요구한다.
- [ ] `pytest tests/integration/test_queue_leases.py tests/integration/test_cancellation.py -q`를 실행한다. fake clock 결과와 실제 Windows process 종료 근거를 검토 후 commit한다.

### T4: 영구 event·artifact·모델 계측/예산

**Files:** `store/evidence.py`, `store/artifacts.py`, `api/artifacts.py`, `models/client.py`, worker spool; `tests/integration/test_evidence_ingest.py`, `tests/unit/test_usage_budget.py`, `tests/integration/test_artifacts.py`.

**Interfaces:** `append_events(attempt_id: UUID, generation: int, batch: list[EventEnvelope]) -> IngestReceipt`; `stage_artifact(metadata: ArtifactManifest) -> ArtifactReceipt`; `commit_artifact(artifact_id: UUID, content: BinaryStream) -> ArtifactReceipt`; `ModelClient.invoke(request: ModelRequest, control: RunControl) -> ModelResponse`; `reserve_cost(call: PlannedCall, budget: BudgetState) -> Reservation`.

- [ ] 같은 seq/같은 hash 재전송 수락, 같은 seq/다른 hash 409, 전송 중 artifact 비공개, hash 불일치 거부, null usage 보존의 실패 시험을 작성한다.
- [ ] API DB commit receipt와 worker local spool 재전송을 구현한다. run cursor의 server global ID와 중복 검사의 attempt/local_seq를 분리한다.
- [ ] artifact staging→ready/expired, run 500MB/전체 20GB 한도, 필수 증거 누락 시 PASS 금지, finish가 final_seq까지 기다리는 계약을 구현한다.
- [ ] 모든 역할·retry를 공통 model client에 연결하고 usage 유무·원본 request ID·tariff 버전·통화·예약/정산을 저장한다. strict 예산의 예약 불가를 preflight에서 알면 BLOCKED, 실행 중 발생하면 새 호출을 중단하고 INCONCLUSIVE로 처리한다. 이미 유효한 필수 violation이 있으면 FAIL을 우선한다.
- [ ] `pytest tests/integration/test_evidence_ingest.py tests/unit/test_usage_budget.py tests/integration/test_artifacts.py -q`를 실행한다. API 전송 끊김/응답 유실·usage 누락·disk full에서도 중복 행동/0 사용량 오인이 없음을 확인 후 commit한다.

**Gate:** 두 task 모두 실제 엔진 없이도 재시작·중복·취소·증거/사용량 계약을 검증할 수 있어야 한다.

## P3 — 최소 Web 수직 기능

### T5: Web adapter·QA validator·작성/실행 화면

**Files:** `adapters/base.py`, `adapters/mobile_agent_web.py`, `validation/web.py`, `validation/visual.py`, `domain/policy.py`, `domain/verdicts.py`, `web/templates/{tests,run}.html`, `web/static/run-poll.js`; `tests/unit/test_verdicts.py`, `tests/integration/test_web_adapter.py`, `tests/acceptance/test_web_vertical.py`.

**Interfaces:** DESIGN §8.1의 agent와 EnvironmentAdapter 계약을 구현/연결한다. `PolicyGate.authorize(proposal: ActionProposal, context: StepContext) -> ActionDecision`; `Validator.evaluate(check: CheckSpec, observation: Observation) -> CheckResult`; `aggregate_verdict(checks: list[CheckResult], path: PathResult, termination: Termination, evidence: EvidenceCompleteness) -> Verdict`.

- [ ] agent done/click 성공만으로 PASS 금지, wrong value/필수 버튼 부재 FAIL, 증거 불충분 unknown, path violation latch·자동 복구 후에도 FAIL 시험을 먼저 작성·실행한다.
- [ ] 고정 승인 step 하나씩 관찰→모델 proposal→policy→행동→후 관찰→검증을 실행하도록 P0 patch를 adapter에 연결한다. 모델은 승인 step/expected를 수정하지 못한다.
- [ ] 공유 storage state 제거·새 context·DPR1·viewport1280×720·ko-KR/Asia-Seoul, 허용 URL·redirect·DOM data 취급, 10초 상태 대기/30초 navigation을 구현한다. upload/download/multi-tab은 명시 미지원으로 preflight 차단한다.
- [ ] Web text/value oracle과 visual evidence/unknown을 연결한다. 각 행동의 전후 PNG/대상·좌표/결과를 event에 남기며 raw reasoning은 저장하지 않는다. upstream 직접 파일 쓰기를 교체하고 메모리 캡처→민감 selector/문자열 마스킹→보관/모델 전송 순서를 시험한다.
- [ ] 서버 HTML+HTMX로 원문/계획 diff·trial 시작·status/판정 분리·전후 화면·취소·2초 cursor polling을 제공한다. 새로고침 시 DB에서 복원한다.
- [ ] `pytest tests/unit/test_verdicts.py tests/integration/test_web_adapter.py -q` 후 승인된 staging에서 `pytest tests/acceptance/test_web_vertical.py -q`를 실행한다. 정상·불일치·요소 부재·timeout을 사람 oracle과 대조하고 commit한다.

**Gate:** 작성→trial→증거→실패 판정까지 한 Web 흐름이 실제 동작. 이 단계는 MVP 전체 완료가 아니다.

## P4 — Android와 Web 공통 운영

### T6: Android adapter·기기 정책·공통 타임라인

**Files:** `adapters/mobile_agent_android.py`, `validation/android.py`, resource/worker 연결, `web/templates/{workers,environments}.html`; `tests/integration/test_android_adapter.py`, `tests/acceptance/test_android_vertical.py`.

**Interfaces:** T5와 동일 adapter 계약을 구현하되 `CapabilitySet`에서 Web과 Android 차이를 보존한다. `transform_touch(point: NormalizedPoint, geometry: ScreenGeometry) -> PixelPoint`; `probe_resource/restore_resource`는 T1 계약을 사용한다.

T5/T6 공통 추가 계약은 DESIGN §8.1의 `EnvironmentAdapter.inspect/acquire/prepare/release`다. agent adapter가 직접 새 자원을 생성하지 않고 LocalChromium/UsbAndroid 환경 handle을 받는다. session ID/lifecycle은 attempt에 영구 기록하고 acquire/release/retry 중복을 시험한다.

- [ ] 모델/원본 크기 불일치·회전·범위 밖 좌표 거부, 한글 입력·shell metacharacters, unauthorized/offline/locked/capture 불가를 먼저 시험한다.
- [ ] 승인 package/activity로만 시작하고 raw shell 대신 검증된 ADB argv를 사용한다. 기기당 한 작업·이전 IME snapshot·복구·quarantine을 구현한다. 앱 reset/reinstall/logout은 승인 설정 외 거부한다.
- [ ] 실제 기기 캡처·행동·결과/현재 package와 app version을 공통 event/manifest에 넣는다. 민감 화면 영역을 저장/전송 전에 마스킹하고 안전하게 정제할 수 없는 화면은 중단한다. Android에서 visual로 추출한 값은 결정적 검사로 표시하지 않는다.
- [ ] HUMAN_REQUIRED/OTP/CAPTCHA는 자동 우회 없이 BLOCKED, 복구 뒤 새 run 시작으로 처리한다. secure capture는 preflight에서 확인되면 BLOCKED, 실행 중 필수 캡처가 사라지면 unknown/INCONCLUSIVE로 처리한다. 이미 유효한 필수 violation이 있으면 FAIL을 우선한다. 한계와 사용자가 할 일을 UI에 표시한다.
- [ ] Web과 동일 작성/실행/증거 화면에서 기기 선택·inventory·점유·허용 기능을 제공한다. 전체 worker slot1과 USB lease를 함께 적용한다.
- [ ] `pytest tests/integration/test_android_adapter.py -q` 후 승인한 QA 앱에서 `pytest tests/acceptance/test_android_vertical.py -q`를 실행한다. 한글/좌표·잘못된 값·연결 해제·IME 복구를 관찰하고 commit한다.

**Gate:** Android에도 Web과 같은 실제 수직 흐름과 부정 판정 근거가 있어야 한다. fake device 시험만으로 완료하지 않는다.

### T6A: 설치 앱 선택·APK 빌드·명시 설치 UI

**Files:** `api/app_builds.py`, `environments/app_builds.py`, `environments/usb_android.py`, `web/templates/app_builds.html`; `tests/integration/test_app_builds.py`, `tests/acceptance/test_app_build_ui.py`.

**Interfaces:** `register_build(project_id: UUID, artifact: ArtifactReceipt, actor: Actor) -> AppBuild`; `inspect_apk(build_id: UUID) -> BuildInspection`; `request_install(build_id: UUID, resource_id: UUID, policy: SetupPolicy, key: str, actor: Actor) -> RunReceipt`; `prepare_app(session: SessionHandle, build: AppBuild | None, policy: SetupPolicy) -> AppPreparationResult`. artifact 저장은 T4 계약을 재사용한다.

- [ ] 업로드 없이 installed package 선택, 잘못된 확장자/hash/용량/ZIP 경로, metadata unknown·minSdk/ABI 불일치, duplicate install key·busy device, 서명/다운그레이드 실패 후 자동 uninstall 금지를 시험한다.
- [ ] UI-03→제한 업로드→hash 검증→app_inspect→ready/rejected/unknown을 연결한다. 신뢰한 SDK 도구로 metadata만 읽고 APK 앱 코드를 관리 API에서 실행하지 않는다. 단일 APK만 지원한다.
- [ ] app_install 관리 job과 테스트 preparing의 명시 install_if_needed가 같은 trusted helper/lease를 쓰게 한다. 기본 use_installed는 재설치하지 않는다. clear_data/reinstall/uninstall은 승인 설정·사용자 영향 확인 때만 적용한다.
- [ ] install 중 취소/USB 단절은 상태 재확인, cleanup/IME 복구, 참조 build pin·보관을 구현한다. package/version만 맞는 외부 설치 앱의 hash는 unknown으로 표시한다.
- [ ] `pytest tests/integration/test_app_builds.py tests/acceptance/test_app_build_ui.py -q`를 실행한다. 합성 QA APK를 UI로 등록·설치·첫 trial 후 두 번째 run에서 업로드/재설치가 없음을 확인하고 commit한다.

## P5 — 승인·회귀·결과 비교

### T7: manifest 승인과 두 플랫폼 회귀

**Files:** `domain/versions.py`, `api/tests.py`, `api/runs.py`, `web/templates/{review,regression,compare}.html`; `tests/integration/test_approved_regression.py`, `tests/unit/test_change_classification.py`.

**Interfaces:** T2 `approve_version`에 근거 run/hash 및 revocation을 연결한다. `classify_change(old: VersionManifest, new: VersionManifest) -> ApprovalRequirement`; `compare_runs(run_ids: list[UUID], actor: Actor) -> ComparisonReport`.

- [ ] 미승인 regression 거부, 승인 hash만 실행, 수정 시 새 revision, 과거 PASS 재사용 금지, revoke 후 실행 거부의 실패 시험을 작성한다. 승인 근거는 해당 버전 플랫폼의 completed/PASS trial만 허용하고 BLOCKED/INCONCLUSIVE/FAIL을 거부한다.
- [ ] 정의/step/check/prompt/model/engine/patch/lock/중요 설정 변경은 재승인 대상으로 하고, 승인 데이터 schema 내 값과 secret rotation은 run snapshot에 기록한다. 계정 권한 변경은 재승인한다.
- [ ] 같은 manifest의 trial 근거·actor/time/diff/comment를 보존하고 승인 내용을 UI에 표시한다. 결과 수정으로 과거 FAIL을 PASS로 만드는 기능은 제공하지 않는다.
- [ ] UI-09의 reason 필수 반려와 rejected 상태·검토 이력을 구현한다. 반려/승인본에서 새 draft→diff→trial→재승인 동선을 연결하고, 기존 approved version은 단순 rejection으로 바꾸지 않는다.
- [ ] Web/Android 각각의 승인 version을 고정해 새 run·증거·검증을 실행하고, 첫 attempt/안전한 retry·recovery·model/target version·시간/비용을 비교한다.
- [ ] `pytest tests/integration/test_approved_regression.py tests/unit/test_change_classification.py -q`를 실행하고 양 플랫폼 실기록을 검토 후 commit한다.

**Gate:** 사용자가 시범 경로·정의·검증을 검토해 특정 버전을 승인하고, 이후 실행에서도 새 검증 결과를 볼 수 있어야 한다.

### T7A: 회귀 묶음·순차 실행·집계·결과 내보내기

**Files:** `domain/suites.py`, `api/suites.py`, `api/results.py`, `store/queue.py`, `web/templates/{suites,suite_run,results,compare}.html`; `tests/integration/test_suite_runs.py`, `tests/acceptance/test_regression_suite_ui.py`.

**Interfaces:** `create_suite_revision(suite_id: UUID, members: list[SuiteMember], defaults: SuiteDefaults, expected_revision: int, actor: Actor) -> SuiteVersion`; `enqueue_suite(request: SuiteRunRequest, key: str, actor: Actor) -> SuiteRunReceipt`; `aggregate_suite(children: list[RunSnapshot]) -> SuiteSummary`; `cancel_suite(suite_run_id: UUID, actor: Actor) -> SuiteSummary`; `request_export(project_id: UUID, selection: ResultSelection, actor: Actor) -> RunReceipt`.

- [ ] 미승인/보관/취소된 version 구성 거부, 0개/101개 거부, exact hash 고정, 입력 override 범위 초과, 중복 submit child1개/entry, API 재시작 후 child 중복 없음의 실패 시험을 작성한다.
- [ ] UI-10 추가/제거/순서·환경/data·기본 continue/stop_on_non_pass·버전 명시 교체를 immutable suite revision으로 저장한다. 실행 transaction에서 resolved snapshot과 모든 child run을 만들고 이전 child terminal·정리 확인 후만 다음 항목을 claim한다.
- [ ] 순차 mixed Web/Android, FAIL/BLOCKED/INCONCLUSIVE/미실행·취소 count, 전체 판정 우선순위, quarantine 다음 항목 차단, parent cancel 중 finalizing child race를 시험한다. terminal parent는 늦은 결과로 바꾸지 않는다.
- [ ] 실패 항목/전체 재실행은 새 run 또는 suite_run과 provenance를 생성한다. 기존 실패는 보존하고 새 revision 자동 latest 추종을 금지한다.
- [ ] UI-11 비교·마스킹 JSON/CSV export를 연결하고 null usage·증거 만료·권한·CSV 수식 안전화를 유지한다. export는 QA verdict 없는 관리 job이다.
- [ ] `pytest tests/integration/test_suite_runs.py tests/acceptance/test_regression_suite_ui.py -q`를 실행한다. UI에서 승인 버전 묶음 저장→실행→child 증거→실패 항목 새 실행→비교/export→재접속 복원까지 확인하고 commit한다.

**Gate:** 단일 테스트 반복만이 아니라 실제 UI의 회귀 묶음 운영을 제공한다. 과거 parent 결과를 새 child 성공으로 덮지 않는다.

## P6 — 운영 내구성·출시 검증

### T8: 장애 주입·보관·권한/정보 보호

**Files:** worker/store/API 보강, `tests/integration/test_fault_matrix.py`, `tests/integration/test_retention_restore.py`, `tests/integration/test_scope_secrets.py`, `docs/validation/fault-report.md`.

**Interfaces:** `recover_resource(resource_id: UUID, proof: RecoveryProof, actor: Actor) -> ResourceSnapshot`; `expire_artifacts(now: datetime) -> RetentionReport`; `restore_backup(manifest: BackupManifest) -> RestoreReport`.

- [ ] 모델 응답 후 cancel/expired generation, worker 종료·API 재시작·네트워크 단절, 늦은 finish·중복 event·외부 거래 직후 응답 유실을 실패 시험으로 작성한다. 같은 거래를 자동 반복하지 않음을 검증한다.
- [ ] 관리 탭 종료와 PC 절전/강제 종료를 별도 시험한다. 탭 종료 후 같은 run이 계속되고 재접속 복원되는지, PC 복귀 시 이전 journal/lease·session을 조정해 lost·정리/quarantine으로 안내하고 자동 중간 재개하지 않는지 확인한다. suite cancel·API 재시작·install 단절도 fault matrix에 포함한다.
- [ ] fault별 DESIGN §6 상태/판정·cleanup/quarantine을 구현하고 필요한 경우 재관찰/수동 검토로 종료한다. lease 만료를 기기 종료 증명으로 쓰지 않는다. 서버에 필수 violation이 확정된 run은 lost여도 FAIL을 유지하고, 없으면 INCONCLUSIVE인지 시험한다.
- [ ] screenshot/로그/HTML/모델 payload에서 secret 및 hidden reasoning 유출, malicious page 지시·범위 밖 URL/app·관리 API 접근을 시험한다. 저장·전송 전 관찰 필터, 비마스킹 원본 디스크 미기록, 민감 영역과 필수 oracle 충돌의 사전 BLOCKED/실행 중 unknown→INCONCLUSIVE를 시험한다. 개인 인증·CSRF·worker scope/revoke도 검증한다.
- [ ] 90일 metadata/30일 screenshot/7일 spool/24시간 debug·승인 증거 pin·20GB/500MB cap·tombstone/410·백업 복원 일관성을 fake clock과 제한 디스크 fixture로 시험한다.
- [ ] `pytest tests/integration/test_fault_matrix.py tests/integration/test_retention_restore.py tests/integration/test_scope_secrets.py -q`를 실행하고 실제 Windows 취소·USB·worker 종료를 각 해당 상황 최소 3회 확인한 뒤 commit한다.

### T9: 양 플랫폼 acceptance·측정·문서 handoff

**Files:** `tests/acceptance/test_mvp_matrix.py`, `docs/validation/mvp-results.md`, `docs/validation/known-limitations.md`, 사용자 운영 안내.

**Interfaces:** `AcceptanceReport`는 raw run ID/manifest·ground truth·false pass/fail·unknown/blocked·first/retry/recovery·비용 계측 상태·시간/점유/증거 bytes를 포함한다. pass gate는 DESIGN §13과 동일하다.

- [ ] Web/Android 정상 각20회, 값 불일치/요소 부재/timeout 각5회, UI 위치/문구 변경 각5회와 지정 버튼 제거 시험 matrix를 작성한다. 사람 oracle·reset·데이터 ID·실행 seed/환경을 사전에 고정한다.
- [ ] UI_SPEC의 첫 설정/테스트 구축/회귀 운영/변경/장애 5개 동선을 **브라우저 UI에서** 검증한다. 검색·편집·복제·보관·단계 순서·반려/재승인·버전 비교·APK/설치·mixed 묶음 continue/stop·실패 항목 새 실행·export를 포함한다. API/CLI 성공만으로 이 gate를 통과시키지 않는다.
- [ ] DESIGN §13의 묶음 정책·관리 탭 닫기/재접속·PC 절전/종료 시험을 각 조합 최소 3회 수행한다. screenshot fit/100%/zoom이 기기 해상도에 관계없이 읽히고 만료·마스킹·연결 단절·미저장 상태가 정확한지 확인한다.
- [ ] `pytest tests/acceptance/test_mvp_matrix.py -q`를 승인한 환경에서 실행하고 run ID·원자료·사람 라벨을 기록한다. 정상 first PASS≥18/20, retry 포함≥19/20, 부정 case false PASS0을 각각 확인한다. 불충족이면 원인을 분류하고 gate를 낮추지 않는다.
- [ ] API/UI 재연결·버전 고정·정리·budget/usage null·동일 기기 중복 소유0·secret 노출0·terminal 덮어쓰기0을 T8 기록과 대조한다.
- [ ] 전체 필수 검증에 근거가 있는지, 파일/라이선스·키/비밀값·미지원 capability·운영 저장 경로·복구 절차가 문서화됐는지 확인한다.
- [ ] 실행별 p50/p95·호출/측정/추정 비용·storage 추이를 보고한다. 작은 표본 결과를 일반 성공률로 광고하지 않는다. 계획/설계를 실제 구현과 맞춰 갱신하고 검토 후 commit한다.

**최종 gate:** 실제 웹 UI의 양 플랫폼 작성/편집·반려/승인·회귀 묶음·분석, 신뢰할 수 있는 부정 판정·취소/장애·증거/비용·탭/PC 수명이 모두 입증되어야 MVP 완료다. 클라우드 공급자 실측은 후속이며 제품 설치/배포 범위는 그때의 별도 사용자 요청을 따른다.

## P7 — 별도 결정이 필요한 후속 작업

### T10: 중앙형 또는 CUAWright 코드 재생 ADR

이 task는 MVP 필수가 아니며 T9 후 요청이 있을 때만 계획을 상세화한다.

- 중앙형: PostgreSQL migration, TLS·팀 role·worker enrollment/rotation/revoke·artifact object store·다중 worker dispatch. USB 제어는 계속 로컬 worker에서 수행한다.
- 클라우드 환경: 중앙형과 별도로 remote browser/device farm adapter를 검토한다. CDP/API·headless/GUI·emulator 가속·실제 ADB 제어·session TTL/release·고아 정리·사내망/전용 연결·준비/유휴/해제 지연 비용을 실측한다. Appium 지원만으로 Mobile-Agent 호환을 주장하지 않고 ADB를 외부에 무인증 공개하지 않는다. 정의/승인 이력은 유지하되 환경 호환·trial/재승인 gate를 통과해야 한다.
- CUAWright: 조사 SHA `35dbcf389ce2d9a77eb22f539c79a1274ea53559`, package0.2.0을 시작점으로 별도 lock. local_browser/script/Skill Factory 모드를 선택하고 격리 VM·egress·코드 승인·독립 replay·모델0회 계측·현재 oracle을 먼저 검증한다.
- 코드 replay 시험은 승인 script를 직접 선택해 수행한다. `route`가 추천에 모델을 부를 수 있음을 비용에 반영하고 자동 repair가 승인 assertion을 바꾸지 못하게 한다.
- API·DB oracle, 다중 tab·file IO·rotation·영상/logcat은 capability별 독립 gate와 보관 비용을 추가한다.

## 3. 자체 검토와 현재 상태

R01–R03/R08/R14는 T2/T7, R04/R06/R07은 T5, R05는 T6, R09/R15는 T7–T8, R10–R13은 T3–T4/T8, R16은 T9, 후속 R17–R20은 T10에 연결된다. 공통 DTO는 T2 소유, T0/T1의 실험 DTO를 승격하므로 이후 task가 다른 함수 이름/상태를 발명하지 않는다. 진행 상태·verdict·lease·한도 값은 DESIGN을 단일 기준으로 삼는다.

개정 요구 추적: R21→T2A/T5, R22→T7A/T8–T9, R23→T6A, R24→T7/T7A, R25→T1/T5–T6A, R26→T2A/T3/T8–T9, R27→T9. UI_SPEC의 모든 핵심 조작은 UI_SPEC §4 추적표의 API/데이터/worker와 연결된다. T2A/T6A/T7A는 기존 task ID를 바꾸지 않고 추가한 독립 검토 단위다.

현재 산출물은 **RESEARCH.md, DESIGN.md, UI_SPEC.md, IMPLEMENTATION_PLAN.md 개정 문서와 v0.1 보관본**이다. 위 제품 파일 구조, patch, tests, 설치, 실험, 모델 호출, 실행 결과는 아직 없다. 합격 기준은 계획이며 검증된 제품 성능이 아니다.
