# 실행 공통 계약 · 제품 설계 v0.6 / 작업계획 v0.8

규범 기준일: 2026-10-31. **구현·검증할 계약**이며 이 문서만으로 DTO/API/DB/VM/시험 전체가 완료됐다는 뜻은 아니다. 실제 완료 범위는 WORK_PROGRESS와 인계를 따른다. 2026-11-01 보완: [계약 수정 결과](../validation/reviews/2026-11-01-remediation-result.md).
[읽는 순서](README.md) · [인계 양식](HANDOFF.md) · [검토·보완 기록](REVIEW.md).
작업자는 담당 카드에 지정된 절과 선행 작업의 인계 기록을 읽는다. 이전 채팅은 필수 입력이 아니다.

## C00 · 실행 범위와 공통 완료 규칙

- 최초 설계 개정은 문서 작업이었다. 구현 요청 뒤 상세 작업 ID와 실제 인계로 진행한다. 현재 core 구현과 검토 보완의 증거는 WORK_PROGRESS를 따르며, 설치·모델/기기 실행·배포까지 완료됐다고 추정하지 않는다.
- 파일 경로는 저장소 root 기준이다. 제품 Python은 `src/aiqa/`, 시험은 `tests/`, 런타임 데이터는 비동기화 `%LOCALAPPDATA%/AIQA/`에 둔다.
- 큰 `contracts.py` 대신 `src/aiqa/contracts/{common,cases,recordings,jobs,resources,actions,evidence,models,checks,replay,reviews,healing,reports,benchmarks}.py`로 나눈다. `__init__.py`는 필요 시 재노출만 한다. root 계획의 과거 contracts.py 표기를 이 책임 경계로 구체화한다.
- API만 SQLite에 접근한다. worker/VM은 인증 HTTP·정제 spool을 쓰고 DB 파일을 열지 않는다. API 단일 프로세스 writer, 긴 모델/파일 작업 중 DB transaction을 잡지 않는다.
- Web은 CUAWright authoring + 같은 PC의 격리 VM/신뢰 driver가 수행하는 승인 code replay다. Android는 Mobile-Agent authoring + host ADB action replay다. 두 플랫폼 모두 MVP다.
- TC는 선택이다. 케이스가 검증 정의/설정/녹화 절차/증거를 소유한다. 녹화 중 승인0, 미승인/실패/중단 기록도 먼저 저장한다.
- 일반 replay actor0, 검증 AI는 명시 check에만, healing은 기본OFF다. 실제 검증 실패와 원본·기본 실행본을 AI가 자동 변경하지 않는다.
- 상세 작업은 선행 근거 확인 → 지정 부정 시험/검증 → 해당 범위 구현 → 검사/화면/실제 환경 확인 → diff 검토 → 근거/인계 갱신 순서로 수행한다. 단순 CSS·문구는 필요한 화면 확인으로 검증한다.
- 시험 파일/함수·명령은 **미래 산출물**이다. 미실행 검사를 PASS로 쓰지 않는다. 장비/키가 없어 SKIP이면 자동 검사와 별도로 실제 gate는 차단/미실행이다.
- 상세 작업 완료는 체크와 인계 근거가 함께 있어야 한다. W 완료는 소속 상세 작업 전부 완료 + 상위 통합 조건 확인이다. 부모 W가 끝날 때까지 기다리는 대신 상세 작업 DAG를 따른다.
- 계약을 바꾸면 DTO 소유 작업·소비 작업·관련 root 설계/추적표를 함께 수정하고 영향을 기록한다. 사용자 결정 → 영역별 규범(DATA/UI/실행 spec) → 이 보완 계약 → 작업 카드 순으로 대조하며, 충돌 발견 시 REVIEW에 기록하고 해소 전 소비 구현을 차단한다.
- 문서 검사 통과는 제품 시험 통과가 아니다. 기존 prototype은 v0.5 모의 UI이며 실제 DB/engine 근거가 아니다.

## C01 · 공통 타입·API·오류·UI 상태

공통 타입의 UUID/hash는 실제 형식을 따른다. AUT/REC/RUN 같은 화면 ID·sha256:example 등 root 대표 JSON의 축약은 설명용이며 API fixture로 복사하지 않는다. CaseEditInput/CaseVersionView의 정식 필드는 settings다. 화면 예시의 execution_settings 표시는 같은 설정의 설명용 이름이며 별도 저장 원천이 아니다.

```text
UUID = UUID 문자열                    UtcInstant = timezone 있는 UTC ISO8601
Fingerprint = "sha256:" + 64자리 hex    Money = decimal 문자열 + ISO currency
EngineRef = {source_sha, patch_hash, dependency_lock_hash, adapter_version}
SecretRef = {project_id, ref_id, revision}; 실제 값/원문 hash는 저장 DTO에 없음
Actor = {actor_id, project_scope, is_local_owner}; WorkerScope = {worker_id, permitted_projects, permitted_purposes}
CursorPage[T] = {items: list[T], next_cursor: str|null, snapshot_seq: int}
ErrorResponse = {error: {code, message, fields: {field: [message]}, retryable, request_id, current_revision?}}
MutationReceipt = {request_id, resource_id, committed_seq, replayed: bool}
GateDecision = {passed: bool, reasons: [Reason], evidence_refs: [str]}
Reason = {code, field_or_owner?, message, action_href?}
```

API prefix는 `/api/v1`이다. 각 route의 project는 path/owner에서 서버가 확인한다.
browser session/actor/project scope + mutation CSRF/Origin과 worker token/purpose/generation은 별도다.
개인 모드도 인증 없는 mutation을 열지 않는다. 로컬 launcher가 일회용 nonce를 fragment로 전달하고 동일 Origin session bootstrap POST에서 소비하는 방식을 W04-03의 구현 선택으로 고정한다. nonce는 URL query/접근 로그/localStorage에 남기지 않고 60초 만료·1회 사용이다. worker enrollment는 인증된 browser 조작으로 별도 token을 발급한다. SSO/팀 인증은 후속이다.

