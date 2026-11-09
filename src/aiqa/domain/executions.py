"""Trial preview and atomic RUN/ITEM/job admission. This does not open a device or a model."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from aiqa.contracts.cases import CaseDefinition, CaseVersion, PathPolicy
from aiqa.contracts.healing import ApprovedHealingPolicy, HealingRequest, Limits
from aiqa.contracts.jobs import IdempotencyKey
from aiqa.domain.hashing import canonical_hash, canonical_json
from aiqa.domain.resource_readiness import resource_readiness
from aiqa.healing.policy import resolve_healing_policy
from aiqa.domain.projects import next_commit_seq
from aiqa.domain.execution_metadata import item_created_seq, item_release_label, normalized_release_label
from aiqa.store.models import Actor, Transaction
from aiqa.store.queue import JobConflict

_OPERATION = "enqueue_execution"
_CANCEL_EXECUTION = "cancel_execution"
_CANCEL_ITEM = "cancel_case_run"
_SKIP_ITEM = "skip_case_run"
_RERUN = "rerun_execution"
_OPEN_CANCEL = {"queued": "cancelled", "preparing": "cancel_requested", "running": "cancel_requested"}
_EMPTY_DEFINITION = CaseDefinition("", "", (), {}, {}, (), (), PathPolicy())


class ExecutionRejected(Exception):
    """The trial cannot be admitted."""


class ExecutionMissing(Exception):
    """The run or item is not in this project."""


@dataclass(frozen=True, slots=True)
class ExecutionBlocker:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ResolvedTrialItem:
    entry_id: str
    case_id: UUID
    case_version_id: UUID
    manifest_hash: str
    replay_package_id: UUID | None
    replay_package_hash: str
    healing_policy_hash: str
    healing_snapshot: str
    environment_revision_id: UUID
    resource_id: UUID
    dataset_version_id: UUID | None
    approval_id: UUID | None
    limits: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExecutionExclusion:
    entry_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class ExpandedExecutionScope:
    items: tuple[dict[str, object], ...]
    expanded_count: int
    silent_exclusions: int
    release_label: str
    release_floor_runs: int


@dataclass(frozen=True, slots=True)
class ExecutionPreview:
    preview_hash: str
    resolved_items: tuple[ResolvedTrialItem, ...]
    blockers: tuple[ExecutionBlocker, ...]
    proposed_n: int
    self_healing_enabled: bool
    ready: bool
    exclusions: tuple[ExecutionExclusion, ...] = ()
    silent_exclusions: int = 0
    reserved: bool = False
    release_label: str = ""
    release_floor_runs: int = 0


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    execution_id: UUID
    item_ids: tuple[UUID, ...]
    job_ids: tuple[UUID, ...]
    committed_seq: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class CancellationReceipt:
    execution_id: UUID
    case_run_id: UUID | None
    phase: str
    effects: int
    replayed: bool
    preserved_result: str


@dataclass(frozen=True, slots=True)
class CaseRunView:
    case_run_id: UUID
    result: str
    reason: str
    actor_id: UUID
    replayed: bool


def preview_execution(tx: Transaction, actor: Actor, project_id: UUID, payload: dict[str, object]) -> ExecutionPreview:
    """Resolve one trial without reserving a run. Healing is forced off."""

    _scope(actor, project_id)
    items, blockers, exclusions, silent = _resolve(tx, project_id, payload)
    ready = blockers == () and items != () and all(item.replay_package_id is not None for item in items)
    if payload.get("purpose") in {"regression", "reverification"}:
        ready = ready and all(item.approval_id is not None for item in items)
    label = payload.get("release_label")
    release_label = label.strip() if type(label) is str else ""
    return ExecutionPreview(
        preview_hash=_preview_hash(payload, items, blockers, exclusions),
        resolved_items=items,
        blockers=blockers,
        proposed_n=len(items),
        self_healing_enabled=False,
        ready=ready,
        exclusions=exclusions,
        silent_exclusions=silent,
        reserved=False,
        release_label=release_label,
        release_floor_runs=30 if release_label != "" else 0,
    )


def enqueue_execution(
    tx: Transaction, actor: Actor, project_id: UUID, payload: dict[str, object], key: IdempotencyKey
) -> ExecutionReceipt:
    """Commit one RUN with every ITEM and job, or return the stored receipt."""

    _scope(actor, project_id)
    purpose = payload.get("purpose")
    source = payload.get("source")
    if purpose not in {"trial", "regression", "reverification"} or source not in {"single", "selection", "suite"}:
        raise ExecutionRejected("trial source is required")
    if purpose == "trial" and source != "single":
        raise ExecutionRejected("trial source is required")
    if source == "suite" and purpose not in {"regression", "reverification"}:
        raise ExecutionRejected("trial source is required")
    if _mixed_purposes(payload):
        raise ExecutionRejected("trial and formal cannot be mixed")
    if key.project_id != project_id or key.operation != _OPERATION or key.key.strip() == "":
        raise ExecutionRejected("idempotency key does not match")
    suite_version_id = _suite_version_ref(payload) if source == "suite" else None
    if source == "suite" and suite_version_id is None:
        raise ExecutionRejected("suite version is required")
    body_hash = _request_hash(payload)
    existing = tx.connection.execute(
        """
        SELECT body_hash, job_id, execution_id, case_run_id
        FROM job_receipts
        WHERE project_id = ? AND actor_id = ? AND operation = ? AND request_key = ?
        """,
        (str(project_id), str(actor.actor_id), _OPERATION, key.key),
    ).fetchone()
    if existing is not None:
        if str(existing[0]) != body_hash:
            # Old versions did not hash or persist a release label. Replay only:
            # never apply the new label or enqueue another run under this key.
            if not _legacy_receipt_matches(tx, project_id, str(existing[1]), str(existing[0]), payload):
                raise JobConflict("idempotency body does not match")
        return _stored_receipt(tx, project_id, str(existing[2]), str(existing[1]))
    preview = preview_execution(tx, actor, project_id, _preview_payload(payload))
    if not preview.ready:
        raise ExecutionRejected("trial is not ready")
    if payload.get("preview_hash") != preview.preview_hash:
        raise JobConflict("preview is stale")
    _require_item_pins(payload, preview)
    execution_id = uuid4()
    requested_at = datetime.now(timezone.utc).isoformat()
    commit_seq = next_commit_seq(tx, project_id)
    job_purpose = "regression" if purpose == "reverification" else str(purpose)
    failure_policy = str(payload.get("failure_policy"))
    tx.connection.execute(
        """
        INSERT INTO executions (
            project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(project_id),
            str(execution_id),
            _name(payload),
            str(purpose),
            str(source),
            suite_version_id,
            requested_at,
        ),
    )
    job_ids: list[UUID] = []
    item_ids: list[UUID] = []
    for item in preview.resolved_items:
        case_run_id = uuid4()
        job_id = uuid4()
        item_ids.append(case_run_id)
        job_ids.append(job_id)
        tx.connection.execute(
            """
            INSERT INTO case_runs (
                project_id, execution_id, case_run_id, case_id, case_version_id, purpose, requested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(project_id),
                str(execution_id),
                str(case_run_id),
                str(item.case_id),
                str(item.case_version_id),
                str(purpose),
                requested_at,
            ),
        )
        tx.connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id,
                payload_hash, source_refs, limits, status
            ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, 'queued')
            """,
            (
                str(project_id),
                str(job_id),
                job_purpose,
                str(case_run_id),
                body_hash,
                json.dumps([str(item.replay_package_id)], ensure_ascii=False, separators=(",", ":")),
                _snapshot_limits(tx, project_id, item, commit_seq, failure_policy, preview.release_label),
            ),
        )
    tx.connection.execute(
        """
        INSERT INTO job_receipts (
            project_id, actor_id, operation, request_key, body_hash, job_id, purpose,
            recording_id, execution_id, case_run_id, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, 'queued', ?)
        """,
        (
            str(project_id),
            str(actor.actor_id),
            _OPERATION,
            key.key,
            body_hash,
            str(job_ids[0]),
            job_purpose,
            str(execution_id),
            str(item_ids[0]),
            requested_at,
        ),
    )
    return ExecutionReceipt(execution_id, tuple(item_ids), tuple(job_ids), commit_seq, False)


