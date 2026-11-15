# MA03b · 서버 소유 원본 Mobile-Agent 대화

> Use superpowers:executing-plans/TDD inline on authorized original master. BASE f9ceed7. Spec: MOBILE_AGENT_SERVER_WIRING_TASKS.md MA03b and execution/CONTRACTS.md C04/C05/C06/C14 + MA02/MA03a. No paid/device calls, source/proof unchanged.

Goal: construct the actual pinned original SYSTEM_PROMPT/build_messages/history from frozen server intent and server-owned observations/settled outputs. Never trust worker conversation, image URLs or filesystem paths. Send1000×1000 PNG frames/one final original action via existing OpenAI transport. Preserve non-Mobile-Agent calls and all admission/secret/usage boundaries.

## B1 · pure context and explicit server port

Files: models/mobile_agent_context.py for frozen MobileAgentHistoryTurn(output,observation?) and immutable MobileAgentContext JSON, build_mobile_agent_context(intent,current,history,model). openai_server.py optional mobile_context only for authoring/gpt-6-luna, no observation/other sanitized inputs in that mode. Tests unit/test_mobile_agent_context.py + integration/test_ma03b_openai_context.py.

- [x] Write RED tests for original system/history/summary, frozen objective/check/variables/path policy, PNG1000 square + final_answer, last4 image history with text summaries before it, no filesystem image reads, invalid hash/PNG/geometry, secret-ref refusal, duplicate/unsupported/terminal history rejection, bounded history/goal/response, original inputs not mutated.
- [x] Implement using load_protocol verified bytes and in-memory ProviderObservation. Validate all consumed images; no raw capture reasoning. Old summary-only frames need not carry pixels, last4 require them. Validate original tool with strict JSON uniqueness/one block + original parser and upstream_action. Return JSON snapshot to avoid mutable alias. Provider accepts exact context type; all invalid context is unsent, existing single-frame behavior preserved.
- [x] RED/GREEN mocked Responses actual request integration: exact original system, ordered old outputs/current images, no raw URL/path, structured mobile action format, sent counters/usage; no downgrade to another model/role, no arbitrary tuple/dict context, no mixing legacy fields; cancellation before send0; immutable context survives later source dict mutation.
- [x] One fresh read-only review; one Important/Critical TDD fix pass, focused upstream/OpenAI/server regression, handoff/queue/contracts/local commit. Not normal web/handler/DB ACK acceptance.

## B2 · durable authoritative history and engine admission

### B2a · source-pinned engine contract

BASE4ed74fb. Files contracts/mobile_agent_engine.py (dependency-free exact commit/manifest/RPC protocol ref), adapters/mobile_agent_upstream.py (reuse same constants), contracts/authoring.py (hash optional authoring_engine and reject incomplete/unknown marker), recording/model_pin.py (explicit internal engine_ref snapshot), tests/unit/test_mobile_agent_engine_pin.py. Preserve every legacy policy hash when no marker. Snapshot copy must not retain mutable caller dictionaries. Do not enable new protocol for legacy workers; actual admission/handler selection remains B2b/MA04.

- [x] RED tests exact source ref/manifest equality; independent copies; wrong version/hash/protocol/extra fields/null refusal; engine change affects policy hash and partial markers never legacy; legacy known policy hash unchanged; existing pin validator accepts new valid marker.
- [x] Minimal implementation and focused authoring/claim regressions; one final read-only batch review/fix, handoff/local commit.

### B2b · authoritative DB producer and gateway

B2b0 (BASE0e434dd) internal gateway transport first: handle/_admit accept server-only mobile_context, include immutable context in idempotency fingerprint, require exact OpenAI/authoring/recording/Luna and no mixed observation before secret/send; broker admission still uses original frozen request inputs but context transport sends its own complete conversation. Keep worker DTO/HTTP parsing unchanged. Tests integration/test_ma03b_context_gateway.py with existing server secret/gateway fixture, cancellation, measured usage, context collision, unsupported provider/role/model, no durable normal-engine claim. B2b1 next is DB proposal/native ACK producer + endpoint/source admission; do not enable default or skip that gate.

- [x] B2b0 RED mocked gateway tests → code → focused regression/review/handoff/commit. No DB admission or native ACK claim.


