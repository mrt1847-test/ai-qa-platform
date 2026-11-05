"""RX-58: model binding connection checks, compatibility, key-safe replay note."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from uuid import uuid4

import httpx

from aiqa.api.app import create_app
from aiqa.api.worker import model_check_requires_physical_session
from aiqa.config import load_settings
from aiqa.domain.model_bindings import (
    approved_deterministic_replay_requires_model_check,
    bind_model_store,
    save_model_binding_revision,
)
from aiqa.domain.projects import bind_store, create_project
from aiqa.security.secrets import MemorySecretBackend, bind_secret_store, build_server_secret_resolver
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ModelBindingInput, ProjectCreate, SecretInput, SecretRef
from ux_support import session

_BROWSERS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)


def test_rx_58_model_check_modes_and_settings(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    settings = load_settings(
        {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
    )
    backend = MemorySecretBackend()
    app = create_app(settings, secret_backend=backend)
    owner = Actor(uuid4(), None, True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("모델검사", "rx58", "check", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    resolver = build_server_secret_resolver(settings, backend=backend)
    with bind_secret_store(store):
        created = resolver.put(actor, SecretInput(value="fixture-model-key", name="verification"))
    with bind_model_store(store):
        view = save_model_binding_revision(
            ModelBindingInput(
                project_id=project.project_id,
                actor_id=actor.actor_id,
                name="verification",
                role="verification",
                provider="fixture",
                endpoint_kind="https",
                endpoint="https://model.example/v1",
                model="fixture-model",
                key_ref=SecretRef(project.project_id, created.ref_id, created.revision),
                prompt_hash="sha256:" + ("ab" * 32),
                tariff_id="t1",
                compatibility_status="unchecked",
                binding_id=None,
            )
        )
    store.close()

    assert approved_deterministic_replay_requires_model_check() is False
    assert model_check_requires_physical_session() is False

    observed = asyncio.run(_flow(app, str(project.project_id), str(view.binding_id), "fixture-model-key"))
    browser_ok = _browser_shot(tmp_path, observed["page_html"])

    assert observed["ok_status"] == "compatible"
    assert observed["ok_metered"] == 1
    assert observed["ok_qa"] is None
    assert observed["unauthorized"] == "unauthorized"
    assert observed["rate_limited"] == "rate_limited"
    assert observed["timeout"] == "timeout"
    assert observed["key_missing"] == "key_missing"
    assert observed["key_missing_metered"] == 0
    assert observed["compat_status"] == "key_missing" or observed["compat_replay"] is False
    assert observed["replay_requires_check"] is False
    assert observed["approved_without_key"] is True
    assert observed["key_plaintext_echo"] is False
    assert observed["page_has_check"] is True
    assert observed["page_replay_note"] is True
    assert browser_ok is True


async def _flow(app: object, project_id: str, binding_id: str, secret: str) -> dict[str, object]:
    transport = httpx.ASGITransport(app=app)
    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        headers = await session(client, project_id)

        async def check(mode: str, key: str) -> dict[str, object]:
            headers["Idempotency-Key"] = key
            response = await client.post(
                f"/api/v1/model-bindings/{binding_id}/checks",
                params={"project_id": project_id},
                json={"provider": "fixture", "mode": mode},
                headers=headers,
            )
            assert response.status_code == 201, response.text
            body = response.json()
            dumped = json.dumps(body)
            assert secret not in dumped
            assert "fixture-model-key" not in dumped
            return body

        ok = await check("ok", "rx58-ok")
        unauthorized = await check("unauthorized", "rx58-401")
        rate = await check("rate_limited", "rx58-429")
        timeout = await check("timeout", "rx58-timeout")
        missing = await check("key_missing", "rx58-nokey")

        listed = await client.get(
            f"/api/v1/model-bindings/{binding_id}/compatibility",
            params={"project_id": project_id},
            headers=headers,
        )
        assert listed.status_code == 200, listed.text
        compat = listed.json()
        assert secret not in json.dumps(compat)

        page = await client.get(f"/ui/projects/{project_id}/settings")
        assert page.status_code == 200, page.text
        return {
            "ok_status": ok["status"],
            "ok_metered": ok["metered_calls"],
            "ok_qa": ok["qa"],
            "unauthorized": unauthorized["status"],
            "rate_limited": rate["status"],
            "timeout": timeout["status"],
            "key_missing": missing["status"],
            "key_missing_metered": missing["metered_calls"],
            "compat_status": compat["status"],
            "compat_replay": compat["replay_requires_model_check"],
            "replay_requires_check": ok["replay_requires_model_check"],
            "approved_without_key": ok["approved_replay_without_model_key"],
            "key_plaintext_echo": secret in page.text or secret in json.dumps(ok),
            "page_has_check": "연결 검사" in page.text,
            "page_replay_note": "결정적·승인 재생은 모델 연결 검사 없이도 가능합니다" in page.text,
            "page_html": page.text,
        }


def _browser_shot(tmp_path: Path, html: str) -> bool:
    browser = next((path for path in _BROWSERS if path.exists()), None)
    if browser is None:
        return False
    page = tmp_path / "rx58.html"
    shot = tmp_path / "rx58.png"
    page.write_text(html, encoding="utf-8")
    completed = subprocess.run(
        [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            f"--screenshot={shot}",
            page.resolve().as_uri(),
        ],
        check=False,
        capture_output=True,
        timeout=60,
    )
    return completed.returncode == 0 and shot.exists() and shot.stat().st_size > 1024
