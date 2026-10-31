# AI QA 플랫폼 Implementation Plan v0.3

개정일: **2026-10-31**. [v0.2 계획](docs/history/v0.2/IMPLEMENTATION_PLAN.md)은 보관했다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.
>
> **준비 문서다. 모든 제품 구현·설치·시험·모델 호출·배포 단계는 미착수이며 이 문서가 실행 승인은 아니다.**

**Goal:** 웹 UI에서 TC와 자동화 케이스를 관리하고, 각 녹화 동작의 화면/로그를 승인 없이 먼저 저장한 뒤 녹화 완료 후 사람이 검토·승인하여 단일/선택/묶음 수행과 리포트로 연결한다.

**Architecture:** A안 Mobile-Agent Web/Android의 agent adapter와 로컬 Chromium/USB 환경 adapter를 유지한다. 영구 job queue는 REC/관리 작업과 정식 ITEM을 분리하고, 실행 부모 RUN과 exact TC/AUT/data/environment snapshot을 저장한다. 승인과 저장을 분리하고 원본 QA를 분석/재실행으로 덮지 않는다.

**Tech Stack:** Python 3.11 잠정, FastAPI/Jinja2/HTMX, SQLAlchemy/Alembic/SQLite, 로컬 artifact, worker/runner, Playwright Chromium/ADB, 호환성 검증할 API 모델.

**Spec:** [DESIGN.md](DESIGN.md), UI·데이터/API 규범은 [UI_SPEC.md](UI_SPEC.md), upstream은 [RESEARCH.md](RESEARCH.md). 아래 파일/함수는 신규 플랫폼 제안이며 upstream API가 아니다.

## Global Constraints

- Web·직접 연결 Android 둘 다 실제 웹 UI로 제공한다. CLI/API demo만으로 합격 불가.
- TC/AUT/REC/RUN/ITEM을 분리하고 exact version/hash·project scope를 보존한다.
- **녹화 중 승인은 없다. 미승인/중단/미완성도 저장하고 완료·보관 확정 후 저장본을 검토·승인한다.**
- 각 탭/입력/swipe/back 등 action마다 전후 PNG·로그·오류·검증을 저장한다. 대표 화면 하나로 대체 금지.
- 승인 대상은 AUT version과 source/trial evidence digest다. 정식 실행은 승인된 유효 버전만, trial은 미승인도 허용한다.
- 숨겨진 사고·비밀값 원문은 기록하지 않는다. 마스킹을 디스크/전송 전에 적용한다.
- 기본 한도는 job/ITEM 600초·action50·model call80·action retry1·model retry2·USD2.00 제안. 전체 attempt 자동 retry0.
- heartbeat10초/server lease45초/worker watchdog30초/행동 전 여유10초. 총 실행 slot1·기기당1개.
- runtime DB/증거는 비동기화 `%LOCALAPPDATA%/AIQA/`, API는127.0.0.1. UI/테스트 browser와 process 수명을 분리한다.
- 미지원 수동 녹화/영상/pause·원격/cloud/무모델 replay는 후속. 로컬 실행과 모델 API 배치를 혼동하지 않는다.

## Review Focus

1. 저장 전 승인 또는 녹화 중 review gate가 생기지 않아야 한다(T5/T6).
2. 한 목표 step에 여러 action일 때 각각의 전후 PNG/로그와 출처를 잃지 않아야 한다(T4/T5).
3. TC 변경·최신 draft/approved 혼재·다른 증거 hash가 잘못 승인/실행되지 않아야 한다(T2/T6/T7).
4. 취소/lost·증거 누락·보조 job에 무조건 QA verdict를 부여하지 않아야 한다(T1/T5/T9).
5. 리포트의 7개 terminal 결과+진행=N, 최초 실패·마지막 시도·새 재실행을 혼동하지 않아야 한다(T8/T9).

## 1. 단계·의존관계

