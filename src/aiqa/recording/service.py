"""Recording start and seal. Preflight does not reserve a device or call a model."""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID, uuid4

import hashlib

from aiqa.contracts.jobs import IdempotencyKey, JobSubmission
from aiqa.domain.hashing import canonical_hash
from aiqa.replay.android_plan import (
    PlanRejected,
    android_mapping_digest,
    android_trace_ready,
    build_android_package_from_manifest,
)
from aiqa.replay.compiler import CompiledPackage
from aiqa.replay.packages import validate_package_body
from aiqa.store.artifacts import ArtifactRejected, require_ready_artifacts
from aiqa.recording.manifests import (
    FinishConflict,
    ManifestReceipt,
    MaterializationReceipt,
    RecordingFinishInput,
    RecordingView,
    finish_body_hash,
)
from aiqa.store.models import Actor, RecordingManifest, Transaction
from aiqa.store.queue import JobConflict, enqueue_job


class PreflightRejected(Exception):
    """The start was refused before any recording row existed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class HashMismatch(Exception):
    """The submitted version hash is not the stored hash."""


@dataclass(frozen=True, slots=True)
class RerecordInput:
    """A full rerecording. It keeps the base and does not resume the middle."""

    case_id: UUID
    base_version_id: UUID
    expected_head: UUID
    reason: str
    resource_id: str
    web_url: str
    data_name: str
    reset_policy: str
    confirm_device: bool
    confirm_target: bool
    confirm_data: bool
    confirm_reset: bool
    objective_diff: str | None


class ResourceBusy(Exception):
    """The resource is occupied. This start does not reserve it."""

    def __init__(self, job_id: str) -> None:
        super().__init__(job_id)
        self.job_id = job_id


@dataclass(frozen=True, slots=True)
class RecordingStartInput:
    """One start request. The hash is checked against the stored version."""

    case_id: UUID
    input_case_version_id: UUID
    input_version_hash: str
    resource_id: str


@dataclass(frozen=True, slots=True)
class RecordingReceipt:
    """The recording and job created together, or the earlier receipt."""

    recording_id: UUID
    job_id: UUID
    replayed: bool
    status: str


def start_recording(
    connection: object,
    actor: Actor,
    project_id: UUID,
    spec: RecordingStartInput,
    request_key: str,
) -> RecordingReceipt:
    """Check the version, resource, permission, secret, binding, and budget, then enqueue."""

    version = _version(connection, project_id, spec)
    if version is None:
        raise PreflightRejected("case version is missing")
    stored_hash, settings_json, _tc = version
    if spec.input_version_hash != stored_hash:
        raise HashMismatch("version hash does not match")
    settings = json.loads(settings_json)
    base_id = _rerecord_base(connection, project_id, spec.case_id, settings)
    existing = connection.execute(
        "SELECT 1 FROM job_receipts WHERE project_id=? AND actor_id=? AND operation='enqueue_job' AND request_key=?",
        (str(project_id),str(actor.actor_id),request_key),
    ).fetchone()
    if existing is None:
        _require_resource(connection, project_id, spec.resource_id, str(settings.get("target_kind", "")))
        _require_secrets(connection, project_id, settings.get("secret_refs", {}))
        _require_authoring(connection, project_id)
        _require_budget(settings.get("limits", {}))
    receipt = enqueue_job(
        Transaction(connection),  # type: ignore[arg-type]
        JobSubmission(
            project_id=project_id,
            purpose="recording",
            case_id=spec.case_id,
            case_version_id=spec.input_case_version_id,
            base_case_version_id=base_id,
            source_refs=(spec.resource_id,),
            limits=json.dumps({"timeout_seconds": int(settings["limits"]["timeout_seconds"])}, sort_keys=True),
        ),
        IdempotencyKey(actor.actor_id, project_id, "enqueue_job", request_key),
    )
    if receipt.recording_id is None:
        raise PreflightRejected("recording was not created")
    return RecordingReceipt(receipt.recording_id, receipt.job_id, receipt.replayed, receipt.status)


def _rerecord_base(connection, project_id, case_id, settings):
    raw = settings.get('rerecord_base_version_id')
    if raw is None or raw == '':
        return None
    try:
        base_id = UUID(str(raw))
    except ValueError as exc:
        raise PreflightRejected('base version is missing') from exc
    if not str(settings.get('rerecord_reason','')).strip() or settings.get('rerecord_confirmed') is not True:
        raise PreflightRejected('rerecording confirmation is missing')
    if connection.execute('SELECT 1 FROM case_versions WHERE project_id=? AND case_id=? AND version_id=?',(str(project_id),str(case_id),str(base_id))).fetchone() is None:
        raise PreflightRejected('base version is missing')
    return base_id


def _version(
    connection: object, project_id: UUID, spec: RecordingStartInput
) -> tuple[str, str, object] | None:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT versions.content_hash, versions.settings_json, cases.tc_reference
        FROM case_versions AS versions
        JOIN automation_cases AS cases
          ON cases.project_id = versions.project_id AND cases.case_id = versions.case_id
        WHERE versions.project_id = ? AND versions.case_id = ? AND versions.version_id = ?
        """,
        (str(project_id), str(spec.case_id), str(spec.input_case_version_id)),
    ).fetchone()
    if row is None:
        return None
    return (str(row[0]), str(row[1]), row[2])


