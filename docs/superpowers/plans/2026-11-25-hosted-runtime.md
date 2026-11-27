# HS-2~6 account-independent implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development for independent storage/deployment tasks and inline TDD for the database task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 사용자 계정·배포·운영 키 없이 준비할 수 있는 Postgres, private Storage, Fly 서버/worker 연결 코드를 완성하고 실제 사용자가 할 단계만 별도로 남긴다.

**Architecture:** 기존 도메인과 승인/증거 계약을 재사용한다. API만 Postgres/Storage/모델 비밀을 소유하고 worker는 HTTPS만 사용한다. 로컬 SQLite/files/DPAPI는 유지한다. Hosted 실행 준비는 명시 preflight로 검사하며 fixture 성공과 실제 배포 수용은 구분한다.

**Tech Stack:** existing Python/FastAPI, psycopg3, httpx, Supabase Storage REST, Fly Machines/Docker. Actual cloud accounts and paid AI requests are outside this run.

**Spec:** `docs/superpowers/specs/2026-11-20-render-supabase-worker-design.md`; direct predecessor `docs/validation/tasks/HS-1.md`.

## Global Constraints

- master에서 작업하고 기존 작업/승인본/실제 DB를 초기화하거나 이관하지 않는다.
- 녹화 저장 후 사람 승인. AI0 재생과 기본 healing OFF 유지.
- 서버 ACK는 원격 저장과 내용 검증 뒤에만 기록한다. 서버 cache/worker PC가 사라져도 이미 저장한 근거를 조회할 수 있어야 한다.
- 계정 생성·구매·운영 배포·push·실제 모델 호출은 하지 않는다. 필요한 개발 의존성/임시 DB만 작업 폴더 안에서 사용한다.
- 독립 카드의 코드 구현은 외부 계정 대기로 막지 않는다. 코드 미완료는 외부 대기로 위장하지 않는다.

## Review Focus

- Postgres 트랜잭션 실패 후 rollback/savepoint 복구, 동시 writer와 기존 멱등성.
- SQLite trigger가 지키던 immutable version/evidence/approval를 Postgres에서 동일하게 강제.
- 파일 업로드 재시도/중복/다른 bytes/불명 응답과 cache 제거 후 조회.
- TLS/프록시/비밀 누락, worker 자식의 서버 비밀 격리, 이미지에 비밀 포함 금지.
- PC offline에도 서버에 저장 완료된 evidence/승인 조회가 유지되며 재연결 후 자동 재실행하지 않음.

## Task 1 — HS-2 Postgres backend (root owns shared config/store)

Files: `src/aiqa/store/database.py`, new `store/postgres*.py`, dedicated Postgres migrations/schema; config/package metadata; dialect-sensitive callsites only where required; `tests/integration/test_hs2_*.py`.

Interfaces: `StorageConfig` chooses explicit backend; `open_store(config)` returns existing Store interface. `PostgresConnection.execute(sql, params=())` supports the existing bounded SQL surface (qmark parameters, INSERT OR IGNORE, rowid ordering, json scalar extraction) and translates integrity failures to the existing domain exception boundary while preserving transaction recovery. Unknown/unsupported SQL fails explicitly. Hosted deployment preflight requires `AIQA_DATABASE_URL`; no SQLite fallback in a deployed Fly app.

- [x] RED: settings/backend isolation and secret redaction; placeholder/quoted literal translation; rollback/savepoint and error recovery.
- [x] Implement psycopg connection adapter, transaction writer serialization and migration lock; avoid weakening domain gates.
- [x] Port full current table/index/constraint/trigger schema; record coverage against the current migration head, refuse missing guards or schema drift.
- [x] Exercise a temporary actual PostgreSQL instance if available; real project/case/version/recording/review/approval and receipt operations, concurrent writers, rollback and restart.
- [x] Preserve SQLite regressions; honest remaining SQL/backup limitations if any.

## Task 2 — HS-3 private durable object storage (storage agent)

Files: new `store/object_storage.py` and storage facade modules; `store/artifacts.py`, evidence/upload/read/retention callsites; isolated storage tests. Do not edit config/database/app/pyproject shared files: return exact integration changes to root.