| 단계 | 작업 | 선행 | 완료 기준 |
|---|---|---|---|
| P0 기술 검증 | T0–T1 | 향후 구현 요청·합성 대상/모델 정책 | 두 플랫폼 제어·action capture boundary·Windows/좌표/IME·정리 근거 |
| P1 자산과 UI | T2–T3 | P0 | project·TC·case/data·exact revision·권한·검색/편집 UI |
| P2 실행/증거 | T4 | T2 | action별 마스킹 PNG/로그·spool/usage/예산·정형 이벤트 |
| P3 녹화·저장 | T5 | T1–T4 | UI 녹화→중간 기록→완료/중단 저장→AUT draft, 승인 불필요 |
| P4 완료 후 검토 | T6 | T5 | saved evidence review·trial·approve/reject·impact/동작 누락 차단 |
| P5 수행·리포트 | T7–T8 | T6 | 독립/선택/suite RUN·순차 ITEM·7결과·분모·분석/export |
| P6 내구성·출시 | T9–T10 | T8 | 두 플랫폼 UI·부정/장애·탭/PC·저장/승인 순서·리포트 gate |
| P7 후속 | T11 | 별도 요청 | cloud/고급 녹화/replay를 새 ADR·실측 gate로 검토 |

P0는 플랫폼별 engineer2일의 탐색 한도를 제안한다. 실제 성공/일정을 보장하지 않는다. A안 Web 호환/capture gate가 실패하면 B의 격리 비용까지 포함해 재결정한다. Android만 성공해도 최종 범위를 축소하지 않는다.

## 2. 제안 제품 파일 구조 — 아직 생성하지 않음

```text
src/aiqa/contracts.py                  # TC/Case/REC/Execution/ITEM·action/evidence DTO
src/aiqa/api/{catalog,recordings,cases,executions,reports,resources,auth}.py
src/aiqa/domain/{versions,approvals,verdicts,suites,reporting}.py
src/aiqa/store/{models,queue,evidence,artifacts}.py
src/aiqa/worker/{service,runner,processes,resources}.py
src/aiqa/recording/{service,action_executor,review_manifest}.py
src/aiqa/adapters/{base,mobile_agent_web,mobile_agent_android}.py
src/aiqa/environments/{base,local_chromium,usb_android,app_builds}.py
src/aiqa/models/{client,compatibility}.py
src/aiqa/validation/{web,android,visual}.py
src/aiqa/web/templates/                # UI_SPEC의15화면
src/aiqa/web/static/                   # HTMX·최소 JS/CSS
src/aiqa/launcher.py                   # API/worker 지속 프로세스·상태/종료 안내
migrations/                           # canonical schema
patches/mobile-agent/                 # pinned upstream·작은 patch·라이선스
tests/{unit,integration,acceptance}/
docs/validation/                      # 실제 측정/시나리오 근거
```

## T0: upstream·모델·action 계측 가능성 검증

**Files:** `models/compatibility.py`, `tests/integration/test_upstream_contracts.py`, `patches/mobile-agent/README.md`, `docs/validation/upstream.md`, dependency lock.

**Interfaces:** `check_binding(binding: ModelBinding, fixture: CompatibilityFixture) -> CompatibilityReport`; `describe_capture_boundaries(engine: EngineRef) -> CaptureCapability`. DTO는 T2 contracts로 승격한다.

- [ ] file URI/한글·공백 경로·provider/endpoint/action schema·unknown action 거부/usage null의 실패 fixture를 작성·실행한다.
- [ ] MobileAgent SHA `81fa28b564ef7a695521500bc15a0e1324b2b394`를 시작점으로 patch/lock·출처를 기록한다. README와 실제 code의 차이를 해결한다.
- [ ] **매 tap/swipe/type/back의 직전·반환 후** capture/log hook을 직접 연결할 수 있는지 확인한다. 기존 pre-step PNG/stdout만으로 완료 처리하지 않는다. 복합 행동은 하위 action 계측이 필요하다.
- [ ] 향후 허용한 API 모델로 이미지·좌표/행동 schema·timeout·usage 최소 시험, Web/Android 각1회 실제 관찰/행동/후 캡처를 기록한다. 데모1회는 안정성 근거가 아니다.
- [ ] `pytest tests/integration/test_upstream_contracts.py -q`와 실기록을 검토하고 commit한다. 둘 중 한쪽 또는 필수 capture boundary 미확보면 gate 실패다.

