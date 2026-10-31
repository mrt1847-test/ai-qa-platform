"""W00-02: one app factory, loopback settings, and API liveness only."""

from __future__ import annotations

import asyncio
import os
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from aiqa.api.app import create_app
from aiqa.config import AppSettings, SettingsError, load_settings

_CLIENT_ATTRS = (
    "db",
    "database",
    "engine",
    "adb",
    "model",
    "model_client",
    "http_client",
)
_PRODUCT_CLIENT_MODULES = ("aiqa.worker", "aiqa.replay", "aiqa.probes")


def _raises_settings(env: dict[str, str]) -> bool:
    try:
        load_settings(env)
    except SettingsError:
        return True
    return False


def test_w00_02(tmp_path: Path) -> None:
    local = tmp_path / "LocalAppData"
    root_a = local / "AIQA"
    root_b = tmp_path / "runtime-b"
    base_env = {"LOCALAPPDATA": str(local)}

    with patch.dict(os.environ, {"AIQA_HOST": "0.0.0.0", "AIQA_PORT": "1"}, clear=False):
        isolated = load_settings(base_env)
    assert isolated.host == "127.0.0.1"
    assert isolated.port == 8000
    assert isolated.runtime_root == root_a
    assert not root_a.exists()

    with patch.dict(
        os.environ,
        {"LOCALAPPDATA": str(local), "AIQA_RUNTIME_ROOT": str(root_a)},
        clear=False,
    ):
        os.environ.pop("AIQA_HOST", None)
        os.environ.pop("AIQA_PORT", None)
        from_process_env = load_settings(None)
    assert from_process_env == AppSettings(host="127.0.0.1", port=8000, runtime_root=root_a)

    explicit = load_settings({**base_env, "AIQA_PORT": "8123", "AIQA_RUNTIME_ROOT": str(root_a)})
    assert explicit.port == 8123

    non_loopback_rejected = _raises_settings({**base_env, "AIQA_HOST": "0.0.0.0"})
    assert non_loopback_rejected
    for host in ("localhost", "::1", "10.1.2.3", ""):
        assert _raises_settings({**base_env, "AIQA_HOST": host})
    with pytest.raises(SettingsError):
        AppSettings(host="0.0.0.0", port=8000, runtime_root=root_a)
    for port in ("0", "65536", "-1", "abc", "8000.5", ""):
        assert _raises_settings({**base_env, "AIQA_PORT": port})
    with pytest.raises(SettingsError):
        load_settings({})
    with patch.dict(os.environ, {"AIQA_HOST": "0.0.0.0", "LOCALAPPDATA": str(local)}, clear=False):
        with pytest.raises(SettingsError):
            create_app()

    connects = {"n": 0}
    popens = {"n": 0}
    outbound = {"n": 0}
    real_connect = sqlite3.connect
    real_popen = subprocess.Popen
    real_create_connection = socket.create_connection

    def track_connect(*args, **kwargs):
        connects["n"] += 1
        return real_connect(*args, **kwargs)

    def track_popen(*args, **kwargs):
        popens["n"] += 1
        return real_popen(*args, **kwargs)

    def track_outbound(*args, **kwargs):
        outbound["n"] += 1
        return real_create_connection(*args, **kwargs)

    product_before = {
        name for name in sys.modules if name.startswith(_PRODUCT_CLIENT_MODULES)
    }
    with (
        patch("sqlite3.connect", track_connect),
        patch("subprocess.Popen", track_popen),
        patch("socket.create_connection", track_outbound),
    ):
        with patch.dict(
            os.environ,
            {"LOCALAPPDATA": str(local), "AIQA_RUNTIME_ROOT": str(root_a)},
            clear=False,
        ):
            os.environ.pop("AIQA_HOST", None)
            os.environ.pop("AIQA_PORT", None)
            app_default = create_app()
        assert app_default.state.settings == from_process_env
        app_a = create_app(explicit)
        assert app_default is not app_a
        app_b = create_app(
            load_settings({**base_env, "AIQA_RUNTIME_ROOT": str(root_b), "AIQA_PORT": "8124"})
        )
        app_a.state.marker = "only-a"
        leaked = getattr(app_b.state, "marker", None) == "only-a"

        liveness_observation = {}
        async def call_app() -> tuple[httpx.Response, httpx.Response, httpx.Response, httpx.Response]:
            transport = httpx.ASGITransport(app=app_a)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
                health_response = await client.get("/api/v1/health")
                health_repeat = await client.get("/api/v1/health")
                liveness_observation.update(connections=connects['n'], runtime_files=int(root_a.exists()) + int(root_b.exists()))
                business_response = await client.get("/api/v1/projects")
                mutation_response = await client.post("/api/v1/projects")
            return health_response, health_repeat, business_response, mutation_response

        health, health_again, business, mutation = asyncio.run(call_app())

    product_after = {
        name for name in sys.modules if name.startswith(_PRODUCT_CLIENT_MODULES)
    }
    state_clients = sum(
        1 for name in _CLIENT_ATTRS if getattr(app_a.state, name, None) is not None
    )
    runtime_files = liveness_observation['runtime_files']
    external_clients_created = (
        liveness_observation['connections']
        + popens["n"]
        + outbound["n"]
        + len(product_after - product_before)
        + state_clients
        + runtime_files
        + int(leaked or app_a is app_b)
    )

    assert health_again.status_code == health.status_code
    assert health_again.json() == health.json()
    assert mutation.status_code == 422  # Completed route rejects missing mutation key.
    assert app_a.state.settings.runtime_root == root_a
    assert app_b.state.settings.runtime_root == root_b
    assert "/api/v1/projects" in app_a.openapi()['paths']
    assert business.json() == {'items': []}
    assert connects['n'] > liveness_observation['connections']  # Real catalog read opens its store.

    observed = {
        "health_status": health.status_code,
        "body": health.json(),
        "business_endpoint_status": business.status_code,
        "external_clients_created": external_clients_created,
        "non_loopback_rejected": non_loopback_rejected,
    }
    assert observed == {
        "health_status": 200,
        "body": {"status": "ok", "component": "api"},
        "business_endpoint_status": 200,
        "external_clients_created": 0,
        "non_loopback_rejected": True,
    }
