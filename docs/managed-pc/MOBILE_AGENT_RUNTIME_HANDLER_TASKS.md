# MA04c1 · Original runtime handler Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL superpowers:executing-plans inline master; TDD. BASEd99eb64.

Goal: normal pinned Android claim→case/serial/current fence→selected app preparation→original session→HandlerResult ready for existing runtime finish.
Architecture: new worker/mobile_agent_handler.py OriginalAndroidRecordingHandler subclasses existing AndroidRecordingHandler only for shared context/binders/gate. Override handle (no old planner loop). Owned client/runtime root, canonical attempt directory before any preparation. Exact engine only, no default switch in this unit.
Tech: existing Python/FastAPI/HTTPX/Pillow/ADB typed ports.
Spec: MOBILE_AGENT_SERVER_WIRING_TASKS.md MA04, CONTRACTS C04/C05/C06 and AI-LIVE-04-MA04B2.

Global constraints: original master approved, no actual paid/device I/O; source-v2 immutable physical ACK; unknown retry0; save→human approve separate; existing fixture/Web unmodified; no DB open in worker; owner/pin/case/serial/time/lease before side effect. Full RX87 stays incomplete.

Review Focus: missing remote fence/preparer invalid claim must have0 I/O; preparation consumes native/time cap; pure local allowed avoids HTTP polling and charging native twice; failed post-preparation/session preserves known ACKs/IDs and no ready mapping; repeated canonical attempt path blocks preparation as well as model/native.

Task1 interfaces: new handler consumes same AndroidRecordingContext, guard, driver, target preparer and client's HTTPS ports; session gains worker_actions/worker_seconds caps narrowed against claim; result gains separate before_artifact_ids, populated from validated MobileAgentWorkerTurn.before_artifact_id, preserving existing artifact_ids meaning. Produces HandlerResult source_artifact_hashes including preparation+before+after/log/source IDs. C1 is callable via existing runtime binders by subclass, C2 selects it in operational factory and publishes engine support/admission.

- [x] RED tests/integration/test_ma04_mobile_runtime_handler.py normal Android marked case actual upstream+ASGI/fake OpenAI/ADB/app launch→HandlerResult→real runtime finish stores unapproved manifest;0 side effect missing fence/preparer/serial/case, action cap1 before preparation, no same-attempt restart, denied before_dispatch no native, preparation elapsed cutoff no model. Expected initially missing module.
- [x] Implement handler/session cap and model-before identity plumbing; map only before_native→before_dispatch (charge once), before_model→before_model, rest→before_lookup. Prepare checkpoints use before_lookup and final launch wrapper before_dispatch. Parent allowed local cancel/time/keepalive.failed only; HTTP gates at boundaries. Reserve preparation action and elapsed time, canonical project/attempt directory before launch; failures return error preserving count/ACK IDs/cursor.
- [x] Focused handler/session/model/target/keepalive tests green, one fresh review + single TDD fix pass, docs/contracts/NEXT/local commit. Then immediately C2 factory/admission and normal end-to-end journey. Cost/RX29 not prerequisite.

Ruling: inheritance reuses only gates/binders/context, not the legacy planning loop. Cost: changes to shared base contracts require these integration tests. Default remains legacy until operational registration/admission C2.

인계: [AI-LIVE-04-MA04C1](../validation/tasks/AI-LIVE-04-MA04C1.md). 최종108pass. 다음 C2 운영 등록/admission.
