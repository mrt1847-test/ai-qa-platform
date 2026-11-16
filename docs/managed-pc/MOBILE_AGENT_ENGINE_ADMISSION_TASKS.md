# MA04c2 · Original engine registration and admission Implementation Plan

> REQUIRED SUB-SKILL superpowers:executing-plans inline/TDD. BASE040867d master.

Goal: operational Android worker actually selects OriginalAndroidRecordingHandler, publishes exact supported engine/protocol with current boot, normal server REC admission freezes that engine only for supported worker/OpenAI Luna. Explicit fixture/Web remain separate.
Architecture: new worker/mobile_agent_registration.py adds/removes engine capability inside existing authenticated inventory permissions JSON (no schema/secret); runtime reports only actual recording route's verified original source. New recording/mobile_agent_admission.py reads chosen project's physical alias/inventory/current worker presence, exact ref+boot and immutable binding revision. service passes selected resource to same freeze for REC/rerecord; idempotent retry preserves original pin. Factory selects new handler. No live API/ADB or default model changes.
Spec: MOBILE_AGENT_SERVER_WIRING_TASKS MA04, AI-LIVE-04-MA04C1 and CONTRACTS C04/C05/C06/C14.

Review Focus: stale prior boot or unsupported engine never inferred from generic ready; original ref cannot be provided by browser; binding provider/model/endpoint metadata only no key reads; fixture/Web/unmarked old pins maintain exact bytes; actual WorkerRuntime ack/keepalive/finish/cleanup path reaches saved unapproved version without old planning loop.

- [x] RED normal Android OpenAI Luna ready capability gets exact hash-covered marker, missing/stale/bad capability or unsupported model/endpoint refuses with0jobs; fixture/Web unchanged. Operational factory returns new handler and no legacy plan_provider. Inventory strips forged/stale fields unless actual original recording route+verified source+prepared adapter and current boot. Source mismatch advertises no original capability. Fresh boot mismatch blocked.
- [x] Minimal modules/runtime/factory/service wiring; capability shape authoring_engine exact ref + authoring_engine_boot_id matches presence. No new DB table/migration. Android original requires OpenAI gpt-6-luna official endpoint; fixture worker+fixture binding stays unmarked. Cache request reuses old engine after inventory changes. Existing internal original test fixtures must declare actual new support rather than bypass admission.
- [x] Actual runtime cycle fixture original child+normal API control/finish stores manifest/package,0approval; focused admission/resource/model/handler regression; one fresh review + single TDD fix pass; docs/contracts/NEXT/local commit. Next MA05 stored review/approval/replay, remaining RX87 validation/healing/UI.

완료 인계: [AI-LIVE-04-MA04C2](../validation/tasks/AI-LIVE-04-MA04C2.md). Focus106pass, 전체와 후속은 인계/기준선에 분리 기록. 다음 MA05a failure evidence.
