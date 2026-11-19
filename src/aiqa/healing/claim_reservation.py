"""Server-owned healing reservation. A worker flag is not an episode grant."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from aiqa.healing.service import reserve_healing_episode
from aiqa.store.healing import HealingRejected
from aiqa.worker.control import RunControl
from aiqa.worker.healing_pin import resolve_claim_healing_pin
from aiqa.contracts.healing import HealingTrigger


def reserve_claimed_healing(connection, worker, *, project_id, job_id, attempt_id, action_id, reason, request_key, now):
    """Reserve from the current regression claim. Client episode id and allowed are ignored."""

    if project_id not in worker.permitted_projects or "regression" not in worker.permitted_purposes:
        raise HealingRejected("worker cannot use this lease")
    if type(request_key) is not str or request_key.strip() == "":
        raise HealingRejected("request key is missing")
    job = connection.execute(
        "SELECT purpose, status, limits, case_run_id FROM jobs WHERE project_id=? AND job_id=?",
        (str(project_id), str(job_id)),
    ).fetchone()
    if job is None or job[0] != "regression" or job[3] is None:
        raise HealingRejected("regression claim required")
    cancelled = connection.execute(
        "SELECT 1 FROM job_cancellations WHERE project_id=? AND job_id=?",
        (str(project_id), str(job_id)),
    ).fetchone()
    if cancelled is not None:
        raise HealingRejected("job was cancelled")
    lease = connection.execute(
        """SELECT worker_id, expires_at, generation FROM leases
           WHERE project_id=? AND job_id=? ORDER BY generation DESC LIMIT 1""",
        (str(project_id), str(job_id)),
    ).fetchone()
    if lease is None or lease[0] != worker.worker_id:
        raise HealingRejected("worker cannot use this lease")
    expires = datetime.fromisoformat(str(lease[1]))
    if expires.tzinfo is None or expires <= now.astimezone(timezone.utc):
        raise HealingRejected("lease expired")
    attempt = connection.execute(
        "SELECT job_id, generation FROM attempts WHERE project_id=? AND attempt_id=?",
        (str(project_id), str(attempt_id)),
    ).fetchone()
    if attempt is None or attempt[0] != str(job_id) or int(attempt[1]) != int(lease[2]):
        raise HealingRejected("attempt does not match the claim")
    claim = connection.execute(
        "SELECT worker_id, job_id, purpose FROM claim_receipts WHERE project_id=? AND attempt_id=?",
        (str(project_id), str(attempt_id)),
    ).fetchone()
    if claim is None or claim[0] != worker.worker_id or claim[1] != str(job_id) or claim[2] != "regression":
        raise HealingRejected("claim does not authorize healing")
    try:
        limits = json.loads(job[2])
    except (TypeError, ValueError):
        raise HealingRejected("healing pin invalid") from None
    snapshot = {
        "purpose": "regression",
        "self_healing_enabled": limits.get("self_healing_enabled") is True,
        "replay_package_id": limits.get("replay_package_id"),
        "replay_package_hash": limits.get("replay_package_hash"),
        "policy_ref": limits.get("policy_ref"),
        "limits": limits,
    }
    try:
        pin = resolve_claim_healing_pin(snapshot)
    except (TypeError, ValueError):
        raise HealingRejected("healing pin invalid") from None
    if not pin.enabled or pin.policy is None or pin.binding is None or pin.binding.get("role") != "healing":
        raise HealingRejected("authoring grant is not a healing grant")
    violated = connection.execute(
        """SELECT 1 FROM check_results
           WHERE project_id=? AND attempt_id=? AND action_id=? AND status='violated'""",
        (str(project_id), str(attempt_id), str(action_id)),
    ).fetchone()
    if violated is not None:
        raise HealingRejected("product violation blocks healing")
    package = UUID(str(limits["replay_package_id"]))
    remaining = int((expires - now.astimezone(timezone.utc)).total_seconds())
    trigger = HealingTrigger(
        UUID(str(job[3])), attempt_id, package, request_key.strip(), reason, pin.policy,
        int(pin.policy.effective_limits["timeout_seconds"]), remaining, pin.policy.binding_revision,
        False, action_id,
    )
    return reserve_healing_episode(trigger, RunControl(connection, project_id, job_id, "before_lookup"))


def reserve_claimed_healing_http(store, worker, payload):
    """HTTP entry. episode_id and allowed in the body are not authority."""

    try:
        project_id = UUID(str(payload.get("project_id")))
        job_id = UUID(str(payload.get("job_id")))
        attempt_id = UUID(str(payload.get("attempt_id")))
        action_id = UUID(str(payload.get("action_id")))
        reason = payload.get("reason")
        request_key = payload.get("request_key")
        if type(reason) is not str or type(request_key) is not str:
            raise ValueError
    except (TypeError, ValueError):
        return 422, {"eligible": False, "reason": "healing request invalid"}
    try:
        with store.transaction() as connection:
            receipt = reserve_claimed_healing(
                connection, worker, project_id=project_id, job_id=job_id, attempt_id=attempt_id,
                action_id=action_id, reason=reason, request_key=request_key, now=datetime.now(timezone.utc),
            )
    except HealingRejected as exc:
        return 403, {"eligible": False, "reason": str(exc)}
    return 200, {
        "eligible": receipt.eligible,
        "episode_id": None if receipt.episode_id is None else str(receipt.episode_id),
        "reserved_calls": receipt.reserved_calls,
        "reserved_seconds": receipt.reserved_seconds,
        "replayed": receipt.replayed,
    }
