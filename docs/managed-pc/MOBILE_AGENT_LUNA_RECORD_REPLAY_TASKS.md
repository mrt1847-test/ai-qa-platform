# Actual Mobile-Agent Luna recording and deterministic replay

> Use superpowers:executing-plans. User explicitly requested actual upstream recording followed by AI-free replay; prior local Luna evaluator is not this acceptance.

Goal: run pinned Mobile-Agent v3.5 mobile_use/main, original build_messages/history/SYSTEM_PROMPT/parse_action/rescale_coordinates, with gpt-6-luna Responses transport; save actual native actions and per-step before/after PNG/log then reload the same immutable trace for replay with zero model calls.

Spec: user instruction 2026-11-15 and docs/managed-pc/RUNTIME_BOUNDARIES.md pinned upstream 81fa28b564ef7a695521500bc15a0e1324b2b394. Work on original master; preserve existing editor and user dirty changes.

Architecture: vendor pinned MIT source and provenance. Remove unused eager numpy/OpenAI/Qwen imports from utils, postpone annotations, replace only I/O ports at runtime: GUIOwlWrapper -> Luna Responses, AdbTools -> observed typed driver. Original main, prompt, history, parser, rescale remain executed. No replacement planner. Optional Pillow dependency supports original image/annotation functions. Upstream resized coordinates are explicitly transformed back to physical display before driver; traces hold physical pixels. Run in a dedicated process because upstream writes relative paths.

Constraints: selected named Gmarket emulator only; no install/reset/grant/login/purchase; only mouse text, external screen Back only. Max10 generations/1024 output each/240sec new-send deadline, no retries/fallback, unknown dispatch stop. Preserve upstream raw action and request provenance. AI success is a claim pending human review. Replay in a separate process with no key/model port, fixed source hash, explicit selected target/initial state, healing OFF. Server approval is not invented by a local technical run.

- [x] 1 Vendor source/license/hash manifest and minimal documented import-only patch. Add tests proving actual upstream main and original message/history/parser execute, normalized mapping and safe action rejection; run RED then implement engine/Responses conversation port.
- [x] 2 Add recording/replay CLI around the same engine/typed driver: fsynced before/planned/send/ACK/after journal, trace incrementally saved even after capture failure; source SHA/geometry/selected device checks; replay records before/after, argv equality, AI0 process with no key. Test tampered source, ambiguous/capture failure, permission and deadline paths RED/GREEN.
- [x] 3 Start existing dedicated AVD without resetting data. Actual upstream+Luna search recording, stop and save; restore comparable public app entry without clearing data, replay saved trace without model/key, observe final screen. Save full evidence and reasoning checklist; report any mismatch as failure, never repair via hidden AI calls.
- [x] 4 One fresh final review, one important fix pass with relevant regression, docs/NEXT distinction and explicit local commit. Existing baseline nine suite failures stay visible; no unrelated UI commit.

Review focus: source provenance and actual main dispatch; normalized/resized/physical coordinates; terminal/unsupported actions that upstream silently ignores; capture failure after ACK preserving real trace; replay initial-state drift and falsely claiming QA success. Each receives a focused test or explicit live evidence.

Ruling: existing pending binding-editor changes remain uncommitted and outside this batch. Ruling: this creates the actual reusable upstream engine and local record/replay entry point; normal management server model binding/secretref/admission still needs separate integration and must not be claimed complete.


Live integration corrections: Luna image frame1000square, one-action structured response codec, final_answer/commentary separation (official Responses phase), bounded read-only foreground/hierarchy settling and stable resource target comparison were required by actual failures. No local replanner replaces Mobile-Agent. Frame matching now prefers a unique clickable resource at the exact recorded point and same attributes; otherwise bounded pixel comparison. Stable resources let animated placeholders vary without allowing overlays/different controls. XML is obtained only on the registered dedicated public target, never transmitted to the model, and pinned with evidence. Source bytes are immutable; replay refuses incomplete recording pins and target changes before app setup. Intermediate provider errors and stopped/partial attempts remain separate evidence.

Official implementation references: https://developers.openai.com/api/docs/guides/structured-outputs and https://developers.openai.com/api/reference/resources/responses/methods/retrieve (phase). Pinned upstream links remain in RUNTIME_BOUNDARIES.

검증/실제 증거와 명시 경계: [AI-LIVE-03](../validation/tasks/AI-LIVE-03.md). 2026-11-15 재개 시 유료 호출 없이85파일 hash·4argv·키 비노출 대조, 집중60passed2.85s와 native 회귀를 확인했다. fresh review·수정·실제 실행·증거 인계를 마쳤으며 이 계획을 포함해 명시 stage/로컬 commit한다.