def _require_resource(connection: object, project_id: UUID, resource_id: str, target: str) -> None:
    from aiqa.domain.resource_readiness import resource_readiness

    readiness = resource_readiness(connection, project_id, resource_id, target)  # type: ignore[arg-type]
    if readiness.code == "RESOURCE_BUSY":
        raise ResourceBusy(readiness.job_id)
    if not readiness.ready:
        raise PreflightRejected(readiness.message)


def _require_secrets(connection: object, project_id: UUID, refs: object) -> None:
    if type(refs) is not dict:
        raise PreflightRejected("secret ref is missing")
    for value in refs.values():
        if type(value) is not dict:
            raise PreflightRejected("secret ref is missing")
        found = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT 1 FROM secret_revisions
            WHERE project_id = ? AND ref_id = ? AND revision = ?
            """,
            (str(project_id), str(value.get("ref_id")), int(value.get("revision", 0))),
        ).fetchone()
        if found is None:
            raise PreflightRejected("secret ref is missing")


def _require_authoring(connection: object, project_id: UUID) -> None:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT 1 FROM binding_revisions
        WHERE project_id = ? AND role = 'authoring'
        LIMIT 1
        """,
        (str(project_id),),
    ).fetchone()
    if row is None:
        raise PreflightRejected("authoring binding is missing")


def start_rerecording(
    connection: object, actor: Actor, project_id: UUID, spec: RerecordInput, request_key: str
) -> RecordingReceipt:
    """Copy the base into a new input and recording. A moved head stays a branch."""

    if (
        spec.reason.strip() == ""
        or request_key.strip() == ""
        or not (spec.confirm_device and spec.confirm_target and spec.confirm_data and spec.confirm_reset)
    ):
        raise PreflightRejected("device, target, data, and reset must be confirmed")
    replay = _replay_rerecord(connection, actor, project_id, spec, request_key)
    if replay is not None:
        return replay
    version_id, content_hash = _copy_rerecord_input(connection, actor, project_id, spec)
    start = RecordingStartInput(spec.case_id, version_id, content_hash, spec.resource_id)
    version = _version(connection, project_id, start)
    if version is None:
        raise PreflightRejected("case version is missing")
    settings = json.loads(version[1])
    _require_resource(connection, project_id, spec.resource_id, str(settings.get("target_kind", "")))
    _require_secrets(connection, project_id, settings.get("secret_refs", {}))
    _require_authoring(connection, project_id)
    _require_budget(settings.get("limits", {}))
    queued = enqueue_job(
        Transaction(connection),  # type: ignore[arg-type]
        JobSubmission(
            project_id=project_id,
            purpose="recording",
            case_id=spec.case_id,
            case_version_id=version_id,
            source_refs=(spec.resource_id,),
            limits=json.dumps({"timeout_seconds": int(settings["limits"]["timeout_seconds"])}, sort_keys=True),
            base_case_version_id=spec.base_version_id,
        ),
        IdempotencyKey(actor.actor_id, project_id, "enqueue_job", request_key),
    )
    if queued.recording_id is None:
        raise PreflightRejected("recording was not created")
    return RecordingReceipt(queued.recording_id, queued.job_id, queued.replayed, queued.status)