## T1: 환경 session·job/lease·취소 기반

**Files:** `environments/*`, `worker/*`, `store/queue.py`, `tests/integration/test_sessions_queue.py`.

**Interfaces:** `acquire_environment(spec: EnvironmentSpec, lease: Lease) -> SessionHandle`; `release_environment(session: SessionHandle) -> CleanupReport`; `claim_job(worker_id: UUID) -> JobSpec | None`; `cancel_job(job_id: UUID) -> JobSnapshot`.

- [ ] 원자 claim/동시 기기1개·중복 ack/runner1개·generation·취소/완료 race·watchdog을 fake clock으로 실패 시험한다.
- [ ] Windows native·USB권한/IME·resize/회전·실제 touch·Chromium headless/별도 context·Job Object 정리 근거를 확인한다. WSL/container가 필요하면 USB/ADB/화면/파일 경계를 별도 검증한다.
- [ ] job과 부모 RUN을 분리한다. REC/관리 job의 모든 terminal verdict는 null, trial/정식 ITEM만 QA 집계 경로를 사용한다.
- [ ] lease expiry는 종료 증명이 아니므로 quarantine, cleanup/recover proof 뒤 해제한다. 모델 대기 중 취소도 늦은 응답 행동을 막는다.
- [ ] `pytest tests/integration/test_sessions_queue.py -q`와 실제 Windows 종료/USB 시험을 확인하고 commit한다.

## T2: canonical 데이터·불변 버전·권한

**Files:** `contracts.py`, `store/models.py`, `domain/versions.py`, migrations, `api/auth.py`, `tests/integration/test_assets_versions.py`.

**Interfaces:** `save_tc_revision(tc_id: UUID, definition: TCDefinition, expected_revision: int, actor: Actor) -> TCVersion`; `save_case_revision(case_id: UUID, spec: CaseDefinition, expected_revision: int, actor: Actor) -> CaseVersion`; `compute_validity(case: CaseVersion, tc: TCVersion) -> CaseValidity`.

- [ ] **검증 부족 TC/AUT draft 저장 허용**, exact 주 TC/target binding·project FK/불변 content·TC semantic impact·복제 시 승인 미복제의 실패 시험을 작성한다.
- [ ] UI_SPEC §7의 TC/AUT/REC/execution/ITEM/jobs·versioned datasets·analysis 관계를 구현한다. v0.2 tests/runs API를 동시에 만들지 않는다.
- [ ] local session/CSRF·worker enrollment/token scope·OS secret ref·감사 기록을 연결한다. 모든 하위 ID/artifact에 project 권한을 확인한다.
- [ ] schema 안 data값/metadata 변경과 TC 의미·AUT manifest 변경을 구별하고 current/historical 유효성·사유를 저장한다.
- [ ] `pytest tests/integration/test_assets_versions.py -q`로 재시작 복원·교차 project 차단을 확인하고 commit한다.

## T3: project·TC·AUT·환경/data 관리 UI

**Files:** `api/catalog.py`, `api/cases.py`, `api/resources.py`, `web/templates/`, `launcher.py`, `tests/acceptance/test_asset_ui.py`.

**Interfaces:** `list_tcs(project_id: UUID, query: AssetQuery) -> CursorPage[TCView]`; `list_cases(project_id: UUID, query: AssetQuery) -> CursorPage[CaseView]`; `register_app_build(request: BuildRequest) -> AppBuild`; `prepare_app(session: SessionHandle, policy: SetupPolicy) -> AppPreparationResult`.

- [ ] UI01–04/06/14/15의 빈 상태·검색/분류/컬럼/filter/page·미저장/409/403·복제/보관·설정/secret 미반환을 먼저 시험한다.
- [ ] TC 정의/연결 자동화/이력 탭, latest draft와 approved의 분리, 자동화 없는 TC 제외 사유·TC 변경 badge를 구현한다.
- [ ] installed package 기본 선택과 APK/hash/metadata·minSdk/ABI·명시 설치/초기화·dataset revision을 연결한다. 매 run 재설치하지 않는다.
- [ ] 시작 도구가 API/worker를 브라우저 탭의 자식이 아닌 프로세스로 시작하고 상태를 안내하게 한다. UI가 ADB/셸을 직접 호출하지 않게 한다.
- [ ] `pytest tests/acceptance/test_asset_ui.py -q`로 실제 웹 조작/복원을 확인하고 commit한다.

