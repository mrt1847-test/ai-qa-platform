"""Validate a replay package body and read its case version view."""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from aiqa.contracts.replay import PackageValidation, ReplayPackageBody, StepMapping
from aiqa.domain.hashing import canonical_hash
from aiqa.store.models import RecordingManifest

_SCHEMA = "replay-package-v1"
_RUNTIMES = frozenset({"web", "android"})
_ANDROID_ACTIONS = frozenset({"tap", "type", "swipe", "back"})


def validate_package_body(body: ReplayPackageBody, source: RecordingManifest) -> PackageValidation:
    """Check source, runtime, lock, and mappings. Missing or unknown mapping is not ready."""

    reasons: list[str] = []
    if body.schema_version != _SCHEMA:
        reasons.append("schema is not supported")
    if body.source_manifest_id != source.manifest_id or body.source_manifest_hash != source.body_hash:
        reasons.append("source does not match")
    if body.raw_source_hash not in _source_hashes(source):
        reasons.append("source does not match")
    if body.runtime_ref not in _RUNTIMES:
        reasons.append("runtime is not supported")
    if body.compiler_ref.strip() == "" or body.lock_hash.strip() == "" or body.approved_code_or_plan_hash.strip() == "":
        reasons.append("code or plan is missing")
    if body.produced_version_id not in {None, ""} or body.produced_version_hash not in {None, ""}:
        reasons.append("produced version stays outside the package hash")
    if body.compiled_hash not in {None, ""} or body.compiled_hash == body.raw_source_hash:
        reasons.append("compiled hash stays outside the raw source")
    mapped = _mapped(body.mappings)
    if mapped is None or body.step_mapping_hash != _mapping_hash(body.mappings):
        reasons.append("mapping is unknown")
    elif any(helper not in mapped for helper in body.helpers):
        reasons.append("mapping is missing")
    digest = _body_hash(body)
    return PackageValidation(reasons == [], tuple(reasons), digest)


def _source_hashes(source: RecordingManifest) -> set[str]:
    try:
        parsed = json.loads(source.source_artifact_hashes)
    except json.JSONDecodeError:
        return set()
    if type(parsed) is not list:
        return set()
    return {str(item) for item in parsed if type(item) is str and item.strip() != ""}


def _mapped(mappings: tuple[StepMapping, ...]) -> set[str] | None:
    names: set[str] = set()
    for item in mappings:
        if item.step_id.strip() == "" or item.action_id.strip() == "" or item.line < 1:
            return None
        names.add(item.step_id)
    return names


def _mapping_hash(mappings: tuple[StepMapping, ...]) -> str:
    return canonical_hash(
        {
            "steps": [
                {"action_id": item.action_id, "line": item.line, "step_id": item.step_id}
                for item in mappings
            ]
        },
        "canon-json-v1",
    )


@dataclass(frozen=True, slots=True)
class PackageStepView:
    step_id: str
    position: int
    step_hash: str


@dataclass(frozen=True, slots=True)
class ReplayPackageView:
    version_id: UUID
    replay_package_id: UUID | None
    ready: bool
    raw_source_hash: str
    approved_code_hash: str
    runtime_ref: str
    compiler_ref: str
    lock_hash: str
    package_hash: str
    steps: tuple[PackageStepView, ...]
    reasons: tuple[str, ...]
    recording_ids: tuple[str, ...]
    editable: bool