- 장기 작업은202 `{job_id, recording_id?, execution_id?, status_href}`, 동기 신규 저장201, 수정/동일 receipt 재전송200을 사용한다. 최초 응답은 원래 receipt와 함께 보존한다.
- schema/field422, revision·key/body·hash 충돌409, 권한403, 타 소속/존재 은닉404, 미인증401, 저장 공간 부족507, upload 크기413, 증거 파일 만료410이다. 응답에 stacktrace/secret을 넣지 않는다.
- mutation은 `Idempotency-Key`, version/pointer 수정은 `If-Match` 또는 명시 expected ID를 요구한다. (actor,project,operation,key)와 body hash를 7일 보관한다. 같은 body는 같은 receipt, 다른 body409, 7일 뒤는 새 요청이므로 client는 UUID를 재사용하지 않는다. manifest/approval의 업무 unique 제약은 7일 후에도 유지한다.
- 구현의 browser CRUD receipt는 business write와 같은 transaction에서 확정하며 재전송은 원 body/HTTP200을 반환한다. 민감 입력의 비교에는 원문 SHA가 아닌 OS 사용자 보호 key 기반 HMAC을 쓴다. 재접속해도 local owner actor는 유지하고 CSRF GET은 기존 cookie-bound token을 읽기만 한다. 최초 프로젝트 1개의 동일 Origin 로컬 setup 이후 프로젝트 생성에도 session/CSRF가 필요하다. 팀/원격 인증 완료라는 뜻은 아니다.
- cursor 기본25/최대100, filter/sort allowlist와 안정적인 ID tie-break를 사용한다. 목록 cursor·project commit seq·attempt local_seq는 다른 타입이다.
- UI 공통 상태는 loading(기존 값/마지막 갱신 유지·중복 제출 비활성), empty(다음 조작 안내), 422(입력 보존/필드 오류), 403, 409(서버 diff/재확인), stale(마지막 수신/연결 상태), missing/expired/corrupt, 미저장(저장/버리기/이동 취소)다.
- URL에는 filter/sort/page/선택 ID만, sessionStorage에는 비밀 없는 scroll/열 설정만 저장한다. secret/편집 buffer/실제 모델 key를 browser 저장소에 두지 않는다. 탭 재접속은 GET으로 복원하고 mutation을 다시 보내지 않는다.
- 1440px 기본/1024px 보조 패널 접기·keyboard/focus·색 외 상태 문구를 제공한다. 조작은 실제 API에 연결되거나 명시적 비활성 사유가 있어야 한다. 미구현을 성공 mock으로 채우지 않는다.
- 요청 거부 HTTP 오류와 claim 후 확정 ITEM의 BLOCKED/FAIL 등을 구별한다. preview 거부를 실제 검증 실패로 집계하지 않는다.

## C02 · 케이스·정의·버전·선택 TC

```text
CaseDefinition = {raw_text, objective, preconditions: [str],
 variables: {name: typed_value}, secret_refs: {name: SecretRef},
 steps: [{id, instruction, expected: [CheckSpec]}],
 final_expected: [CheckSpec], path_policy: {must_use: [str], forbidden: [str]}}
CaseSettings = {target_kind: web|android, execution_mode: recorded_replay,
 environment_revision_id, app_build_id?, install_policy, reset_policy, cleanup_policy,
 limits: Limits, verifier_bindings, healing_policy: ApprovedHealingPolicy}
CaseEditInput = {definition, settings, recorded_steps, parent_version_id?, expected_head?, reason}
CaseRevisionInput = {definition, settings, recorded_steps, parent_version_id?, base_version_id?,
 source_manifest_id?, reason, expected_head?, proposal_id?}
CaseVersionView = {project_id, case_id, id, revision, creation_kind, parent/base IDs,
 definition, settings, recorded_steps, source_manifest_id?, replay_package_id?,
 content_hash, verification_digest, readiness: CaseReadiness}
CaseView = {metadata, latest_draft_version_id?, current_approval_id?, selected_version: CaseVersionView}
CaseMetadata = {name, folder_id?, tags: [str], priority?, assignee?, tc_reference?, archived_at?, lock_version}
```

- `canon-json-v1`은 UTF8/key 정렬/공백 없음/유한 수/금액 문자열/schema_version 고정이다. content hash에서 이름/태그/TC/live pointer/실제 secret/파일 가용성을 제외한다. verification_digest는 목적/조건/input schema/기대/필수 path의 의미 snapshot이다.
- (project,id) UNIQUE·동일 case composite FK·참조 row DELETE RESTRICT·불변 content UPDATE/DELETE trigger를 적용한다.
- `save_case_revision(actor, case_id, input, expected_head) -> CaseVersionView`는 revision/step/check projection/CAS/audit를 한 transaction에서 확정한다. 명시 branch는 head를 변경하지 않는다. 단계 복제는 새 ID, 의미 변경은 semantic_hash 갱신이다.
- 공개 편집 API는 CaseEditInput만 받는다. source_manifest/package/approval/produced version 같은 provenance 필드는 서버 materializer만 공급하며 client가 지정하면422다. proposal_id도 수락 API에서 검증해 내부 revision으로 넘긴다.
- 의미 편집은 새 version·package=null이다. 과거 package/REC/action review/approval을 복사하지 않는다. MVP의 절차/기대/핵심 설정 변경은 새 전체 REC→package→OFF trial→review다. 동일 source 재컴파일인 package_rebuild를 의미 편집의 대용으로 쓰지 않는다.
- `GET/POST projects/{p}/cases`, `GET/PATCH cases/{c}`(PATCH는 metadata), `GET/POST cases/{c}/versions`, `GET case-versions/{v}/diff?base={b}`, `POST cases/{c}/clone|archive`다. clone은 새 AUT/draft/provenance·approval0이다.
- `GET/POST projects/{p}/folders|tags`, `PATCH folders/{f}|tags/{t}`로 분류 metadata를 편집한다. folder parent는 동일 project·순환422, 참조 중 삭제 RESTRICT·보관 사용이다. 담당자는 개인 actor 표시이며 팀 계정 관리는 후속이다.
- TC는 `GET/POST projects/{p}/tcs`, `GET/POST tcs/{t}/versions`, `POST tcs/{t}/clone|archive`, `PUT/DELETE cases/{c}/tc-reference`다. 참조만 바뀌면 case hash/승인은 불변이다.
- `POST cases/{c}/tc-import-proposals`, `POST cases/{c}/proposal-acceptances`는 exact proposal/hash + expected_head를 사용한다. diff 명시 수락만 새 case version이다. TC 수정/보관은 자동 동기화/실행 차단을 일으키지 않는다.

## C03 · 독립된 readiness·artifact 가용성

```text
CaseReadiness = {saved: bool, recordable: bool, replayable: bool, reviewable: bool,
 formal_runnable: bool, reasons: [Reason]}
RecordingView = {id, case_id, input_case_version_id, input_hash, base_case_version_id?,
 storage_status: local|spooling|stored, outcome: completed|interrupted|error|null,
 procedure_readiness: complete|incomplete|needs_review,
 evidence_completeness: complete|incomplete, latest_manifest_id?, job_id}
ArtifactView = {id, hash, bytes, content_type, storage_state, capture_metadata,
 redaction_policy_version, availability: ready|missing|expired|corrupt|pending,
 retention: {protections, expires_at?, releases}}
```