def _replay_rerecord(
    connection: object, actor: Actor, project_id: UUID, spec: RerecordInput, request_key: str
) -> RecordingReceipt | None:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT recording_id, job_id FROM job_receipts
        WHERE project_id = ? AND actor_id = ? AND operation = 'enqueue_job' AND request_key = ?
        """,
        (str(project_id), str(actor.actor_id), request_key),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    stored = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT recordings.base_case_version_id, versions.reason, versions.settings_json
        FROM recordings
        JOIN case_versions AS versions
          ON versions.project_id = recordings.project_id
         AND versions.version_id = recordings.input_case_version_id
        WHERE recordings.project_id = ? AND recordings.recording_id = ?
        """,
        (str(project_id), str(row[0])),
    ).fetchone()
    if stored is None:
        raise JobConflict("idempotency body does not match")
    settings = json.loads(str(stored[2]))
    same = (
        str(stored[0]) == str(spec.base_version_id)
        and str(stored[1]) == spec.reason
        and str(settings.get("resource_id", "")) == spec.resource_id
        and str(settings.get("objective_diff", "")) == (spec.objective_diff or "")
    )
    if not same:
        raise JobConflict("idempotency body does not match")
    return RecordingReceipt(UUID(str(row[0])), UUID(str(row[1])), True, "queued")


