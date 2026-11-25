# HS-1 Hosted secrets implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** hosted API가 Windows 저장소 없이 배포 비밀을 읽고 동일한 요청 영수증을 재시작 후에도 검증한다.

**Architecture:** Fly secrets가 환경 변수로 주입한 값을 읽는 전용 backend를 선택한다. 배포 비밀은 읽기 전용이며 SQL에는 기존 reference/audit만 등록한다. 로컬 Credential Manager/DPAPI 동작은 보존한다.

**Tech Stack:** Python standard library, existing FastAPI/SQLite test runtime. Postgres/Storage/deployment are HS-2~4.

**Spec:** `docs/superpowers/specs/2026-11-20-render-supabase-worker-design.md`

## Global Constraints

- OIDC 비밀과 모델 키는 Fly.io 비밀에 둔다. 브라우저와 워커 프로세스에는 넣지 않는다.
- 로컬 개발은 기존 SQLite, 로컬 파일, Windows 자격 증명 관리자를 유지한다.
- 이번 작업은 계정 생성·배포·운영 키 조회·AI 호출을 하지 않는다. 사용자가 지정한 master에서 작업한다.

## Review Focus

- Windows DLL이 없는 프로세스에서도 API import/health가 가능해야 한다.
- 손상/중복/다른 account의 배포 설정은 값을 노출하지 않고 거부한다.
- 배포 비밀을 UI 쓰기로 변경했다고 가장하거나 SQL에 원문을 넣지 않는다.
- hosted 영수증 키 누락/교체와 local DPAPI DB 혼용은 새 키를 만들지 않고 거부한다.
- 같은 배포 설정으로 새 앱을 만들어도 모델 ref와 요청 digest를 재사용한다.

## Task 1: deployment secret backend

Files: `security/environment_secrets.py` (new), `security/secrets.py`, `tests/integration/test_hs1_hosted_secrets.py` (new), paths under `src/aiqa` unless tests.

Produces: `EnvironmentSecretBackend(account, environ=None)` implements read/write/delete. `AIQA_HOSTED_SECRETS_JSON` maps exact `AIQA/<account>/oidc/client_secret` and `AIQA/<account>/secret/<project UUID>/<ref UUID>/<revision>` to values. Writes/deletes reject; no process-environment mutation.

- [x] RED: isolated subprocess with no WinDLL imports app; backend profile/account isolation, malformed/duplicate JSON, read-only writes, missing key, restart, redaction tests.
- [x] Implement lazy Windows DLL binding and hosted backend selection; keep injected test backends.
- [x] GREEN: run HS-1 focused tests and existing secret account/model/OIDC regressions.

## Task 2: portable receipt protection

Files: `security/receipt_digest.py`, `store/database.py`, `api/mutations.py`, `store/artifact_ingest.py`, HS-1 tests.

Produces: a per-StorageConfig hosted receipt provider, supplied explicitly to both digest callsites; `AIQA_RECEIPT_HMAC_KEY` is base64 of 32 random bytes. SQL stores a versioned HMAC verifier marker, never the key. Existing local DPAPI envelopes remain unchanged; provider/envelope mismatch fails closed. No ambient global profile.

- [x] RED: stable digests across new providers/connections; missing/wrong/rotated keys, local/hosted envelope mismatch, SQL/repr redaction, separate app isolation.
- [x] Implement provider and callsite wiring. Missing config fails only when protected mutation is attempted, not liveness.
- [x] GREEN: new tests plus browser receipt/upload and local DPAPI regressions.

## Task 3: reference provisioning and handoff

Files: `security/provision_hosted_secret.py` (new), `security/secrets.py`, HS-1 tests, hosted operator documentation, NEXT_ACTION/WORK_PROGRESS/HS-1 handoff.

Produces: operator-only `python -m aiqa.security.provision_hosted_secret --project-id UUID --actor-id UUID --ref-id UUID --revision N --name NAME`; no secret argv. Reads already deployed value, verifies existing active project admin membership, registers metadata/audit/snapshot in one transaction. Same ref/revision/name is idempotent; rotation requires next revision, old refs remain. No HTTP provisioning endpoint.

- [x] RED: register/resolve/rotate/restart; unauthorized/missing value/gapped revision/renamed existing revision leave metadata unchanged and expose no values.
- [x] Implement CLI and domain metadata operation; ensure normal hosted secret writes return a fixed actionable error without plaintext or false success.
- [x] GREEN: focused tests and related existing regression set; fresh whole-change reviewer required by executing-plans, then one fix pass if needed.
- [x] Record actual Windows fixture evidence and Linux limitation separately; update queue to HS-2 only if HS-1 code contract is met; commit on master, no push/deploy.

## Ledger

BASE: `master e0c9aa8`, clean. Existing master worktree used; original OneDrive folder is another branch and is untouched.

Ruling: read-only deployment backend plus operator reference provisioning — Fly secrets are the durable authority; in-memory UI writes would claim persistence incorrectly. Browser key creation/rotation is unavailable in this profile and must say so.

Ruling: Linux runtime acceptance is separate from the code portability proof — this PC has no Docker and WSL reports no installed distribution. Isolated subprocess tests remove Windows DLL support; do not label those real Linux tests.

Final review: fresh `hs1_final_review` (gpt-6.2-astra), two findings accepted: scoped rollback cleanup P1 and local worker env isolation P2. Both reproduced by failing tests before the fix pass.

Final: Ruling: Linux process boot/host boot identification and live Fly/OIDC remain HS-4; this card proves app import and secret/receipt contracts only. Postgres and hosted object durability remain HS-2/3. CLI actor identity relies on existing operator server access; active admin membership is checked transactionally and the CLI creates no grants.

Ruling: existing local settings UI regression expected an AI0 replay explanation already absent at BASE. Restore that user-facing policy sentence rather than weaken the assertion. No replay behavior or policy changes.

Task 1~3: complete — final focused Python command in `docs/validation/tasks/HS-1.md`: 111 passed (54.37s), JS1 passed, diff check clean. BASE e0c9aa8; the final implementation commit includes this ledger.

Final: fixed scoped rollback cleanup and worker environment isolation — each named regression RED→GREEN; final focused suite111/111. No deferred minors. A separate full-repository run was not performed.
