# MA04a · 원본 worker model callback와 관찰/증거 경계

> Use executing-plans/TDD inline original master. BASE5f141d4. Spec MOBILE_AGENT_SERVER_WIRING_TASKS.md MA04 + execution/CONTRACTS.md MA03b. No paid/device calls or default admission switch.

Goal: parent-owned model callback for run_mobile_agent_process -> existing HTTPS worker model API. Worker never owns model API key, never forwards child system/messages, never treats model response as native ACK.

Files: worker/mobile_agent_models.py MobileAgentModelPort(client,claim,token_output_limit=512), immutable MobileAgentWorkerTurn, controlled ModelPortRejected; worker/model_observations.py marked engine uploads role=before/action_id=ma-call UUID (legacy source upload unchanged). Tests integration/test_ma04_mobile_model_port.py using normal marked REC/claim/PNG/DB/model fixture and MockHTTP; no native/real provider.

Interface: __call__(request,current frame from RPC,*,before_send)->str. Validate exact engine pin, root/snapshot identity, nonsecret intent; frame=MobileAgentModelFrame (PNG/geometry/IDs only), per-claim cap and source ID uniqueness, no concurrent/reentrant calls. Assign call UUID, upload before ACK and bind observation with existing helper, then invoke boundary once immediately before request_model. Check returned allowed/action flag/role/purpose/call/attempt/generation/model/observation/image identities. Preserve immutable receipt for logs, pending turn until post evidence ACK. Any preparation/model/receipt failure latches stopped with no retry. local requests counter is API attempts, not billed calls.

accept_evidence(call_id,receipt,after_id,log_id) accepts matching pending call, same attempt, late=false and exact distinct server artifact IDs; clears pending only after evidence acknowledgement. Server independently verifies log/native/source before next call, so this local receipt is not authority token. Finish stops further calls. Native/wait evidence uploader and actual runner/journal/finish registration are MA04b/c.

- [x] RED normal port -> ma-call before + server original context + checked receipt, no child messages uploaded; pending prevents next model until actual after/log commit; mismatched receipt/late proof/sensitive intent/cancel/no key role; source cap/reentrancy as applicable.
- [x] Minimal implementation + marked uploader branch. Preserve legacy observation role/naming, worker credential stays client-side. No arbitrary shell/local env/key lookup.
- [x] One fresh review/fix pass and model/observation/source pipeline regressions, handoff/queue/contracts/local commit. Not whole web/main recording acceptance.

Review focus: no model/native resends after uncertainty; callback boundary ordering vs uploads; receipt scope/hash identity and immutable claim/turn; simultaneous calls and pending ACK; legacy uploader compatibility. Ruling: tests use existing client HTTP transport and only synthetic credentials; actual capture/driver remain later.

완료: ../validation/tasks/AI-LIVE-04-MA04A.md, 집중51passed46.19s. fresh ACK의 동일 upload 연결은 MA04b uploader, 실제 handler/admission 등록은 MA04b/c다.
