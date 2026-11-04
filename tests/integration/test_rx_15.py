"""RX-15: CUAWright Web recording adapter — hooks, allowlist, no host escape."""

from __future__ import annotations

import binascii
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from aiqa.adapters.cuawright_web import (
    CuawrightRejected,
    CuawrightWebAdapter,
    make_recording_manifest,
)
from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.replay.compiler import compile_allowlisted_web_source
from aiqa.replay.driver import ApprovedWebPackage
from aiqa.worker.isolated_web import admit_recording_channel, require_web_ready
from aiqa.worker.web_isolation_backend import IsolationConfig, WebIsolationGate, fixture_backend


def _png(width: int = 24, height: int = 48) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", binascii.crc32(kind + body) & 0xFFFFFFFF)
        )

    row = b"\x00" + b"\x00" * width * 3
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def _observation() -> Observation:
    from uuid import uuid4

    return Observation(
        str(uuid4()),
        datetime.now(timezone.utc).isoformat(),
        CaptureGeometry(24, 48, 24, 48, "identity", 0, (0, 0, 24, 48)),
        _png(),
        "<button id='go'>Go</button>",
        "",
        (),
        "",
        True,
        "web",
    )


def _complete_trajectory() -> dict[str, object]:
    return {
        "complete": True,
        "steps": [
            {
                "hook": "hook.web.code_output.step_script",
                "code": "qa_runtime.click('#go')",
                "summary": {"type": "click", "selector": "#go"},
            },
            {
                "hook": "hook.web.code_output.script_py",
                "code": "qa_runtime.fill('#name', 'ada')",
                "summary": {"type": "fill", "selector": "#name", "value": "ada"},
            },
        ],
    }


def test_adapter_rejects_shell_cdp_host_read_truncation_and_code_edit(tmp_path: Path) -> None:
    adapter = CuawrightWebAdapter()
    with pytest.raises(CuawrightRejected, match="workspace shell"):
        adapter.extract_trajectory(
            {
                "complete": True,
                "steps": [
                    {
                        "hook": "hook.web.code_output.shell",
                        "code": "echo hi",
                    }
                ],
            }
        )
    with pytest.raises(CuawrightRejected, match="direct CDP"):
        adapter.extract_trajectory(
            {
                "complete": True,
                "steps": [
                    {
                        "hook": "hook.web.playwright.cdp",
                        "code": "qa_runtime.click('#go')",
                    }
                ],
            }
        )
    with pytest.raises(CuawrightRejected, match="host read"):
        adapter.extract_trajectory(
            {
                "complete": True,
                "steps": [
                    {
                        "hook": "hook.web.code_output.step_script",
                        "code": "open('/etc/passwd').read()",
                    }
                ],
            }
        )
    with pytest.raises(ValueError, match="recording channel"):
        admit_recording_channel("cdp")
    admit_recording_channel("ipc")
    assert require_web_ready(None) is False

    truncated = adapter.extract_trajectory(
        {
            "complete": False,
            "steps": [
                {
                    "hook": "hook.web.code_output.step_script",
                    "code": "qa_runtime.click('#go')",
                    "summary": {"type": "click", "selector": "#go"},
                }
            ],
        }
    )
    assert truncated.package_ready is False
    assert "truncated" in truncated.reject_reason
    with pytest.raises(CuawrightRejected, match="truncated|not ready"):
        adapter.build_approval_package(
            truncated,
            origin="https://app.example.test",
            revision="lock-1",
            manifest=make_recording_manifest(raw_source=truncated.reviewable_source),
            lock_hash="lock-1",
        )

    bundle = adapter.extract_trajectory(_complete_trajectory())
    assert bundle.package_ready is True
    assert len(bundle.raw_sources) == 2
    assert all(item.accepted for item in bundle.summaries)
    assert "qa_runtime.click('#go')" in bundle.reviewable_source
    with pytest.raises(CuawrightRejected, match="unauthorized code modification"):
        adapter.assert_replay_source_unchanged(bundle, bundle.reviewable_source + "\n# patched")

    origin = "https://app.example.test"
    manifest = make_recording_manifest(raw_source=bundle.reviewable_source)
    draft = adapter.build_approval_package(
        bundle,
        origin=origin,
        revision="lock-1",
        manifest=manifest,
        lock_hash="lock-1",
    )
    assert draft.origin == origin
    assert draft.digest.startswith("sha256:")
    compiled = compile_allowlisted_web_source(
        bundle.reviewable_source, lock_hash="lock-1", source=manifest
    )
    assert len(compiled.steps) == 2
    assert draft.compiled.body.approved_code_or_plan_hash == compiled.body.approved_code_or_plan_hash
    assert [step.call for step in draft.compiled.steps] == [step.call for step in compiled.steps]

    now = datetime(2026, 11, 4, 6, 30, tzinfo=timezone.utc)
    gate = WebIsolationGate(
        IsolationConfig(
            backend=fixture_backend(allowed_origins=(origin,)),
            proof_secret=b"rx15-fixture-secret!!",
        )
    )
    proof = gate.issue_proof(now=now)
    approved = ApprovedWebPackage(digest=draft.digest, revision=draft.revision, origin=origin)
    seen: list[str] = []
    results = adapter.run_allowlisted_steps(
        bundle,
        approved=approved,
        gate=gate,
        proof=proof,
        before=_observation(),
        after=_observation(),
        spool=tmp_path / "spool",
        now=now,
        runner=lambda action: seen.append(action.type),
    )
    assert [item.action.type for item in results] == ["click", "fill"]
    assert seen == ["click", "fill"]
    assert all(item.ai_calls == 0 and item.retries == 0 for item in results)
    assert all(item.before_ref and item.after_ref for item in results)