reason code는 적어도 DEFINITION_AMBIGUOUS / VARIABLE_MISSING / RESOURCE_UNAVAILABLE /
CAPABILITY_UNSUPPORTED / MODEL_BINDING_UNAVAILABLE / BUDGET_UNAVAILABLE / PACKAGE_MISSING /
PACKAGE_INVALID / EVIDENCE_INCOMPLETE / SOURCE_INCOMPLETE / TRIAL_MISSING / TRIAL_NOT_CLEAN /
TRIAL_NOT_PASS / REVIEW_INCOMPLETE / APPROVAL_MISSING / APPROVAL_REVOKED / SCOPE_MISMATCH를 구별한다.
저장 허용과 recordable/replayable/reviewable/formal을 하나의 status로 합치지 않는다.
draft 저장도 schema·secret 제약을 지켜야 한다. trial은 ready package와 현재 검사가 필요하지만 승인은 필요 없다. 정식은 exact 유효 승인도 필요하다.

typed artifact ref는 action/check/source/review/build/export/package/healing/proposal 중 정확히 한 owner를 가진다.
resource_probe의 읽기 capture는 resource_observations(project/resource/probe job/attempt/captured_at/geometry/artifact)와 artifact_refs.resource_observation_id로 소유를 연결한다. 다른 실행의 action 후 PNG로 재사용하지 않는다.
provenance ref는 영구 pin이 아니다. 같은 project라도 다른 ITEM/attempt 증거는 membership transaction에서 거부한다.
후에 missing이 드러나도 과거 QA/hash를 고치지 않고 새 승인/새 수행의 가용성을 차단한다.

## C04 · job·lease·session·취소

```text
JobPurpose = recording|trial|regression|structure|app_inspect|app_install|resource_probe|
 model_check|export|evidence_sync|package_rebuild|backup
JobSpec = {id, purpose, project_id, recording_id?, case_run_id?, payload_hash,
 source_refs, limits, status}
Lease = {resource_key?, worker_id, job_id, generation, expires_at}
EnvironmentSpec = {target_kind, environment_revision_id, resource_id, app_build_id?,
 install/reset/cleanup policies, engine_ref, viewport/geometry, allowed_scope}
SessionHandle = {session_id, attempt_id, generation, target_kind, driver_handle_ref}
CleanupReport = {released: bool, quarantined: bool, reasons, proof_refs}
```

**보완 결정:** backup을 관리 job enum에 명시한다. app_inspect는 저장 APK metadata 검사다.
실제 USB installed-package 관찰은 physical lease가 있는 resource_probe다.
recording은 REC만, trial/regression은 ITEM만, 관리 job은 두 owner null + 별도 source_refs다.
execution purpose reverification의 worker job은 regression이다.
structure는 authoring role, model_check는 maintenance role 호출이며 둘 다 관리 QA=null이다.
backup/evidence_sync/package_rebuild는 기기/browser/model 제어 권한이 없다. app_inspect도 APK code 실행은 없다.
resource_probe는 읽기 전용 관찰, app_install/reset은 명시 허용 설정으로만 한다.

- `claim_job(worker, now) -> JobLease|null`, `renew_lease(worker, token) -> LeaseView`, `acknowledge_attempt(lease, nonce) -> AttemptReceipt`, `cancel_job(actor,id,expected) -> JobSnapshot`을 사용한다.
- claim transaction이 queued 조건부 변경+lease+attempt를 만들며 ACK는 그 attempt 확인이다. 중복 ACK가 새 attempt/runner를 만들지 않는다.
- total slot1, 같은 (worker,native serial) 물리 기기1이다. project별 별칭도 같은 lease key이며 관리 job도 slot1이다.
- poll2초 / heartbeat10초 / lease45초 / worker watchdog30초 / 행동 전 lease 잔여10초 이상이다.
- 취소 유예5초 / 정리30초, process/context/IME/resource 정리 증명이 없으면 quarantine이다. lease 만료만으로 ready로 만들지 않는다.
- 전체 attempt 자동 retry0. action retry1은 미dispatch가 증명된 전달 전 실패에만 허용한다. read-only lookup/poll은 외부 명령 재전송과 구별한다. dispatch_started 이후 timeout/ACK 누락은 자동 재전송 금지다.
- job 상태는 root DESIGN §6.1과 같다: queued→preparing→running→finalizing→completed, preparing/running→cancel_requested→finalizing, queued→completed(skip)/cancelled, preparing/running/finalizing→error/lost. terminal은 completed/error/cancelled/lost다. leased/cancelling을 새 status로 추가하지 않는다.
- finalizing/terminal의 **새** 취소 요청은409다. 같은 Idempotency-Key의 기존 취소 재전송은 원래 receipt를 반환한다. UI phase replaying/verifying/healing은 job status와 별개다.
- API 재시작 중 동일 live runner의 지속은 유효 generation/watchdog 안에서만 가능하다. PC 복귀/runner 사망 뒤 checkpoint 자동 재개는 없다.
- terminal 뒤 늦은 event는 stale inbox/audit로 분리하고 결과를 덮지 않는다.

## C05 · 행동·관찰·증거·dispatch

2026-11-01 runtime 보완: PreparedAction의 attempt identity는 Observation ID와 다르다. 같은 attempt/action의 dispatch_started 이후에는 재호출·프로세스 재시작으로 전송을 반복하지 않는다. 실제 dispatch 전과 journal flush 후에 제어/lease 여유를 검사하며, phase 객체를 다시 만들어 예산을 초기화하지 않는다.

```text
ActionProposal = {step_id, action_id, type, intent, target_binding?, coordinates?,
 input: LiteralInput|SecretRef?, approved_path_ref}
CaptureGeometry = {physical_width,height, model_width,height, transform, rotation, content_bounds}
Observation = {captured_at, geometry, sanitized_png_ref, sanitized_dom_or_hierarchy?,
 scope_fingerprint, observation_id}
ActionEnvelope = {attempt_id, action_seq, step_id, action_id, package_step_id?,
 proposal_hash, dispatch_state, before_ref?, after_ref?, log_ref?, error?, outcome_known}
EventEnvelope = {attempt_id, local_seq, captured_at, type, minimum_facts, payload_hash, body_hash}
DispatchState = planned|lookup_failed|dispatch_started|acknowledged|observed|unknown
```

