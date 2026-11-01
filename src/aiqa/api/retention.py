"""Typed retention pins. Manual release cannot drop an approval pin."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from aiqa.api.auth import (
    AuthRequired,
    CsrfRejected,
    OriginRejected,
    ProjectHidden,
    authorize_browser,
    bound_auth_store,
)
from aiqa.store.artifacts import (
    APK_BYTE_LIMIT,
    PROJECT_BYTE_LIMIT,
    ArtifactRejected,
    ProtectionConflict,
    append_typed_pin,
    release_manual_pin,
    within_apk_budget,
)
from aiqa.store.database import migrate_store
from aiqa.store.retention import RetentionPlan, RetentionPolicy, RetentionSubject, UtcInstant, plan_retention


def install_retention(application: FastAPI) -> None:
    """Attach pin routes once. This does not open SQLite."""

    if getattr(application.state, "retention_installed", False):
        return
    application.add_api_route(
        "/api/v1/artifacts/{artifact_id}/retention-protections",
        post_protection,
        methods=["POST"],
    )
    application.add_api_route(
        "/api/v1/retention-protections/{protection_id}/release",
        post_release,
        methods=["POST"],
    )
    application.add_api_route(
        "/api/v1/projects/{project_id}/retention-previews",
        post_preview,
        methods=["POST"],
    )
    application.state.retention_installed = True


async def post_protection(artifact_id: str, request: Request) -> JSONResponse:
    project = _uuid(request.query_params.get("project_id", ""))
    artifact = _uuid(artifact_id)
    if project is None or artifact is None:
        return _error(404, "not_found", "artifact was not found")
    payload = await _object(request)
    kind = "" if payload is None else payload.get("kind")
    if type(kind) is not str:
        return _error(422, "validation", "pin is invalid")
    key = request.headers.get("idempotency-key", "").strip()
    if key == "":
        return _error(422, "validation", "Idempotency-Key is required")
    digest = hashlib.sha256(kind.encode("utf-8")).hexdigest()
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_browser(request, project, "pin_retention")
                with store.transaction() as connection:
                    replayed, protection = _receipt(connection, project, actor.actor_id, "pin_retention", key, digest)
                    if protection is None:
                        protection = append_typed_pin(connection, project, artifact, kind, datetime.now(timezone.utc))
                        _remember(connection, project, actor.actor_id, "pin_retention", key, digest, protection)
            except CsrfRejected:
                return _error(403, "permission", "csrf token was rejected")
            except OriginRejected:
                return _error(403, "permission", "origin was rejected")
            except ProjectHidden:
                return _error(404, "not_found", "artifact was not found")
            except AuthRequired:
                return _error(401, "unauthorized", "session is missing")
            except ProtectionConflict:
                return _error(409, "conflict", "pin body does not match")
            except ArtifactRejected:
                return _error(422, "validation", "pin is invalid")
    finally:
        store.close()
    return JSONResponse(
        status_code=200 if replayed else 201,
        content={"protection_id": str(protection), "artifact_id": str(artifact), "kind": kind, "replayed": replayed},
    )


async def post_release(protection_id: str, request: Request) -> JSONResponse:
    project = _uuid(request.query_params.get("project_id", ""))
    protection = _uuid(protection_id)
    if project is None or protection is None:
        return _error(404, "not_found", "pin was not found")
    key = request.headers.get("idempotency-key", "").strip()
    if key == "":
        return _error(422, "validation", "Idempotency-Key is required")
    digest = hashlib.sha256(str(protection).encode("utf-8")).hexdigest()
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_browser(request, project, "release_retention")
                with store.transaction() as connection:
                    replayed, stored = _receipt(connection, project, actor.actor_id, "release_retention", key, digest)
                    if stored is None:
                        release_manual_pin(connection, project, protection, datetime.now(timezone.utc))
                        _remember(connection, project, actor.actor_id, "release_retention", key, digest, protection)
                        stored = protection
            except CsrfRejected:
                return _error(403, "permission", "csrf token was rejected")
            except OriginRejected:
                return _error(403, "permission", "origin was rejected")
            except ProjectHidden:
                return _error(404, "not_found", "pin was not found")
            except AuthRequired:
                return _error(401, "unauthorized", "session is missing")
            except ProtectionConflict:
                return _error(409, "conflict", "pin is already released")
            except ArtifactRejected:
                return _error(422, "validation", "manual release cannot drop another pin")
    finally:
        store.close()
    return JSONResponse(status_code=200 if replayed else 201, content={"protection_id": str(stored), "replayed": replayed})


async def post_preview(project_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    if project is None:
        return _error(404, "not_found", "project was not found")
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                authorize_browser(request, project, "preview_retention")
                with store.transaction() as connection:
                    before = _protected_count(connection, project)
                    plan = preview_retention(connection, project, datetime.now(timezone.utc))
                    after = _protected_count(connection, project)
            except CsrfRejected:
                return _error(403, "permission", "csrf token was rejected")
            except OriginRejected:
                return _error(403, "permission", "origin was rejected")
            except ProjectHidden:
                return _error(404, "not_found", "project was not found")
            except AuthRequired:
                return _error(401, "unauthorized", "session is missing")
    finally:
        store.close()
    return JSONResponse(
        status_code=200,
        content={
            "core_facts_deleted": plan.core_facts_deleted,
            "expired_has_tombstone": plan.expired_has_tombstone,
            "unacked_spool_deleted": plan.unacked_spool_deleted,
            "old_stats_available": plan.old_stats_available,
            "protected_files_auto_deleted": before - after,
        },
    )


def read_storage(connection: object, project_id: UUID) -> dict[str, object]:
    """Summarize file use. Protected bytes stay even when they pass the cap."""

    project_bytes = _sum_bytes(connection, project_id)
    total_bytes = _sum_bytes(connection, None)
    protected_bytes = _protected_bytes(connection, project_id)
    pins = [
        _pin_label(str(row[0]))
        for row in connection.execute(  # type: ignore[attr-defined]
            """
            SELECT kind FROM artifact_protections AS pins
            WHERE pins.project_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM protection_releases AS released
                  WHERE released.project_id = pins.project_id AND released.protection_id = pins.protection_id
              )
            ORDER BY kind
            """,
            (str(project_id),),
        ).fetchall()
    ]
    facts = connection.execute(  # type: ignore[attr-defined]
        "SELECT COUNT(*) FROM item_finalizations WHERE project_id = ?",
        (str(project_id),),
    ).fetchone()
    pending = connection.execute(  # type: ignore[attr-defined]
        "SELECT COUNT(*) FROM gc_claims WHERE project_id = ?",
        (str(project_id),),
    ).fetchone()
    sample = connection.execute(  # type: ignore[attr-defined]
        "SELECT artifact_id FROM artifact_objects WHERE project_id = ? ORDER BY artifact_id LIMIT 1",
        (str(project_id),),
    ).fetchone()
    return {
        "project_id": str(project_id),
        "project_bytes": project_bytes,
        "total_bytes": total_bytes,
        "protected_bytes": protected_bytes,
        "protected_count": len(pins),
        "pins": pins,
        "facts": 0 if facts is None else int(facts[0]),
        "pending": 0 if pending is None else int(pending[0]),
        "total_limit_bytes": PROJECT_BYTE_LIMIT,
        "item_limit_bytes": APK_BYTE_LIMIT,
        "item_accepts_499": within_apk_budget(499 * 1024 * 1024, 0),
        "item_accepts_500": within_apk_budget(APK_BYTE_LIMIT, 0),
        "item_stops_after_500": not within_apk_budget(APK_BYTE_LIMIT + 1, 0),
        "quota_stops_new_actions": protected_bytes > PROJECT_BYTE_LIMIT or total_bytes > PROJECT_BYTE_LIMIT,
        "partial_record_saved": _partial_saved(connection, project_id),
        "artifact_id": "" if sample is None else str(sample[0]),
        "missing": _missing(connection, project_id),
        "used_bytes": project_bytes,
        "limit_bytes": PROJECT_BYTE_LIMIT,
        "over_protected": protected_bytes > PROJECT_BYTE_LIMIT,
        "deletion_scheduled": 0 if pending is None else int(pending[0]),
    }


def preview_retention(connection: object, project_id: UUID, now: datetime) -> RetentionPlan:
    """Plan expiry without deleting a protected file."""

    subjects: list[RetentionSubject] = []
    for row in connection.execute(  # type: ignore[attr-defined]
        "SELECT case_run_id, content_hash FROM item_finalizations WHERE project_id = ?",
        (str(project_id),),
    ).fetchall():
        subjects.append(RetentionSubject("core_fact", str(row[0]), now, str(row[1])))
    for row in connection.execute(  # type: ignore[attr-defined]
        "SELECT artifact_id, content_hash, stored_at FROM artifact_objects WHERE project_id = ?",
        (str(project_id),),
    ).fetchall():
        stored = _stored(str(row[2]), now)
        subjects.append(
            RetentionSubject(
                "png",
                str(row[0]),
                stored,
                str(row[1]),
                protected=_is_protected(connection, project_id, str(row[0])),
            )
        )
    if not subjects:
        subjects.append(RetentionSubject("core_fact", "none", now, "sha256:none"))
    return plan_retention(RetentionPolicy(tuple(subjects)), UtcInstant(now))


def _protected_count(connection: object, project_id: UUID) -> int:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT COUNT(*) FROM artifact_protections AS pins
        WHERE pins.project_id = ?
          AND NOT EXISTS (
              SELECT 1 FROM protection_releases AS released
              WHERE released.project_id = pins.project_id AND released.protection_id = pins.protection_id
          )
        """,
        (str(project_id),),
    ).fetchone()
    return 0 if row is None else int(row[0])


