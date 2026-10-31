# Contract review remediation implementation plan

> **For agentic workers:** Use test-driven-development and scoped implementation/review. This plan implements the approved review findings without introducing later product features.

**Goal:** Correct R01–R20 and V01 from the 2026-11-01 contract review, preserve existing user work, and verify the actual product app.

**Architecture:** Keep the current FastAPI/SQLite application and immutable case versions. Add forward migrations rather than resetting data; centralize mutation validation and protect dispatch/evidence boundaries.

**Tech Stack:** Existing Python 3.11, FastAPI, SQLite, pytest, plain browser templates/JS. No installation, deployment, model call, or device action.

**Spec:** `2026-11-01-contract-review.md`, root DATA_DESIGN/UI_SPEC, execution CONTRACTS C00–C14.

## Global constraints

- Preserve the dirty worktree and user runtime data. No reset, clean, commit, push, or user DB migration execution.
- Work in the existing checkout: product files are untracked and do not travel with a new Git worktree. Permission profile makes `.git` read-only. User authorized fixing this current implementation.
- Existing contract decisions and review acceptance criteria are the design. Do not add later model/native/replay features.
- Test the real app factory; fixture providers represent only external native/model boundaries.
- Add adversarial regressions before fixes. Preserve fail-closed behavior; fail if image sanitization cannot be guaranteed.
- Only independent file owners may edit concurrently. Subagents do not spawn additional agents.

## Review focus

- A one-field edit must preserve all other snapshot data, including Android settings and multiple checks.
- Repeated requests, restarted processes, and unknown dispatch must not duplicate external effects.
- Stored evidence bytes and source manifests must survive new recovery revisions and GC.
- Browser mutations must enforce the same Origin/CSRF/idempotency/validation as APIs.
- Forward schema constraints must reject inconsistent ownership without destroying historical user data.

## Tasks and ownership

### A · Case snapshots, proposals, schema integrity (R01/02/04/18/19/20, V01)

Files: domain versions/proposals/hash helpers; forward migration `0022_review_integrity.py`; W05/W06 tests and new `tests/integration/test_review_domain.py`.

- [x] Reproduce snapshot hash collisions, step setting loss, stale-base acceptance, invalid package/version/receipt relations, and fact deletion as failing tests.
- [x] Hash execution snapshot consistently in every version producer; preserve settings/recorded steps during edits; reject stale proposal bases.
- [x] Add forward constraints for exact package/version relations, materialization ownership, and permanent fact UPDATE/DELETE protection. Keep valid construction transactions possible.
- [x] Correct duplicate fixture helper and approval setup without weakening invariants.
- [x] Run domain/schema regressions and record evidence.

### B · Product routing and UI mutations (R03/05/06/13/14/15)

Files: api app/catalog/cases/settings/tcs/auth as needed; browser templates/JS; W10/W04 tests; new `tests/acceptance/test_review_ui.py`. Domain services consume A's unchanged public signatures.

- [x] Reproduce real-app route absence, destructive roundtrip, missing mutation protection, duplicate clone, negative limits, and disconnected TC operations.
- [x] Install all completed routes lazily; preserve complete editing snapshots and use secure shared request headers.
- [x] Persist same key/body receipt atomically, reject different body, enforce limits, connect TC actions and proposal acceptance/rejection to real APIs.
- [x] Run actual ASGI/browser navigation and UI/API regression tests without manually installing the catalog.
- [x] Record tests and remaining environmental limitations.

### C · Dispatch and sanitization (R07/08/09)

Files: contracts actions, security redaction, recording action_executor, worker control/dispatch_journal; W13/W09 tests; new `tests/integration/test_review_actions.py`.

- [x] Pin unknown delivery repeat, attempt identity isolation, cancellation during lookup, actual action ceiling/lease safety, and pixel PNG secret behavior with failing tests.
- [x] Persist dispatch transitions scoped to attempt/action; deny repeated delivery and recheck live control immediately before dispatch.
- [x] Apply actual budgets on the command path; preserve read-only evidence recovery after cancellation.
- [x] Treat unprovable image redaction as an error; valid PNG tests replace pretend PNG strings where appropriate.
- [x] Run action/control regressions and record results.

### D · Evidence durability and ownership (R10/11/12/16/17)

Files: recording recovery, worker spool, store evidence/artifacts, contracts evidence, API artifacts/recordings; forward migration `0023_review_evidence.py`; W14 tests; new `tests/integration/test_review_evidence.py`.

- [x] Pin recovery overwrite, wrong/missing owner, invalid duplicate upload metadata, conflicting spool seq, and prefix ACK after purge/restart.
- [x] Store immutable recovery objects and explicit lineage; keep old manifest bytes intact and failures non-destructive.
- [x] Validate typed owner and lease/attempt scope before dedup, atomically create ready/ref receipt, preserve every provenance reference.
- [x] Retain prefix/hash metadata after file GC, reject conflicting payloads, and atomically replace spool journal.
- [x] Run file/DB/API recovery and ingest regressions.

### E · Integration review and progress evidence

- [x] Run all safe tests, excluding only W01-02 live VM gate. Check dependencies/compile and actual browser journey as supported by installed tooling.
- [x] Review code changes against every R/V acceptance criterion. Add follow-up fixes for verified gaps and rerun affected tests.
- [x] Record per-finding resolution and evidence in `2026-11-01-remediation-result.md`; retain original review as historical evidence.
- [x] Synchronize affected handoffs/current progress without marking later live gates complete. Keep W15-01 as next product task once remediation is verified.

## Execution ledger

- Baseline: master 0826522, user implementation untracked; prior review suite 50 passed/3 fixture failures/1 live deselected.
- Ruling: Fix the current worktree in place without changing Git metadata — preserves the implementation under review; no commit or isolated worktree is required to fulfill the authorized correction.
- Ruling: Approved review acceptance criteria plus existing specs define the repair — avoid changing contracts to accommodate defective code.
- Shared boundaries: A↔B version view/read/write signatures; A↔D new migrations ordered 0022/0023; C↔D sanitized capture and spool receipts. Preserve signatures or notify consumer before changing.
- A/B/C/D tasks have explicit regression, implementation, and verification steps; each agrees with its own scope. A and B may not edit the same file; root owns C/D. Product progress docs are E-only.

- Final: original20findings/V01 and follow-up regressions repaired; evidence and limits in remediation-result. No new W leaf or live gate completed.