def _copy_rerecord_input(connection: object, actor: Actor, project_id: UUID, spec: RerecordInput) -> tuple[UUID, str]:
    source = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT versions.definition_json, versions.settings_json, versions.recorded_steps_json,
               versions.content_hash, versions.verification_digest, versions.readiness_json,
               cases.next_revision, cases.latest_draft_version_id, cases.lock_version, cases.case_id
        FROM case_versions AS versions
        JOIN automation_cases AS cases
          ON cases.project_id = versions.project_id AND cases.case_id = versions.case_id
        WHERE versions.project_id = ? AND versions.case_id = ? AND versions.version_id = ?
        """,
        (str(project_id), str(spec.case_id), str(spec.base_version_id)),
    ).fetchone()
    if source is None or str(source[9]) != str(spec.case_id):
        raise PreflightRejected("base version is missing")
    definition = json.loads(str(source[0]))
    if type(definition) is not dict:
        raise PreflightRejected("base version is missing")
    if spec.objective_diff not in {None, ""}:
        definition["objective"] = spec.objective_diff
    settings = json.loads(str(source[1]))
    if type(settings) is not dict:
        settings = {}
    settings["target_kind"] = str(settings.get("target_kind", "web"))
    settings["resource_id"] = spec.resource_id
    settings["web_url"] = spec.web_url
    settings["data_name"] = spec.data_name
    settings["reset_policy"] = spec.reset_policy
    settings["limits"] = {"timeout_seconds": 30}
    settings["objective_diff"] = spec.objective_diff or ""
    content_hash = str(source[3])
    if spec.objective_diff not in {None, ""}:
        content_hash = canonical_hash(definition, "canon-json-v1")
    version_id = uuid4()
    head = None if source[7] is None else str(source[7])
    branch = head != str(spec.expected_head)
    connection.execute(  # type: ignore[attr-defined]
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
            str(project_id),
            str(spec.case_id),
            str(version_id),
            int(source[6]),
            str(spec.base_version_id),
            str(spec.base_version_id),
            1 if branch else 0,
            json.dumps(definition, ensure_ascii=False, sort_keys=True),
            json.dumps(settings, ensure_ascii=False, sort_keys=True),
            str(source[2]),
            content_hash,
            str(source[4]),
            str(source[5]),
            str(actor.actor_id),
            spec.reason,
            "2026-11-01T00:00:00+00:00",
        ),
    )
    if branch:
        connection.execute(  # type: ignore[attr-defined]
            """
            UPDATE automation_cases
            SET next_revision = ?, lock_version = lock_version + 1
            WHERE project_id = ? AND case_id = ? AND lock_version = ?
            """,
            (int(source[6]) + 1, str(project_id), str(spec.case_id), int(source[8])),
        )
    else:
        connection.execute(  # type: ignore[attr-defined]
            """
            UPDATE automation_cases
            SET latest_draft_version_id = ?, next_revision = ?, lock_version = lock_version + 1
            WHERE project_id = ? AND case_id = ? AND lock_version = ?
            """,
            (str(version_id), int(source[6]) + 1, str(project_id), str(spec.case_id), int(source[8])),
        )
    return version_id, content_hash


def finish_recording(
    connection: object, actor: Actor, project_id: UUID, spec: RecordingFinishInput
) -> ManifestReceipt:
    """Stop new actions, seal the source, and save an unapproved draft. This does not wait when the artifacts are already stored."""

    if spec.outcome not in {"completed", "error"} or spec.final_seq < 0 or spec.request_key.strip() == "":
        raise PreflightRejected("invalid finish")
    return _seal(connection, actor, project_id, spec)


def stop_recording(connection: object, actor: Actor, project_id: UUID, recording_id: UUID, request_key: str) -> RecordingView:
    """Preserve an interrupted recording. This does not approve it."""

    spec = RecordingFinishInput(recording_id, "interrupted", 0, (), request_key)
    _seal(connection, actor, project_id, spec)
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT completion_status, stop_status FROM recordings
        WHERE project_id = ? AND recording_id = ?
        """,
        (str(project_id), str(recording_id)),
    ).fetchone()
    if row is None:
        raise PreflightRejected("recording is missing")
    return RecordingView(recording_id, str(row[0]), str(row[1]), None)