- tap/type/swipe/back와 Web click/fill/scroll/select 등 P0에서 확인한 subset만 지원한다. compound step도 실제 행동마다 전후 PNG/log/시각/명령/결과/오류를 남긴다.
- capture→메모리 관찰 filter→보관용 정제 이미지/DOM/log→spool이다. secret/hidden reasoning 원문은 debug에도 저장/전송 금지다. filter/전 캡처 실패는 command0, 후 실패는 incomplete/unknown이다.
- 현재 filter는 실제 PNG의 CRC/geometry/압축 데이터를 검사하고, 신뢰할 픽셀 정제를 보장할 수 없는 민감 캡처는 거부한다. 문자열을 PNG bytes에서 치환해 정제했다고 주장하지 않는다. Native authoring에서 픽셀 정제 coverage를 연결하기 전 `secrets=()`로 이 차단을 우회하지 않는다.
- `PolicyGate.authorize(proposal, context) -> ActionDecision`, `prepare_action(proposal, observation) -> PreparedAction`, `dispatch_action(prepared, control) -> DispatchReceipt`, `observe_action(receipt, control) -> ActionObservation`을 사용한다.
- **native API보다 먼저 dispatch_started를 durable local journal에 flush**한다. 실패하면 command0, 이후 navigation/ADB timeout을 lookup_failed로 되돌리지 않는다.
- Web driver만 raw Playwright/CDP를 소유하고 script는 package에 속한 typed IPC만 쓴다. VM만 마련하고 동일 권한 script를 안전하다고 간주하지 않는다. 권한/egress/credential/host mount 분리를 실제 검증한다.
- Android는 host 지정 serial의 argument list, raw shell 없음이다. geometry/rotation/content bounds가 불명이거나 바뀌면 중지/BLOCKED, 비율 추정 tap은 없다. secret ref는 허용 input 때만 해석하고 IME는 finally 복구·실패 quarantine이다.
- 원래 미전송 capture와 나중 재관찰은 별개다. 후자는 after_delayed이며 즉시 후 PNG 누락을 채우지 않는다.
- artifact는 staging→같은 볼륨 tmp flush/hash→rename→DB ready/ref/ACK다. ready 파일이 없거나 바뀌면 missing/corrupt다.
- runtime `ArtifactUpload`는 `project_id, owner_kind(REC|ITEM), owner_id, attempt_id?, action_id?, check_id?, role, filename, media_type, declared_hash, declared_length, body`다. before/after는 해당 attempt의 action, check는 check ref가 필수다. 그 외 recording source/log는 REC ref로 보존한다. 다른 management owner는 후속 소유 작업에서 typed 관계를 구현하기 전에는 거부한다. MIME와 소속을 확인하기 전에 dedup/ACK하지 않는다. Worker HTTP upload도 같은 key/body의 원 receipt와 다른 body409를 보존하며 lease 판단에는 서버 시각을 쓴다.
- spool 7일 자동 정리는 **ACK된 것만**이다. 미ACK는 기한으로 버리지 않고 공간 부족 시 새 행동 중지/부분 보존/복구 안내다. server receipt/hash 확인 없이 삭제하지 않는다.
- ACK 파일을 지워도 prefix/seq/hash metadata는 유지한다. 새 recovery manifest의 파일은 기존 경로를 덮어쓰지 않고 별도 object 경로를 쓰며 prior manifest를 연결한다. 복구 파일 stage/flush와 DB writer transaction을 분리하고, metadata/job receipt만 원자 확정한다. delayed는 여전히 즉시 후 증거가 아니다.

## C06 · 모델 역할·Check·usage·예산

```text
ModelBinding = {id, revision, role, provider, endpoint_kind, endpoint, model,
 secret_ref, prompt_ref, prompt_hash, compatibility_hash, tariff_id}
ModelRequest = {call_id, role, owner_kind, owner_id, check_id?|episode_id?,
 binding_revision, sanitized_inputs, token_output_limit, deadline}
ModelResponse = {call_id, actual_model?, content, usage?, measurement_status, provider_request_id?}
CheckSpec = {id, step_id?, required, subject, kind, expected, method,
 verifier_binding_id?, allow_unknown_supplement: bool}
CheckResult = {check_id, status: satisfied|violated|unknown|not_run, method,
 expected_snapshot, sanitized_observed, reason, artifact_refs, observed_at}
Limits = {timeout_seconds:600, max_actions:50, max_model_calls:80,
 max_action_retries:1, max_model_retries:2, max_attempt_retries:0, budget:"2.00", currency:"USD"}
```

숫자는 검토용 초기 profile이며 API 가격·성공률·실제 청구 hard cap의 보장이 아니다.
모든 모델 전송과 transport retry를 세며 role은 authoring/verification/healing/maintenance다.
정상 replay actor0, script에는 binding secret/직접 LLM 경로가 없다.
check method는 deterministic / ai_visual / deterministic_then_ai_unknown이다.
unknown 보완은 사전 허용 check만, violated를 AI로 satisfied로 바꾸지 않는다.
AI parse 실패/가림/증거 부족/timeout/예산 부족은 unknown이며 키가 필수면 preflight 차단이다. 검사 생략 PASS는 없다.
짧은 관찰/판정 이유는 남기지만 hidden reasoning은 요구하거나 저장하지 않는다.

`invoke(request, control) -> ModelResponse` 전 `reserve_model_call`로 call/time/최대비용을 원자 예약하고 `settle_model_call`로 정산한다. strict 가격 불명은 새 호출 불가, 명시 estimate mode는 불완전 표시다.
input/output/cache/image usage는 nullable, measured/estimated/unreported다. 실제 전송 없음은 calls0/actual model=null+not_used, 계측 누락은 unknown이다.
복수 통화는 분리하고 늦은 청구/보정은 commit_seq가 있는 append ledger다. 취소 후 응답은 기록해도 행동은 금지다.
healer는 ITEM당 episode1/모든 전송 최대2회/30초가 더 엄격한 상한이며 transport retry도2에 포함한다.

## C07 · source→package→trial→repair

`RecordingStartInput = {case_id, input_case_version_id, input_manifest_hash, resource_id}`다. input_manifest_hash는 저장된 입력 CaseVersion.content_hash와 비교하는 wire 이름이다. `RecordingReceipt = {recording_id, job_id, input_case_version_id, input_manifest_hash, status_href}`다.

`POST recordings/{r}/finish|stop`의 browser 입력은 `{expected_state, reason?}`뿐이다. 완료 버튼은 새 행동 중지/flush 요청이며 browser가 source/QA/완결 상태를 확정하지 않는다. 신뢰 worker가 `RecordingFinishInput = {recording_id, attempt_id, generation, final_seq, outcome, source_artifact_hashes, action_mapping, evidence_completeness}`을 인증 finish 경로로 제출하고 서버가 manifest/hash를 확정한다.

```text
RecordingManifest = {id, recording_id, case_id, revision, kind, prior_manifest_id?,
 input_version_hash, source_artifact_hashes, action_mapping, evidence_completeness,
 request_key, body_hash}; compiled hash/output version ID/hash는 body에 없음
ReplayPackageBody = {schema_version, source_manifest_id/hash, raw_source_hash,
 approved_code_or_plan_hash, runtime_ref, compiler_ref, lock_hash, step_mapping_hash}
CompiledPackage = {body: ReplayPackageBody, body_hash, ready_artifact_ids, steps: [PackageStep]}
MaterializationReceipt = {manifest_id, produced_case_version_id, replay_package_id?, committed_seq}
ReplaySpec = ExecutionSpec + {package_id/hash, runtime/lock, resolved_healing_policy}
ReplayOutcome = {termination_reason, actual_summary, action/check refs}; 최종 QA가 아님
```

