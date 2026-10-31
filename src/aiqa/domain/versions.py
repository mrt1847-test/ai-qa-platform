"""Step and check projection. Callers own the transaction around persist_projection."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from aiqa.contracts.cases import (
    CaseDefinition,
    CaseReadiness,
    CaseRevisionInput,
    CaseSettings,
    CaseVersionView,
    CheckSpec,
    PathPolicy,
    ReadinessReason,
    StepSpec,
    check_document,
    secret_ref_document,
)
from aiqa.domain.hashing import SCHEMA_VERSION, canonical_hash, canonical_json, execution_snapshot_hash
from aiqa.domain.projects import next_commit_seq
from aiqa.store.database import Store
from aiqa.store.models import Actor, CaseMetadata, CaseMetadataView, SecretRef, Transaction

_store: ContextVar[Store] = ContextVar("aiqa_case_store")


class StaleHead(Exception):
    """The draft head moved before this save."""


class ForeignParent(Exception):
    """The parent or base version belongs to another case."""


class ForeignSecretRef(Exception):
    """The secret ref belongs to another project."""


class SettingsRejected(Exception):
    """A case setting was rejected and the typed fields stay available."""

    def __init__(self, message: str, submitted: dict[str, object]) -> None:
        super().__init__(message)
        self.submitted = submitted


@dataclass(frozen=True, slots=True)
class StepEditCommand:
    """One explicit step change. The result is a new draft."""

    action: str
    step_id: str = ""
    instruction: str = ""
    expected: str = ""
    direction: str = "down"
    variable: str = ""
    expected_head: UUID | None = None


class CaseNotFound(Exception):
    """The case is not in this project."""


class ForeignTc(Exception):
    """The TC version belongs to another project."""


@contextmanager
def bind_case_store(store: Store) -> Iterator[None]:
    token = _store.set(store)
    try:
        yield
    finally:
        _store.reset(token)


def create_case(actor: Actor, name: str, tc_reference: str | None) -> CaseMetadata:
    if actor.project_scope is None:
        raise CaseNotFound("case was not found")
    if type(name) is not str or name.strip() == "":
        raise ValueError("case name is required")
    case_id = uuid4()
    with _bound_store().transaction() as connection:
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference,
                next_revision, latest_draft_version_id, current_approval_id,
                lock_version, archived_at
            ) VALUES (?, ?, ?, NULL, ?, 1, NULL, NULL, 0, NULL)
            """,
            (str(actor.project_scope), str(case_id), name, tc_reference),
        )
    return CaseMetadata(
        project_id=actor.project_scope,
        case_id=case_id,
        name=name,
        tc_reference=tc_reference,
        folder_id=None,
        lock_version=0,
    )


