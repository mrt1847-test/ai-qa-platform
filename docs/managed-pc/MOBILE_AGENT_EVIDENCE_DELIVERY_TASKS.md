# MA04b1 · 원본 녹화 증거의 durable delivery

> Use executing-plans/TDD inline master. BASE4d5be4e. Spec server wiring MA04 and C05 immutable evidence/no native retry. No actual model/ADB/default switch.

Goal: reuse StepEvidenceCommitter for up to80 logical agent turns + source (native still<=50), preserve exact unconfirmed metadata payload across restart, retry evidence only without rerunning model/device. This is evidence-only groundwork; original subprocess native handler is MA04b2.

Files: worker/step_evidence.py optional namespace=mobile(max81, legacy51 unchanged) and pending_path durable journal, tests/unit/test_mobile_evidence_delivery.py; integration test using marked model port/current turn after/log commit and reconstructed committer. Optional durability only for mobile private worker runtime; no credentials stored. Local state owner project/job/attempt/generation/worker/namespace, validated payload fingerprint and expected ACK scope. Atomic_write/file_lock from worker/files.py; corruption/conflicting body/foreign owner fail before HTTP. One pending packet, receipts detached and payload released after ACK. Resume_pending retries same stored idempotency key/now/events/artifacts, no capture/model/native callback.

- [x] RED namespace step81/mobile accepted and legacy52 rejected; lost response+restart uses exact same payload/clock/key; owner change/corrupt state/body tamper denied, cached ACK after reopen0 HTTP, conflict/pending prefix blocks, failure writing journal0 HTTP. Valid loaded receipt uses original expected_seq and artifact count.
- [x] Implement minimal persistence, schema bound<=8MiB/81 entries, one pending; exact scope and JSON validation, metadata only. File lock serializes load/write. No deletes or compensating cleanup.
- [x] One fresh review/fix pass, focused existing step-evidence and worker-model regression, handoff/queue/contracts/local commit. Full original native/capture/source handler and runtime admission remain next.

Ruling: current-frame before upload already durable on server and model key stays server-side. This journal contains sanitized evidence upload packets/ACKs only. Native prefix must still be fsynced independently by MA04b2 before after-capture/upload. Metadata recovery never resumes recording automatically.

완료 인계: [AI-LIVE-04-MA04B1](../validation/tasks/AI-LIVE-04-MA04B1.md), focused37pass. 다음 MA04b2 native/capture/source coordinator.