def materialize_recording(
    connection: object,
    actor: Actor,
    project_id: UUID,
    manifest_id: UUID,
    compiled: object,
) -> MaterializationReceipt:
    """Commit a ready package with its version and receipt, or keep the empty fallback draft."""

    existing = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT receipts.receipt_id, receipts.produced_version_id, versions.replay_package_id
        FROM materialization_receipts AS receipts
        JOIN case_versions AS versions
          ON versions.project_id = receipts.project_id
         AND versions.version_id = receipts.produced_version_id
        WHERE receipts.project_id = ? AND receipts.manifest_id = ?
        """,
        (str(project_id), str(manifest_id)),
    ).fetchone()
    if existing is not None:
        package_id = None if existing[2] is None else UUID(str(existing[2]))
        return MaterializationReceipt(UUID(str(existing[0])), manifest_id, UUID(str(existing[1])), package_id, True)
    stored = _manifest_row(connection, project_id, manifest_id)
    if stored is None:
        raise PreflightRejected("manifest is missing")
    if not isinstance(compiled, CompiledPackage):
        version_id = _fallback_draft(
            connection, actor, project_id, str(stored.case_id), str(stored.recording_id), manifest_id
        )
        return _receipt(connection, project_id, manifest_id, version_id, None)
    checked = validate_package_body(compiled.body, stored)
    if not checked.ready:
        raise PreflightRejected(checked.reasons[0] if checked.reasons else "package is not ready")
    try:
        require_ready_artifacts(connection, project_id, compiled.ready_artifact_ids)
    except ArtifactRejected as exc:
        raise PreflightRejected(str(exc)) from exc
    package_id = uuid4()
    version_id = _fallback_draft(
        connection, actor, project_id, str(stored.case_id), str(stored.recording_id), manifest_id, package_id
    )
    _insert_ready_package(connection, project_id, str(stored.case_id), package_id, version_id, compiled)
    return _receipt(connection, project_id, manifest_id, version_id, package_id)


def materialize_android_recording(
    connection: object,
    actor: Actor,
    project_id: UUID,
    manifest_id: UUID,
    *,
    ready_artifact_ids: tuple[str, ...] = (),
) -> MaterializationReceipt:
    """Compile a sealed Android manifest into an immutable package for that recording version."""

    stored = _manifest_row(connection, project_id, manifest_id)
    if stored is None:
        raise PreflightRejected("manifest is missing")
    artifact_ids = ready_artifact_ids or _artifact_ids_from_hashes(stored.source_artifact_hashes)
    try:
        compiled = build_android_package_from_manifest(stored, ready_artifact_ids=artifact_ids)
    except PlanRejected as exc:
        raise PreflightRejected(str(exc.reason)) from exc
    return materialize_recording(connection, actor, project_id, manifest_id, compiled)


def rebuild_android_package(
    connection: object,
    actor: Actor,
    project_id: UUID,
    recording_id: UUID,
    request_key: str,
) -> MaterializationReceipt:
    """Seal a package_rebuild manifest and materialize a new version. Prior package digests stay."""

    if type(request_key) is not str or request_key.strip() == "":
        raise PreflightRejected("rebuild key is required")
    source = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT manifest_id, revision, action_mapping, source_artifact_hashes, case_id, evidence_completeness
        FROM recording_manifests
        WHERE project_id = ? AND recording_id = ?
        ORDER BY revision DESC
        LIMIT 1
        """,
        (str(project_id), str(recording_id)),
    ).fetchone()
    if source is None:
        raise PreflightRejected("manifest is missing")
    mapping = str(source[2])
    if not android_trace_ready(mapping):
        raise PreflightRejected("trace is missing")
    existing = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT manifest_id, body_hash FROM recording_manifests
        WHERE project_id = ? AND recording_id = ? AND request_key = ?
        """,
        (str(project_id), str(recording_id), request_key.strip()),
    ).fetchone()
    body = {
        "kind": "package_rebuild",
        "prior_manifest_id": str(source[0]),
        "recording_id": str(recording_id),
        "source_artifact_hashes": str(source[3]),
        "action_mapping": mapping,
    }
    body_hash = canonical_hash(body, "canon-json-v1")
    if existing is not None:
        if str(existing[1]) != body_hash:
            raise FinishConflict("rebuild body does not match")
        return materialize_android_recording(connection, actor, project_id, UUID(str(existing[0])))
    manifest_id = uuid4()
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO recording_manifests (
            project_id, case_id, recording_id, manifest_id, revision, kind, prior_manifest_id,
            input_version_hash, source_artifact_hashes, action_mapping, evidence_completeness,
            request_key, body_hash
        ) VALUES (?, ?, ?, ?, ?, 'package_rebuild', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(project_id),
            str(source[4]),
            str(recording_id),
            str(manifest_id),
            int(source[1]) + 1,
            str(source[0]),
            _input_version_hash(connection, project_id, recording_id),
            str(source[3]),
            mapping,
            str(source[5]),
            request_key.strip(),
            body_hash,
        ),
    )
    return materialize_android_recording(connection, actor, project_id, manifest_id)


def _seal(connection: object, actor: Actor, project_id: UUID, spec: RecordingFinishInput) -> ManifestReceipt:
    recording = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT case_id, input_case_version_id, completion_status
        FROM recordings WHERE project_id = ? AND recording_id = ?
        """,
        (str(project_id), str(spec.recording_id)),
    ).fetchone()
    if recording is None:
        raise PreflightRejected("recording is missing")
    body_hash = finish_body_hash(spec)
    stored = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT manifest_id, body_hash FROM recording_manifests
        WHERE project_id = ? AND recording_id = ? AND request_key = ?
        """,
        (str(project_id), str(spec.recording_id), spec.request_key),
    ).fetchone()
    if stored is not None:
        if str(stored[1]) != body_hash:
            raise FinishConflict("finish body does not match")
        return ManifestReceipt(UUID(str(stored[0])), spec.recording_id, body_hash, True)
    if spec.outcome != "interrupted":
        _require_artifacts(connection, project_id, spec.artifact_ids)
    outcome = "interrupted" if spec.outcome == "interrupted" else spec.outcome
    mapping, source_hashes, should_compile = _android_seal_payload(spec, outcome)
    connection.execute(  # type: ignore[attr-defined]
        """
        UPDATE recordings
        SET stop_status = 'stopped', completion_status = ?, evidence_status = 'complete',
            storage_status = CASE WHEN ? = 'interrupted' THEN storage_status ELSE 'stored' END
        WHERE project_id = ? AND recording_id = ? AND completion_status = 'open'
        """,
        (outcome, outcome, str(project_id), str(spec.recording_id)),
    )
    manifest_id = uuid4()
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO recording_manifests (
            project_id, case_id, recording_id, manifest_id, revision, kind, prior_manifest_id,
            input_version_hash, source_artifact_hashes, action_mapping, evidence_completeness,
            request_key, body_hash
        ) VALUES (?, ?, ?, ?, 1, 'original', NULL, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(project_id),
            str(recording[0]),
            str(spec.recording_id),
            str(manifest_id),
            str(recording[1]),
            source_hashes,
            mapping,
            "complete",
            spec.request_key,
            body_hash,
        ),
    )
    compiled: CompiledPackage | None = None
    if should_compile:
        stored = _manifest_row(connection, project_id, manifest_id)
        if stored is not None:
            try:
                compiled = build_android_package_from_manifest(
                    stored,
                    ready_artifact_ids=spec.artifact_ids,
                )
            except PlanRejected:
                compiled = None
    materialize_recording(connection, actor, project_id, manifest_id, compiled)
    return ManifestReceipt(manifest_id, spec.recording_id, body_hash, False)


def _android_seal_payload(spec: RecordingFinishInput, outcome: str) -> tuple[str, str, bool]:
    mapping = spec.action_mapping if type(spec.action_mapping) is str else "{}"
    if android_trace_ready(mapping):
        digest = android_mapping_digest(mapping)
        hashes = list(spec.artifact_ids)
        if digest not in hashes:
            hashes.append(digest)
        return mapping, json.dumps(hashes, sort_keys=True), True
    fallback = json.dumps(
        {"final_seq": spec.final_seq, "outcome": outcome, "wait_limit_seconds": 30},
        sort_keys=True,
    )
    return fallback, json.dumps(list(spec.artifact_ids), sort_keys=True), False


def _input_version_hash(connection: object, project_id: UUID, recording_id: UUID) -> str:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT versions.content_hash
        FROM recordings
        JOIN case_versions AS versions
          ON versions.project_id = recordings.project_id
         AND versions.case_id = recordings.case_id
         AND versions.version_id = recordings.input_case_version_id
        WHERE recordings.project_id = ? AND recordings.recording_id = ?
        """,
        (str(project_id), str(recording_id)),
    ).fetchone()
    if row is None:
        raise PreflightRejected("input version is missing")
    return str(row[0])