def parse_case_settings(payload: dict[str, object], project_id: UUID | None) -> CaseSettings:
    """Read one case settings document. Global caps stay outside the saved case values."""

    target = payload.get("target_kind")
    if target not in {"web", "android"}:
        raise ValueError("invalid settings")
    submitted = _public_settings(payload)
    healing = payload.get("healing_policy", {})
    if type(healing) is not dict:
        raise SettingsRejected("invalid healing", submitted)
    if healing.get("default_enabled", False) is not False:
        raise SettingsRejected("healing stays off", submitted)
    if type(healing.get("allowed", False)) is not bool:
        raise SettingsRejected("invalid healing", submitted)
    method = str(payload.get("verifier_method", "deterministic"))
    if method not in {"deterministic", "ai_visual", "deterministic_then_ai_unknown"}:
        raise SettingsRejected("invalid verifier", submitted)
    binding = str(payload.get("verifier_binding_id", ""))
    if method != "deterministic" and binding == "":
        raise SettingsRejected("ai binding is required", submitted)
    try:
        episodes = int(healing.get("max_episodes_per_item", 1))
        calls = int(healing.get("max_model_calls_per_item", 2))
        seconds = int(healing.get("max_seconds", 30))
    except (TypeError, ValueError) as exc:
        raise SettingsRejected("healing limit exceeded", submitted) from exc
    if episodes < 0 or episodes > 1 or calls < 0 or calls > 2 or seconds < 0 or seconds > 30:
        raise SettingsRejected("healing limit exceeded", submitted)
    secret_refs = _parse_setting_refs(payload.get("secret_refs", {}), project_id, submitted)
    document: dict[str, object] = {
        "web_url": str(payload.get("web_url", "")),
        "android_package": str(payload.get("android_package", "")),
        "environment_revision_id": str(payload.get("environment_revision_id", "")),
        "data_revision_id": str(payload.get("data_revision_id", "")),
        "secret_refs": {
            name: {"project_id": str(ref.project_id), "ref_id": str(ref.ref_id), "revision": ref.revision}
            for name, ref in secret_refs.items()
        },
        "install_policy": str(payload.get("install_policy", "none")),
        "reset_policy": str(payload.get("reset_policy", "none")),
        "cleanup_policy": str(payload.get("cleanup_policy", "none")),
        "limits": {"timeout_seconds": _limit(payload.get("limits", {}), submitted)},
        "verifier_bindings": [
            {
                "method": method,
                "binding_id": binding,
                "allow_unknown_supplement": payload.get("allow_unknown_supplement", False) is True,
            }
        ],
        "healing_policy": {
            "allowed": healing.get("allowed", False) is True,
            "default_enabled": False,
            "scope": str(healing.get("scope", "")),
            "max_episodes_per_item": episodes,
            "max_model_calls_per_item": calls,
            "max_seconds": seconds,
        },
    }
    mode = payload.get("execution_mode", "recorded_replay")
    if mode != "recorded_replay":
        raise SettingsRejected("execution mode stays recorded", submitted)
    return CaseSettings(target_kind=str(target), execution_mode="recorded_replay", document=document)


def settings_document(settings: CaseSettings) -> str:
    """Serialize case settings. The replay package is not part of this document."""

    body = {"execution_mode": settings.execution_mode, "target_kind": settings.target_kind}
    body.update(settings.document)
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _public_settings(payload: dict[str, object]) -> dict[str, object]:
    healing = payload.get("healing_policy", {})
    public_healing = healing if type(healing) is dict else {}
    return {
        "web_url": payload.get("web_url", ""),
        "android_package": payload.get("android_package", ""),
        "environment_revision_id": payload.get("environment_revision_id", ""),
        "data_revision_id": payload.get("data_revision_id", ""),
        "install_policy": payload.get("install_policy", "none"),
        "reset_policy": payload.get("reset_policy", "none"),
        "cleanup_policy": payload.get("cleanup_policy", "none"),
        "verifier_method": payload.get("verifier_method", "deterministic"),
        "verifier_binding_id": payload.get("verifier_binding_id", ""),
        "healing_policy": {
            "allowed": public_healing.get("allowed", False),
            "default_enabled": False,
            "scope": public_healing.get("scope", ""),
        },
    }


def _limit(payload: object, submitted: dict[str, object]) -> int:
    if type(payload) is not dict:
        raise SettingsRejected("invalid limit", submitted)
    try:
        timeout = int(payload.get("timeout_seconds", 600))
    except (TypeError, ValueError) as exc:
        raise SettingsRejected("invalid limit", submitted) from exc
    if timeout < 1 or timeout > 600:
        raise SettingsRejected("invalid limit", submitted)
    return timeout