- 입력/실패/부분 draft는 package0, ready exact version은1이다. sealed source→compile/계측 검사→artifact ready→한 transaction에서 version/package/steps/receipt/CAS를 확정한다. version hash에 package hash를 넣고 역방향은 hash body 밖 receipt라 순환하지 않는다. 양방향 composite FK는 DEFERRABLE INITIALLY DEFERRED다.
- compiler가 없는 W16-05도 raw source/manifest와 package=null/사유 있는 draft를 저장한다. W29/W30 뒤 W16-07에서 ready compiler를 finish에 통합한다.
- receipt가 있는 manifest 재전송은 같은 version이다. 후에 성공해도 옛 draft에 attach하지 않는다. package_rebuild 새 manifest(원 capture/source hash+새 compiler/lock)→새 version/trial/review다. creation_kind는 recorded, manifest.kind로 rebuild를 구별한다.
- `POST recordings/{r}/package-rebuilds`는 {source_manifest_id, compiler_ref, lock_ref, expected_draft_head?, reason}을 받는 관리 job이다. source ref 연결·QA=null·physical/model 제어 없음이다.
- `ReplayRunner.run(spec,sink,control) -> ReplayOutcome`는 code/plan 직접 재생·매번 새 관찰/check다. 일반 actor0이고 원래 engine model loop를 재시작하지 않는다.
- healer는 target 후보만 typed로 낸다. 신뢰 코드가 승인 role/name+container 또는 resource-id/text/context·unique/visible/enabled로 동일 target을 증명한다. action/input/path/expected/new popup/navigation 변경, visual-only/canvas/rotation/크기 변경·불명 dispatch는 MVP 범위 밖이다.
- `HealingService.propose(context) -> HealingProposal`, `validate_healing_proposal(proposal, observation) -> HealingDecision`, `apply_runtime_override(accepted, control) -> ActionObservation`을 사용한다.
- override는 해당 ITEM/attempt/package에 append한 부속 사실이다. proposal은 불변 diff/근거이며 `POST healing-episodes/{e}/repair-proposals`로 저장한다. 채택은 rerecordings의 repair_proposal_id→새 전체 REC→OFF trial→사후 승인이다. 기존 code/default/suite/export 변경0이다.

## C08 · review·approve·재녹화

```text
ReviewSnapshot = {id, case_version_id/hash, source_manifest_id/hash,
 trial_case_run_id/final_result_hash, evidence_entries, evidence_set_hash,
 expected_current_approval_id?, created_commit_seq}
ReviewEvidenceEntry = {owner_kind: REC|ITEM, owner_id, attempt_id, action_id,
 artifact_ref_id, role, expected_hash, evidence_digest}
ActionReviewInput = {review_id, entry_key, evidence_digest,
 state: reviewed|needs_change|evidence_missing, comment}
ApprovalInput = {review_id, version_hash, evidence_set_hash,
 expected_current_approval_id?, reason}
RerecordInput = {base_case_version_id, input_case_version_id, input_manifest_hash, expected_draft_head?,
 reason, resource_id, repair_proposal_id?}
```

recording/storing 중 review/approval은 없다.
completed source + complete procedure/evidence + ready exact package + 같은 hash의 **OFF/actor0/PASS trial** + 필수 action review + evidence 가용성을 요구한다. 명시 AI verifier 사용은 허용한다.
source REC와 trial ITEM의 A001은 별도 entry다. owner/attempt/action/artifact 경로를 transaction에서 검사하고 표시 번호만 맞추지 않는다.
review30일 pin/연장 append, 승인은 approved event+source/trial/package required pin+default pointer+audit의 원자 CAS다. 실패 시 rollback, 옛 승인을 자동 철회하지 않는다.
반려는 reason/actor/time/hash를 남기고 기록/옛 default를 유지한다. 새 버전에 옛 review/approval을 복사하지 않는다.
철회는 별도 event, 현재 default면 null/no fallback, exact old approval의 queued는 BLOCKED·running 취소를 영구 기록한다. 과거 terminal은 불변, pin release+90일 유예·다른 유효 pin은 유지다.
재녹화는 같은 AUT의 전체 흐름·새 input/output version·base/reason이며 default를 유지한다. latest draft는 CAS, 늦은 finish는 branch다.
`request_review`/`review_action`/`approve_case`/`reject_case`/`revoke_approval`은 이 exact snapshot을 소비한다.

## C09 · RUN/ITEM·묶음·결과

`ExecutionSelection = {items: list[ExecutionItemChoice]?, suite_version_id?}`다. choice는 `{entry_id, case_version_id, approval_id?, dataset_version_id?, row_id?, environment_revision_id, resource_id, install_policy}`다. preview가 hash와 승인/policy/binding/secret ref revision을 고정해 resolved_items로 반환한다. 접수의 `items`는 `ExecutionItemInput = choice + {manifest_hash, replay_package_id, replay_package_hash, healing_policy_hash}`다. manifest_hash는 CaseVersion.content_hash와 대조하는 wire 이름이고 client approval_id는 preview/exact scope와 일치할 때만 쓴다. request에 exact_items라는 별도 필드는 만들지 않는다.

```text
ExecutionPreviewInput = {name, purpose: trial|regression|reverification,
 source: single|selection|suite|rerun, selection: ExecutionSelection, self_healing_enabled:false,
 release_label?, failure_policy, exclusions, rerun_reason?}
ExecutionPreview = {preview_hash, resolved_items, exclusions, blockers,
 proposed_N, resolved_approval_ids, snapshot_hashes, expires_if_inputs_change}
ExecutionCreateInput = {preview_hash, name, purpose, source, items: list[ExecutionItemInput],
 exclusions, self_healing_enabled, release_label?, failure_policy}
ExecutionReceipt = {execution_id, item_ids, job_ids, committed_seq}
CaseRunFacts = {case/version/verification/package hashes, approval_id?, data/env/target/build,
 status, verdict, disposition, display_result?, first/latest_attempt, violations,
 requested_at, created/finalized seq, healing_used/outcome, unassisted_pass, role_usage}
ApprovedHealingPolicy = {allowed, default_enabled:false, scope, model_binding_ref,
 max_episodes_per_item:1, max_model_calls_per_item:2, max_seconds:30}
ResolvedHealingPolicy = {requested_enabled, effective_enabled, approved_policy_hash,
 effective_limits, binding_revision, resolution_hash}
```

