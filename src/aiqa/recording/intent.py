"""Freeze case verification goals onto a recording. No secrets or provider calls."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from uuid import UUID

from aiqa.contracts.cases import CaseDefinition, check_document, secret_ref_document
from aiqa.contracts.worker_attempt import RecordingIntent
from aiqa.domain.hashing import SCHEMA_VERSION, canonical_hash
from aiqa.domain.versions import definition_from_document


class IntentRejected(ValueError):
    """Recording intent could not be frozen or bound to a model request."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


_SECRET_MARKERS = frozenset(
    {
        "secret",
        "secret_value",
        "secret_plaintext",
        "api_key",
        "password",
        "token",
        "bearer",
    }
)


def freeze_recording_intent(
    *,
    case_version_id: UUID,
    content_hash: str,
    definition: CaseDefinition,
    project_id: UUID | None = None,
) -> RecordingIntent:
    """Build an immutable intent from a saved case version. Secret values stay out."""

    if type(content_hash) is not str or not content_hash.startswith("sha256:"):
        raise IntentRejected("content_hash is invalid")
    for ref in definition.secret_refs.values():
        if project_id is not None and ref.project_id != project_id:
            raise IntentRejected("foreign secret ref")
    document = intent_document_from_definition(definition, case_version_id, content_hash)
    return RecordingIntent(
        case_version_id=str(case_version_id),
        content_hash=content_hash,
        objective=str(document["objective"]),
        preconditions=tuple(str(item) for item in document["preconditions"]),  # type: ignore[arg-type]
        steps=tuple(dict(item) for item in document["steps"]),  # type: ignore[arg-type]
        final_expected=tuple(dict(item) for item in document["final_expected"]),  # type: ignore[arg-type]
        variables=dict(document["variables"]),  # type: ignore[arg-type]
        secret_refs={str(k): dict(v) for k, v in document["secret_refs"].items()},  # type: ignore[arg-type]
        path_policy=dict(document["path_policy"]),  # type: ignore[arg-type]
        intent_hash=canonical_hash(document, SCHEMA_VERSION),
    )


def intent_document_from_definition(
    definition: CaseDefinition, case_version_id: UUID, content_hash: str
) -> dict[str, object]:
    return {
        "case_version_id": str(case_version_id),
        "content_hash": content_hash,
        "final_expected": [check_document(check) for check in definition.final_expected],
        "objective": definition.objective,
        "path_policy": {
            "forbidden": list(definition.path_policy.forbidden),
            "must_use": list(definition.path_policy.must_use),
        },
        "preconditions": list(definition.preconditions),
        "secret_refs": {
            name: secret_ref_document(ref) for name, ref in definition.secret_refs.items()
        },
        "steps": [
            {
                "expected": [check_document(check) for check in step.expected],
                "id": step.id,
                "instruction": step.instruction,
            }
            for step in definition.steps
        ],
        "variables": dict(definition.variables),
    }


def intent_to_document(intent: RecordingIntent) -> dict[str, object]:
    return {
        "case_version_id": intent.case_version_id,
        "content_hash": intent.content_hash,
        "final_expected": list(intent.final_expected),
        "objective": intent.objective,
        "path_policy": dict(intent.path_policy),
        "preconditions": list(intent.preconditions),
        "secret_refs": {name: dict(ref) for name, ref in intent.secret_refs.items()},
        "steps": list(intent.steps),
        "variables": dict(intent.variables),
    }


def authoring_inputs(intent: RecordingIntent) -> tuple[str, ...]:
    """Server-owned sanitized authoring inputs. Never includes secret plaintext."""

    parts = [f"objective:{intent.objective}"]
    for item in intent.preconditions:
        parts.append(f"precondition:{item}")
    for step in intent.steps:
        parts.append(f"step:{step.get('id', '')}:{step.get('instruction', '')}")
        for check in step.get("expected", []):
            if type(check) is dict:
                parts.append(
                    f"check:{check.get('id', '')}:{check.get('kind', '')}:{check.get('expected', '')}"
                )
    for check in intent.final_expected:
        parts.append(
            f"final:{check.get('id', '')}:{check.get('kind', '')}:{check.get('expected', '')}"
        )
    for name, value in sorted(intent.variables.items()):
        parts.append(f"var:{name}:{json.dumps(value, sort_keys=True, separators=(',', ':'))}")
    for name, ref in sorted(intent.secret_refs.items()):
        parts.append(f"secret_ref:{name}:{ref.get('ref_id')}:{ref.get('revision')}")
    return tuple(parts)


def reject_secret_plaintext(values: object) -> None:
    """Refuse worker-supplied secret material on model-request inputs."""

    if type(values) is str:
        lowered = values.lower()
        for marker in _SECRET_MARKERS:
            if marker in lowered and ("=" in values or ":" in values):
                # Allow objective text that merely mentions secrets; block key=value shapes.
                if any(token in lowered for token in ("api_key=", "password=", "secret=", "token=")):
                    raise IntentRejected("secret plaintext is forbidden")
        return
    if type(values) is list:
        for item in values:
            reject_secret_plaintext(item)
        return
    if type(values) is dict:
        for key, value in values.items():
            if str(key).lower() in _SECRET_MARKERS:
                raise IntentRejected("secret plaintext is forbidden")
            reject_secret_plaintext(value)