def _parse_setting_refs(
    payload: object,
    project_id: UUID | None,
    submitted: dict[str, object],
) -> dict[str, SecretRef]:
    if type(payload) is not dict:
        raise SettingsRejected("invalid secret ref", submitted)
    refs: dict[str, SecretRef] = {}
    for name, value in payload.items():
        if type(value) is not dict or any(key in value for key in ("value", "secret", "secret_plaintext", "secret_value")):
            raise SettingsRejected("secret ref was rejected", submitted)
        try:
            ref = SecretRef(
                project_id=UUID(str(value.get("project_id"))),
                ref_id=UUID(str(value.get("ref_id"))),
                revision=int(value["revision"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SettingsRejected("secret ref was rejected", submitted) from exc
        if project_id is not None and ref.project_id != project_id:
            raise SettingsRejected("secret ref was rejected", submitted)
        refs[str(name)] = ref
    return refs


def _settings_secret_refs(settings: CaseSettings) -> dict[str, SecretRef]:
    raw = settings.document.get("secret_refs", {})
    if type(raw) is not dict:
        return {}
    refs: dict[str, SecretRef] = {}
    for name, value in raw.items():
        if type(value) is not dict:
            continue
        refs[str(name)] = SecretRef(
            project_id=UUID(str(value["project_id"])),
            ref_id=UUID(str(value["ref_id"])),
            revision=int(value["revision"]),
        )
    return refs


def save_case_revision(
    actor: Actor,
    case_id: UUID,
    revision: CaseRevisionInput,
    expected_head: UUID | None,
) -> CaseVersionView:
    if actor.project_scope is None:
        raise CaseNotFound("case was not found")
    for ref in revision.definition.secret_refs.values():
        if ref.project_id != actor.project_scope:
            raise ForeignSecretRef("secret ref belongs to another project")
    for ref in _settings_secret_refs(revision.settings).values():
        if ref.project_id != actor.project_scope:
            raise ForeignSecretRef("secret ref belongs to another project")
    store = _bound_store()
    ensure_projection_tables(store._connection)
    version_id = uuid4()
    readiness = _readiness(revision.definition)
    with store.transaction() as connection:
        case_row = connection.execute(
            """
            SELECT next_revision, latest_draft_version_id, lock_version
            FROM automation_cases
            WHERE project_id = ? AND case_id = ?
            """,
            (str(actor.project_scope), str(case_id)),
        ).fetchone()
        if case_row is None:
            raise CaseNotFound("case was not found")
        next_revision = int(case_row[0])
        latest = None if case_row[1] is None else str(case_row[1])
        lock_version = int(case_row[2])
        if not revision.branch:
            if latest is None:
                if expected_head is not None:
                    raise StaleHead("draft head changed")
            elif expected_head is None or str(expected_head) != latest:
                raise StaleHead("draft head changed")
        _require_same_case(connection, actor.project_scope, case_id, revision.parent_version_id)
        _require_same_case(connection, actor.project_scope, case_id, revision.base_version_id)
        persist_projection(connection, str(version_id), revision.definition)
        stored = connection.execute(
            """
            SELECT content_hash, verification_digest, body_json
            FROM definition_documents
            WHERE version_id = ?
            """,
            (str(version_id),),
        ).fetchone()
        if stored is None:
            raise RuntimeError("projection was not stored")
        settings_json = settings_document(revision.settings)
        recorded_steps_json = json.dumps(list(revision.recorded_steps), ensure_ascii=False, separators=(",", ":"))
        content_hash = execution_snapshot_hash(
            json.loads(str(stored[2])), json.loads(settings_json), list(revision.recorded_steps)
        )
        created_at = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind,
                parent_version_id, base_version_id, is_branch, definition_json,
                settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id,
                reason, created_at
            ) VALUES (?, ?, ?, ?, 'input', ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?)
            """,
            (
                str(actor.project_scope),
                str(case_id),
                str(version_id),
                next_revision,
                None if revision.parent_version_id is None else str(revision.parent_version_id),
                None if revision.base_version_id is None else str(revision.base_version_id),
                1 if revision.branch else 0,
                str(stored[2]),
                settings_json,
                recorded_steps_json,
                content_hash,
                str(stored[1]),
                json.dumps(_readiness_json(readiness), ensure_ascii=False, separators=(",", ":")),
                str(actor.actor_id),
                revision.reason,
                created_at,
            ),
        )
        commit_seq = next_commit_seq(Transaction(connection), actor.project_scope)
        connection.execute(
            """
            INSERT INTO case_revision_audits (
                project_id, case_id, version_id, commit_seq, actor_id, action, created_at
            ) VALUES (?, ?, ?, ?, ?, 'save', ?)
            """,
            (str(actor.project_scope), str(case_id), str(version_id), commit_seq, str(actor.actor_id), created_at),
        )
        if revision.branch:
            updated = connection.execute(
                """
                UPDATE automation_cases
                SET next_revision = ?, lock_version = lock_version + 1
                WHERE project_id = ? AND case_id = ? AND lock_version = ?
                """,
                (next_revision + 1, str(actor.project_scope), str(case_id), lock_version),
            )
        else:
            updated = connection.execute(
                """
                UPDATE automation_cases
                SET latest_draft_version_id = ?, next_revision = ?, lock_version = lock_version + 1
                WHERE project_id = ? AND case_id = ? AND lock_version = ?
                  AND (
                    (? IS NULL AND latest_draft_version_id IS NULL)
                    OR latest_draft_version_id = ?
                  )
                """,
                (
                    str(version_id),
                    next_revision + 1,
                    str(actor.project_scope),
                    str(case_id),
                    lock_version,
                    None if expected_head is None else str(expected_head),
                    None if expected_head is None else str(expected_head),
                ),
            )
        if updated.rowcount != 1:
            raise StaleHead("draft head changed")
    return CaseVersionView(
        project_id=actor.project_scope,
        case_id=case_id,
        id=version_id,
        revision=next_revision,
        creation_kind="input",
        parent_version_id=revision.parent_version_id,
        base_version_id=revision.base_version_id,
        content_hash=content_hash,
        verification_digest=str(stored[1]),
        replay_package_id=None,
        readiness=readiness,
    )


def _require_same_case(
    connection: sqlite3.Connection, project_id: UUID, case_id: UUID, version_id: UUID | None
) -> None:
    if version_id is None:
        return
    row = connection.execute(
        "SELECT project_id, case_id FROM case_versions WHERE version_id = ?",
        (str(version_id),),
    ).fetchone()
    if row is None or str(row[0]) != str(project_id) or str(row[1]) != str(case_id):
        raise ForeignParent("version belongs to another case")


def apply_step_edit(actor: Actor, case_id: UUID, command: StepEditCommand) -> tuple[CaseVersionView, tuple[str, ...]]:
    """Save one step change as a new draft. A copy receives a new id."""

    loaded = _stored_definition(actor, case_id)
    if loaded is None:
        raise CaseNotFound("case was not found")
    definition, head, settings, recorded_steps = loaded
    if command.expected_head != head:
        raise StaleHead("draft head changed")
    edited = _edit_definition(definition, command)
    view = save_case_revision(
        actor,
        case_id,
        CaseRevisionInput(
            definition=edited, settings=settings, recorded_steps=recorded_steps,
            parent_version_id=head, reason="step",
        ),
        head,
    )
    return view, tuple(step.id for step in edited.steps)


def _stored_definition(
    actor: Actor, case_id: UUID
) -> tuple[CaseDefinition, UUID, CaseSettings, tuple[dict[str, object], ...]] | None:
    if actor.project_scope is None:
        raise CaseNotFound("case was not found")
    with _bound_store().transaction() as connection:
        row = connection.execute(
            """
            SELECT latest_draft_version_id
            FROM automation_cases
            WHERE project_id = ? AND case_id = ?
            """,
            (str(actor.project_scope), str(case_id)),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        stored = connection.execute(
            "SELECT definition_json, settings_json, recorded_steps_json FROM case_versions WHERE project_id = ? AND version_id = ?",
            (str(actor.project_scope), str(row[0])),
        ).fetchone()
    if stored is None:
        return None
    settings_body = json.loads(str(stored[1]))
    settings = CaseSettings(
        target_kind=settings_body.pop("target_kind"),
        execution_mode=settings_body.pop("execution_mode", "recorded_replay"),
        document=settings_body,
    )
    return (
        _definition_from_body(json.loads(str(stored[0]))), UUID(str(row[0])),
        settings, tuple(json.loads(str(stored[2]))),
    )


def _edit_definition(definition: CaseDefinition, command: StepEditCommand) -> CaseDefinition:
    steps = list(definition.steps)
    variables = dict(definition.variables)
    if command.action == "add":
        steps.append(_new_step(command.instruction, command.expected))
    elif command.action == "duplicate":
        steps = list(_duplicate_step(tuple(steps), command.step_id))
    elif command.action == "remove":
        _require_check_kept(definition, command.step_id)
        steps = [step for step in steps if step.id != command.step_id]
        if len(steps) == len(definition.steps):
            raise ValueError("step was not found")
    elif command.action == "move":
        steps = list(_move_step(tuple(steps), command.step_id, command.direction))
    elif command.action == "bind_variable":
        steps, variables = _bind_variable(tuple(steps), variables, command.step_id, command.variable)
    else:
        raise ValueError("step action is invalid")
    return CaseDefinition(
        raw_text=definition.raw_text,
        objective=definition.objective,
        preconditions=definition.preconditions,
        variables=variables,
        secret_refs=definition.secret_refs,
        steps=tuple(steps),
        final_expected=definition.final_expected,
        path_policy=definition.path_policy,
    )


def _new_step(instruction: str, expected: str) -> StepSpec:
    checks = () if expected == "" else (CheckSpec(str(uuid4()), "text", expected),)
    return StepSpec(str(uuid4()), instruction, checks)


def _duplicate_step(steps: tuple[StepSpec, ...], step_id: str) -> tuple[StepSpec, ...]:
    copied: list[StepSpec] = []
    found = False
    for step in steps:
        copied.append(step)
        if step.id == step_id:
            found = True
            copied.append(
                StepSpec(
                    str(uuid4()),
                    step.instruction,
                    tuple(CheckSpec(str(uuid4()), check.kind, check.expected) for check in step.expected),
                    step.point,
                )
            )
    if not found:
        raise ValueError("step was not found")
    return tuple(copied)


def _move_step(steps: tuple[StepSpec, ...], step_id: str, direction: str) -> tuple[StepSpec, ...]:
    index = next((position for position, step in enumerate(steps) if step.id == step_id), -1)
    if index < 0:
        raise ValueError("step was not found")
    target = index - 1 if direction == "up" else index + 1
    if target < 0 or target >= len(steps):
        return steps
    items = list(steps)
    items[index], items[target] = items[target], items[index]
    return tuple(items)


def _bind_variable(
    steps: tuple[StepSpec, ...],
    variables: dict[str, object],
    step_id: str,
    variable: str,
) -> tuple[tuple[StepSpec, ...], dict[str, object]]:
    if variable == "" or not variable.replace("_", "").isalnum():
        raise ValueError("variable name is invalid")
    found = False
    bound: list[StepSpec] = []
    marker = "{{" + variable + "}}"
    for step in steps:
        if step.id != step_id:
            bound.append(step)
            continue
        found = True
        instruction = step.instruction if marker in step.instruction else f"{step.instruction} {marker}".strip()
        bound.append(StepSpec(step.id, instruction, step.expected, step.point))
    if not found:
        raise ValueError("step was not found")
    if variable not in variables:
        variables[variable] = ""
    return tuple(bound), variables


def _require_check_kept(definition: CaseDefinition, step_id: str) -> None:
    removed = next((step for step in definition.steps if step.id == step_id), None)
    if removed is None:
        return
    referenced = set(definition.path_policy.must_use)
    if any(check.id in referenced or check.expected in referenced for check in removed.expected):
        raise ValueError("required check is still referenced")


def definition_from_document(payload: dict[str, object]) -> CaseDefinition:
    steps_raw = payload.get("steps", [])
    final_raw = payload.get("final_expected", [])
    policy = payload.get("path_policy", {})
    variables = payload.get("variables", {})
    preconditions = payload.get("preconditions", [])
    secret_raw = payload.get("secret_refs", {})
    if (
        type(steps_raw) is not list
        or type(final_raw) is not list
        or type(policy) is not dict
        or type(variables) is not dict
        or type(preconditions) is not list
        or type(secret_raw) is not dict
    ):
        raise ValueError("stored definition is invalid")
    return CaseDefinition(
        raw_text=str(payload.get("raw_text", "")),
        objective=str(payload.get("objective", "")),
        preconditions=tuple(str(item) for item in preconditions),
        variables=dict(variables),
        secret_refs=_secret_refs_from_body(secret_raw),
        steps=tuple(_step_from_body(item) for item in steps_raw),
        final_expected=tuple(_check_from_body(item) for item in final_raw),
        path_policy=PathPolicy(
            must_use=tuple(str(item) for item in policy.get("must_use", [])),
            forbidden=tuple(str(item) for item in policy.get("forbidden", [])),
        ),
    )


def _secret_refs_from_body(payload: dict[str, object]) -> dict[str, SecretRef]:
    refs: dict[str, SecretRef] = {}
    for name, value in payload.items():
        if type(value) is not dict:
            raise ValueError('stored secret reference is invalid')
        refs[str(name)] = SecretRef(
            project_id=UUID(str(value["project_id"])),
            ref_id=UUID(str(value["ref_id"])),
            revision=int(value["revision"]),
        )
    return refs


# Preserve the internal name for existing read paths while sharing one parser
# with proposal acceptance and clone projections.
_definition_from_body = definition_from_document


def _step_from_body(payload: object) -> StepSpec:
    if type(payload) is not dict:
        raise ValueError("stored step is invalid")
    expected = payload.get("expected", [])
    if type(expected) is not list:
        raise ValueError("stored step is invalid")
    point = payload.get("point")
    parsed = None
    if type(point) is list and len(point) == 2:
        parsed = (int(point[0]), int(point[1]))
    return StepSpec(str(payload.get("id")), str(payload.get("instruction")), tuple(_check_from_body(item) for item in expected), parsed)


def _check_from_body(payload: object) -> CheckSpec:
    if type(payload) is not dict:
        raise ValueError("stored check is invalid")
    return CheckSpec(str(payload.get("id")), str(payload.get("kind")), str(payload.get("expected")))


def latest_draft(actor: Actor, case_id: UUID) -> dict[str, object] | None:
    """Read the saved draft text. A missing case returns None."""

    if actor.project_scope is None:
        raise CaseNotFound("case was not found")
    with _bound_store().transaction() as connection:
        row = connection.execute(
            """
            SELECT latest_draft_version_id
            FROM automation_cases
            WHERE project_id = ? AND case_id = ?
            """,
            (str(actor.project_scope), str(case_id)),
        ).fetchone()
        if row is None:
            return None
        if row[0] is None:
            return {"version_id": None, "raw_text": "", "objective": ""}
        stored = connection.execute(
            "SELECT definition_json FROM case_versions WHERE project_id = ? AND version_id = ?",
            (str(actor.project_scope), str(row[0])),
        ).fetchone()
    body = {} if stored is None else json.loads(str(stored[0]))
    return {
        "version_id": str(row[0]),
        "raw_text": str(body.get("raw_text", "")),
        "objective": str(body.get("objective", "")),
    }


def _readiness(definition: CaseDefinition) -> CaseReadiness:
    reasons: list[ReadinessReason] = []
    if definition.objective.strip() == "" or not definition.steps:
        reasons.append(ReadinessReason("DEFINITION_AMBIGUOUS", "definition is incomplete"))
    if any(not step.expected for step in definition.steps) and not definition.final_expected:
        reasons.append(ReadinessReason("EXPECTED_REQUIRED", "a required expected value is missing"))
    return CaseReadiness(
        saved=True,
        recordable=False,
        replayable=False,
        reviewable=False,
        formal_runnable=False,
        reasons=tuple(reasons),
    )


def _readiness_json(readiness: CaseReadiness) -> dict[str, object]:
    return {
        "formal_runnable": readiness.formal_runnable,
        "reasons": [{"code": reason.code, "message": reason.message} for reason in readiness.reasons],
        "recordable": readiness.recordable,
        "replayable": readiness.replayable,
        "reviewable": readiness.reviewable,
        "saved": readiness.saved,
    }


def _bound_store() -> Store:
    try:
        return _store.get()
    except LookupError as exc:
        raise RuntimeError("case store is not bound") from exc

def verification_digest(definition: CaseDefinition) -> str:
    _reject_values(definition.variables)
    document = {
        "final_expected": [check_document(check) for check in definition.final_expected],
        "objective": definition.objective,
        "path_policy": {
            "forbidden": list(definition.path_policy.forbidden),
            "must_use": list(definition.path_policy.must_use),
        },
        "preconditions": list(definition.preconditions),
        "secret_refs": {
            name: {"ref_id": str(ref.ref_id), "revision": ref.revision}
            for name, ref in definition.secret_refs.items()
        },
        "steps": [_semantic_step(step) for step in definition.steps],
        "variable_schema": {name: _type_label(value) for name, value in definition.variables.items()},
    }
    return canonical_hash(document, SCHEMA_VERSION)


def ensure_projection_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS definition_documents (
            version_id TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL,
            verification_digest TEXT NOT NULL,
            body_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS step_projections (
            version_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            semantic_hash TEXT NOT NULL,
            PRIMARY KEY (version_id, step_id),
            FOREIGN KEY (version_id) REFERENCES definition_documents(version_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS check_projections (
            version_id TEXT NOT NULL,
            step_id TEXT,
            check_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            semantic_hash TEXT NOT NULL,
            PRIMARY KEY (version_id, check_id),
            FOREIGN KEY (version_id, step_id) REFERENCES step_projections(version_id, step_id)
        )
        """
    )


def persist_projection(connection: sqlite3.Connection, version_id: str, definition: CaseDefinition) -> None:
    if version_id.strip() == "":
        raise ValueError("version_id is required")
    body = _content_document(definition)
    digest = verification_digest(definition)
    connection.execute(
        """
        INSERT INTO definition_documents (version_id, content_hash, verification_digest, body_json)
        VALUES (?, ?, ?, ?)
        """,
        (version_id, canonical_hash(body, SCHEMA_VERSION), digest, canonical_json(body)),
    )
    seen_checks: set[str] = set()
    for position, step in enumerate(definition.steps):
        connection.execute(
            """
            INSERT INTO step_projections (version_id, step_id, position, semantic_hash)
            VALUES (?, ?, ?, ?)
            """,
            (version_id, step.id, position, canonical_hash(_semantic_step(step), SCHEMA_VERSION)),
        )
        for check_position, check in enumerate(step.expected):
            _insert_check(connection, version_id, step.id, check, check_position, seen_checks)
    for position, check in enumerate(definition.final_expected):
        _insert_check(connection, version_id, None, check, position, seen_checks)


def _content_document(definition: CaseDefinition) -> dict[str, object]:
    _reject_values(definition.variables)
    return {
        "final_expected": [check_document(check) for check in definition.final_expected],
        "objective": definition.objective,
        "path_policy": {
            "forbidden": list(definition.path_policy.forbidden),
            "must_use": list(definition.path_policy.must_use),
        },
        "preconditions": list(definition.preconditions),
        "raw_text": definition.raw_text,
        "secret_refs": {name: secret_ref_document(ref) for name, ref in definition.secret_refs.items()},
        "steps": [
            {
                "expected": [check_document(check) for check in step.expected],
                "id": step.id,
                "instruction": step.instruction,
                "point": None if step.point is None else [step.point[0], step.point[1]],
            }
            for step in definition.steps
        ],
        "variables": dict(definition.variables),
    }


def _semantic_step(step: StepSpec) -> dict[str, object]:
    return {
        "expected": [check_document(check) for check in step.expected],
        "id": step.id,
        "instruction": step.instruction,
    }


def _insert_check(
    connection: sqlite3.Connection,
    version_id: str,
    step_id: str | None,
    check: CheckSpec,
    position: int,
    seen: set[str],
) -> None:
    if check.id in seen:
        raise ValueError("check id must be unique in the definition")
    seen.add(check.id)
    connection.execute(
        """
        INSERT INTO check_projections (version_id, step_id, check_id, position, semantic_hash)
        VALUES (?, ?, ?, ?, ?)
        """,
        (version_id, step_id, check.id, position, canonical_hash(check_document(check), SCHEMA_VERSION)),
    )


def _reject_values(values: dict[str, object]) -> None:
    for value in values.values():
        canonical_json(value)


def assign_tc_reference(actor: Actor, case_id: UUID, tc_version_id: UUID | None) -> CaseMetadataView:
    """Pin or clear a TC version without a case revision, hash change, or approval change."""

    if actor.project_scope is None:
        raise CaseNotFound("case was not found")
    with _bound_store().transaction() as connection:
        if tc_version_id is not None:
            owner = connection.execute(
                "SELECT project_id FROM tc_versions WHERE version_id = ?",
                (str(tc_version_id),),
            ).fetchone()
            if owner is None or str(owner[0]) != str(actor.project_scope):
                raise ForeignTc("tc version belongs to another project")
        updated = connection.execute(
            """
            UPDATE automation_cases
            SET tc_reference = ?, lock_version = lock_version + 1
            WHERE project_id = ? AND case_id = ?
            """,
            (
                None if tc_version_id is None else str(tc_version_id),
                str(actor.project_scope),
                str(case_id),
            ),
        )
        if updated.rowcount != 1:
            raise CaseNotFound("case was not found")
        connection.execute(
            """
            INSERT INTO case_tc_references (project_id, case_id, tc_version_id)
            VALUES (?, ?, ?)
            ON CONFLICT (project_id, case_id) DO UPDATE SET tc_version_id = excluded.tc_version_id
            """,
            (
                str(actor.project_scope),
                str(case_id),
                None if tc_version_id is None else str(tc_version_id),
            ),
        )
        created_at = datetime.now(timezone.utc).isoformat()
        commit_seq = next_commit_seq(Transaction(connection), actor.project_scope)
        connection.execute(
            """
            INSERT INTO case_tc_reference_audits (
                project_id, case_id, tc_version_id, action, actor_id, commit_seq, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(actor.project_scope),
                str(case_id),
                None if tc_version_id is None else str(tc_version_id),
                "unlink" if tc_version_id is None else "link",
                str(actor.actor_id),
                commit_seq,
                created_at,
            ),
        )
        row = connection.execute(
            """
            SELECT name, tc_reference, current_approval_id, latest_draft_version_id, lock_version
            FROM automation_cases
            WHERE project_id = ? AND case_id = ?
            """,
            (str(actor.project_scope), str(case_id)),
        ).fetchone()
    if row is None:
        raise CaseNotFound("case was not found")
    return CaseMetadataView(
        project_id=actor.project_scope,
        case_id=case_id,
        name=str(row[0]),
        tc_reference=None if row[1] is None else UUID(str(row[1])),
        current_approval_id=None if row[2] is None else UUID(str(row[2])),
        latest_draft_version_id=None if row[3] is None else UUID(str(row[3])),
        lock_version=int(row[4]),
    )


def _type_label(value: object) -> str:
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "int"
    if type(value) is str:
        return "string"
    if isinstance(value, list | tuple):
        return "array"
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "null"
    raise ValueError("variable value cannot be described")