- preview는 예약이 아니다. enqueue/claim에서 exact approval/revoke·package/policy/data/env/실제 환경을 재검사한다. client의 임의 approval 값을 신뢰하지 않는다.
- trial은 승인 불필요/OFF 강제, 정식은 exact 유효 승인 필수다. 유효 과거본 명시 선택은 사유와 함께 허용하고 최신으로 자동 교체하지 않는다. 한 RUN에 trial/정식 혼합은 없다.
- RUN+전체 ITEM/jobs+명시 exclusions+receipt는 원자 생성이다. ITEM=case version×data 행×target, N1..100, N0/101이상422다. 제외는 범위 확정 전 명시 확인, 확정 후 미실행은 NOT_RUN 등으로 분모 안이다.
- suite는 exact version/hash/approval·entryID/data/env/순서/failure policy의 불변 revision이다. 새 승인 알림은 diff만, 명시 새 suite revision으로 교체한다. mixed는 target별 resource 필수·암묵 의존/병렬 없음이다.
- continue는 안전한 다음 항목, stop_on_non_pass는 나머지 NOT_RUN이다. 사용자 취소 CANCELLED, 미시작 skip은 SKIPPED/자원 없음, running skip409다. 모든 ITEM terminal 뒤 부모 terminal이다.
- 필수 위반은 FAIL latch 최우선이다. 위반 없고 전제 환경/사람 입력 불가면 BLOCKED, 실행/증거 불명이면 INCONCLUSIVE, 모든 필수 현재 check/path 만족이면 PASS다. REC/관리 QA는 항상 null이다.
- terminal display7종은 PASS/FAIL/BLOCKED/INCONCLUSIVE/SKIPPED/CANCELLED/NOT_RUN, +진행=N이다. FAIL+cancel은 FAIL1회, healed PASS는 PASS 안 badge이며8번째 결과가 아니다.
- 완료율=terminal/N, 검증통과=P/(P+F), 전체통과=P/N, 미검증=B+I+SKIPPED+CANCELLED+NOT_RUN이다. 분모0은null/산출불가다. N10/P6/F2/B1/NOT_RUN1→100%/75%/60%/미검증2다.
- unassisted_pass=PASS이면서 action error/retry/recovery/healing 없음이다. verifier 사용은 별도 축이다. 새 rerun은 새 RUN/ITEM+원본/root lineage/사유이며 옛 FAIL은 불변이다.
- 월3000TC×1data×1환경은 최소30RUN을 release_label로 조회/집계한다. 3000 ITEM 단일 RUN/자동 batch 기능은 추가하지 않는다.

## C10 · 장기 facts·비교·as_of·export·보관

- parent requested_at의 UTC[from,to), UI는KST다. REC/관리 제외·trial 기본 제외, attempt retry1관측/rerun새관측이다.
- project commit seq는 변경과 같은 transaction이다. created seq≤as_of만 분모, finalized seq≤as_of만 terminal, actual fingerprint/usage도 관찰/정산 seq 이전만 쓴다. 미래 값을 과거에 소급하지 않는다.
- series=(project,case,verification_digest,target,env profile revision,data fingerprint,oracle policy)다.
- strict는 series+actual build/device OS/browser/viewport DPR/engine patch/model prompt+package/runtime/lock+요청 healing ONOFF/policy+verifier method/binding이다. key schema version을 고정하고 secret 원문 hash는 제외한다.
- all_observations 기본, latest_terminal은 strict마다 requested_at/executionID/ITEMID 순 마지막1개다. 더 최신 진행은 별도 badge다. 혼합 조건은 명시 배너/내역, 검증 완화는 다른 series다.
- model 미사용 not_used와 실행/계측 불명 unknown을 합치지 않는다. NOT_RUN/준비 전 취소 duration=null, p50/p95는 관측 수/조건과 함께 표시한다.
- export는 CSV/printable_html만, as_of/criteria/filter/cohort/source IDs/생성UTC를 고정한다. 늦은 정산으로 덮지 않고 secret/hidden reasoning 제외·CSV 수식/XSS 안전화를 적용한다. localhost 링크를 공개 공유라고 표시하지 않는다.
- core facts/approval/lineage/manifest/hash/ledger는 project 보관 중 장기, detail90일/PNG log30일/ACK spool7일/정제 debug24시간이다. provenance와 active pin은 별개다.
- 유효 과거 승인도 package/source/trial required pin이며 default 교체로 해제하지 않는다. review30일 연장 가능·철회90일 유예다. GC는 무보호 ready만 claim→delete_pending→파일삭제→tombstone이다.
- 전체 파일20GB(project 합산 파일 저장소)/REC·ITEM500MB 제안이다. 보호 파일을 몰래 지우지 않고 새 행동 중지/부분 저장한다. archive는 이력을 지우지 않는다. 파괴적 이력 purge UI는 MVP 밖이며 별도 요구/영향 승인으로 다룬다.
- 백업은 local_owner 전용 ‘이 PC 전체 저장소’ 작업이다. project URL은 요청 이력 namespace이며 project-only 백업을 의미하지 않는다. API 소유 storage service가 SQLite online snapshot+project별 commit cursor map+ready artifact manifest/hash+GC 임시 중지/보호를 만든다. worker는 목적/만료/manifest로 제한된 HTTP bytes 복사만 하고 SQLite를 열지 않는다. 비공개 backup receipt/파일은 일반 project artifact 조회로 노출하지 않고 owner 전용 endpoint로 받는다. 누락은 incomplete·OS secret 평문 복사 금지다.
- 복원은 local_owner 전용·PC 전체 영향이다. 별도 경로에서 schema/FK/integrity/hash/누락 검증→모든 project 진행 작업 정리→API storage 유지보수 모드의 명시 활성화다. 옛 queued/running 재투입0·lease/token/session 폐기·resource quarantine→probe·key 재설정, 과거 QA 불변이다.

## C11 · 추가 route와 UI 책임 경계

root UI_SPEC §7 route를 계승하고 빠져 있던 route를 아래처럼 고정한다. project scope/CSRF/receipt는 C01을 따른다.