def _artifact_ids_from_hashes(raw: str) -> tuple[str, ...]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if type(parsed) is not list:
        return ()
    ids: list[str] = []
    for item in parsed:
        if type(item) is not str:
            continue
        text = item.strip()
        # Artifact UUID refs stay; mapping digests and opaque hashes are skipped.
        if len(text) == 36 and text.count("-") == 4:
            ids.append(text)
    return tuple(ids)


def _require_artifacts(connection: object, project_id: UUID, artifact_ids: tuple[str, ...]) -> None:
    if artifact_ids == ():
        raise PreflightRejected("required artifact is missing")
    for artifact_id in artifact_ids:
        row = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT 1 FROM artifact_objects
            WHERE project_id = ? AND artifact_id = ? AND status = 'ready' AND acked = 1
            """,
            (str(project_id), artifact_id),
        ).fetchone()
        if row is None:
            raise PreflightRejected("required artifact is missing")


def _manifest_row(connection: object, project_id: UUID, manifest_id: UUID) -> RecordingManifest | None:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT case_id, recording_id, revision, kind, prior_manifest_id, input_version_hash,
               source_artifact_hashes, action_mapping, evidence_completeness, request_key, body_hash
        FROM recording_manifests
        WHERE project_id = ? AND manifest_id = ?
        """,
        (str(project_id), str(manifest_id)),
    ).fetchone()
    if row is None:
        return None
    return RecordingManifest(
        project_id,
        UUID(str(row[0])),
        UUID(str(row[1])),
        manifest_id,
        int(row[2]),
        str(row[3]),
        None if row[4] is None else UUID(str(row[4])),
        str(row[5]),
        str(row[6]),
        str(row[7]),
        str(row[8]),
        str(row[9]),
        str(row[10]),
    )


