"""OS secret store. SQLite keeps the reference and revision, never the secret or its hash."""

from __future__ import annotations

import ctypes
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from ctypes import wintypes
from datetime import datetime, timezone
from uuid import UUID, uuid4

from aiqa.domain.projects import next_commit_seq
from aiqa.store.database import Store
from aiqa.store.models import (
    Actor,
    RuntimeScope,
    SecretInput,
    SecretRef,
    SecretRefView,
    SecretValue,
    Transaction,
)

logger = logging.getLogger("aiqa.security.secrets")
_store: ContextVar[Store] = ContextVar("aiqa_secret_store")
_MAX_SECRET_BYTES = 4096


class SecretValidationError(Exception):
    def __init__(self, fields: dict[str, list[str]]) -> None:
        super().__init__("invalid secret")
        self.fields = fields


class SecretScopeDenied(Exception):
    """The ref is outside the caller project. The message never includes secret text."""


class SecretUnavailable(Exception):
    """The OS secret store could not accept or return the secret."""


@contextmanager
def bind_secret_store(store: Store) -> Iterator[None]:
    token = _store.set(store)
    try:
        yield
    finally:
        _store.reset(token)


def put_secret(actor: Actor, secret: SecretInput) -> SecretRefView:
    if actor.project_scope is None:
        raise SecretScopeDenied("secret ref is outside this project")
    value = _validated_value(secret.value)
    project_id = actor.project_scope
    store = _bound_store()
    with store.transaction() as connection:
        planned = _plan(connection, project_id, secret)
    ref = SecretRef(project_id=project_id, ref_id=planned[0], revision=planned[1])
    _write_os(ref, value)
    created_at = _now()
    try:
        with store.transaction() as connection:
            commit_seq = next_commit_seq(Transaction(connection), project_id)
            connection.execute(
                """
                INSERT INTO secret_refs (
                    project_id, ref_id, revision, name, availability, created_at, actor_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(project_id),
                    str(ref.ref_id),
                    ref.revision,
                    planned[2],
                    "available",
                    created_at,
                    str(actor.actor_id),
                ),
            )
            connection.execute(
                """
                INSERT INTO secret_ref_audits (
                    project_id, ref_id, revision, commit_seq, actor_id, action, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(project_id),
                    str(ref.ref_id),
                    ref.revision,
                    commit_seq,
                    str(actor.actor_id),
                    planned[3],
                    created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO secret_ref_snapshots (
                    project_id, ref_id, revision, commit_seq, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (str(project_id), str(ref.ref_id), ref.revision, commit_seq, created_at),
            )
    except Exception:
        discard_os_secret(ref)
        raise
    store.on_rollback(lambda: discard_os_secret(ref))
    return SecretRefView(
        project_id=project_id,
        ref_id=ref.ref_id,
        revision=ref.revision,
        name=planned[2],
        availability="available",
    )


def resolve_secret(ref: SecretRef, scope: RuntimeScope) -> SecretValue:
    if scope.project_id != ref.project_id:
        logger.info(
            "secret resolve denied project_id=%s ref_id=%s revision=%s",
            scope.project_id,
            ref.ref_id,
            ref.revision,
        )
        raise SecretScopeDenied("secret ref is outside this project")
    with _bound_store().transaction() as connection:
        row = connection.execute(
            """
            SELECT availability
            FROM secret_refs
            WHERE project_id = ? AND ref_id = ? AND revision = ?
            """,
            (str(ref.project_id), str(ref.ref_id), ref.revision),
        ).fetchone()
    if row is None or str(row[0]) != "available":
        logger.info("secret resolve missed ref_id=%s revision=%s", ref.ref_id, ref.revision)
        raise SecretScopeDenied("secret ref was not found")
    try:
        value = _read_os(ref)
    except OSError:
        logger.info("secret resolve unavailable ref_id=%s revision=%s", ref.ref_id, ref.revision)
        raise SecretUnavailable("os secret is unavailable") from None
    return SecretValue(value=value)


def latest_secret(project_id: UUID, ref_id: UUID) -> SecretRefView | None:
    with _bound_store().transaction() as connection:
        row = connection.execute(
            """
            SELECT revision, name, availability
            FROM secret_refs
            WHERE project_id = ? AND ref_id = ?
            ORDER BY revision DESC
            LIMIT 1
            """,
            (str(project_id), str(ref_id)),
        ).fetchone()
    if row is None:
        return None
    return SecretRefView(
        project_id=project_id,
        ref_id=ref_id,
        revision=int(row[0]),
        name=str(row[1]),
        availability=str(row[2]),
    )


def discard_os_secret(ref: SecretRef) -> None:
    if not _delete.argtypes:
        _configure()
    if not _delete(_target(ref), _CRED_TYPE_GENERIC, 0):
        if ctypes.get_last_error() != _ERROR_NOT_FOUND:
            raise SecretUnavailable("os secret store rejected the delete")


def _plan(
    connection: sqlite3.Connection, project_id: UUID, secret: SecretInput
) -> tuple[UUID, int, str, str]:
    if secret.ref_id is None:
        if type(secret.name) is not str or secret.name.strip() == "":
            raise SecretValidationError({"name": ["required"]})
        return uuid4(), 1, secret.name, "create"
    row = connection.execute(
        """
        SELECT name, revision
        FROM secret_refs
        WHERE project_id = ? AND ref_id = ?
        ORDER BY revision DESC
        LIMIT 1
        """,
        (str(project_id), str(secret.ref_id)),
    ).fetchone()
    if row is None:
        raise SecretScopeDenied("secret ref was not found")
    return secret.ref_id, int(row[1]) + 1, str(row[0]), "rotate"


def _validated_value(value: object) -> str:
    if type(value) is not str or value == "":
        raise SecretValidationError({"value": ["required"]})
    if len(value.encode("utf-8")) > _MAX_SECRET_BYTES:
        raise SecretValidationError({"value": ["too long"]})
    return value


def _bound_store() -> Store:
    try:
        return _store.get()
    except LookupError as exc:
        raise RuntimeError("secret store is not bound") from exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _target(ref: SecretRef) -> str:
    return f"AIQA/secret/{ref.project_id}/{ref.ref_id}/{ref.revision}"


class _FileTime(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FileTime),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168
_write = ctypes.WinDLL("advapi32").CredWriteW
_read = ctypes.WinDLL("advapi32").CredReadW
_free = ctypes.WinDLL("advapi32").CredFree
_delete = ctypes.WinDLL("advapi32").CredDeleteW


def _configure() -> None:
    _write.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
    _write.restype = wintypes.BOOL
    _read.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_Credential)),
    ]
    _read.restype = wintypes.BOOL
    _free.argtypes = [ctypes.c_void_p]
    _free.restype = None
    _delete.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _delete.restype = wintypes.BOOL


def _write_os(ref: SecretRef, value: str) -> None:
    if not _write.argtypes:
        _configure()
    blob = ctypes.create_string_buffer(value.encode("utf-8"))
    cred = _Credential()
    cred.Type = _CRED_TYPE_GENERIC
    cred.TargetName = _target(ref)
    cred.Comment = "AIQA secret ref"
    cred.CredentialBlobSize = len(blob) - 1
    cred.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_char))
    cred.Persist = _CRED_PERSIST_LOCAL_MACHINE
    cred.UserName = "aiqa-local"
    if not _write(ctypes.byref(cred), 0):
        raise SecretUnavailable("os secret store rejected the write")


def _read_os(ref: SecretRef) -> str:
    if not _read.argtypes:
        _configure()
    found = ctypes.POINTER(_Credential)()
    if not _read(_target(ref), _CRED_TYPE_GENERIC, 0, ctypes.byref(found)):
        raise OSError(ctypes.get_last_error())
    try:
        cred = found.contents
        raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
    finally:
        _free(found)
    return raw.decode("utf-8")
