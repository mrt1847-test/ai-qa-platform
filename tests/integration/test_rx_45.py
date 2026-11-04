"""RX-45: operational model provider settings and mock HTTPS transport."""

from __future__ import annotations

import json
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from aiqa.api.app import create_app
from aiqa.config import SettingsError, load_settings
from aiqa.contracts.models import OwnedCheck, OwnedEpisode, RoleBinding
from aiqa.domain.projects import bind_store, create_project
from aiqa.models.broker import (
    AttemptModelPolicy,
    ModelRequestDenied,
    WorkerModelRequest,
    build_model_gateway,
)
from aiqa.models.provider_http import (
    FixtureProviderHttp,
    OperationalProviderHttp,
    ProviderHttpError,
    build_provider_from_settings,
    structured_fixture_content,
)
from aiqa.security.secrets import (
    MemorySecretBackend,
    bind_secret_store,
    build_server_secret_resolver,
)
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate, SecretInput, SecretRef, WorkerScope


def _env(root: Path, **extra: str) -> dict[str, str]:
    values = {
        "AIQA_HOST": "127.0.0.1",
        "AIQA_PORT": "8000",
        "AIQA_RUNTIME_ROOT": str(root),
    }
    values.update(extra)
    return values


def _req() -> WorkerModelRequest:
    return WorkerModelRequest(
        call_id=uuid4(),
        purpose="regression",
        role="verification",
        owner_kind="check",
        owner_id="check-1",
        binding_revision=1,
        sanitized_inputs=("ok",),
        token_output_limit=16,
        deadline="2099-01-01T00:00:00+00:00",
        check_id="check-1",
        generation=1,
    )


def _policy(project_id, item_id: str, secret_ref: SecretRef, *, max_calls: int = 2):
    return AttemptModelPolicy(
        project_id=project_id,
        item_id=item_id,
        purpose="regression",
        healing_enabled=False,
        max_calls=max_calls,
        budget="2.00",
        bindings=(RoleBinding("verification", 1, "ops-v", str(secret_ref.ref_id)),),
        checks=(OwnedCheck("check-1", item_id),),
        episodes=(OwnedEpisode("episode-1", item_id),),
        secret_refs={"verification": secret_ref},
        generation=1,
    )


def test_rx_45_settings_select_fixture_or_operational(tmp_path: Path) -> None:
    fixture_settings = load_settings(
        _env(tmp_path / "fix", AIQA_MODEL_PROVIDER_MODE="fixture")
    )
    assert fixture_settings.model_provider.mode == "fixture"
    assert isinstance(build_provider_from_settings(fixture_settings), FixtureProviderHttp)

    with pytest.raises(SettingsError, match="BASE_URL"):
        load_settings(_env(tmp_path / "bad", AIQA_MODEL_PROVIDER_MODE="operational"))

    ops_settings = load_settings(
        _env(
            tmp_path / "ops",
            AIQA_MODEL_PROVIDER_MODE="operational",
            AIQA_MODEL_PROVIDER_BASE_URL="https://provider.example",
            AIQA_MODEL_PROVIDER_CA_BUNDLE=str(tmp_path / "ca.pem"),
        )
    )
    assert ops_settings.model_provider.mode == "operational"
    assert ops_settings.model_provider.base_url == "https://provider.example"
    provider = build_provider_from_settings(ops_settings)
    assert getattr(provider, "kind") == "operational"
    assert provider.allow_live is True


