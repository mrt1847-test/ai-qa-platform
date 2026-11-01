"""Trial preview and atomic RUN/ITEM/job admission. This does not open a device or a model."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from aiqa.contracts.cases import CaseDefinition, CaseVersion, PathPolicy
from aiqa.contracts.healing import ApprovedHealingPolicy, HealingRequest, Limits
from aiqa.contracts.jobs import IdempotencyKey
from aiqa.domain.hashing import canonical_hash, canonical_json
from aiqa.healing.policy import resolve_healing_policy
from aiqa.domain.projects import next_commit_seq
from aiqa.store.models import Actor, Transaction
from aiqa.store.queue import JobConflict

_OPERATION = "enqueue_execution"
_EMPTY_DEFINITION = CaseDefinition("", "", (), {}, {}, (), (), PathPolicy())


class ExecutionRejected(Exception):
    """The trial cannot be admitted."""


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


@dataclass(frozen=True, slots=True)
class ExecutionPreview:
    preview_hash: str
    resolved_items: tuple[ResolvedTrialItem, ...]
    blockers: tuple[ExecutionBlocker, ...]
    proposed_n: int
    self_healing_enabled: bool
    ready: bool


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    execution_id: UUID
    item_ids: tuple[UUID, ...]
    job_ids: tuple[UUID, ...]
    committed_seq: int
    replayed: bool


def preview_execution(tx: Transaction, actor: Actor, project_id: UUID, payload: dict[str, object]) -> ExecutionPreview:
    """Resolve one trial without reserving a run. Healing is forced off."""

    _scope(actor, project_id)
    items, blockers = _resolve(tx, project_id, payload)
    ready = blockers == () and items != () and all(item.replay_package_id is not None for item in items)
    return ExecutionPreview(
        preview_hash=_preview_hash(payload, items, blockers),
        resolved_items=items,
        blockers=blockers,
        proposed_n=len(items),
        self_healing_enabled=False,
        ready=ready,
    )


def enqueue_execution(
    tx: Transaction, actor: Actor, project_id: UUID, payload: dict[str, object], key: IdempotencyKey
) -> ExecutionReceipt:
    """Commit one trial RUN, ITEM, and job, or return the stored receipt."""

    _scope(actor, project_id)
    if key.project_id != project_id or key.operation != _OPERATION or key.key.strip() == "":
        raise ExecutionRejected("idempotency key does not match")
    preview = preview_execution(tx, actor, project_id, _preview_payload(payload))
    if not preview.ready or payload.get("preview_hash") != preview.preview_hash:
        raise ExecutionRejected("trial is not ready")
    _require_item_pins(payload, preview)
    body_hash = _request_hash(payload, preview)
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
            raise JobConflict("idempotency body does not match")
        limits = tx.connection.execute(
            "SELECT limits FROM jobs WHERE project_id = ? AND job_id = ?",
            (str(project_id), str(existing[1])),
        ).fetchone()
        stored = json.loads(str(limits[0])) if limits is not None else {}
        return ExecutionReceipt(
            UUID(str(existing[2])),
            (UUID(str(existing[3])),),
            (UUID(str(existing[1])),),
            int(stored.get("commit_seq", 0)),
            True,
        )
    item = preview.resolved_items[0]
    execution_id = uuid4()
    case_run_id = uuid4()
    job_id = uuid4()
    requested_at = datetime.now(timezone.utc).isoformat()
    commit_seq = next_commit_seq(tx, project_id)
    tx.connection.execute(
        """
        INSERT INTO executions (
            project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at
        ) VALUES (?, ?, ?, 'trial', 'single', NULL, ?)
        """,
        (str(project_id), str(execution_id), _name(payload), requested_at),
    )
    tx.connection.execute(
        """
        INSERT INTO case_runs (
            project_id, execution_id, case_run_id, case_id, case_version_id, purpose, requested_at
        ) VALUES (?, ?, ?, ?, ?, 'trial', ?)
        """,
        (str(project_id), str(execution_id), str(case_run_id), str(item.case_id), str(item.case_version_id), requested_at),
    )
    limits = canonical_json(
        {
            "budget": "2.00",
            "commit_seq": commit_seq,
            "currency": "USD",
            "healing_snapshot": item.healing_snapshot,
            "replay_package_hash": item.replay_package_hash,
            "replay_package_id": str(item.replay_package_id),
            "self_healing_enabled": False,
            "timeout_seconds": 600,
        }
    )
    tx.connection.execute(
        """
        INSERT INTO jobs (
            project_id, job_id, purpose, recording_id, case_run_id,
            payload_hash, source_refs, limits, status
        ) VALUES (?, ?, 'trial', NULL, ?, ?, ?, ?, 'queued')
        """,
        (
            str(project_id),
            str(job_id),
            str(case_run_id),
            body_hash,
            json.dumps([str(item.replay_package_id)], ensure_ascii=False, separators=(",", ":")),
            limits,
        ),
    )
    tx.connection.execute(
        """
        INSERT INTO job_receipts (
            project_id, actor_id, operation, request_key, body_hash, job_id, purpose,
            recording_id, execution_id, case_run_id, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'trial', NULL, ?, ?, 'queued', ?)
        """,
        (
            str(project_id),
            str(actor.actor_id),
            _OPERATION,
            key.key,
            body_hash,
            str(job_id),
            str(execution_id),
            str(case_run_id),
            requested_at,
        ),
    )
    return ExecutionReceipt(execution_id, (case_run_id,), (job_id,), commit_seq, False)


def _resolve(
    tx: Transaction, project_id: UUID, payload: dict[str, object]
) -> tuple[tuple[ResolvedTrialItem, ...], tuple[ExecutionBlocker, ...]]:
    if payload.get("purpose") != "trial" or payload.get("source") != "single":
        raise ExecutionRejected("trial source is required")
    if payload.get("failure_policy") not in {"continue", "stop_on_non_pass"}:
        raise ExecutionRejected("failure policy is required")
    selection = payload.get("selection", payload)
    raw_items = selection.get("items") if type(selection) is dict else None
    if type(raw_items) is not list or not 1 <= len(raw_items) <= 100:
        raise ExecutionRejected("item count is outside 1..100")
    resolved: list[ResolvedTrialItem] = []
    blockers: list[ExecutionBlocker] = []
    for raw in raw_items:
        if type(raw) is not dict:
            raise ExecutionRejected("item is invalid")
        item, item_blockers = _one_item(tx, project_id, raw)
        resolved.append(item)
        blockers.extend(item_blockers)
    return tuple(resolved), tuple(blockers)


def _one_item(
    tx: Transaction, project_id: UUID, raw: dict[str, object]
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
    if tx.connection.execute(
        "SELECT 1 FROM resource_aliases WHERE project_id = ? AND physical_key_id = ?",
        (str(project_id), str(resource_id)),
    ).fetchone() is None:
        blockers.append(ExecutionBlocker("RESOURCE_UNAVAILABLE", "resource is missing"))
    if dataset_id is not None and tx.connection.execute(
        "SELECT 1 FROM dataset_versions WHERE project_id = ? AND version_id = ?",
        (str(project_id), str(dataset_id)),
    ).fetchone() is None:
        blockers.append(ExecutionBlocker("RESOURCE_UNAVAILABLE", "dataset is missing"))
    definition = json.loads(str(row[1]))
    settings = json.loads(str(row[2]))
    if not _has_check(definition):
        blockers.append(ExecutionBlocker("DEFINITION_AMBIGUOUS", "required check is missing"))
    blockers.extend(_key_blockers(tx, project_id, settings))
    timeout = _timeout(settings)
    if timeout < 1:
        blockers.append(ExecutionBlocker("BUDGET_UNAVAILABLE", "budget is missing"))
    approval = None if row[5] is None else UUID(str(row[5]))
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
    )
    return item, tuple(blockers)


def _key_blockers(tx: Transaction, project_id: UUID, settings: dict[str, object]) -> tuple[ExecutionBlocker, ...]:
    method = "deterministic"
    binding_id = ""
    bindings = settings.get("verifier_bindings")
    if type(bindings) is list and bindings != [] and type(bindings[0]) is dict:
        method = str(bindings[0].get("method", method))
        binding_id = str(bindings[0].get("binding_id", ""))
    elif type(settings.get("verifier_method")) is str:
        method = str(settings.get("verifier_method"))
        binding_id = str(settings.get("verifier_binding_id", ""))
    if method == "deterministic":
        return ()
    if binding_id.strip() == "":
        return (ExecutionBlocker("MODEL_BINDING_UNAVAILABLE", "ai key is missing"),)
    found = tx.connection.execute(
        """
        SELECT key_ref_id FROM binding_revisions
        WHERE project_id = ? AND binding_id = ?
        ORDER BY revision DESC LIMIT 1
        """,
        (str(project_id), binding_id),
    ).fetchone()
    if found is None:
        return (ExecutionBlocker("MODEL_BINDING_UNAVAILABLE", "ai key is missing"),)
    secret = tx.connection.execute(
        "SELECT 1 FROM secret_refs WHERE project_id = ? AND ref_id = ?",
        (str(project_id), str(found[0])),
    ).fetchone()
    if secret is None:
        return (ExecutionBlocker("MODEL_BINDING_UNAVAILABLE", "ai key is missing"),)
    return ()


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
    items = payload.get("items")
    if type(items) is not list:
        raise ExecutionRejected("item is invalid")
    return {
        "name": payload.get("name"),
        "purpose": payload.get("purpose"),
        "source": payload.get("source"),
        "selection": {"items": items},
        "failure_policy": payload.get("failure_policy"),
        "exclusions": payload.get("exclusions", []),
    }


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
    payload: dict[str, object], items: tuple[ResolvedTrialItem, ...], blockers: tuple[ExecutionBlocker, ...]
) -> str:
    return canonical_hash(
        {
            "blockers": [blocker.code for blocker in blockers],
            "failure_policy": payload.get("failure_policy"),
            "items": [
                {
                    "case_version_id": str(item.case_version_id),
                    "environment_revision_id": str(item.environment_revision_id),
                    "healing_policy_hash": item.healing_policy_hash,
                    "manifest_hash": item.manifest_hash,
                    "replay_package_hash": item.replay_package_hash,
                    "replay_package_id": None if item.replay_package_id is None else str(item.replay_package_id),
                    "resource_id": str(item.resource_id),
                }
                for item in items
            ],
            "purpose": "trial",
            "self_healing_enabled": False,
            "source": "single",
        },
        "canon-json-v1",
    )


def _request_hash(payload: dict[str, object], preview: ExecutionPreview) -> str:
    return canonical_hash(
        {
            "failure_policy": payload.get("failure_policy"),
            "name": _name(payload),
            "preview_hash": preview.preview_hash,
            "purpose": "trial",
            "self_healing_enabled": False,
            "source": "single",
        },
        "canon-json-v1",
    )


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