## T4: action별 전후 PNG·정제 로그·spool·usage

**Files:** `recording/action_executor.py`, `store/evidence.py`, `store/artifacts.py`, `models/client.py`, `tests/integration/test_action_evidence.py`, `tests/unit/test_usage_budget.py`.

**Interfaces:** `execute_action(proposal: ActionProposal, context: ActionContext) -> ActionRecord`; `append_evidence(batch: list[EvidenceEnvelope]) -> IngestReceipt`; `invoke_model(request: ModelRequest, control: RunControl) -> ModelResponse`.

- [ ] S1의 tap/type/swipe3개에 action3개·전후PNG6개·로그3개, 정상/명령실패/캡처실패·timestamp/transform 연결의 실패 시험을 만든다.
- [ ] 메모리 캡처→민감 영역/문자열 마스킹→local spool→artifact/event ACK를 구현한다. 비마스킹 원본 디스크 기록·hidden reasoning 저장 금지다.
- [ ] 전 캡처 실패면 행동 중지, 후 캡처 실패면 무조건 재동작 없이 불명 상태·지연 캡처 표기를 남긴다. 누락은 기록 보존·승인 차단 정보다.
- [ ] seq/hash 멱등성·staging/ready·spool 재전송·필수 증거 pin/만료·용량 한도를 시험한다. model 역할/retry의 nullable usage·tariff·예산 예약을 계측한다.
- [ ] `pytest tests/integration/test_action_evidence.py tests/unit/test_usage_budget.py -q`와 실제 양 플랫폼 action 예시를 검토하고 commit한다.

## T5: 녹화→먼저 저장→AUT 초안

**Files:** `recording/service.py`, `api/recordings.py`, `web/templates/recording.html`, `tests/acceptance/test_recording_save_before_approval.py`.

**Interfaces:** `start_recording(request: RecordingRequest, key: str, actor: Actor) -> RecordingReceipt`; `finish_recording(recording_id: UUID, actor: Actor) -> StorageReceipt`; `stop_recording(recording_id: UUID, actor: Actor) -> StorageReceipt`; `materialize_case_draft(recording_id: UUID, tc_version_id: UUID) -> CaseVersion`.

- [ ] **승인 레코드 0건인 상태에서** 정상/중단/실패·검증 부족 REC/AUT가 먼저 저장되는 시험을 작성한다. 녹화 중 approve 요청은 거부하고 기록은 지속 보존해야 한다.
- [ ] UI05에 미리보기·action/전송 count·메모·완료/중단만 제공한다. 승인 버튼/동작 승인 대기는 구현하지 않는다.
- [ ] finish/stop→새 행동 차단→seal/flush/cleanup→stored·AUT draft 자동 저장을 구현한다. TC 없는 REC도 보존하고 사후 연결/최소 TC 생성은 별도 조작이다.
- [ ] 서버 단절 시 local/spooling을 표시하고 ACK 전 stored로 표시하지 않는다. crash/terminal job 뒤에는 새 제어 권한 없이 read-only evidence 복구를 허용하며 원본 QA/terminal job 결과를 바꾸지 않는다.
- [ ] `pytest tests/acceptance/test_recording_save_before_approval.py -q`를 UI로 실행하고 Web/Android tap·type/swipe/back의 저장된 전후PNG/로그를 확인해 commit한다.

## T6: 저장 완료 후 동작 검토·trial·AUT 승인

**Files:** `recording/review_manifest.py`, `domain/approvals.py`, `validation/*`, `web/templates/case_review.html`, `tests/integration/test_post_recording_approval.py`.

**Interfaces:** `request_review(case_version_id: UUID, actor: Actor) -> ReviewSnapshot`; `review_action(review: ActionReviewRequest, actor: Actor) -> ActionReview`; `approve_case(case_version_id: UUID, evidence: EvidenceDigestSet, actor: Actor, reason: str) -> Approval`.