B2b1 (BASE7149d97): implement models/mobile_agent_history.py and integration/test_ma03b_mobile_history.py. Pure producer first, then normal endpoint dispatch. Query current authorize_recording/intent/exact engine; select <=80 charged same-attempt receipts; exclude only own matching pending reservation; reject paid error/unknown/late/foreign policy/worker. Every prior nonterminal response must reference same-call registered observation and same-action `ma-<call UUID>` before/after/log ready artifacts. Native acknowledgement log exact schema mobile-agent-step-v1: call_id/action_id/state=observed/native_calls(1 or wait0)/native(asdict typed physical action or null)/before_image_hash/after_image_hash. After+log IDs must appear together in a completed current-worker evidence commit. Current observation registration must follow that ACK. Revalidate owned artifact hashes outside DB writers, current authority after reads, return immutable context+source fingerprint. Native evidence is trusted authenticated worker ACK, never a model-success claim or actual human QA assertion. No DB schema change/no default engine enable.

- [x] B2b1 producer RED scoped normal REC/claim/image/receipt evidence tests: empty history, actual same-action ACK chain, missing ACK, paid failure/pending, foreign worker/policy, log tamper, wrong native args, old-history TTL allowed but current freshness required, no writer across file/Pillow I/O. Then code/review/focused regression/handoff.

- [x] Read only same project/attempt/worker/policy/source-pinned engine receipts, validate successful permitted model replies and correlate stored observations. Refuse pending/unknown/late/terminal histories and out-of-order/duplicate captures. Native execution completion must be source-evidence ACK, not a model-success claim. Reuse current-frame authorization and immutable artifact hash validation without granting old images new action authority.
- [x] Build conversation outside DB writer transactions, recheck all pins at send. Explicit snapshot/engine marker must distinguish new original protocol from legacy worker parser; no silent behavior change. Gateway carries internal server context only, request DTO never carries worker system/messages.
- [x] Normal REC/claim/image ACK/receipt tests include restart/idempotency, foreign history, tamper, current control expiration, old history beyond current TTL, unsupported provider, measured usage. Integrate producer before MA04 worker registration.

Constraints: <=80 model steps, <=4 historical images + current, input PNG<=2MB each and original validated physical geometry, output input image1000square, Responses conversation cap5images/8MB. Model fixed user Luna. Goal from authoring_inputs plus path_policy, bounded; intent secret_refs fail closed. Plaintext secret coverage remains unavailable. Actual original main executes child in MA03a; pure loader alone is not a planner. No arbitrary file reads; no API key/env loading, retries, DB resets, approval auto-promotion. Supported source checkout/Pillow.

Review focus: history trusted provenance vs helper type; secret/image size/hash bounds and no raw metadata; strict action/terminal validation; original history summarization and final phase; mutable context aliases and pre-send billing.

B1 완료 근거: ../validation/tasks/AI-LIVE-04-MA03B1.md, 집중110passed16.47s. 다음 B2 DB 소유 이력·명시 engine pin/gateway 연결.

B2a 완료: ../validation/tasks/AI-LIVE-04-MA03B2A.md, 집중77passed24.82s. 기존 consumer는 새 marker를 전송 전에 거절하고 실제 default 접수는 유지한다. B2b producer/MA04 handler는 미완료.

B2b0 완료: ../validation/tasks/AI-LIVE-04-MA03B2B0.md, 집중42passed19.16s. B2b1 DB receipt/관찰과 same-action before/after/log ACK producer 및 정상 engine endpoint가 다음이다.

B2b1 producer 완료: ../validation/tasks/AI-LIVE-04-MA03B2B1.md, 집중73passed49.78s. ACK time은 staging created_at이 아닌 completed response의 server_committed_at이다. endpoint 선택/final-send fingerprint는 B2b2 미완료.

### B2b2 · normal endpoint context selection (BASE47855f7)

Files recording_authorization.py (server-only engine_kind from verified pin), recording_requests.py (marked grant -> producer -> gateway context; final history fingerprint and current policy/source at actual send; validate one original reply and preserve measured usage on invalid reply), mobile_agent_context.py (terminal-aware strict current reply validator, history still terminal-forbidden), mobile_agent_history.py (controlled recursive malformed output), tests/integration/test_ma03b_recording_endpoint.py. No worker DTO, default server admission or actual handler enable.

- [x] RED normal REC/claim/PNG/marked-engine API tests original prompt/current+history/schema, missing native ACK0 send, tamper at HTTP preparation0 send, invalid model action charged1/measured/no content, valid terminal not auto-approved, cached reply after native evidence action_allowedfalse while before evidence reuses freely.
- [x] Minimal branch outside writers, source recheck at before_send after HTTP build. Old unmarked path unchanged. Single fresh review/fix pass and changed-area regression/handoff/commit. Next MA04 engine-selecting worker/admission.

MA03b B2b2 완료: ../validation/tasks/AI-LIVE-04-MA03B2B2.md, 집중125passed82.42s. 다음 MA04a worker callback/ma-call frame/evidence 대기. default admission/실제 handler 등록은 함께 검증하기 전 유지한다.
