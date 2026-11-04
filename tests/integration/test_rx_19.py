"""RX-19: server service-account secret resolver, Cred Manager, no plaintext DTOs."""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

import pytest

from aiqa.api.app import create_app
from aiqa.config import HOSTED_SECRET_ACCOUNT, LOCAL_SECRET_ACCOUNT, load_settings
from aiqa.domain.projects import bind_store, create_project
from aiqa.security.secrets import (
    MemorySecretBackend,
    SecretScopeDenied,
    SecretUnavailable,
    WindowsCredentialBackend,
    backup_secret_manifest,
    bind_secret_runtime,
    bind_secret_store,
    build_server_secret_resolver,
    discard_os_secret,
    scrub_worker_dto,
)
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate, RuntimeScope, SecretInput, SecretRef


def _local_env(root: Path) -> dict[str, str]:
    return {
        "AIQA_HOST": "127.0.0.1",
        "AIQA_PORT": "8000",
        "AIQA_RUNTIME_ROOT": str(root),
    }


def _hosted_env(root: Path) -> dict[str, str]:
    return {
        **_local_env(root),
        "AIQA_PROFILE": "hosted",
        "AIQA_PUBLIC_ORIGIN": "https://manage.example.test",
        "AIQA_TRUSTED_PROXIES": "127.0.0.1",
    }


def test_profile_injects_service_account_resolver(tmp_path: Path) -> None:
    local = load_settings(_local_env(tmp_path / "local"))
    assert local.secret_account == LOCAL_SECRET_ACCOUNT
    hosted = load_settings(_hosted_env(tmp_path / "hosted"))
    assert hosted.secret_account == HOSTED_SECRET_ACCOUNT

    app = create_app(hosted)
    resolver = app.state.secret_resolver
    assert resolver.account == HOSTED_SECRET_ACCOUNT
    assert resolver.profile == "hosted"
    assert isinstance(resolver.backend, WindowsCredentialBackend)


def test_resolver_scope_rotation_and_no_plaintext_leak(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    settings = load_settings(_hosted_env(root))
    backend = MemorySecretBackend()
    resolver = build_server_secret_resolver(settings, backend=backend)
    assert resolver.account == HOSTED_SECRET_ACCOUNT

    app = create_app(settings)
    app.state.secret_resolver = resolver
    store = app.state.open_store()
    migrate_store(store)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    with bind_store(store):
        project_a = create_project(owner, ProjectCreate("A", "seca", "", "web"))
        project_b = create_project(owner, ProjectCreate("B", "secb", "", "web"))
    actor_a = Actor(owner.actor_id, project_a.project_id, True)
    plain = "rx19-plain-SECRET-value"
    rotated = "rx19-rotated-SECRET-value"
    messages: list[str] = []

    class _Grab(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            messages.append(record.getMessage())

    logger = logging.getLogger("aiqa.security.secrets")
    handler = _Grab()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    created_ref: SecretRef | None = None
    try:
        with bind_secret_store(store):
            created = resolver.put(actor_a, SecretInput(value=plain, name="model-key"))
            created_ref = SecretRef(project_a.project_id, created.ref_id, created.revision)
            owned = resolver.resolve_for_server(
                created_ref, RuntimeScope(project_a.project_id, actor_a.actor_id)
            )
            assert owned.value == plain

            rotated_view = resolver.put(
                actor_a, SecretInput(value=rotated, name="", ref_id=created.ref_id)
            )
            rotated_ref = SecretRef(project_a.project_id, created.ref_id, rotated_view.revision)
            assert rotated_ref.revision != created_ref.revision
            assert (
                resolver.resolve_for_server(
                    rotated_ref, RuntimeScope(project_a.project_id, actor_a.actor_id)
                ).value
                == rotated
            )

            with pytest.raises(SecretScopeDenied):
                resolver.resolve_for_server(
                    rotated_ref, RuntimeScope(project_b.project_id, actor_a.actor_id)
                )
            with pytest.raises(SecretScopeDenied):
                resolver.resolve_for_server(
                    SecretRef(project_a.project_id, uuid4(), 1),
                    RuntimeScope(project_a.project_id, actor_a.actor_id),
                )

            # Wrong service account cannot read the hosted target.
            foreign = build_server_secret_resolver(
                load_settings({**_hosted_env(root), "AIQA_SECRET_ACCOUNT": "other-svc"}),
                backend=backend,
            )
            with pytest.raises(SecretUnavailable):
                foreign.resolve_for_server(
                    rotated_ref, RuntimeScope(project_a.project_id, actor_a.actor_id)
                )

            # Key replacement: delete OS blob for current revision → safe failure.
            with bind_secret_runtime(backend, resolver.account):
                discard_os_secret(rotated_ref)
            with pytest.raises(SecretUnavailable):
                resolver.resolve_for_server(
                    rotated_ref, RuntimeScope(project_a.project_id, actor_a.actor_id)
                )

            with store.transaction() as connection:
                manifest = backup_secret_manifest(connection, project_a.project_id)
            assert manifest
            assert all("value" not in row for row in manifest)
            assert all(plain not in str(row) and rotated not in str(row) for row in manifest)

        worker_dto = scrub_worker_dto(
            {
                "snapshot": {"digest": "abc", "secret": plain, "api_key": rotated},
                "bindings": [{"name": "login", "password": plain, "ref_id": str(created.ref_id)}],
                "token": plain,
                "safe": "visible",
            }
        )
        assert worker_dto == {
            "snapshot": {"digest": "abc", "secret": None, "api_key": None},
            "bindings": [{"name": "login", "password": None, "ref_id": str(created.ref_id)}],
            "token": None,
            "safe": "visible",
        }
        assert plain not in str(worker_dto) and rotated not in str(worker_dto)

        blob = b""
        for path in (root / "db").glob("aiqa.sqlite*"):
            blob += path.read_bytes()
        assert plain.encode() not in blob and rotated.encode() not in blob
        assert messages
        assert all(plain not in message and rotated not in message for message in messages)
    finally:
        logger.removeHandler(handler)
        store.close()


def test_windows_credential_backend_roundtrip(tmp_path: Path) -> None:
    """Initial hosted account path uses CredWriteW/CredReadW (not a reboot acceptance)."""

    settings = load_settings(_hosted_env(tmp_path / "wincred"))
    backend = WindowsCredentialBackend()
    resolver = build_server_secret_resolver(settings, backend=backend)
    app = create_app(settings)
    store = app.state.open_store()
    migrate_store(store)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("Win", "wincred", "", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    value = f"rx19-wincred-{uuid4()}"
    ref: SecretRef | None = None
    try:
        with bind_secret_store(store):
            view = resolver.put(actor, SecretInput(value=value, name="wincred-key"))
            ref = SecretRef(project.project_id, view.ref_id, view.revision)
            assert (
                resolver.resolve_for_server(
                    ref, RuntimeScope(project.project_id, actor.actor_id)
                ).value
                == value
            )
    finally:
        if ref is not None:
            with bind_secret_runtime(backend, settings.secret_account):
                discard_os_secret(ref)
        store.close()