def test_rx_45_mock_https_request_response_quota_idempotency_and_secret(tmp_path: Path) -> None:
    hits: list[str] = []
    issued: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/complete"
        auth = request.headers.get("Authorization", "")
        key = request.headers.get("Idempotency-Key", "")
        body = json.loads(request.content.decode("utf-8"))
        hits.append(key)
        if auth != "Bearer secret-value":
            return httpx.Response(401, json={"error": "unauthorized"})
        if key in issued:
            return httpx.Response(
                200,
                json={
                    "content": structured_fixture_content("verification"),
                    "provider_request_id": issued[key],
                    "actual_model": body["model"],
                },
            )
        if len(issued) >= 2:
            return httpx.Response(429, json={"error": "quota"})
        request_id = f"ops-{len(issued) + 1}"
        issued[key] = request_id
        return httpx.Response(
            200,
            json={
                "content": structured_fixture_content("verification"),
                "provider_request_id": request_id,
                "actual_model": body["model"],
            },
        )

    transport = httpx.MockTransport(handler)
    provider = OperationalProviderHttp(
        allow_live=True,
        base_url="https://provider.example",
        transport=transport,
    )
    first = provider.complete(
        model="ops-v",
        role="verification",
        secret="secret-value",
        sanitized_inputs=("ok",),
        token_output_limit=16,
    )
    again = provider.complete(
        model="ops-v",
        role="verification",
        secret="secret-value",
        sanitized_inputs=("ok",),
        token_output_limit=16,
    )
    assert first.provider_request_id == "ops-1"
    assert again.provider_request_id == first.provider_request_id
    assert provider.call_count == 2
    assert len(hits) == 1  # client-side idempotent cache avoids second HTTP

    with pytest.raises(ValueError, match="secret"):
        provider.complete(
            model="ops-v",
            role="verification",
            secret="",
            sanitized_inputs=("ok",),
            token_output_limit=16,
        )
    assert provider.call_count == 2

    other = provider.complete(
        model="ops-v",
        role="verification",
        secret="secret-value",
        sanitized_inputs=("other",),
        token_output_limit=16,
    )
    assert other.provider_request_id == "ops-2"
    with pytest.raises(ProviderHttpError, match="provider_quota"):
        provider.complete(
            model="ops-v",
            role="verification",
            secret="secret-value",
            sanitized_inputs=("third",),
            token_output_limit=16,
        )


def test_rx_45_wrong_address_and_wrong_ca(tmp_path: Path) -> None:
    unreachable = OperationalProviderHttp(
        allow_live=True,
        base_url="https://127.0.0.1:1",
        verify_tls=False,
        timeout_seconds=1.0,
    )
    with pytest.raises(
        ProviderHttpError, match="provider_unreachable|provider_transport|provider_timeout"
    ):
        unreachable.complete(
            model="ops-v",
            role="verification",
            secret="secret-value",
            sanitized_inputs=("ok",),
            token_output_limit=8,
        )

    # Self-signed server with a mismatched CA bundle must fail TLS verify.
    cert, key, wrong_ca = _make_tls_pair(tmp_path)
    server = _TlsEchoServer(cert, key)
    server.start()
    try:
        bad = OperationalProviderHttp(
            allow_live=True,
            base_url=f"https://127.0.0.1:{server.port}",
            ca_bundle=wrong_ca,
            verify_tls=True,
            timeout_seconds=2.0,
        )
        with pytest.raises(
            ProviderHttpError, match="provider_transport|provider_unreachable|provider_timeout"
        ):
            bad.complete(
                model="ops-v",
                role="verification",
                secret="secret-value",
                sanitized_inputs=("ok",),
                token_output_limit=8,
            )
    finally:
        server.stop()


