"""Store a sanitized after-capture with the action it belongs to."""

from __future__ import annotations

import json
from pathlib import Path

from aiqa.contracts.actions import Observation
from aiqa.contracts.evidence import ActionObservation
from aiqa.security.redaction import RedactionError, filter_capture


def store_action_observation(
    spool: Path,
    action_id: str,
    before_ref: str | None,
    captured: Observation | None,
    *,
    timing: str,
    command_result: str,
    error_ref: str | None,
    check_refs: tuple[str, ...],
    secrets: tuple[str, ...],
    before_rotation: int | None,
) -> ActionObservation:
    """Write the evidence record. A delayed capture does not fill a missing immediate PNG."""

    after_ref: str | None = None
    captured_at = None if captured is None else captured.captured_at
    rotation = None if captured is None or captured.geometry is None else captured.geometry.rotation
    outcome = "complete"
    stored_timing = timing
    if timing != "immediate":
        stored_timing = "delayed"
        outcome = "unknown"
    elif captured is None or not captured.capture_ok:
        outcome = "unknown"
        stored_timing = "immediate"
    elif before_rotation is None or rotation != before_rotation:
        outcome = "unknown"
    else:
        try:
            cleaned = filter_capture(captured, secrets)
        except RedactionError:
            outcome = "incomplete"
        else:
            folder = spool / "after"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{action_id}.png").write_bytes(cleaned.png)
            after_ref = f"after/{action_id}"
    if stored_timing == "delayed" and captured is not None and captured.capture_ok:
        try:
            cleaned = filter_capture(captured, secrets)
        except RedactionError:
            outcome = "incomplete"
        else:
            folder = spool / "delayed"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{action_id}.png").write_bytes(cleaned.png)
            after_ref = f"delayed/{action_id}"
    record = ActionObservation(
        action_id,
        before_ref,
        after_ref,
        captured_at,
        rotation,
        command_result,
        error_ref,
        check_refs,
        stored_timing,
        outcome,
        False,
    )
    folder = spool / "evidence"
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "action_id": record.action_id,
        "before_ref": record.before_ref,
        "after_ref": record.after_ref,
        "captured_at": record.captured_at,
        "rotation": record.rotation,
        "command_result": record.command_result,
        "error_ref": record.error_ref,
        "check_refs": list(record.check_refs),
        "timing": record.timing,
        "outcome": record.outcome,
        "native_evidence": record.native_evidence,
    }
    (folder / f"{action_id}.json").write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return record