Interfaces: existing artifact I/O keeps Path local support; hosted facade uses server-only `AIQA_SUPABASE_URL`, `AIQA_SUPABASE_SERVICE_KEY`, `AIQA_SUPABASE_BUCKET` and `AIQA_ARTIFACT_BACKEND=supabase`. Distinguish disposable cache from remote durability. No public URL or admin token in DTOs.

- [x] RED: immutable upload/retry conflict, remote readback hash verification, timeout/refusal, remote private read after cache removal, deletion/protection semantics.
- [x] Implement HTTP port with bounded timeouts/response sizes, no credential-bearing redirects, read-only verified cache use.
- [x] Wire all recording/evidence/package/read/download paths; do not mark artifact ACK from local cache alone. Flag unsupported hosted paths explicitly rather than local-only success.
- [x] GREEN: new storage and relevant recording/retention/review regressions. Return documentation of integration and limitations.

## Task 3 — HS-4/5 account-independent Fly/worker entry (deployment agent)

Files: `Dockerfile`, `.dockerignore`, `fly.toml.example`, new `src/aiqa/hosted/*`, worker environment example/run scripts, isolated tests and operator runbook. No edits to main shared config/store/app/pyproject; propose any minimal integration to root.

Interfaces: `python -m aiqa.hosted.entry` runs API only on container interface with approved profile/settings. Existing `create_app` and OIDC/membership are reused. Preflight requires hosted Postgres/private Storage, protected receipt key, OIDC/client secret and correct public origin; reports names/status only. Manifest disables auto-stop and configures one machine and liveness. Worker uses existing outbound HTTPS client and cannot receive management DB/storage/model secrets.

- [x] RED: missing/unsafe config; valid synthetic config, no secret output; startup without Windows DLL; worker env isolation.
- [x] Implement Linux-safe API lifespan/reconciliation entry and Fly manifests, startup migration entry, health/proxy handling without trusting arbitrary forwarded headers.
- [x] Provide first-project/admin bootstrap and explicit worker enrollment instructions/code using existing authorization; no actual user account changes in this run.
- [x] GREEN: static manifest/container checks and mocked process/ASGI tests; actual Linux build if existing tooling permits, otherwise expose reproducible build check for user/CI.

## Task 4 — Integration, review, handoff (root)

- [x] Integrate shared config/dependency wiring and independent changes. Verify no silent SQLite/local-files deployed default.
- [x] Review each independently owned task; fix real findings with RED→GREEN, then whole-change review.
- [x] Run meaningful cross-component regression, package/source checks and record exact fixture/live scope. No fake external pass.
- [x] Update HS cards, NEXT_ACTION, WORK_PROGRESS and one user-ready setup checklist with concrete commands/files. Commit on master.
- [x] Continue remaining account-independent implementation if a reviewed code gap remains. Stop only at work requiring user accounts/credentials/actual deployment or an explicit unavoidable blocker; preserve exact resume commands.

## Ledger

BASE `master 3525226`, clean. User explicitly authorizes continuous implementation of all feasible HS work, then asks for their own remaining setup. Fly.io selected; no architecture selection question is pending.

Ruling: retain current Python/domain model rather than replace the application with a new ORM or new auth. PostgreSQL portability and object durability are code obligations, not simply connection-string acceptance.

Ruling: independent Storage and Fly packaging can be implemented in parallel with Postgres, with shared config wiring owned by root. Neither may claim production readiness before the database and object invariants integrate.


### 2026-11-27 integration/review ledger