- [ ] recording/storing 중 승인·다른 manifest/REC/trial·전후PNG/로그/필수 검토 누락·TC 변경·trial non-PASS는 승인 거부 시험을 작성한다. 거부/반려가 저장본을 삭제하지 않아야 한다.
- [ ] UI07에 source/trial 범위·동작별 전후/명령·검증·retry·검토함/수정 필요와 review counts를 구현한다. 저장은 선행 완료 상태다.
- [ ] 동일 AUT manifest의 새 trial과 현재 QA oracle을 연결한다. engine done/click 성공만으로 PASS 금지·필수 경로 latch를 적용한다.
- [ ] approve/reject/revoke의 actor/time/reason·case/source/trial/action digest를 결합하고 새 revision에 자동 복사하지 않는다. 원본 REC·승인 evidence는 pin한다.
- [ ] `pytest tests/integration/test_post_recording_approval.py -q`와 UI 승인/반려→새 draft→trial/재승인 동선을 검토하고 commit한다.

## T7: 단일·선택·묶음 공통 수행

**Files:** `api/executions.py`, `domain/suites.py`, `store/queue.py`, `web/templates/{execution_setup,execution,suites}.html`, `tests/integration/test_execution_items.py`.

**Interfaces:** `preview_execution(request: ExecutionRequest, actor: Actor) -> ExecutionPreview`; `enqueue_execution(request: ExecutionRequest, key: str, actor: Actor) -> ExecutionReceipt`; `cancel_item(item_id: UUID, actor: Actor) -> ItemSnapshot`; `skip_item(item_id: UUID, reason: str, actor: Actor) -> ItemSnapshot`.

- [ ] single1/selectionN/suiteN에 새 RUN·exact ITEM/jobs가 생성되고 중복 key·data 확장 최대100·미승인/TC 변경·명시 제외/분모가 정확한지 시험한다.
- [ ] UI06의 TC 편집 없는 단독/선택 실행, UI08 구성/복제·명시 새 version 교체, UI09 4단계 preview/설정/접수를 연결한다.
- [ ] resource1·순차·cleanup/quarantine·continue/stop·취소/skip/finalizing race·재시작 후 중복 ITEM 없음 규칙을 구현한다.
- [ ] selected 실패 재실행은 새 RUN/ITEM+원본 ref/사유다. 기존 parent 결과/버전은 변경하지 않는다.
- [ ] `pytest tests/integration/test_execution_items.py -q`와 mixed UI 수행을 확인하고 commit한다.

## T8: ITEM 분석·7결과 리포트·CSV/HTML

**Files:** `domain/reporting.py`, `api/reports.py`, `web/templates/{case_run,report,comparison}.html`, `tests/unit/test_report_math.py`, `tests/acceptance/test_reports_ui.py`.

**Interfaces:** `summarize_execution(execution_id: UUID, as_of: EventCursor) -> ExecutionReport`; `derive_display_result(item: ItemSnapshot) -> DisplayResult | None`; `add_analysis(item_id: UUID, record: AnalysisRequest, actor: Actor) -> AnalysisRecord`; `export_report(execution_id: UUID, format: ExportFormat) -> JobReceipt`.

- [ ] 7terminal+진행=N·확정 전 제외/후skip·취소직전FAIL·분모0·N10(P6/F2/B1/NOT_RUN1) 수학을 실패 시험한다. 100%완료/75%검증통과/60%전체통과/미검증2를 확인한다.
- [ ] UI10–13의 상태/판정/분석 분리·동작별 증거 확대·첫 실패/시도/설정·trial 기본 제외·단일 리포트를 구현한다.
- [ ] 분석/이의 의견·issue URL을 별도 저장하고 원본 verdict/최초 실패를 변경하지 않는다. 새 재실행 통과와 first/latest attempt를 함께 표시한다.
- [ ] CSV/printable HTML export의 as_of/criteria_version/snapshot·권한·마스킹/CSV안전·중간보고/만료 상태를 구현한다. localhost 외부 공유를 보장하지 않는다.
- [ ] `pytest tests/unit/test_report_math.py tests/acceptance/test_reports_ui.py -q`를 실행해 검토 후 commit한다.

