# Assertion and Readiness Implementation Plan

> **For agentic workers:** superpowers:executing-plans with independent modules delegated under dispatching-parallel-agents. Root owns worker integration; disjoint file ownership prevents shared edits.

**Goal:** Evaluate and persist real replay Assertions, and wait for recorded target readiness without repeating input.

**Architecture:** Extend existing native source/worker gates, source-owned check binding, ACKed evidence and server-only verification broker. Keep authoring success separate from QA.

**Tech Stack:** Python/FastAPI/SQLite, existing ADB observation, Pillow signatures, Jinja/JavaScript.

**Spec:** ../specs/2026-11-19-assertion-readiness-design.md

## Global Constraints

- Preserve existing dirty work. Follow-up branch `codex/assertion-readiness-final` starts at the same `1dc66b6` commit as master. No commit/push requested.
- Actor AI0 during replay. Visual checks only use explicit verification policy; never authoring fallback.
- Missing/unknown required checks cannot become PASS. Cancelled or ambiguous input is never resent.
- Native geometry/source/check identity and current lease are authoritative.

## Review Focus

- Delayed static skeleton must not permit a different next interaction target.
- Missing/duplicate/redacted hierarchy targets remain unknown.
- A forged worker visual PASS cannot replace a server evaluator result.
- Same-key evidence/finish/model confirmation cannot re-run the device or provider.
- Final native budget exhaustion must still allow bounded read-only verification.

## Tasks

- [x] Readiness: RED delayed-target/timeout/cancel/old-source tests; implement strict optional target conditions and recorded wait; GREEN focused tests.
- [x] Server visual checks: RED scope/ownership/image/policy/idempotency tests; implement authorized ACK-image evaluation through existing broker; GREEN.
- [x] Normalized QA: RED result provenance/omission/violation tests; persist source-owned check results at finish and aggregate verdict; GREEN.
- [x] Worker integration: RED deterministic boundary/resource/late-load/one-dispatch tests; attach per-step ACK, evaluate due checks, propagate normalized results and status; GREEN.
- [x] UI: select screen verification for free-form Assertions with explicit verification binding; preserve existing deterministic cases and compact labels; focused JS checks.
- [x] Run affected integration and full project tests with plugin autoload disabled (environment auto-loaded plugins hung the prior diagnostic test). Review complete diff with a fresh reviewer and fix substantive findings. Full result: 1,771 passed, 24 failed, 1 skipped; all 24 failed tests also fail against the master comparison. Affected Python 109/109 and web 59/59 pass; see follow-up validation report.

## Ledger

2026-11-19: Source audit confirmed dropped waits and placeholder check coverage. Existing scope and explicit immediate-fix request supply authorization; no repeated design approval. Root integrates, independent agents own readiness, visual server, finish persistence. Existing screenshots/video retain historical INCONCLUSIVE provenance.

2026-11-24: Continued from master without changing its existing uncommitted files. Fresh review found and regression tests reproduced three follow-up bugs: later gestures skipped recorded readiness, a lost step-evidence ACK discarded its recovery callback, and cancellation during an after-observation erased a known native ACK. All three are corrected. The recording wizard now saves explicit verification mode and verification-role binding. Local HTTP integration covers native replay through ACKed evidence, server evaluation and final PASS/FAIL/INCONCLUSIVE; browser inspection confirms the compact wizard controls. These checks use fixture devices/providers, not a new physical Android or paid-model acceptance run. Full-suite results are recorded separately in the follow-up validation report.

2026-11-25 KST: Full suite completed in four independent file partitions (449 tests each). Master comparison includes migrations and pinned third-party protocol sources. All 24 failing test IDs reproduce on that comparison; the existing failures remain documented, so this is not a claim that the entire repository suite is green. Validation: `docs/validation/tasks/2026-11-24-assertion-readiness-followup.md`.