- Database: full generated schema/manifest + psycopg adapter integrated. Real queued recording exposed Boolean JSON guard, unknown NULL typing, batch reconciliation, and video row-width errors; each has regression coverage and was fixed. Temporary actual PostgreSQL17.12 loopback checks: **29 passed in60.82s**. Later added real first-admin→OIDC→dataset receipt→new app/retry/conflict seam: **1 passed in6.85s**, separate from that run. Its initial fixture incorrectly opened a second writer instead of borrowing the request store; corrected the fixture to preserve the real app factory. No production writer gate was weakened.
- Storage: remote ACK/read/delete, cache loss, recovery/export/APK phases integrated. Fresh review found real NoSuchKey wire handling, non-idempotent recovery keys, pre-auth retention read, invalid UUID types. The latter three produced **12 RED** cases before correction; focused final storage/key-ref run **77 passed in25.85s**. This is mocked REST/ASGI, not Supabase live acceptance.
- Runtime/auth: Windows import moved behind local use, pinned server protocol copied, standard RS256/JWKS verification and browser state cookie added. Slow exchange now leaves event loop/writer free; finalize checks live membership/state. Worker allowlist retains real Android inputs and excludes server secrets. Static/process/ASGI regression with RX auth paths previously **86 passed**; actual Linux build unavailable (Docker/WSL absent).
- `node --test tests/web/*.test.cjs`: **59 passed**, exit0. No manual browser visual/keyboard acceptance was performed for the settings key-reference UI.
- Whole regression: first eight observed failures reproduced unchanged on BASE `3525226` in a separate git archive (the seven acceptance nodes plus `test_unknown_native_log_disables_cached_action_without_a_second_send`). Full run remains subject to the final evidence below; do not synthesize a full green total from focused passes.
- Local test assets/dependencies remain under git-ignored `.review-work`; no service installation/PATH mutation, user DB reset, cloud deploy, actual key read, paid model or ADB call. Actual Supabase session/role/TLS, Linux/Fly/OIDC, independent browser/PC OFF checks remain HS-4/5/6 live work.

- Later frontend seam regression switches raw replacement to deployed-reference mode, verifies the raw field is cleared/absent from outgoing JSON, checks exact selected ref and idempotency header, and resets mode after save. Final full JS command after adding this test: **60 passed**, exit0 (`.review-work/hosted-runtime/final-js.log`). Prior59 is an earlier run, not an additional60.
- Package build initially lacked wheel in the reused environment. Installed setuptools/wheel only in ignored scratch and re-ran `pip wheel --no-deps --no-build-isolation`: exit0. Inspected wheel SQL/JSON/runtime/auth/template/JS resources. No global/editable environment mutation; not a Linux image test. Local links in13 changed/related docs resolve, `git diff --check` exit0.

- Final packaging review found `core.autocrlf=true` could rewrite the checksummed SQL and shell entry on a fresh Windows checkout. Synthetic Git init/add/checkout reproduced a **RED hash mismatch**. Added narrow LF rules in `.gitattributes` (no checksum weakening); complete offline schema suite then **8 passed in1.83s**, including the fresh-checkout contract. This test and the first-admin seam were added after full-run collection and are reported separately from that run.


### Final verification and disposition — 2026-11-27

- Full command: `python -B -m pytest -q -p no:cacheprovider --tb=short`, using this checkout's source, isolated JWT/psycopg dependencies and explicit loopback test-Postgres URL. **23 failed,1982 passed,1 skipped in2151.02s**, exit1. All23 failure nodes were directly reproduced on BASE `3525226` using its isolated git archive: acceptance7, previously known6, healing3, final ITEM/UI6, plus the separately captured unknown-native1. Failure-set comparison: **23=23, unmatched0**. This is not a whole BASE run and not an all-green result. Exact nodes and unresolved causes are in the regression baseline document; no security/QA gate was weakened.
- Full log: `.review-work/hosted-runtime/final-pytest.log`; BASE logs `baseline-{acceptance,six,additional,last}.log` plus the recorded unknown-native tool output. The later Postgres first-admin seam1 and checkout regression1 are separate passes, not added to the full total.
- Final JS60, wheel build/resource inspection, schema export check, narrow checkout/schema8 and source whitespace checks pass. Actual PostgreSQL29 plus later seam1 verified; Storage mock77 and auth/runtime fixture results retain their documented scope. PowerShell runbook7 blocks parsed without execution.
- HS-2/3 code complete; HS-4/5 deployment/worker preparation code complete; HS-6 synthetic contract journey complete. Actual Linux/Fly/Supabase/OIDC/different-network/PC OFF acceptance remains unexecuted. NEXT_ACTION Current is HS-4 real setup. User actions and complete commands are in HOSTED_SETUP_CHECKLIST/FLY_HOSTED_RUNBOOK.
- No remaining reviewed implementation finding in this HS scope. Existing baseline failures remain unresolved; additional members, hosted archive/restore, remote orphan audit and large-file resumable transfer are explicit boundaries. Code/fixtures do not confer production acceptance. Commit these implementation/handoff changes locally on master; no push/deploy.

- Temporary loopback PostgreSQL fixture was cleanly stopped after verification (pg_ctl exit0); data remains only in ignored scratch for reproducibility. Worker shell entry is staged executable with LF preserved.