## T9: 장애·보관·원본 보호 통합

**Files:** `tests/integration/test_fault_matrix.py`, `tests/integration/test_storage_review_integrity.py`, `docs/validation/faults.md`.

- [ ] REC와 ITEM 각각 모델대기취소·USB/browser/worker 중단·서버 재시작·중복/late event·업로드 단절·disk full을 시험한다. 부분 기록은 보존하고 승인 없이는 저장 안 하는 흐름이 없어야 한다.
- [ ] 늦은 model/action은 차단하고 필요한 read-only evidence 복구만 허용한다. source digest 변경은 새 보관 revision/review이며 원본 terminal 결과는 불변이다.
- [ ] 탭 종료는 계속·재접속 복원, PC 종료/절전은 lost/정리·quarantine과 새 수행을 안내한다. runtime 지속/자동 재개를 보장하지 않는다.
- [ ] 90일metadata/30일PNG/7일ACKspool/24시간debug·승인근거pin·20GB/REC·ITEM500MB·백업복원·secret/hidden reasoning 비저장을 확인한다.
- [ ] 각 장애 최소3회·`pytest tests/integration/test_fault_matrix.py tests/integration/test_storage_review_integrity.py -q` 결과를 기록하고 commit한다.

## T10: 양 플랫폼 UI 출시 gate

**Files:** `tests/acceptance/test_mvp_ui_matrix.py`, `docs/validation/mvp-results.md`, 운영/알려진 제약 안내.

- [ ] UI_SPEC §9의12개 합격 시나리오를 UI로 실행한다. TC→REC→동작별저장→완료→저장본 검토/승인→독립/선택/suite→리포트/분석/재실행을 포함한다.
- [ ] Web/Android 정상 각20회(첫attempt≥18/20·허용 retry포함≥19/20 제안), 값불일치/요소부재/timeout 각5회, UI위치/문구변경 각5회, 거짓PASS0을 사람 oracle과 대조한다. 기준은 초기 제안이며 일반 성공률 보장이 아니다.
- [ ] artifact·로그·review 누락 승인이0, 녹화중승인0, 미승인저장성공, 중복기기소유/외부행동·terminal덮어쓰기·secret유출0을 확인한다.
- [ ] 시간p50/p95·모델 measured/estimated/partial·점유/저장량, 프로젝트/버전/분모·PC/탭·키보드/복원/오류 UI를 측정한다.
- [ ] `pytest tests/acceptance/test_mvp_ui_matrix.py -q`와 근거 RUN/REC/ITEM·human label을 검토해 설계/사용 안내를 실제 구현과 맞춘다. 두 플랫폼+모든 핵심 UI 동선 충족 전 MVP 완료로 표시하지 않는다.

## T11: 후속 ADR·확장 — 별도 요청 후

중앙 관리/PostgreSQL/TLS·여러 worker·remote browser/device farm은 환경 capability·실제 ADB/제어API·가속·sessionTTL/release/고아·과금/사내망을 실측한다. Appium 지원만으로 Mobile-Agent 호환을 주장하지 않는다.

수동 조작 녹화·영상·pause/resume·CUAWright 무모델 replay는 각각 별도 capture/권한·코드 승인/격리·현재 oracle·모델0회 계측 gate를 둔다. 기본 AI 녹화 기록 저장과 혼동하지 않는다. 예약/CI/알림·TC CSV 가져오기·PDF 자동 생성은 후속이다.

## 3. 현재 상태

완료 대상은 **UI_SPEC/DESIGN/IMPLEMENTATION_PLAN 문서 개정과 RESEARCH 보충**, v0.2 보관이다. 제품 파일/테스트/설치/기기 조작/모델 호출/배포는 아직 없다. v0.3의 T0–T11이 현행 계획이며 v0.2의 T2A/T6A/T7A 등은 보관본 기록이다. 핵심 상태/데이터/API는 UI_SPEC, 운영/QA는 DESIGN, upstream 사실은 RESEARCH를 단일 기준으로 삼는다.
