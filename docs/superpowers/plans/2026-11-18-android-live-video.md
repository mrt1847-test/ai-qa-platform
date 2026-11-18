# Android Live Video Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 웹에서 Android 실시간 영상을 보면서 기존 자연어 녹화·저장본 재생을 수행하고 실시간 화면을 본다. 영상 저장 기능은 구현하지 않는다.

**Architecture:** Android 워커가 연속 H.264를 fragmented MP4로 포장해 인증 API로 올린다. 관리 서버는 제한된 메모리 세션을 중계하며 브라우저 MediaSource video가 재생한다.

**Tech Stack:** Python/FastAPI/httpx, Android ADB screenrecord, optional imageio-ffmpeg, vanilla JS MediaSource.

**Spec:** ../specs/2026-11-18-android-live-video-design.md

## 1. 제한된 영상 세션과 인증 API

Create `src/aiqa/video/sessions.py`, `src/aiqa/api/video.py`; attach in `api/app.py`.

Interfaces: `VideoSessions.create(project, resource, actor)`, `claim(..., producer)`, `append(..., sequence, bytes)`, `read(..., after)`, `keepalive`, `stop`. Encoded init/fragment bytes remain separate from evidence ingestion. IDs and producer fences are server-owned.

- [ ] RED: unit tests for expiry, capacity, ordered/idempotent MP4 fragments and publisher ownership; API tests for missing session/CSRF, foreign project/resource/worker and sensitive jobs.
- [ ] GREEN: bounded in-memory session store and existing-auth routes; run these tests.

## 2. Android 영상 워커

Create `src/aiqa/worker/video.py`; add video methods to `worker/http_client.py`, lifecycle integration in `worker/runtime.py`, optional video dependency in `pyproject.toml`.

Interfaces: `AndroidVideoService(settings, binding).start()/close()`, `iter_mp4_segments(stream)`. The service uses its own HTTP client, fixed local ADB binding and an owned screenrecord/FFmpeg pipeline. No execution or model APIs are invoked.

- [ ] RED: MP4 box boundary/size/EOF and subprocess lifecycle tests; delivery retries keep the same sequence, stop demand terminates processes, secrets suspend capture.
- [ ] GREEN: worker pipeline, bounded queue/timeouts and close; run targeted worker tests.

## 3. 웹 영상 패널

Create `web/templates/components/live_video.html`, `web/static/live_video.js` and styles; include from the project shell. Track project/resource/session in sessionStorage, never credentials. Existing selected resource controls bind the panel. Recording detail supplies its physical resource for direct navigation.

- [ ] RED: JS lifecycle tests for ordered append, stale/disconnected state, resource switch,  page navigation reconnect and unsupported MediaSource.
- [ ] GREEN: native video with connect/disconnect controls, CSRF mutations and bounded polling; run JS and relevant template/API tests.

## 4. 실제 검증과 README 교체

- [ ] Review the whole change independently; address material findings.
- [ ] Verify live browser playback against actual emulator movement; confirm there is no video-save/download control or endpoint.
- [ ] Film the completed web user flow with continuous video; replace README media and provenance without presenting INCONCLUSIVE/error as PASS.
- [ ] Decode final video, verify output links/hashes and report remaining limits.

## Review focus

Foreign project/worker access, raw sensitive pixels, publisher takeover and duplicate chunks, unbounded buffers/orphaned ADB processes, stale UI and player reconnect are required failure paths.

## Execution ledger

- Ruling: proceed without another design approval round because the user selected web video integration, repeatedly asked to continue, and rejected repeated per-step approvals. Implementation choices above are the implementer's decisions.
- Ruling: use a new `codex/android-live-video` branch in the current workspace, preserving the user's committed baseline and existing runtime assets. No worktree consent is inferred.
- Baseline: clean repository at `32e6000`; earlier viewer/media changes were already committed by the user.
- Prior standalone recording processes were checked; no owned Android screenrecord remained. Start the existing AVD for actual stream verification.

- Scope correction: user explicitly limited the product feature to live viewing. Removed video download endpoint/storage path and changed whole-session buffering to a rolling latest-GOP transport buffer, purged on stop. Product UI will only provide view/connect and disconnect.
- Task 1: actor/project/worker scope, ordering, capacity, expiry, sensitive/foreign device fences and durable publisher recovery tests implemented; first 21 targeted tests passed before scope correction. Rolling-buffer/no-download regression tests were observed failing and are being completed.