def _sum_bytes(connection: object, project_id: UUID | None) -> int:
    if project_id is None:
        row = connection.execute("SELECT COALESCE(SUM(byte_length), 0) FROM artifact_objects").fetchone()  # type: ignore[attr-defined]
    else:
        row = connection.execute(  # type: ignore[attr-defined]
            "SELECT COALESCE(SUM(byte_length), 0) FROM artifact_objects WHERE project_id = ?",
            (str(project_id),),
        ).fetchone()
    return 0 if row is None else int(row[0])


def _protected_bytes(connection: object, project_id: UUID) -> int:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT COALESCE(SUM(objects.byte_length), 0)
        FROM artifact_objects AS objects
        WHERE objects.project_id = ?
          AND EXISTS (
              SELECT 1 FROM artifact_protections AS pins
              WHERE pins.project_id = objects.project_id AND pins.artifact_id = objects.artifact_id
                AND NOT EXISTS (
                    SELECT 1 FROM protection_releases AS released
                    WHERE released.project_id = pins.project_id AND released.protection_id = pins.protection_id
                )
          )
        """,
        (str(project_id),),
    ).fetchone()
    return 0 if row is None else int(row[0])


def _partial_saved(connection: object, project_id: UUID) -> bool:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT 1 FROM artifact_objects
        WHERE project_id = ? AND byte_length > 0 AND byte_length <= ?
        """,
        (str(project_id), APK_BYTE_LIMIT),
    ).fetchone()
    return row is not None