def load_replay_package_view(connection: object, project_id: UUID, version_id: UUID) -> ReplayPackageView | None:
    """Read one version's package. A missing package still returns the case recordings."""

    version = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT case_id, replay_package_id, reason
        FROM case_versions
        WHERE project_id = ? AND version_id = ?
        """,
        (str(project_id), str(version_id)),
    ).fetchone()
    if version is None:
        return None
    case_id = str(version[0])
    recordings = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT recording_id FROM recordings
        WHERE project_id = ? AND case_id = ?
        ORDER BY recording_id
        """,
        (str(project_id), case_id),
    ).fetchall()
    expired = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT 1
        FROM recordings
        JOIN artifact_objects
          ON artifact_objects.project_id = recordings.project_id
         AND artifact_objects.owner_id = recordings.recording_id
        WHERE recordings.project_id = ? AND recordings.case_id = ? AND artifact_objects.custody = 'expired'
        """,
        (str(project_id), case_id),
    ).fetchone()
    reasons: list[str] = []
    package_id = None if version[1] is None else UUID(str(version[1]))
    raw_source = approved = runtime = compiler = lock = package_hash = ""
    steps: tuple[PackageStepView, ...] = ()
    stored_ready = False
    if package_id is None:
        reasons.append("package is missing")
        if str(version[2]) == "compiler is missing":
            reasons.append("compiler is missing")
    else:
        package = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT ready, raw_source_hash, approved_code_hash, runtime_ref, compiler_ref,
                   lock_hash, body_hash, step_mapping_hash
            FROM replay_packages
            WHERE project_id = ? AND case_id = ? AND package_id = ?
            """,
            (str(project_id), case_id, str(package_id)),
        ).fetchone()
        if package is None:
            reasons.append("package is missing")
        else:
            stored_ready = int(package[0]) == 1
            raw_source, approved, runtime, compiler, lock, package_hash = (
                str(package[1]),
                str(package[2]),
                str(package[3]),
                str(package[4]),
                str(package[5]),
                str(package[6]),
            )
            rows = connection.execute(  # type: ignore[attr-defined]
                """
                SELECT step_id, position, step_hash
                FROM package_steps
                WHERE project_id = ? AND package_id = ?
                ORDER BY position
                """,
                (str(project_id), str(package_id)),
            ).fetchall()
            steps = tuple(PackageStepView(str(row[0]), int(row[1]), str(row[2])) for row in rows)
            if str(package[7]) != stored_mapping_hash(steps):
                reasons.append("mapping does not match")
            if not stored_ready:
                reasons.append("compiler is missing")
    if expired is not None:
        reasons.append("artifact is expired")
    return ReplayPackageView(
        version_id,
        package_id,
        stored_ready and reasons == (),
        raw_source,
        approved,
        runtime,
        compiler,
        lock,
        package_hash,
        steps,
        tuple(reasons),
        tuple(str(row[0]) for row in recordings),
        False,
    )


def android_trace_reasons(events: object) -> tuple[str, ...]:
    """Name why a Mobile-Agent trace cannot become a ready plan. Model events are ignored."""

    if type(events) is not list or events == []:
        return ("trace is missing",)
    reasons: list[str] = []
    action_ids: set[str] = set()
    for item in events:
        if type(item) is not dict:
            reasons.append("trace is missing")
            continue
        kind = item.get("kind")
        if kind == "model":
            continue
        if kind not in {"action", "wait", "check"}:
            reasons.append("action is unknown")
            continue
        if item.get("secret_literal") not in {None, ""}:
            reasons.append("secret literal is not allowed")
            continue
        action_id = item.get("action_id")
        line = item.get("line")
        if type(action_id) is not str or action_id.strip() == "" or type(line) is not int or line < 1:
            reasons.append("mapping is missing")
            continue
        if not _geometry_ready(item.get("geometry")):
            reasons.append("geometry is missing")
            continue
        if kind == "action":
            if item.get("action") not in _ANDROID_ACTIONS:
                reasons.append("action is unknown")
                continue
            action_ids.add(action_id)
            continue
        maps_to = item.get("maps_to")
        if type(maps_to) is not str or maps_to not in action_ids:
            reasons.append("mapping is missing")
    return tuple(dict.fromkeys(reasons))


def _geometry_ready(value: object) -> bool:
    if type(value) is not dict:
        return False
    bounds = value.get("content_bounds")
    if type(value.get("rotation")) is not int or type(bounds) is not list or len(bounds) != 4:
        return False
    return all(type(item) is int for item in bounds)


def stored_mapping_hash(steps: tuple[PackageStepView, ...]) -> str:
    """Hash the stored step rows. The page shows these rows and does not rewrite them."""

    return canonical_hash(
        {
            "steps": [
                {"position": step.position, "step_hash": step.step_hash, "step_id": step.step_id}
                for step in steps
            ]
        },
        "canon-json-v1",
    )


def _body_hash(body: ReplayPackageBody) -> str:
    return canonical_hash(
        {
            "approved_code_or_plan_hash": body.approved_code_or_plan_hash,
            "compiler_ref": body.compiler_ref,
            "lock_hash": body.lock_hash,
            "raw_source_hash": body.raw_source_hash,
            "runtime_ref": body.runtime_ref,
            "schema_version": body.schema_version,
            "source_manifest_hash": body.source_manifest_hash,
            "source_manifest_id": str(body.source_manifest_id),
            "step_mapping_hash": body.step_mapping_hash,
        },
        "canon-json-v1",
    )
