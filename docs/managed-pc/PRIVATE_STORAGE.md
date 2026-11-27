# Private artifact storage (HS-3)

2026-11-25. Account-independent implementation; synthetic HTTP/ASGI validation
does not establish actual Supabase/Fly availability or HS-6 acceptance.

The API owns `AIQA_SUPABASE_SERVICE_KEY`. Set `AIQA_ARTIFACT_BACKEND=supabase`,
`AIQA_SUPABASE_URL=https://<project-ref>.supabase.co`, and
`AIQA_SUPABASE_BUCKET=<private-bucket-id>` in the server environment. Create the
bucket as **private** and permit the application's configured object sizes.
The REST port sends `application/octet-stream`; MIME allowlists must permit it.
Keep the environment name `AIQA_SUPABASE_SERVICE_KEY` for either a new
`sb_secret_...` server secret key or a legacy `service_role` JWT. New secret keys
are sent in `apikey` only; legacy JWTs also use `Authorization: Bearer`.
`sb_publishable_...` browser keys are rejected. Never use an anonymous/browser key. Do not put these
settings into worker environments, browser payloads, source control, or images.

`StorageConfig.from_settings()` constructs one explicit
`artifact_root(cache_dir, backend=..., supabase_url=..., service_key=..., bucket=...)`.
Local mode returns the original `Path`. Supabase mode returns
`DurableArtifactRoot` with a `cache_dir` attribute, deliberately without path
coercion. Application shutdown closes its HTTP client; individual request stores
must not close that shared client.

An upload verifies the private bucket, checks for existing immutable bytes, uses
non-upsert POST, then downloads and checks the digest/length before returning a
durable receipt. Different bytes under an existing key are refused. A timeout or
ambiguous response never becomes an ACK; a retry can verify and reuse the object
already written by the first request. No Storage URL or service key is returned
in an artifact DTO. All reads use authenticated private GET and validate against
the stored digest before evidence is accepted. Removing or corrupting the cache
cannot promote local bytes into a durable success. Requests refuse redirects,
ignore ambient HTTP proxy configuration, and cap connection/read waits and
response sizes. Object bodies are limited to 500 MiB, with existing domain
limits (for example 5 MB evidence and 500 MiB APK) still applied.
Missing-object checks accept HTTP 404 and Storage's HTTP 400 compatibility
response only when structured `code=NoSuchKey` and `statusCode="404"` agree.
Authentication, missing-bucket, malformed, and other error responses cannot
authorize a new upload or verify deletion.
The compatibility Path readers still require writable disposable cache space.
A cache write failure reports the artifact unavailable and refuses a new ACK;
verified remote bytes remain in place so the same staged upload can be retried
after cache permissions/capacity are repaired, without uploading duplicate bytes.

PNG/log uploads, worker evidence commits, observation/history reads, evidence
viewers, recording timelines, late-capture recovery, exports and APK fetches use
this facade. Replay packages, approved plans, mappings, approval events and
review snapshots already persist in SQL; their source artifacts use the private
facade. A browser's artifact endpoint remains an authenticated API URL. Read
handlers run in the thread pool, and artifact viewer/read scopes use the store's
read-only transaction so a slow remote GET does not acquire the writer fence.
Recovery and export POST processing also runs in the thread pool. Recovery
stages its captures between metadata transactions. Export admission freezes the
manifest in a queued SQL job, publishes and verifies its stable object key with
no SQL transaction open, then marks that same job completed with a snapshot CAS.
Only completed hosted exports can report `artifact_ready`; every later read still
checks the remote bytes. A failed or ambiguous publish keeps the queued identity
and frozen `created_at`/`as_of` snapshot for the same request's retry.

Review rationale (2026-11-26): these are SQL/Storage ordering obligations. A
queued export receipt records admission, not an artifact ACK; a local cache or
lost upload response cannot mark it ready. Heartbeat regressions exercise slow
recovery/export publication and slow artifact reads to catch both event-loop
blocking and a writer fence held across remote I/O.
APK registration similarly runs ZIP inspection and private upload/readback
outside SQL and the event loop. A project/hash stage keeps the same object key
across upload failures; the app-build row becomes visible only after verified
publication. Existing local direct-domain callers retain their behavior.

Recovery uses a stable UUID5 manifest identity for the same project/recording/
request key and body, so a lost upload response cannot create a new object set
on every retry. Local recovery keeps its existing UUID/cleanup behavior.

Retention read endpoints authorize project access before materializing private
payloads. Retention checks existing pins before invoking the Storage delete API and
verifies remote absence before custody/tombstone updates. Failed deletion leaves
the SQL metadata untombstoned. SQL rows and protection rules keep their existing
lifetimes. Uncertain evidence metadata commits preserve staged remote bytes;
successful redundant evidence stages can be removed after reference checks.

Explicit boundaries:

- Whole-PC SQLite backup/restore refuses hosted Storage/Postgres. Hosted archive
  export, integrity verification, point-in-time restore, and operator recovery
  need a dedicated Postgres plus private-object archive provider. An ephemeral
  Fly disk copy is not a hosted backup.
- Live video is the existing short-lived latest-GOP transport buffer, separate
  from evidence/approval; there is no video recording archive/download feature.
  Its pixels intentionally disappear on stop/disconnect/restart. PNGs and logs
  remain the durable review evidence. Adding an archival video product requires
  a separate privacy/retention contract.
- Interrupted recovery-manifest uploads preserve unreferenced remote objects
  rather than risk deletion after an uncertain SQL outcome. Hosted reconciliation
  checks registered objects and reports SQL staging count; it does not enumerate
  all remote orphans. An operator orphan audit must compare complete object
  inventory to committed manifests/staging before any removal. No bucket-wide
  lifecycle deletion is configured by this code.
- Standard REST uploads support APKs within the application limit. Resumable
  transfer and streaming large APK downloads are follow-up efficiency work;
  current code bounds the body and fails safely on timeout.

Official protocol references: [standard immutable uploads](https://supabase.com/docs/guides/storage/uploads/standard-uploads),
[server API key types and authentication limitations](https://supabase.com/docs/guides/getting-started/api-keys),
[authenticated private reads](https://supabase.com/docs/guides/storage/serving/downloads),
[bucket access model](https://supabase.com/docs/guides/storage/buckets/fundamentals),
and [Storage API deletion](https://supabase.com/docs/guides/storage/management/delete-objects).