def _missing(connection: object, project_id: UUID) -> bool:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT 1 FROM artifact_objects
        WHERE project_id = ? AND custody IN ('expired', 'missing')
        """,
        (str(project_id),),
    ).fetchone()
    return row is not None


def _is_protected(connection: object, project_id: UUID, artifact_id: str) -> bool:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT 1 FROM artifact_protections AS pins
        WHERE pins.project_id = ? AND pins.artifact_id = ?
          AND NOT EXISTS (
              SELECT 1 FROM protection_releases AS released
              WHERE released.project_id = pins.project_id AND released.protection_id = pins.protection_id
          )
        """,
        (str(project_id), artifact_id),
    ).fetchone()
    return row is not None


def _stored(value: str, now: datetime) -> datetime:
    if value.strip() == "":
        return now
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return now
    return parsed.astimezone(timezone.utc)


def _pin_label(kind: str) -> str:
    return {"approval": "승인", "review": "검토", "manual": "수동", "backup": "백업", "build": "빌드"}.get(kind, kind)


def _receipt(
    connection: object, project: UUID, actor_id: UUID, operation: str, key: str, digest: str
) -> tuple[bool, UUID | None]:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT body_hash, protection_id FROM retention_command_receipts
        WHERE project_id = ? AND actor_id = ? AND operation = ? AND idempotency_key = ?
        """,
        (str(project), str(actor_id), operation, key),
    ).fetchone()
    if row is None:
        return False, None
    if str(row[0]) != digest:
        raise ProtectionConflict("pin body does not match")
    return True, UUID(str(row[1]))


def _remember(
    connection: object, project: UUID, actor_id: UUID, operation: str, key: str, digest: str, protection: UUID
) -> None:
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO retention_command_receipts (
            project_id, actor_id, operation, idempotency_key, body_hash, protection_id
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (str(project), str(actor_id), operation, key, digest, str(protection)),
    )


async def _object(request: Request) -> dict[str, object] | None:
    body = await request.json()
    if type(body) is not dict:
        return None
    return body


def _uuid(value: object) -> UUID | None:
    if type(value) is not str or value.strip() == "":
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})