def test_rx_45_app_wires_operational_from_settings_and_gateway_uses_secret(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        assert request.headers.get("Authorization") == "Bearer live-secret"
        return httpx.Response(
            200,
            json={
                "content": structured_fixture_content("verification"),
                "provider_request_id": "wired-1",
                "actual_model": body["model"],
            },
        )

    settings = load_settings(
        _env(
            tmp_path / "app",
            AIQA_MODEL_PROVIDER_MODE="operational",
            AIQA_MODEL_PROVIDER_BASE_URL="https://provider.example",
        )
    )
    provider = build_provider_from_settings(
        settings, transport=httpx.MockTransport(handler)
    )
    backend = MemorySecretBackend()
    app = create_app(settings, secret_backend=backend, model_provider=provider)
    assert getattr(app.state.model_gateway.provider, "kind") == "operational"

    store = app.state.open_store()
    migrate_store(store)
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("RX45", "rx45", "", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    resolver = build_server_secret_resolver(settings, backend=backend)
    with bind_secret_store(store):
        created = resolver.put(actor, SecretInput(value="live-secret", name="model"))
        secret_ref = SecretRef(project.project_id, created.ref_id, created.revision)

    gateway = build_model_gateway(resolver, provider=provider)
    gateway.register_policy(_policy(project.project_id, "attempt-1", secret_ref, max_calls=1))
    worker = WorkerScope(
        worker_id=str(uuid4()),
        permitted_projects=frozenset({project.project_id}),
        permitted_purposes=frozenset({"regression"}),
        token_id=None,
    )
    request = _req()
    receipt = gateway.handle(
        worker,
        request,
        project_id=project.project_id,
        item_id="attempt-1",
        idempotency_key="rx45-1",
        actor_id=actor.actor_id,
        store=store,
    )
    assert receipt.provider_request_id == "wired-1"
    assert '"status":"satisfied"' in receipt.content.replace(" ", "")
    assert provider.call_count == 1

    # Gateway-level idempotency: no second provider HTTP for the same key+body.
    replayed = gateway.handle(
        worker,
        request,
        project_id=project.project_id,
        item_id="attempt-1",
        idempotency_key="rx45-1",
        actor_id=actor.actor_id,
        store=store,
    )
    assert replayed.replayed is True
    assert provider.call_count == 1

    with pytest.raises(ModelRequestDenied, match="quota"):
        gateway.handle(
            worker,
            _req(),
            project_id=project.project_id,
            item_id="attempt-1",
            idempotency_key="rx45-2",
            actor_id=actor.actor_id,
            store=store,
        )
    assert provider.call_count == 1


def _make_tls_pair(root: Path) -> tuple[Path, Path, Path]:
    # Minimal self-signed material via openssl when available; otherwise skip-style files for CA mismatch only.
    openssl = Path(r"C:\Program Files\Git\usr\bin\openssl.exe")
    cert = root / "server.pem"
    key = root / "server.key"
    ca = root / "ca.pem"
    wrong = root / "wrong-ca.pem"
    if not openssl.is_file():
        pytest.skip("openssl is required for TLS CA mismatch coverage")
    conf = root / "req.cnf"
    conf.write_text(
        "[req]\ndistinguished_name=req_distinguished_name\nx509_extensions=v3\nprompt=no\n"
        "[req_distinguished_name]\nCN=127.0.0.1\n"
        "[v3]\nsubjectAltName=IP:127.0.0.1\nbasicConstraints=CA:TRUE\n",
        encoding="ascii",
    )
    import subprocess

    subprocess.run(
        [
            str(openssl),
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-config",
            str(conf),
        ],
        check=True,
        capture_output=True,
    )
    ca.write_bytes(cert.read_bytes())
    # Distinct wrong CA.
    subprocess.run(
        [
            str(openssl),
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(root / "wrong.key"),
            "-out",
            str(wrong),
            "-days",
            "1",
            "-config",
            str(conf),
            "-subj",
            "/CN=other",
        ],
        check=True,
        capture_output=True,
    )
    return cert, key, wrong


class _TlsEchoServer:
    def __init__(self, cert: Path, key: Path) -> None:
        self._cert = cert
        self._key = key
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port = 0

    def start(self) -> None:
        handler = type(
            "H",
            (BaseHTTPRequestHandler,),
            {
                "do_POST": lambda self: (
                    self.send_response(200),
                    self.send_header("Content-Type", "application/json"),
                    self.end_headers(),
                    self.wfile.write(b'{"content":"{\\"status\\":\\"ok\\"}","provider_request_id":"x","actual_model":"m"}'),
                ),
                "log_message": lambda self, *_args: None,
            },
        )
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=str(self._cert), keyfile=str(self._key))
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
        self.port = int(httpd.server_address[1])
        self._httpd = httpd
        self._thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