def _receipt(
    connection: object, project_id: UUID, manifest_id: UUID, version_id: UUID, package_id: UUID | None
) -> MaterializationReceipt:
    receipt_id = uuid4()
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO materialization_receipts (project_id, receipt_id, manifest_id, produced_version_id, body_hash)
        VALUES (?, ?, ?, ?, ?)
        """,
        (str(project_id), str(receipt_id), str(manifest_id), str(version_id), str(manifest_id)),
    )
    return MaterializationReceipt(receipt_id, manifest_id, version_id, package_id, False)


def _insert_ready_package(
    connection: object,
    project_id: UUID,
    case_id: str,
    package_id: UUID,
    version_id: UUID,
    compiled: CompiledPackage,
) -> None:
    body = compiled.body
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO replay_packages (
            project_id, package_id, case_id, case_version_id, ready, schema_version,
            source_manifest_id, source_manifest_hash, raw_source_hash, approved_code_hash,
            runtime_ref, compiler_ref, lock_hash, step_mapping_hash, body_hash
        ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(project_id),
            str(package_id),
            case_id,
            str(version_id),
            body.schema_version,
            str(body.source_manifest_id),
            body.source_manifest_hash,
            body.raw_source_hash,
            body.approved_code_or_plan_hash,
            body.runtime_ref,
            body.compiler_ref,
            body.lock_hash,
            body.step_mapping_hash,
            compiled.body_hash,
        ),
    )
    for position, step in enumerate(compiled.steps, start=1):
        connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO package_steps (project_id, package_id, step_id, position, step_hash)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(project_id),
                str(package_id),
                step.step_id,
                position,
                hashlib.sha256(step.call.encode("utf-8")).hexdigest(),
            ),
        )
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO package_version_links (project_id, case_id, version_id, package_id)
        VALUES (?, ?, ?, ?)
        """,
        (str(project_id), case_id, str(version_id), str(package_id)),
    )