| 조작 | route | 담당 |
|---|---|---|
| 선택 기기 화면 | GET resources/{r}/preview, 없으면 POST resources/{r}/probes | W11-01 / W11-07 |
| 설치 앱 관찰 | POST resources/{r}/probes kind=installed_apps | W11-04, physical lease 필수 |
| 원 source 재컴파일 | POST recordings/{r}/package-rebuilds | W16-07 / W29 |
| 시범/정식 | POST projects/{p}/execution-previews, POST projects/{p}/executions | W17-01 / W20 |
| 제안 diff 수락 | POST cases/{c}/proposal-acceptances | W10-07 / W16-02 |
| 묶음 갱신 후보 | GET suites/{s}/upgrade-proposals | W21-03 |
| 검토 보호 연장 | POST review-requests/{r}/retention-extensions | W18-05 |
| 수정 제안 저장 | POST healing-episodes/{e}/repair-proposals | W31-05 |
| 분석 | GET/POST case-runs/{i}/analysis-records | W23-03 |
| pin/해제 | POST artifacts/{a}/retention-protections, POST retention-protections/{p}/release | W26-02 |
| 공간 계획 | GET projects/{p}/storage, POST projects/{p}/retention-previews | W26-03 |
| 백업/복원 | POST projects/{p}/backups, GET backups/{b}, GET backups/{b}/download, POST backups/{b}/restore-validations, POST restore-validations/{v}/activations | W26-04 / W26-05 |
| 모델 검사 | POST model-bindings/{b}/checks, GET model-bindings/{b}/compatibility | W15-04 |
| 활동/worker | GET projects/{p}/audit, GET projects/{p}/workers, POST projects/{p}/worker-enrollments, POST workers/{w}/revoke | W11-08 |
| project event | GET projects/{p}/events?after_commit_seq= | W12-02 |
| attempt event | GET attempts/{a}/events?after_local_seq= | W08-04 / W12-02 |
| 로컬 상태/종료 | GET local-status, POST local-shutdown | W12 |

기기 선택 시 화면은 권한 있는 최근 정제 capture+시각이다. busy면 읽기 권한 있는 session만, 미관찰/만료는 사유를 표시한다.
MVP는2초 polling 관찰 화면이며 live video/수동 원격 제어는 후속이다. 읽기 preview도 lease 없이 ADB/CDP를 호출해 만들지 않는다.
UI04/07/11은 EvidenceViewer/PackageView를 공유하되 owner/version을 명시한다. 화면 부품을 공유한다고 source/trial 실체를 섞지 않는다.
UI15의 global/default 변경은 case 승인 범위를 확대하거나 진행 snapshot을 변경하지 않는다.

## C12 · 제안·메모·관찰의 영속 소유 보완

- `case_edit_proposals`: project/case/base version/hash·kind(structure|tc_import)·정제 body/hash·source_job_id 또는 tc_version_id. 같은 case structure job 또는 같은 project TC만 연결한다. raw model reasoning/secret은 저장하지 않는다.
- `case_proposal_decisions`: proposal_id·accept/reject·actor/time/commit_seq·produced_case_version_id nullable. 수락은 proposal/hash/expected_head 검사+새 version+decision+audit 원자 확정, proposal당 수락1·동일 key/receipt·stale409다. 거부는 case 내용 변경0이다.
- `recording_notes`: project/REC/id/actor/time/commit_seq/text/request_key. browser 메모는 worker local_seq를 배정하지 않고 별도 append만 한다. 검증 목표/제어/approval hash를 바꾸지 않는다.
- `resource_observations`: project/resource/probe_job/attempt/captured_at/geometry/scope_hash/artifact. 읽기 capture이며 actual action의 before/after 대체 불가다. artifact_refs의 resource_observation_id를 정확히1 owner CHECK에 포함한다.
- manual protection release는 manual만 처리한다. approval/review/backup/build 보호는 해당 도메인 수명 API에서만 해제한다.
- 보완 소유는 W06-01(notes), W06-08(observations), W06-09(proposals)다. UI/API 소비 전에 완료해야 한다.

백업 내부 전송은 `POST worker/jobs/{j}/backup-snapshots`, `POST worker/jobs/{j}/backup-completions`로 분리한다. 유효 generation·purpose=backup·owner의 전체 저장소 grant·정확한 manifest/receipt만 허용하며 일반 worker token으로 live DB/임의 파일을 읽게 하지 않는다. DB snapshot은 API 저장 계층이 만들고 worker는 opaque bytes만 다룬다.

W04-03은 worker/enrollment 기본 schema, W06-10은 전역 물리 자원 key/project 별칭, W06-02는 해당 key를 참조하는 lease/job/attempt를 소유한다. 자원 inventory 서비스보다 먼저 FK 대상 schema를 확정한다. 결과7종/비율의 순수 kernel(W23-01)은 W06-06 뒤에 구현해 W09/시범/UI의 첫 사용 전에 준비한다. 전체 리포트 UI는 W22 이후 별도 작업이다.

FK 대상 schema는 소비 service보다 먼저 만든다. W05-02=case/folder/tag 기본, W05-04=TC, W05-05=env/data/model binding, W06-02=suite/entry+RUN/ITEM/job/attempt/lease, W06-04=artifact/protection+app_builds/backup_receipts/manual_retention_requests, W06-06=장기 facts+analysis_records다. 실제 동작 서비스는 후속 담당에 남긴다. W06-07은 모든 FK 대상 존재 및 nullable FK를 가진 실제 insert를 검사해 미래 테이블 누락을 잡는다.

서로 FK를 참조하는 schema 카드(W06)는 전체 부모 구현 전에도 test-only 부모 key fixture를 갖춘 독립 SQLite에서 해당 CHECK/UNIQUE/불변 제약을 검사할 수 있다. 이 fixture는 제품 migration/부모 구현을 대체하지 않으며 foreign_keys를 꺼서 통과시키지 않는다. 실제 DB 통합 PASS는 모든 해당 정의가 있는 canonical migration head의 upgrade/FK/integrity/insert 검사(W06-07)다. W06-08/09 추가 후 같은 전체 검사를 재수행하고, W07은 마지막 W06-09 통과에 의존한다. 따라서 schema 카드의 단위 PASS와 제품 DB 통합 PASS를 인계에서 구분한다.

## C13 · 먼저 만드는 최소 실행 기반

W00-01→W00-02→W00-03→W00-04가 첫 구현 경로다. 기존 W01-01 완료와 W01-02 차단은 보존한다.
초기 기반은 VM/USB/모델 키 없이 구현·검증하며 실제 DB/domain/worker/agent 기능은 후속 작업이다.

- W00-01: Python3.11 기준 src-layout·distribution `aiqa`·editable install·최소 runtime(FastAPI/Uvicorn/Jinja2)/dev(pytest/httpx)·전이 버전 constraints `requirements.lock`·pytest를 구성한다. 현재 src/tests/conftest·완료 probe를 읽고 필요한 차이만 수정한다.
- install 재현 명령: `python -m pip install -e ".[dev]" -c requirements.lock`, `python -m pip check`. lock 생성 도구/명령·실제 Python/OS/버전을 W00-01 인계에 남긴다. 현재 문서 작성에서 실행하지 않는다.
- 과거 source 조사용 코드가 일부 존재한다. package import가 pytest의 sys.path 보정에만 의존하지 않게 하고, 저장소 밖 cwd의 editable import와 기존 W01-01 선택 회귀를 확인한다.
- 최소 기반 lock에 Mobile-Agent/CUAWright/model SDK·VM/ADB를 넣지 않는다. W03-02가 나중에 실제 호환 검증 후 필요한 의존성만 확장한다. key/비밀번호를 pyproject/lock/.gitignore 예시에 쓰지 않는다.
- product runtime 경로는 비동기화 LOCALAPPDATA/AIQA다. 초기 import/health/page는 DB나 외부 client를 만들거나 실제 기기를 관찰하지 않는다.

