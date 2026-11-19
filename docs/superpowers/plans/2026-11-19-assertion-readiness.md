# Assertion and Readiness Implementation Plan

> **For agentic workers:** superpowers:executing-plans with independent modules delegated under dispatching-parallel-agents. Root owns worker integration; disjoint file ownership prevents shared edits.

**Goal:** Evaluate and persist real replay Assertions, and wait for recorded target readiness without repeating input.

**Architecture:** Extend existing native source/worker gates, source-owned check binding, ACKed evidence and server-only verification broker. Keep authoring success separate from QA.

**Tech Stack:** Python/FastAPI/SQLite, existing ADB observation, Pillow signatures, Jinja/JavaScript.

**Spec:** ../specs/2026-11-19-assertion-readiness-design.md

## Global Constraints

- Preserve existing dirty work and the dedicated codex/android-live-video branch. No commit/push requested.
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

- [ ] Readiness: RED delayed-target/timeout/cancel/old-source tests; implement strict optional target conditions and recorded wait; GREEN focused tests.
- [ ] Server visual checks: RED scope/ownership/image/policy/idempotency tests; implement authorized ACK-image evaluation through existing broker; GREEN.
- [ ] Normalized QA: RED result provenance/omission/violation tests; persist source-owned check results at finish and aggregate verdict; GREEN.
- [ ] Worker integration: RED deterministic boundary/resource/late-load/one-dispatch tests; attach per-step ACK, evaluate due checks, propagate normalized results and status; GREEN.
- [ ] UI: select screen verification for free-form Assertions with explicit verification binding; preserve existing deterministic cases and compact labels; focused JS checks.
- [ ] Run affected integration and full project tests with plugin autoload disabled (environment auto-loaded plugins hung the prior diagnostic test). Review complete diff with a fresh reviewer and fix substantive findings.

## Ledger

2026-11-19: Source audit confirmed dropped waits and placeholder check coverage. Existing scope and explicit immediate-fix request supply authorization; no repeated design approval. Root integrates, independent agents own readiness, visual server, finish persistence. Existing screenshots/video retain historical INCONCLUSIVE provenance.