def _fallback_draft(
    connection: object,
    actor: Actor,
    project_id: UUID,
    case_id: str,
    recording_id: str,
    manifest_id: UUID,
    package_id: UUID | None = None,
) -> UUID:
    source = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT versions.definition_json, versions.settings_json, versions.recorded_steps_json,
               versions.content_hash, versions.verification_digest, versions.readiness_json,
               versions.version_id, cases.next_revision, cases.latest_draft_version_id, cases.lock_version
        FROM recordings
        JOIN case_versions AS versions
          ON versions.project_id = recordings.project_id
         AND versions.case_id = recordings.case_id
         AND versions.version_id = recordings.input_case_version_id
        JOIN automation_cases AS cases
          ON cases.project_id = recordings.project_id AND cases.case_id = recordings.case_id
        WHERE recordings.project_id = ? AND recordings.recording_id = ?
        """,
        (str(project_id), recording_id),
    ).fetchone()
    if source is None:
        raise PreflightRejected("input version is missing")
    version_id = uuid4()
    head = None if source[8] is None else str(source[8])
    late = head != str(source[6])
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO case_versions (
            project_id, case_id, version_id, revision, creation_kind,
            parent_version_id, base_version_id, is_branch, definition_json,
            settings_json, recorded_steps_json, content_hash, verification_digest,
            source_manifest_id, replay_package_id, readiness_json, actor_id,
            reason, created_at
        ) VALUES (?, ?, ?, ?, 'input', ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(project_id),
            case_id,
            str(version_id),
            int(source[7]),
            str(source[6]),
            1 if late else 0,
            str(source[0]),
            str(source[1]),
            str(source[2]),
            str(source[3]),
            str(source[4]),
            str(manifest_id),
            None if package_id is None else str(package_id),
            str(source[5]),
            str(actor.actor_id),
            "compiler is missing" if package_id is None else "package ready",
            "2026-11-01T00:00:00+00:00",
        ),
    )
    if late:
        connection.execute(  # type: ignore[attr-defined]
            """
            UPDATE automation_cases
            SET next_revision = ?, lock_version = lock_version + 1
            WHERE project_id = ? AND case_id = ? AND lock_version = ?
            """,
            (int(source[7]) + 1, str(project_id), case_id, int(source[9])),
        )
    else:
        connection.execute(  # type: ignore[attr-defined]
            """
            UPDATE automation_cases
            SET latest_draft_version_id = ?, next_revision = ?, lock_version = lock_version + 1
            WHERE project_id = ? AND case_id = ? AND lock_version = ?
            """,
            (str(version_id), int(source[7]) + 1, str(project_id), case_id, int(source[9])),
        )
    return version_id


def _require_budget(limits: object) -> None:
    if type(limits) is not dict:
        raise PreflightRejected("budget is missing")
    try:
        timeout = int(limits.get("timeout_seconds", 0))
    except (TypeError, ValueError) as exc:
        raise PreflightRejected("budget is missing") from exc
    if timeout < 1:
        raise PreflightRejected("budget is missing")


def inspect_recording(connection: object, project_id: UUID, spec: RecordingStartInput) -> dict[str, object]:
    """Report current blockers without creating a recording, lease, job or model call."""
    version = _version(connection, project_id, spec)
    if version is None:
        raise PreflightRejected("case version is missing")
    if spec.input_version_hash != version[0]:
        raise HashMismatch("version hash does not match")
    settings = json.loads(version[1])
    reasons = []
    checks = [
        ('base',lambda: _rerecord_base(connection, project_id, spec.case_id, settings)),
        ("resource", lambda: _require_resource(connection, project_id, spec.resource_id, str(settings.get("target_kind", "")))),
        ("secrets", lambda: _require_secrets(connection, project_id, settings.get("secret_refs", {}))),
        ("authoring", lambda: _require_authoring(connection, project_id)),
        ("budget", lambda: _require_budget(settings.get("limits", {}))),
    ]
    for code, check in checks:
        try:
            check()
        except (PreflightRejected, ResourceBusy) as exc:
            label = {"base":"재녹화 기준과 사유·확인을 보완해 주세요.", "resource":"기기 연결·권한·점유 상태를 확인해 주세요.", "secrets":"사용할 계정의 비밀 참조를 확인해 주세요.", "authoring":"녹화 AI 모델 연결이 필요합니다.", "budget":"녹화 시간·비용 한도를 확인해 주세요."}[code]
            reasons.append({"code":code, "message":label, "detail":str(exc), "href":f"/ui/projects/{project_id}/"+("settings" if code in {"authoring","budget","secrets"} else "environments")})
    return {"ready":not reasons,"reasons":reasons,"input_case_version_id":str(spec.input_case_version_id),"input_version_hash":spec.input_version_hash}