def cancel_execution(
    tx: Transaction, actor: Actor, execution_id: UUID, key: IdempotencyKey
) -> CancellationReceipt:
    """Cancel every open item in one run. A stored result stays as it is."""

    return _cancel(tx, actor, execution_id, None, key, _CANCEL_EXECUTION)


def cancel_case_run(
    tx: Transaction, actor: Actor, case_run_id: UUID, key: IdempotencyKey
) -> CancellationReceipt:
    """Cancel one item. A completed item and a stored violation stay as they are."""

    row = tx.connection.execute(
        "SELECT execution_id FROM case_runs WHERE project_id = ? AND case_run_id = ?",
        (str(actor.project_scope), str(case_run_id)),
    ).fetchone()
    if row is None or actor.project_scope is None:
        raise ExecutionMissing("item was not found")
    return _cancel(tx, actor, UUID(str(row[0])), case_run_id, key, _CANCEL_ITEM)


def skip_case_run(
    tx: Transaction, actor: Actor, case_run_id: UUID, reason: str, key: IdempotencyKey
) -> CaseRunView:
    """Skip one queued item that has not been dispatched. No resource is taken."""

    if actor.project_scope is None:
        raise ExecutionMissing("item was not found")
    _scope(actor, actor.project_scope)
    if type(reason) is not str or reason.strip() == "":
        raise ExecutionRejected("skip reason is required")
    if key.project_id != actor.project_scope or key.actor_id != actor.actor_id or key.operation != _SKIP_ITEM or key.key.strip() == "":
        raise ExecutionRejected("idempotency key does not match")
    owned = tx.connection.execute(
        """
        SELECT case_runs.execution_id, jobs.job_id, jobs.status, jobs.purpose, jobs.limits
        FROM case_runs
        JOIN jobs
          ON jobs.project_id = case_runs.project_id
         AND jobs.case_run_id = case_runs.case_run_id
        WHERE case_runs.project_id = ? AND case_runs.case_run_id = ?
        """,
        (str(actor.project_scope), str(case_run_id)),
    ).fetchone()
    if owned is None:
        raise ExecutionMissing("item was not found")
    body_hash = canonical_hash({"case_run_id": str(case_run_id), "reason": reason.strip()}, "canon-json-v1")
    existing = tx.connection.execute(
        """
        SELECT body_hash, status FROM job_receipts
        WHERE project_id = ? AND actor_id = ? AND operation = ? AND request_key = ?
        """,
        (str(actor.project_scope), str(actor.actor_id), _SKIP_ITEM, key.key),
    ).fetchone()
    if existing is not None:
        if str(existing[0]) != body_hash:
            raise JobConflict("idempotency body does not match")
        return CaseRunView(case_run_id, "SKIPPED", str(existing[1]), actor.actor_id, True)
    if _stored_core(tx, actor.project_scope, str(case_run_id)) is not None or str(owned[2]) != "queued" or _dispatched(tx, actor.project_scope, str(owned[1])):
        raise JobConflict("item can no longer be skipped")
    seq = next_commit_seq(tx, actor.project_scope)
    tx.connection.execute(
        """
        INSERT INTO item_finalizations (
            project_id, case_run_id, created_seq, finalized_seq, release_label, content_hash, core_result, denominator
        ) VALUES (?, ?, ?, ?, ?, ?, 'SKIPPED', 1)
        """,
        (str(actor.project_scope), str(case_run_id), item_created_seq(tx.connection, actor.project_scope, case_run_id, seq), seq, item_release_label(tx.connection, actor.project_scope, case_run_id), f"SKIPPED:{case_run_id}"),
    )
    updated = tx.connection.execute(
        "UPDATE jobs SET status = 'completed' WHERE project_id = ? AND job_id = ? AND status = 'queued'",
        (str(actor.project_scope), str(owned[1])),
    )
    if updated.rowcount != 1:
        raise JobConflict("item can no longer be skipped")
    tx.connection.execute(
        """
        INSERT INTO job_receipts (
            project_id, actor_id, operation, request_key, body_hash, job_id, purpose,
            recording_id, execution_id, case_run_id, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
        """,
        (
            str(actor.project_scope),
            str(actor.actor_id),
            _SKIP_ITEM,
            key.key,
            body_hash,
            str(owned[1]),
            str(owned[3]),
            str(owned[0]),
            str(case_run_id),
            reason.strip(),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    _stop_later(tx, actor.project_scope, str(owned[0]), str(case_run_id), str(owned[4]))
    return CaseRunView(case_run_id, "SKIPPED", reason.strip(), actor.actor_id, False)


def preview_rerun(
    tx: Transaction, actor: Actor, execution_id: UUID, payload: dict[str, object], key: IdempotencyKey
) -> ExecutionPreview:
    """Copy the exact snapshot into a new run. The original result stays where it is."""

    if actor.project_scope is None:
        raise ExecutionRejected("rerun is invalid")
    project_id = actor.project_scope
    if key.project_id != project_id or key.operation != _RERUN or key.key.strip() == "":
        raise ExecutionRejected("idempotency key does not match")
    reason = payload.get("reason")
    scope = payload.get("scope")
    if type(reason) is not str or reason.strip() == "" or scope not in {"failed", "all", "items"}:
        raise ExecutionRejected("rerun is invalid")
    original = tx.connection.execute(
        """
        SELECT name, purpose FROM executions
        WHERE project_id = ? AND execution_id = ?
        """,
        (str(project_id), str(execution_id)),
    ).fetchone()
    if original is None or str(original[1]) == "trial":
        raise ExecutionMissing("execution was not found")
    body_hash = canonical_hash(
        {
            "case_run_ids": payload.get("case_run_ids", []),
            "environment_change_confirmed": payload.get("environment_change_confirmed") is True,
            "environment_revision_id": payload.get("environment_revision_id", ""),
            "execution_id": str(execution_id),
            "reason": reason.strip(),
            "scope": scope,
        },
        "canon-json-v1",
    )
    existing = tx.connection.execute(
        """
        SELECT body_hash, execution_id FROM job_receipts
        WHERE project_id = ? AND actor_id = ? AND operation = ? AND request_key = ?
        """,
        (str(project_id), str(actor.actor_id), _RERUN, key.key),
    ).fetchone()
    if existing is not None:
        if str(existing[0]) != body_hash:
            raise JobConflict("idempotency body does not match")
        return _stored_rerun_preview(tx, project_id, str(existing[1]))
    chosen = _rerun_choices(tx, project_id, execution_id, scope, payload.get("case_run_ids"))
    requested_env = payload.get("environment_revision_id")
    confirmed = payload.get("environment_change_confirmed") is True
    override = requested_env.strip() if type(requested_env) is str else ""
    changed = override != "" and any(_limit_text(row[5], "environment_revision_id") != override for row in chosen)
    if changed and not confirmed:
        raise ExecutionRejected("configuration change must be explicit")
    blockers: list[ExecutionBlocker] = []
    resolved: list[ResolvedTrialItem] = []
    for row in chosen:
        environment = override if override != "" else _limit_text(row[5], "environment_revision_id")
        resource = _limit_text(row[5], "resource_id")
        approval = _limit_text(row[5], "approval_id")
        item_blockers = _rerun_blockers(tx, project_id, UUID(str(row[1])), UUID(str(row[2])), str(row[3]), environment, approval, resource)
        blockers.extend(item_blockers)
        if environment == "" or resource == "":
            continue
        resolved.append(
            ResolvedTrialItem(
                str(row[0]),
                UUID(str(row[1])),
                UUID(str(row[2])),
                str(row[3]),
                _optional_uuid(_limit_text(row[5], "replay_package_id")),
                _limit_text(row[5], "replay_package_hash"),
                _limit_text(row[5], "healing_policy_hash"),
                _limit_text(row[5], "healing_snapshot"),
                UUID(environment),
                UUID(resource),
                None,
                _optional_uuid(approval),
            )
        )
    preview = ExecutionPreview(
        preview_hash="",
        resolved_items=tuple(resolved),
        blockers=tuple(blockers),
        proposed_n=len(resolved),
        self_healing_enabled=False,
        ready=blockers == [] and resolved != [],
        reserved=False,
    )
    stamped = ExecutionPreview(
        preview_hash=_rerun_hash(execution_id, reason.strip(), preview, changed),
        resolved_items=preview.resolved_items,
        blockers=preview.blockers,
        proposed_n=preview.proposed_n,
        self_healing_enabled=False,
        ready=preview.ready,
        reserved=False,
    )
    if not stamped.ready:
        return stamped
    _insert_rerun(tx, actor, execution_id, str(original[0]), reason.strip(), chosen, stamped, changed, body_hash, key)
    return stamped


def rerun_targets(connection, project_id: UUID, execution_id: UUID) -> list[dict[str, object]]:
    """Expose the stored resource IDs for the rerun form's connection check."""
    execution = connection.execute(
        "SELECT purpose FROM executions WHERE project_id = ? AND execution_id = ?",
        (str(project_id), str(execution_id)),
    ).fetchone()
    if execution is None or execution[0] == "trial":
        return []
    try:
        rows = _rerun_choices(Transaction(connection), project_id, execution_id, "all", None)
    except ExecutionRejected:
        return []
    return [
        {
            "case_run_id": str(row[0]),
            "resource_id": _limit_text(row[5], "resource_id"),
            "failed": row[6] == "FAIL",
        }
        for row in rows
    ]


def _rerun_choices(
    tx: Transaction, project_id: UUID, execution_id: UUID, scope: object, raw_ids: object
) -> tuple[tuple[object, ...], ...]:
    rows = tx.connection.execute(
        """
        SELECT case_runs.case_run_id, case_runs.case_id, case_runs.case_version_id,
               case_versions.content_hash, jobs.job_id, jobs.limits, item_finalizations.core_result
        FROM case_runs
        JOIN case_versions
          ON case_versions.project_id = case_runs.project_id
         AND case_versions.version_id = case_runs.case_version_id
        JOIN jobs
          ON jobs.project_id = case_runs.project_id
         AND jobs.case_run_id = case_runs.case_run_id
        LEFT JOIN item_finalizations
          ON item_finalizations.project_id = case_runs.project_id
         AND item_finalizations.case_run_id = case_runs.case_run_id
        WHERE case_runs.project_id = ? AND case_runs.execution_id = ?
        ORDER BY case_runs.rowid
        """,
        (str(project_id), str(execution_id)),
    ).fetchall()
    if scope == "failed":
        chosen = tuple(row for row in rows if str(row[6] or "") == "FAIL")
    elif scope == "all":
        chosen = tuple(rows)
    else:
        if type(raw_ids) is not list or raw_ids == [] or any(type(item) is not str for item in raw_ids):
            raise ExecutionRejected("rerun item is invalid")
        known = {str(row[0]) for row in rows}
        if any(item not in known for item in raw_ids):
            raise ExecutionRejected("rerun item is invalid")
        chosen = tuple(row for row in rows if str(row[0]) in set(raw_ids))
    if chosen == ():
        raise ExecutionRejected("rerun item is invalid")
    return chosen


def _rerun_blockers(
    tx: Transaction,
    project_id: UUID,
    case_id: UUID,
    version_id: UUID,
    content_hash: str,
    environment: str,
    approval: str,
    resource_id: str,
) -> tuple[ExecutionBlocker, ...]:
    found: list[ExecutionBlocker] = []
    if environment == "" or tx.connection.execute(
        "SELECT 1 FROM environment_revisions WHERE project_id = ? AND revision_id = ?",
        (str(project_id), environment),
    ).fetchone() is None:
        found.append(ExecutionBlocker("RESOURCE_UNAVAILABLE", "environment is missing"))
    _, approval_blockers = _formal_approval(tx, project_id, case_id, version_id, content_hash, approval or None, approval)
    found.extend(approval_blockers)
    version = tx.connection.execute(
        "SELECT settings_json FROM case_versions WHERE project_id = ? AND case_id = ? AND version_id = ?",
        (str(project_id), str(case_id), str(version_id)),
    ).fetchone()
    settings = {} if version is None else json.loads(str(version[0]))
    readiness = resource_readiness(tx.connection, project_id, resource_id, str(settings.get("target_kind", "")))
    if not readiness.ready:
        found.append(ExecutionBlocker(readiness.code, readiness.message))
    return tuple(found)


def _insert_rerun(
    tx: Transaction,
    actor: Actor,
    original_execution_id: UUID,
    original_name: str,
    reason: str,
    chosen: tuple[tuple[object, ...], ...],
    preview: ExecutionPreview,
    changed: bool,
    body_hash: str,
    key: IdempotencyKey,
) -> None:
    project_id = actor.project_scope
    assert project_id is not None
    root = _limit_text(chosen[0][5], "root_execution_id") or str(original_execution_id)
    execution_id = uuid4()
    requested_at = datetime.now(timezone.utc).isoformat()
    tx.connection.execute(
        """
        INSERT INTO executions (
            project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at
        ) VALUES (?, ?, ?, 'reverification', 'rerun', NULL, ?)
        """,
        (str(project_id), str(execution_id), f"{original_name} 재실행", requested_at),
    )
    job_ids: list[str] = []
    item_ids: list[str] = []
    for row, item in zip(chosen, preview.resolved_items, strict=True):
        case_run_id = str(uuid4())
        job_id = str(uuid4())
        item_ids.append(case_run_id)
        job_ids.append(job_id)
        tx.connection.execute(
            """
            INSERT INTO case_runs (
                project_id, execution_id, case_run_id, case_id, case_version_id, purpose, requested_at
            ) VALUES (?, ?, ?, ?, ?, 'reverification', ?)
            """,
            (str(project_id), str(execution_id), case_run_id, str(item.case_id), str(item.case_version_id), requested_at),
        )
        limits = {
            "approval_id": "" if item.approval_id is None else str(item.approval_id),
            "configuration_changed": changed,
            "environment_revision_id": str(item.environment_revision_id),
            "healing_policy_hash": item.healing_policy_hash,
            "healing_snapshot": item.healing_snapshot,
            "original_case_run_id": str(row[0]),
            "original_execution_id": str(original_execution_id),
            "replay_package_hash": item.replay_package_hash,
            "replay_package_id": "" if item.replay_package_id is None else str(item.replay_package_id),
            "resource_id": str(item.resource_id),
            "rerun_reason": reason,
            "root_execution_id": root,
        }
        tx.connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id,
                payload_hash, source_refs, limits, status
            ) VALUES (?, ?, 'regression', NULL, ?, ?, '["source"]', ?, 'queued')
            """,
            (str(project_id), job_id, case_run_id, body_hash, canonical_json(limits)),
        )
    tx.connection.execute(
        """
        INSERT INTO job_receipts (
            project_id, actor_id, operation, request_key, body_hash, job_id, purpose,
            recording_id, execution_id, case_run_id, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'reverification', NULL, ?, ?, 'queued', ?)
        """,
        (
            str(project_id),
            str(actor.actor_id),
            _RERUN,
            key.key,
            body_hash,
            job_ids[0],
            str(execution_id),
            item_ids[0],
            requested_at,
        ),
    )


def _stored_rerun_preview(tx: Transaction, project_id: UUID, execution_id: str) -> ExecutionPreview:
    rows = tx.connection.execute(
        """
        SELECT case_runs.case_run_id, case_runs.case_id, case_runs.case_version_id,
               case_versions.content_hash, jobs.limits
        FROM case_runs
        JOIN case_versions
          ON case_versions.project_id = case_runs.project_id
         AND case_versions.version_id = case_runs.case_version_id
        JOIN jobs
          ON jobs.project_id = case_runs.project_id
         AND jobs.case_run_id = case_runs.case_run_id
        WHERE case_runs.project_id = ? AND case_runs.execution_id = ?
        ORDER BY case_runs.rowid
        """,
        (str(project_id), execution_id),
    ).fetchall()
    items = tuple(
        ResolvedTrialItem(
            str(row[0]),
            UUID(str(row[1])),
            UUID(str(row[2])),
            str(row[3]),
            _optional_uuid(_limit_text(row[4], "replay_package_id")),
            _limit_text(row[4], "replay_package_hash"),
            _limit_text(row[4], "healing_policy_hash"),
            _limit_text(row[4], "healing_snapshot"),
            UUID(_limit_text(row[4], "environment_revision_id")),
            UUID(_limit_text(row[4], "resource_id")),
            None,
            _optional_uuid(_limit_text(row[4], "approval_id")),
        )
        for row in rows
    )
    reason = "" if rows == [] else _limit_text(rows[0][4], "rerun_reason")
    changed = False if rows == [] else _limit_flag(rows[0][4], "configuration_changed")
    original = "" if rows == [] else _limit_text(rows[0][4], "original_execution_id")
    preview = ExecutionPreview(
        preview_hash="",
        resolved_items=items,
        blockers=(),
        proposed_n=len(items),
        self_healing_enabled=False,
        ready=True,
        reserved=False,
    )
    return ExecutionPreview(
        preview_hash=_rerun_hash(UUID(original), reason, preview, changed),
        resolved_items=items,
        blockers=(),
        proposed_n=len(items),
        self_healing_enabled=False,
        ready=True,
        reserved=False,
    )


def _rerun_hash(execution_id: UUID, reason: str, preview: ExecutionPreview, changed: bool) -> str:
    return canonical_hash(
        {
            "blockers": [blocker.code for blocker in preview.blockers],
            "changed": changed,
            "execution_id": str(execution_id),
            "items": [
                {
                    "approval_id": None if item.approval_id is None else str(item.approval_id),
                    "case_version_id": str(item.case_version_id),
                    "environment_revision_id": str(item.environment_revision_id),
                    "resource_id": str(item.resource_id),
                }
                for item in preview.resolved_items
            ],
            "reason": reason,
        },
        "canon-json-v1",
    )


def _limit_text(raw: object, name: str) -> str:
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return ""
    if type(parsed) is not dict:
        return ""
    value = parsed.get(name, "")
    return value if type(value) is str else ""


def _limit_flag(raw: object, name: str) -> bool:
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return False
    return type(parsed) is dict and parsed.get(name) is True


def _optional_uuid(value: str) -> UUID | None:
    if value == "":
        return None
    return UUID(value)


def _dispatched(tx: Transaction, project_id: UUID, job_id: str) -> bool:
    lease = tx.connection.execute(
        "SELECT 1 FROM leases WHERE project_id = ? AND job_id = ?",
        (str(project_id), job_id),
    ).fetchone()
    if lease is not None:
        return True
    attempt = tx.connection.execute(
        "SELECT 1 FROM attempts WHERE project_id = ? AND job_id = ? AND physical_key_id IS NOT NULL",
        (str(project_id), job_id),
    ).fetchone()
    return attempt is not None


def _stop_later(tx: Transaction, project_id: UUID, execution_id: str, case_run_id: str, limits_text: str) -> None:
    try:
        limits = json.loads(limits_text)
    except json.JSONDecodeError:
        return
    if type(limits) is not dict or limits.get("failure_policy") != "stop_on_non_pass":
        return
    rows = tx.connection.execute(
        """
        SELECT case_runs.case_run_id, jobs.job_id, jobs.status
        FROM case_runs
        JOIN jobs
          ON jobs.project_id = case_runs.project_id
         AND jobs.case_run_id = case_runs.case_run_id
        WHERE case_runs.project_id = ? AND case_runs.execution_id = ?
        ORDER BY case_runs.rowid
        """,
        (str(project_id), execution_id),
    ).fetchall()
    seen = False
    for later_id, job_id, status in rows:
        if str(later_id) == case_run_id:
            seen = True
            continue
        if not seen or str(status) != "queued" or _stored_core(tx, project_id, str(later_id)) is not None:
            continue
        if _dispatched(tx, project_id, str(job_id)):
            continue
        seq = next_commit_seq(tx, project_id)
        tx.connection.execute(
            """
            INSERT INTO item_finalizations (
                project_id, case_run_id, created_seq, finalized_seq, release_label, content_hash, core_result, denominator
            ) VALUES (?, ?, ?, ?, ?, ?, 'NOT_RUN', 1)
            """,
            (str(project_id), str(later_id), item_created_seq(tx.connection, project_id, later_id, seq), seq, item_release_label(tx.connection, project_id, later_id), f"NOT_RUN:{later_id}"),
        )
        tx.connection.execute(
            "UPDATE jobs SET status = 'completed' WHERE project_id = ? AND job_id = ? AND status = 'queued'",
            (str(project_id), str(job_id)),
        )


def _cancel(
    tx: Transaction,
    actor: Actor,
    execution_id: UUID,
    case_run_id: UUID | None,
    key: IdempotencyKey,
    operation: str,
) -> CancellationReceipt:
    if actor.project_scope is None:
        raise ExecutionMissing("run was not found")
    _scope(actor, actor.project_scope)
    if key.project_id != actor.project_scope or key.actor_id != actor.actor_id or key.operation != operation or key.key.strip() == "":
        raise ExecutionRejected("idempotency key does not match")
    owned = tx.connection.execute(
        "SELECT 1 FROM executions WHERE project_id = ? AND execution_id = ?",
        (str(actor.project_scope), str(execution_id)),
    ).fetchone()
    if owned is None:
        raise ExecutionMissing("run was not found")
    body_hash = canonical_hash(
        {"case_run_id": None if case_run_id is None else str(case_run_id), "execution_id": str(execution_id)},
        "canon-json-v1",
    )
    existing = tx.connection.execute(
        """
        SELECT body_hash, status FROM job_receipts
        WHERE project_id = ? AND actor_id = ? AND operation = ? AND request_key = ?
        """,
        (str(actor.project_scope), str(actor.actor_id), operation, key.key),
    ).fetchone()
    if existing is not None:
        if str(existing[0]) != body_hash:
            raise JobConflict("idempotency body does not match")
        return CancellationReceipt(
            execution_id,
            case_run_id,
            str(existing[1]),
            1,
            True,
            _preserved_result(tx, actor.project_scope, execution_id, case_run_id),
        )
    jobs = _cancel_jobs(tx, actor.project_scope, execution_id, case_run_id)
    if jobs == []:
        raise ExecutionMissing("run was not found")
    phase = _apply_cancel(tx, actor, key.key, jobs)
    if phase is None:
        raise JobConflict("job can no longer be cancelled")
    tx.connection.execute(
        """
        INSERT INTO job_receipts (
            project_id, actor_id, operation, request_key, body_hash, job_id, purpose,
            recording_id, execution_id, case_run_id, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
        """,
        (
            str(actor.project_scope),
            str(actor.actor_id),
            operation,
            key.key,
            body_hash,
            jobs[0][1],
            jobs[0][3],
            str(execution_id),
            jobs[0][0] if case_run_id is None else str(case_run_id),
            phase,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    return CancellationReceipt(
        execution_id,
        case_run_id,
        phase,
        1,
        False,
        _preserved_result(tx, actor.project_scope, execution_id, case_run_id),
    )


def _cancel_jobs(
    tx: Transaction, project_id: UUID, execution_id: UUID, case_run_id: UUID | None
) -> list[tuple[str, str, str, str]]:
    query = """
        SELECT case_runs.case_run_id, jobs.job_id, jobs.status, jobs.purpose
        FROM case_runs
        JOIN jobs
          ON jobs.project_id = case_runs.project_id
         AND jobs.case_run_id = case_runs.case_run_id
        WHERE case_runs.project_id = ? AND case_runs.execution_id = ?
    """
    params: list[str] = [str(project_id), str(execution_id)]
    if case_run_id is not None:
        query += " AND case_runs.case_run_id = ?"
        params.append(str(case_run_id))
    query += " ORDER BY case_runs.rowid"
    rows = tx.connection.execute(query, tuple(params)).fetchall()
    return [(str(row[0]), str(row[1]), str(row[2]), str(row[3])) for row in rows]


def _apply_cancel(tx: Transaction, actor: Actor, request_key: str, jobs: list[tuple[str, str, str, str]]) -> str | None:
    assert actor.project_scope is not None
    project_id = str(actor.project_scope)
    phase = ""
    for case_run_id, job_id, status, _purpose in jobs:
        if _stored_core(tx, actor.project_scope, case_run_id) is not None or status not in _OPEN_CANCEL:
            continue
        taken = tx.connection.execute(
            "SELECT 1 FROM job_cancellations WHERE project_id = ? AND job_id = ?",
            (project_id, job_id),
        ).fetchone()
        if taken is not None:
            continue
        status_after = _OPEN_CANCEL[status]
        stopped = 1 if status == "queued" else 0
        tx.connection.execute(
            """
            INSERT INTO job_cancellations (
                project_id, actor_id, request_key, job_id, expected_state, body_hash,
                status_after, requested_at, runner_stopped, cleanup_completed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                project_id,
                str(actor.actor_id),
                f"{request_key}:{job_id}",
                job_id,
                status,
                canonical_hash({"expected_state": status, "job_id": job_id}, "canon-json-v1"),
                status_after,
                datetime.now(timezone.utc).isoformat(),
                stopped,
            ),
        )
        updated = tx.connection.execute(
            "UPDATE jobs SET status = ? WHERE project_id = ? AND job_id = ? AND status = ?",
            (status_after, project_id, job_id, status),
        )
        if updated.rowcount != 1:
            raise JobConflict("job can no longer be cancelled")
        if status_after == "cancelled":
            seq = next_commit_seq(tx, actor.project_scope)
            tx.connection.execute(
                """
                INSERT INTO item_finalizations (
                    project_id, case_run_id, created_seq, finalized_seq, release_label, content_hash, core_result, denominator
                ) VALUES (?, ?, ?, ?, ?, ?, 'CANCELLED', 1)
                """,
                (project_id, case_run_id, item_created_seq(tx.connection, project_id, case_run_id, seq), seq, item_release_label(tx.connection, project_id, case_run_id), f"CANCELLED:{case_run_id}"),
            )
        phase = "requested" if status_after == "cancel_requested" else phase or "stopped"
    return None if phase == "" else phase


def _stored_core(tx: Transaction, project_id: UUID, case_run_id: str) -> str | None:
    row = tx.connection.execute(
        "SELECT core_result FROM item_finalizations WHERE project_id = ? AND case_run_id = ?",
        (str(project_id), case_run_id),
    ).fetchone()
    return None if row is None else str(row[0])


def _preserved_result(
    tx: Transaction, project_id: UUID, execution_id: UUID, case_run_id: UUID | None
) -> str:
    query = """
        SELECT item_finalizations.core_result
        FROM case_runs
        JOIN item_finalizations
          ON item_finalizations.project_id = case_runs.project_id
         AND item_finalizations.case_run_id = case_runs.case_run_id
        WHERE case_runs.project_id = ? AND case_runs.execution_id = ?
    """
    params: list[str] = [str(project_id), str(execution_id)]
    if case_run_id is not None:
        query += " AND case_runs.case_run_id = ?"
        params.append(str(case_run_id))
    rows = tx.connection.execute(query, tuple(params)).fetchall()
    results = [str(row[0]) for row in rows]
    if "FAIL" in results:
        return "FAIL"
    return "" if results == [] else results[0]


def _resolve(
    tx: Transaction, project_id: UUID, payload: dict[str, object]
) -> tuple[tuple[ResolvedTrialItem, ...], tuple[ExecutionBlocker, ...], tuple[ExecutionExclusion, ...], int]:
    purpose = payload.get("purpose")
    source = payload.get("source")
    if purpose not in {"trial", "regression", "reverification"} or source not in {"single", "selection", "suite"}:
        raise ExecutionRejected("trial source is required")
    if purpose == "trial" and source != "single":
        raise ExecutionRejected("trial source is required")
    if _mixed_purposes(payload):
        raise ExecutionRejected("trial and formal cannot be mixed")
    if payload.get("failure_policy") not in {"continue", "stop_on_non_pass"}:
        raise ExecutionRejected("failure policy is required")
    raw_items = expand_execution_selection(tx, project_id, payload).items
    confirmed = _confirmed_exclusions(payload)
    resolved: list[ResolvedTrialItem] = []
    blockers: list[ExecutionBlocker] = []
    exclusions: list[ExecutionExclusion] = []
    requested: list[str] = []
    for raw in raw_items:
        if type(raw) is not dict:
            raise ExecutionRejected("item is invalid")
        item, item_blockers = _one_item(tx, project_id, raw, str(purpose))
        requested.append(item.entry_id)
        reason = confirmed.get(item.entry_id)
        if reason is not None:
            exclusions.append(ExecutionExclusion(item.entry_id, reason))
            continue
        resolved.append(item)
        blockers.extend(item_blockers)
    kept = {item.entry_id for item in resolved}
    explicit = {item.entry_id for item in exclusions}
    silent = sum(1 for entry in requested if entry not in kept and entry not in explicit)
    if resolved == []:
        raise ExecutionRejected("item count is outside 1..100")
    return tuple(resolved), tuple(blockers), tuple(exclusions), silent


def expand_execution_selection(
    tx: Transaction, project_id: UUID, selection: dict[str, object]
) -> ExpandedExecutionScope:
    """Expand one selection into case version, data row, and target items."""

    source = selection.get("source")
    choices = _base_choices(tx, project_id, selection)
    if source == "single" and len(choices) != 1:
        raise ExecutionRejected("item count is outside 1..100")
    items = _expand_choices(choices)
    if not 1 <= len(items) <= 100:
        raise ExecutionRejected("item count is outside 1..100")
    label = selection.get("release_label")
    release_label = label.strip() if type(label) is str else ""
    return ExpandedExecutionScope(tuple(items), len(items), 0, release_label, 30 if release_label != "" else 0)


def _base_choices(tx: Transaction, project_id: UUID, payload: dict[str, object]) -> list[dict[str, object]]:
    source = payload.get("source")
    selection = payload.get("selection", payload)
    if type(selection) is not dict:
        raise ExecutionRejected("item is invalid")
    if source == "suite":
        version_id = selection.get("suite_version_id", payload.get("suite_version_id"))
        if type(version_id) is not str or version_id.strip() == "":
            raise ExecutionRejected("suite version is required")
        rows = tx.connection.execute(
            """
            SELECT entry_id, case_version_id, approval_id, data_name, environment_revision_id,
                   resource_id, target_kind
            FROM suite_entries
            WHERE project_id = ? AND suite_version_id = ? AND case_id != ''
            ORDER BY position, entry_id
            """,
            (str(project_id), version_id),
        ).fetchall()
        return [
            {
                "entry_id": str(row[0]),
                "case_version_id": str(row[1]),
                "approval_id": str(row[2]),
                "data_name": str(row[3]),
                "environment_revision_id": str(row[4]),
                "resource_id": str(row[5]),
                "target_kind": str(row[6]),
                "install_policy": "none",
            }
            for row in rows
        ]
    raw_items = selection.get("items")
    if type(raw_items) is not list:
        raise ExecutionRejected("item is invalid")
    choices: list[dict[str, object]] = []
    for item in raw_items:
        if type(item) is not dict:
            raise ExecutionRejected("item is invalid")
        choices.append(dict(item))
    return choices


def _expand_choices(choices: list[dict[str, object]]) -> list[dict[str, object]]:
    expanded: list[dict[str, object]] = []
    seen: set[str] = set()
    for choice in choices:
        base = choice.get("entry_id")
        if type(base) is not str or base.strip() == "":
            raise ExecutionRejected("entry is required")
        rows = choice.get("data_rows")
        targets = choice.get("targets")
        row_values = rows if type(rows) is list else [choice.get("data_name", "")]
        target_values = targets if type(targets) is list else [choice.get("target_kind", "web")]
        if row_values == [] or target_values == []:
            continue
        for row in row_values:
            if type(row) is not str:
                raise ExecutionRejected("item is invalid")
            for target in target_values:
                if type(target) is not str or target.strip() == "":
                    raise ExecutionRejected("item is invalid")
                entry = f"{base}:{row}" if type(rows) is list else base
                if type(targets) is list:
                    entry = f"{entry}:{target}"
                if entry in seen:
                    raise ExecutionRejected("entry id is duplicated")
                seen.add(entry)
                item = {key: value for key, value in choice.items() if key not in {"data_rows", "targets"}}
                item["entry_id"] = entry
                item["data_name"] = row
                item["target_kind"] = target
                expanded.append(item)
                if len(expanded) > 100:
                    raise ExecutionRejected("item count is outside 1..100")
    return expanded


def _mixed_purposes(payload: dict[str, object]) -> bool:
    found: set[str] = set()
    purpose = payload.get("purpose")
    if type(purpose) is str:
        found.add(purpose)
    extras = payload.get("purposes")
    if type(extras) is list:
        found.update(item for item in extras if type(item) is str)
    raw_items = payload.get("items")
    selection = payload.get("selection")
    if type(selection) is dict and type(selection.get("items")) is list:
        raw_items = selection.get("items")
    if type(raw_items) is list:
        for item in raw_items:
            if type(item) is dict and type(item.get("purpose")) is str:
                found.add(str(item.get("purpose")))
    return "trial" in found and bool(found.intersection({"regression", "reverification"}))


def _confirmed_exclusions(payload: dict[str, object]) -> dict[str, str]:
    raw = payload.get("exclusions", [])
    if raw is None:
        return {}
    if type(raw) is not list:
        raise ExecutionRejected("exclusion is invalid")
    confirmed: dict[str, str] = {}
    for item in raw:
        if type(item) is not dict:
            raise ExecutionRejected("exclusion is invalid")
        entry = item.get("entry_id")
        reason = item.get("reason")
        if type(entry) is not str or entry.strip() == "":
            raise ExecutionRejected("exclusion is invalid")
        if item.get("confirmed") is True and type(reason) is str and reason.strip() != "":
            confirmed[entry] = reason.strip()
    return confirmed


def _one_item(
    tx: Transaction, project_id: UUID, raw: dict[str, object], purpose: str
) -> tuple[ResolvedTrialItem, tuple[ExecutionBlocker, ...]]:
    version_id = _uuid(raw.get("case_version_id"), "case version is required")
    environment_id = _uuid(raw.get("environment_revision_id"), "environment is required")
    resource_id = _uuid(raw.get("resource_id"), "resource is required")
    dataset_id = None if raw.get("dataset_version_id") in {None, ""} else _uuid(raw.get("dataset_version_id"), "dataset is required")
    entry_id = raw.get("entry_id")
    if type(entry_id) is not str or entry_id.strip() == "":
        raise ExecutionRejected("entry is required")
    row = tx.connection.execute(
        """
        SELECT versions.case_id, versions.definition_json, versions.settings_json, versions.content_hash,
               versions.replay_package_id, cases.current_approval_id
        FROM case_versions AS versions
        JOIN automation_cases AS cases
          ON cases.project_id = versions.project_id AND cases.case_id = versions.case_id
        WHERE versions.project_id = ? AND versions.version_id = ?
        """,
        (str(project_id), str(version_id)),
    ).fetchone()
    if row is None:
        raise ExecutionRejected("case version is missing")
    blockers: list[ExecutionBlocker] = []
    package_id = None if row[4] is None else UUID(str(row[4]))
    package_hash = ""
    if package_id is None:
        blockers.append(ExecutionBlocker("PACKAGE_MISSING", "package is missing"))
    else:
        package = tx.connection.execute(
            """
            SELECT body_hash FROM replay_packages
            WHERE project_id = ? AND case_id = ? AND case_version_id = ? AND package_id = ? AND ready = 1
            """,
            (str(project_id), str(row[0]), str(version_id), str(package_id)),
        ).fetchone()
        if package is None:
            blockers.append(ExecutionBlocker("PACKAGE_MISSING", "package is not ready"))
        else:
            package_hash = str(package[0])
    if tx.connection.execute(
        "SELECT 1 FROM environment_revisions WHERE project_id = ? AND revision_id = ?",
        (str(project_id), str(environment_id)),
    ).fetchone() is None:
        blockers.append(ExecutionBlocker("RESOURCE_UNAVAILABLE", "environment is missing"))
    readiness = resource_readiness(tx.connection, project_id, str(resource_id), str(json.loads(str(row[2])).get("target_kind", "")))
    if not readiness.ready:
        blockers.append(ExecutionBlocker(readiness.code, readiness.message))
    if dataset_id is not None and tx.connection.execute(
        "SELECT 1 FROM dataset_versions WHERE project_id = ? AND version_id = ?",
        (str(project_id), str(dataset_id)),
    ).fetchone() is None:
        blockers.append(ExecutionBlocker("RESOURCE_UNAVAILABLE", "dataset is missing"))
    definition = json.loads(str(row[1]))
    settings = json.loads(str(row[2]))
    if str(row[3]).strip() == "":
        blockers.append(ExecutionBlocker("HASH_MISSING", "version hash is missing"))
    if not _has_check(definition):
        blockers.append(ExecutionBlocker("DEFINITION_AMBIGUOUS", "required check is missing"))
    blockers.extend(_key_blockers(tx, project_id, settings))
    blockers.extend(_build_blockers(tx, project_id, settings))
    timeout = _timeout(settings)
    if timeout < 1:
        blockers.append(ExecutionBlocker("BUDGET_UNAVAILABLE", "budget is missing"))
    approval = None if row[5] is None else UUID(str(row[5]))
    if purpose in {"regression", "reverification"}:
        approval, approval_blockers = _formal_approval(
            tx, project_id, UUID(str(row[0])), version_id, str(row[3]), row[5], raw.get("approval_id")
        )
        blockers.extend(approval_blockers)
    snapshot = resolve_healing_policy(
        CaseVersion(
            version_id,
            project_id,
            UUID(str(row[0])),
            _EMPTY_DEFINITION,
            package_id,
            approval,
            "recorded",
            str(row[3]),
            "",
            approved_healing=_approved_healing(settings),
        ),
        HealingRequest(False, purpose="trial"),
        _global_limits(settings),
    )
    item = ResolvedTrialItem(
        entry_id,
        UUID(str(row[0])),
        version_id,
        str(row[3]),
        package_id,
        package_hash,
        snapshot.resolution_hash,
        snapshot.resolution_hash,
        environment_id,
        resource_id,
        dataset_id,
        approval,
        {"timeout_seconds":_timeout(settings),"budget":str(settings.get('limits',{}).get('budget','2.00')),"currency":str(settings.get('limits',{}).get('currency','USD')),"max_actions":_bounded(settings.get('limits',{}).get('max_actions'),50),"max_model_calls":_bounded(settings.get('limits',{}).get('max_model_calls'),80)},
    )
    return item, tuple(blockers)


def _formal_approval(
    tx: Transaction,
    project_id: UUID,
    case_id: UUID,
    version_id: UUID,
    content_hash: str,
    current: object,
    requested: object,
) -> tuple[UUID | None, tuple[ExecutionBlocker, ...]]:
    chosen = requested if type(requested) is str and requested.strip() != "" else None
    if chosen is None and current is not None:
        chosen = str(current)
    if chosen is None:
        return None, (ExecutionBlocker("APPROVAL_REQUIRED", "approval is required"),)
    row = tx.connection.execute(
        """
        SELECT version_hash FROM approval_events
        WHERE project_id = ? AND approval_id = ? AND case_id = ? AND case_version_id = ?
          AND event_kind = 'approved'
        """,
        (str(project_id), chosen, str(case_id), str(version_id)),
    ).fetchone()
    if row is None:
        return None, (ExecutionBlocker("APPROVAL_REQUIRED", "approval is required"),)
    revoked = tx.connection.execute(
        """
        SELECT 1 FROM approval_events
        WHERE project_id = ? AND prior_approval_id = ? AND event_kind = 'revoked'
        """,
        (str(project_id), chosen),
    ).fetchone()
    if revoked is not None:
        return None, (ExecutionBlocker("APPROVAL_REVOKED", "approval is revoked"),)
    if content_hash.strip() == "" or str(row[0]) != content_hash:
        return None, (ExecutionBlocker("HASH_MISSING", "approval hash does not match"),)
    return UUID(chosen), ()


def _build_blockers(tx: Transaction, project_id: UUID, settings: dict[str, object]) -> tuple[ExecutionBlocker, ...]:
    build_id = settings.get("build_id")
    if type(build_id) is not str or build_id.strip() == "":
        return ()
    found = tx.connection.execute(
        "SELECT 1 FROM app_builds WHERE project_id = ? AND build_id = ?",
        (str(project_id), build_id),
    ).fetchone()
    if found is None:
        return (ExecutionBlocker("BUILD_MISSING", "build is missing"),)
    return ()


def _key_blockers(tx: Transaction, project_id: UUID, settings: dict[str, object]) -> tuple[ExecutionBlocker, ...]:
    method = "deterministic"
    binding_id = ""
    role = ""
    bindings = settings.get("verifier_bindings")
    if type(bindings) is list and bindings != [] and type(bindings[0]) is dict:
        method = str(bindings[0].get("method", method))
        binding_id = str(bindings[0].get("binding_id", ""))
        role = str(bindings[0].get("role", ""))
    elif type(settings.get("verifier_method")) is str:
        method = str(settings.get("verifier_method"))
        binding_id = str(settings.get("verifier_binding_id", ""))
        role = str(settings.get("verifier_role", ""))
    if method == "deterministic":
        return ()
    found: list[ExecutionBlocker] = []
    if role.strip() == "":
        found.append(ExecutionBlocker("ROLE_MISSING", "verifier role is missing"))
    if binding_id.strip() == "":
        found.append(ExecutionBlocker("MODEL_BINDING_UNAVAILABLE", "ai key is missing"))
        return tuple(found)
    binding = tx.connection.execute(
        """
        SELECT key_ref_id FROM binding_revisions
        WHERE project_id = ? AND binding_id = ?
        ORDER BY revision DESC LIMIT 1
        """,
        (str(project_id), binding_id),
    ).fetchone()
    if binding is None:
        found.append(ExecutionBlocker("MODEL_BINDING_UNAVAILABLE", "ai key is missing"))
        return tuple(found)
    secret = tx.connection.execute(
        "SELECT 1 FROM secret_refs WHERE project_id = ? AND ref_id = ?",
        (str(project_id), str(binding[0])),
    ).fetchone()
    if secret is None:
        found.append(ExecutionBlocker("MODEL_BINDING_UNAVAILABLE", "ai key is missing"))
    return tuple(found)


def _has_check(definition: dict[str, object]) -> bool:
    final_expected = definition.get("final_expected")
    if type(final_expected) is list and final_expected != []:
        return True
    steps = definition.get("steps")
    if type(steps) is not list:
        return False
    return any(type(step) is dict and type(step.get("expected")) is list and step.get("expected") != [] for step in steps)


def _approved_healing(settings: dict[str, object]) -> ApprovedHealingPolicy:
    healing = settings.get("healing_policy")
    if type(healing) is not dict:
        healing = {}
    return ApprovedHealingPolicy(
        allowed=healing.get("allowed") is True,
        scope=str(healing.get("scope", "")),
        model_binding_ref=str(healing.get("model_binding_ref", "")),
        binding_revision=str(healing.get("binding_revision", "")),
        healer_key_present=healing.get("healer_key_present") is True,
        max_episodes_per_item=_bounded(healing.get("max_episodes_per_item"), 1),
        max_model_calls_per_item=_bounded(healing.get("max_model_calls_per_item"), 2),
        max_seconds=_bounded(healing.get("max_seconds"), 30),
        default_enabled=False,
    )


def _global_limits(settings: dict[str, object]) -> Limits:
    raw = settings.get("limits")
    if type(raw) is not dict:
        raw = {}
    return Limits(
        timeout_seconds=_bounded(raw.get("timeout_seconds"), 600),
        max_model_calls=_bounded(raw.get("max_model_calls"), 80),
        budget=str(raw.get("budget", "2.00")),
        max_episodes_per_item=_bounded(raw.get("max_episodes_per_item"), 1),
        max_model_calls_per_item=_bounded(raw.get("max_model_calls_per_item"), 2),
        max_seconds=_bounded(raw.get("max_seconds"), 30),
    )


def _bounded(value: object, fallback: int) -> int:
    try:
        number = int(value) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback
    return number if number >= 0 else fallback


def _timeout(settings: dict[str, object]) -> int:
    limits = settings.get("limits")
    if type(limits) is not dict:
        return 0
    try:
        return int(limits.get("timeout_seconds", 0))
    except (TypeError, ValueError):
        return 0


def _preview_payload(payload: dict[str, object]) -> dict[str, object]:
    source = payload.get("source")
    if source == "suite":
        suite_version_id = _suite_version_ref(payload)
        if suite_version_id is None:
            raise ExecutionRejected("suite version is required")
        return {
            "name": payload.get("name"),
            "purpose": payload.get("purpose"),
            "source": "suite",
            "selection": {"suite_version_id": suite_version_id},
            "failure_policy": payload.get("failure_policy"),
            "exclusions": payload.get("exclusions", []),
            "release_label": payload.get("release_label"),
        }
    items = payload.get("items")
    if type(items) is not list:
        raise ExecutionRejected("item is invalid")
    return {
        "name": payload.get("name"),
        "purpose": payload.get("purpose"),
        "source": payload.get("source"),
        "selection": {"items": items},
        "release_label": payload.get("release_label"),
        "failure_policy": payload.get("failure_policy"),
        "exclusions": payload.get("exclusions", []),
    }


def _suite_version_ref(payload: dict[str, object]) -> str | None:
    sid = payload.get("suite_version_id")
    if type(sid) is str and sid.strip() != "":
        return sid.strip()
    selection = payload.get("selection")
    if type(selection) is dict:
        sid = selection.get("suite_version_id")
        if type(sid) is str and sid.strip() != "":
            return sid.strip()
    return None


@dataclass(frozen=True, slots=True)
class ClaimDecision:
    status: str
    approval_id: str | None
    uses_latest: bool


def validate_claim_snapshot(job: object, connection: sqlite3.Connection) -> ClaimDecision:
    """Keep the snapshotted approval. A revoke or a changed app blocks the claim."""

    from aiqa.store.models import JobSpec

    if not isinstance(job, JobSpec):
        raise ExecutionRejected("job snapshot is invalid")
    try:
        limits = json.loads(job.limits)
    except json.JSONDecodeError:
        limits = {}
    if type(limits) is not dict:
        limits = {}
    approval_id = limits.get("approval_id")
    pinned = approval_id if type(approval_id) is str and approval_id != "" else None
    if pinned is not None:
        revoked = connection.execute(
            """
            SELECT 1 FROM approval_events
            WHERE project_id = ? AND prior_approval_id = ? AND event_kind = 'revoked'
            """,
            (str(job.project_id), pinned),
        ).fetchone()
        if revoked is not None:
            return ClaimDecision("BLOCKED", pinned, False)
    build_id = limits.get("build_id")
    build_hash = limits.get("build_hash")
    if type(build_id) is str and build_id != "":
        found = connection.execute(
            "SELECT content_hash FROM app_builds WHERE project_id = ? AND build_id = ?",
            (str(job.project_id), build_id),
        ).fetchone()
        if found is None or str(found[0]) != build_hash:
            return ClaimDecision("BLOCKED", pinned, False)
    environment_id = limits.get("environment_revision_id")
    environment_hash = limits.get("environment_hash")
    if type(environment_id) is str and environment_id != "" and type(environment_hash) is str and environment_hash != "":
        found = connection.execute(
            "SELECT content_hash FROM environment_revisions WHERE project_id = ? AND revision_id = ?",
            (str(job.project_id), environment_id),
        ).fetchone()
        if found is None or str(found[0]) != environment_hash:
            return ClaimDecision("BLOCKED", pinned, False)
    if job.purpose in {"trial", "regression"}:
        package_id = limits.get("replay_package_id")
        package_hash = limits.get("replay_package_hash")
        if type(package_id) is not str or package_id.strip() == "":
            return ClaimDecision("BLOCKED", pinned, False)
        if type(package_hash) is not str or package_hash.strip() == "":
            return ClaimDecision("BLOCKED", pinned, False)
        found = connection.execute(
            """
            SELECT body_hash FROM replay_packages
            WHERE project_id = ? AND package_id = ? AND ready = 1
            """,
            (str(job.project_id), package_id),
        ).fetchone()
        if found is None or str(found[0]) != package_hash:
            return ClaimDecision("BLOCKED", pinned, False)
    return ClaimDecision("ALLOWED", pinned, False)


def _stored_receipt(tx: Transaction, project_id: UUID, execution_id: str, job_id: str) -> ExecutionReceipt:
    rows = tx.connection.execute(
        """
        SELECT jobs.job_id, case_runs.case_run_id
        FROM case_runs
        JOIN jobs
          ON jobs.project_id = case_runs.project_id AND jobs.case_run_id = case_runs.case_run_id
        WHERE case_runs.project_id = ? AND case_runs.execution_id = ?
        ORDER BY case_runs.requested_at, jobs.job_id
        """,
        (str(project_id), execution_id),
    ).fetchall()
    limits = tx.connection.execute(
        "SELECT limits FROM jobs WHERE project_id = ? AND job_id = ?",
        (str(project_id), job_id),
    ).fetchone()
    stored = json.loads(str(limits[0])) if limits is not None else {}
    return ExecutionReceipt(
        UUID(execution_id),
        tuple(UUID(str(row[1])) for row in rows),
        tuple(UUID(str(row[0])) for row in rows),
        int(stored.get("commit_seq", 0)) if type(stored) is dict else 0,
        True,
    )


def _snapshot_limits(
    tx: Transaction, project_id: UUID, item: ResolvedTrialItem, commit_seq: int, failure_policy: str,
    release_label: str = "",
) -> str:
    settings_row = tx.connection.execute(
        "SELECT settings_json FROM case_versions WHERE project_id = ? AND version_id = ?",
        (str(project_id), str(item.case_version_id)),
    ).fetchone()
    settings = json.loads(str(settings_row[0])) if settings_row is not None else {}
    if type(settings) is not dict:
        settings = {}
    build_id = settings.get("build_id") if type(settings.get("build_id")) is str else ""
    build_hash = ""
    if build_id != "":
        build = tx.connection.execute(
            "SELECT content_hash FROM app_builds WHERE project_id = ? AND build_id = ?",
            (str(project_id), build_id),
        ).fetchone()
        build_hash = "" if build is None else str(build[0])
    environment = tx.connection.execute(
        "SELECT content_hash FROM environment_revisions WHERE project_id = ? AND revision_id = ?",
        (str(project_id), str(item.environment_revision_id)),
    ).fetchone()
    return canonical_json(
        {
            "approval_id": None if item.approval_id is None else str(item.approval_id),
            "release_label": normalized_release_label(release_label),
            "budget": "2.00",
            "build_hash": build_hash,
            "build_id": build_id,
            "commit_seq": commit_seq,
            "currency": "USD",
            "environment_hash": "" if environment is None else str(environment[0]),
            "environment_revision_id": str(item.environment_revision_id),
            "healing_snapshot": item.healing_snapshot,
            "replay_package_hash": item.replay_package_hash,
            "replay_package_id": None if item.replay_package_id is None else str(item.replay_package_id),
            "self_healing_enabled": False,
            "timeout_seconds": 600,
            "actor": 0,
            **item.limits,
            "failure_policy": failure_policy,
            "resource_id": str(item.resource_id),
            "dataset_version_id": None if item.dataset_version_id is None else str(item.dataset_version_id),
            "execution_snapshot": {
                "case_version_id": str(item.case_version_id),
                "manifest_hash": item.manifest_hash,
                "environment_revision_id": str(item.environment_revision_id),
                "resource_id": str(item.resource_id),
                "dataset_version_id": None if item.dataset_version_id is None else str(item.dataset_version_id),
                "approval_id": None if item.approval_id is None else str(item.approval_id),
                "entry_id": item.entry_id,
            },
        }
    )


def _require_item_pins(payload: dict[str, object], preview: ExecutionPreview) -> None:
    raw_items = payload.get("items")
    if type(raw_items) is not list or len(raw_items) != len(preview.resolved_items):
        raise ExecutionRejected("item pin does not match")
    for raw, item in zip(raw_items, preview.resolved_items, strict=True):
        if type(raw) is not dict:
            raise ExecutionRejected("item pin does not match")
        if raw.get("manifest_hash") != item.manifest_hash:
            raise ExecutionRejected("item pin does not match")
        if raw.get("replay_package_id") != (None if item.replay_package_id is None else str(item.replay_package_id)):
            raise ExecutionRejected("item pin does not match")
        if raw.get("replay_package_hash") != item.replay_package_hash:
            raise ExecutionRejected("item pin does not match")
        if raw.get("healing_policy_hash") != item.healing_policy_hash:
            raise ExecutionRejected("item pin does not match")


def _preview_hash(
    payload: dict[str, object],
    items: tuple[ResolvedTrialItem, ...],
    blockers: tuple[ExecutionBlocker, ...],
    exclusions: tuple[ExecutionExclusion, ...],
) -> str:
    return canonical_hash(
        {
            "blockers": [blocker.code for blocker in blockers],
            "exclusions": [item.entry_id for item in exclusions],
            "failure_policy": payload.get("failure_policy"),
            "items": [
                {
                    "approval_id": None if item.approval_id is None else str(item.approval_id),
                    "case_version_id": str(item.case_version_id),
                    "environment_revision_id": str(item.environment_revision_id),
                    "healing_policy_hash": item.healing_policy_hash,
                    "manifest_hash": item.manifest_hash,
                    "replay_package_hash": item.replay_package_hash,
                    "replay_package_id": None if item.replay_package_id is None else str(item.replay_package_id),
                    "resource_id": str(item.resource_id),
                    "dataset_version_id":None if item.dataset_version_id is None else str(item.dataset_version_id),
                    "entry_id":item.entry_id,
                }
                for item in items
            ],
            "purpose": payload.get("purpose"),
            "release_label": normalized_release_label(payload.get("release_label")),
            "self_healing_enabled": False,
            "source": payload.get("source"),
        },
        "canon-json-v1",
    )


def _legacy_receipt_matches(
    tx: Transaction, project_id: UUID, job_id: str, body_hash: str, payload: dict[str, object]
) -> bool:
    if body_hash != _request_hash(payload, legacy=True):
        return False
    row = tx.connection.execute(
        "SELECT limits FROM jobs WHERE project_id=? AND job_id=?", (str(project_id), job_id)
    ).fetchone()
    if row is None:
        return False
    try:
        limits = json.loads(str(row[0]))
    except (ValueError, TypeError):
        return False
    return type(limits) is dict and "release_label" not in limits


def _request_hash(payload: dict[str, object], *, legacy: bool = False) -> str:
    document = {
        "failure_policy": payload.get("failure_policy"),
        "name": _name(payload),
        "preview_hash": payload.get("preview_hash"),
        "items": payload.get("items"),
        "exclusions": payload.get("exclusions", []),
        "purpose": payload.get("purpose"),
        "self_healing_enabled": False,
        "source": payload.get("source"),
        "suite_version_id": _suite_version_ref(payload),
    }
    if not legacy:
        document["release_label"] = normalized_release_label(payload.get("release_label"))
    return canonical_hash(document, "canon-json-v1")


def _name(payload: dict[str, object]) -> str:
    name = payload.get("name")
    if type(name) is not str or name.strip() == "":
        raise ExecutionRejected("name is required")
    return name


def _scope(actor: Actor, project_id: UUID) -> None:
    if actor.project_scope != project_id:
        raise ExecutionRejected("project scope does not match")


def _uuid(value: object, message: str) -> UUID:
    if type(value) is not str:
        raise ExecutionRejected(message)
    try:
        return UUID(value)
    except ValueError as exc:
        raise ExecutionRejected(message) from exc


def finish_worker_run(
    connection: sqlite3.Connection,
    worker,
    finish,
    *,
    request_key: str,
    body_hash: str,
    now: datetime,
):
    """Delegate worker attempt finish. Approval remains on the browser path."""

    from aiqa.store.queue import finish_worker_attempt

    return finish_worker_attempt(
        connection,
        worker,
        finish,
        request_key=request_key,
        body_hash=body_hash,
        now=now,
    )


def separate_verify_heal_storage(
    *,
    original_failure: str,
    attempt_result: str,
    approved_package_digest: str,
    package_digest_after: str,
    healer_calls: int,
    verifier_calls: int,
) -> dict[str, object]:
    """Store original failure beside healing attempt without mutating the approved package."""

    return {
        "original_failure": original_failure,
        "healing_attempt_result": attempt_result,
        "approved_package_digest": approved_package_digest,
        "package_digest_after": package_digest_after,
        "approved_package_mutated": package_digest_after != approved_package_digest,
        "healer_calls": healer_calls,
        "verifier_calls": verifier_calls,
    }