```text
AppSettings = {host: "127.0.0.1", port: int(default8000), runtime_root: Path}
load_settings(env: Mapping[str,str] | None = None) -> AppSettings
create_app(settings: AppSettings | None = None) -> FastAPI
GET /api/v1/health -> 200 {"status":"ok","component":"api"}
GET / -> Jinja2 기본 실행 안내 HTML
GET /static/app.css -> CSS
```

- 환경 이름은 AIQA_HOST/AIQA_PORT/AIQA_RUNTIME_ROOT다. 개인 MVP bind는127.0.0.1로 제한하고 잘못된 host/port를 명시 거부한다.
- health는 API process liveness만 뜻한다. DB/worker/VM/모델/device/QA의 준비·PASS가 아니다.
- C01 인증 도입 전 공개 범위는 비밀/업무 데이터 없는 GET health/기본 페이지/static뿐이다. 업무 mutation과 project/REC/RUN API를 fake 성공으로 제공하지 않는다.
- 기본 페이지는 새 제품 server의 template/static 연결을 확인하는 화면이다. prototype의 localStorage/가짜 device/승인/통계를 옮기지 않는다. HTMX 동작과 실제 메뉴는 W10부터 확장한다.
- template/static은 package-data로 포함해 cwd 밖에서도 동작해야 한다. 기존 app factory/layout을 W04/W10이 확장하며 두 번째 앱/샘플 서버를 새 사실 원천으로 만들지 않는다.
- 기본 CLI: `python -m uvicorn aiqa.api.app:create_app --factory --host 127.0.0.1 --port 8000`. W12가 이 실행 경로에 일상 launcher·worker/process 수명 관리를 붙인다.
- W00-04는 테스트가 소유한 subprocess와 loopback HTTP로 시작/health/page/static/종료/port 해제를 검증한다. 다른 process를 종료하지 않고 실제 browser 확인을 남긴다.
- baseline은 bootstrap 검사들과 기존 W01-01을 선택 실행한다. W01-02의 알려진 차단 시험을 삭제/성공 조작/자동 skip해서 전체 suite green으로 표시하지 않는다.
- 뼈대 작업이 모두 끝나도 네이티브 engine 검증을 완료로 올리지 않는다. W00 인계는 local app 실행 근거만 남긴다.

## C14 · 차단된 가지와 독립 구현의 진행

Current/우선순위는 NEXT_ACTION, 직접 선행·환경 요구·검증 등급은 TASK_INDEX가 소유한다.
과거 A→B 전체 직렬 gate 대신 **실제 interface/fact를 소비하는 선행**으로 좁힌다.
VM/key/device 부족은 그 환경을 쓰는 가지와 최종 수용만 막는다.

### 선택·전환

1. 현재 작업의 code/검증 결과를 기록한다. 환경·권한·quota 등 외부 조건 때문에 진행 못 하면 blocked와 원인/재개 조건/근거를 남긴다.
2. blocked를 complete로 바꾸거나 의존 작업을 임의로 열지 않는다. 후보는 미완료·blocked 아님·직접 선행 전부 complete+실제 인계 존재인 작업이다.
3. `environment_requirements`에 알려진 unavailable 조건이 있으면 준비 후보에서 제외한다. unknown은 가벼운 사전 확인으로만 판별하고 같은 알려진 부재 검사를 반복하지 않는다.
4. Next 중 준비된 작업을 먼저 고른다. 없으면 TASK_INDEX를 로컬 코드로 필터해 bootstrap→core→환경 준비된 integration 순으로 후보 요약만 조회한다. JSON 전체/과거 audit를 context에 출력하지 않는다.
5. 선택한 ID/이유를 Current에 올리고 차단 항목은 외부 대기 절에 남긴다. 이전 Current가 차단되어 있어도 독립 후보로 넘어간다.
6. 독립 후보도 없으면 조건/준비 결과를 보고한다. 실패한 task의 진짜 선행을 삭제하거나 fake PASS를 만들어 진행하지 않는다.
7. 알려진 환경 변경/사용자 제공/새 evidence가 생겼을 때 해당 blocked 가지를 재평가한다. 환경 설정을 몰래 변경·구매·권한 확대해 해소하지 않는다.

### 검증 등급과 완료 의미

- `bootstrap`: 최소 Python/app/page/process의 실제 실행. VM/key/device가 필요 없다.
- `core_contract`: 실제 API/SQLite/파일/브라우저/host process로 계약·상태·불변성/오류를 검사한다. 외부 관찰/모델 응답은 tests 전용 fixture/transport/provider를 써서 경계 조건을 재현할 수 있다.
- `source_audit`: pinned source/위치/hash/라이선스 근거. 실제 엔진 실행과 구별한다.
- `live_integration / tool_integration / integration_gate`: 해당 VM/USB/provider/도구의 실제 evidence가 필수다. 없는 환경은 blocked이며 contract fixture가 대체하지 않는다.
- `final_gate`: 모든 관련 실제 검증과 UI/DB/QA/비용·격리가 충족된 최종 수용이다.

core 완료를 위해 fixture를 product runtime·일반 프로젝트 DB에 넣지 않는다. tests 전용 DB/파일/관찰임을 인계에 명시한다.
생산 경로에서 adapter/호환 모델/필수 근거가 없으면 명시 unavailable/BLOCKED/unknown을 반환한다.
초기 core UI의 진짜 기능은 조회/편집/원자 접수·차단 사유/이벤트/분석 등의 계약이며, native 미구현을 성공 callback/no-op/가짜 화면으로 채우지 않는다.

카드의 `live_acceptance_tasks`는 core 계약 이후 실제 엔진으로 수용할 담당이다. 해당 실제 조건은 이관해 유지하며 삭제하지 않는다.
W13의 실제 capture는 W16-04/W29-03/W30-03, W17–19의 실제 source/trial/승인은 W17-04/W19-04,
치유는 W31-07, 실제 mixed 수행/리포트는 W22-04, 장애/품질/비용은 W27/W28/W32에서 요구한다.
W31-06은 관리 UI/기록 계약, W31-07은 실제 치유 gate다. 일반 actor0·필수 FAIL 유지·불명 재dispatch금지·원본 불변은 모든 등급에서 그대로 적용한다.

상위 W 완료는 소속 leaf 전부 + `parent_gate_tasks` + 원래 상위 통합 조건을 만족해야 한다.
따라서 core leaf가 진척되어도 live gate가 남은 parent와 MVP는 미완료다.
known_environment는 **문서상의 환경 관찰 메모**이지 실행 worker capability 증명/설정이 아니다. 실제 실행 전 preflight/claim 재검증을 그대로 수행한다.