def persist_recording_intent(
    connection: sqlite3.Connection,
    *,
    project_id: UUID,
    recording_id: UUID,
    intent: RecordingIntent,
) -> None:
    body = intent_to_document(intent)
    connection.execute(
        """
        INSERT INTO recording_intents (
            project_id, recording_id, case_version_id, content_hash, intent_hash, body_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(project_id),
            str(recording_id),
            intent.case_version_id,
            intent.content_hash,
            intent.intent_hash,
            json.dumps(body, sort_keys=True, separators=(",", ":")),
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def load_recording_intent(
    connection: sqlite3.Connection, project_id: UUID | str, recording_id: UUID | str
) -> RecordingIntent | None:
    row = connection.execute(
        """
        SELECT case_version_id, content_hash, intent_hash, body_json
        FROM recording_intents
        WHERE project_id = ? AND recording_id = ?
        """,
        (str(project_id), str(recording_id)),
    ).fetchone()
    if row is None:
        return None
    body = json.loads(str(row[3]))
    if type(body) is not dict:
        raise IntentRejected("stored intent is invalid")
    return RecordingIntent(
        case_version_id=str(row[0]),
        content_hash=str(row[1]),
        objective=str(body.get("objective", "")),
        preconditions=tuple(str(item) for item in body.get("preconditions", [])),
        steps=tuple(dict(item) for item in body.get("steps", []) if type(item) is dict),
        final_expected=tuple(
            dict(item) for item in body.get("final_expected", []) if type(item) is dict
        ),
        variables=dict(body.get("variables", {})),
        secret_refs={
            str(name): dict(ref)
            for name, ref in dict(body.get("secret_refs", {})).items()
            if type(ref) is dict
        },
        path_policy=dict(body.get("path_policy", {})),
        intent_hash=str(row[2]),
    )


def load_intent_for_attempt(
    connection: sqlite3.Connection, project_id: UUID | str, attempt_id: UUID | str
) -> RecordingIntent | None:
    row = connection.execute(
        """
        SELECT jobs.recording_id
        FROM attempts
        JOIN jobs
          ON jobs.project_id = attempts.project_id AND jobs.job_id = attempts.job_id
        WHERE attempts.project_id = ? AND attempts.attempt_id = ?
        """,
        (str(project_id), str(attempt_id)),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return load_recording_intent(connection, project_id, str(row[0]))


def freeze_intent_for_version(
    connection: sqlite3.Connection,
    *,
    project_id: UUID,
    case_id: UUID,
    case_version_id: UUID,
) -> RecordingIntent:
    row = connection.execute(
        """
        SELECT content_hash, definition_json
        FROM case_versions
        WHERE project_id = ? AND case_id = ? AND version_id = ?
        """,
        (str(project_id), str(case_id), str(case_version_id)),
    ).fetchone()
    if row is None:
        raise IntentRejected("case version is missing")
    payload = json.loads(str(row[1]))
    if type(payload) is not dict:
        raise IntentRejected("case definition is invalid")
    definition = definition_from_document(payload)
    return freeze_recording_intent(
        case_version_id=case_version_id,
        content_hash=str(row[0]),
        definition=definition,
        project_id=project_id,
    )


_OBSERVATION_INPUT_PREFIXES = (
    "observation_id:",
    "geometry:",
    "screen_digest:",
    "hierarchy_digest:",
    "previous_result:",
)


def _observation_context_inputs(worker_inputs: tuple[str, ...]) -> tuple[str, ...]:
    """Keep digest/geometry context from the worker. Raw pixels never appear here."""

    kept: list[str] = []
    for item in worker_inputs:
        if type(item) is not str:
            continue
        if item.startswith(_OBSERVATION_INPUT_PREFIXES):
            kept.append(item)
    return tuple(kept)


def bind_authoring_sanitized_inputs(
    connection: sqlite3.Connection,
    *,
    project_id: UUID,
    attempt_id: str,
    presented_hash: str | None,
    worker_inputs: tuple[str, ...],
) -> tuple[str, ...]:
    """Bind frozen objective and keep observation digests (never secret plaintext)."""

    reject_secret_plaintext(list(worker_inputs))
    observation_context = _observation_context_inputs(worker_inputs)
    intent = load_intent_for_attempt(connection, project_id, attempt_id)
    if intent is None:
        if presented_hash is not None:
            raise IntentRejected("recording intent is missing")
        # Legacy recording authoring without a frozen intent keeps worker inputs.
        return worker_inputs
    if presented_hash is not None and presented_hash != intent.intent_hash:
        raise IntentRejected("intent_hash mismatch")
    for ref in intent.secret_refs.values():
        if str(ref.get("project_id", "")) != str(project_id):
            raise IntentRejected("foreign secret ref")
    return authoring_inputs(intent) + observation_context
