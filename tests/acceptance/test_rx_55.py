"""RX-55: NL structure job → compare → accept/reject; secret/stale blocked."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
from pathlib import Path
from uuid import uuid4

import httpx

from aiqa.api.app import create_app
from aiqa.config import load_settings
from aiqa.domain.model_bindings import bind_model_store, save_model_binding_revision
from aiqa.domain.projects import bind_store, create_project
from aiqa.models.provider_http import structured_fixture_content
from aiqa.recording.structure import structure_body_from_text
from aiqa.security.secrets import MemorySecretBackend, bind_secret_store
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ModelBindingInput, ProjectCreate, SecretInput, SecretRef
from aiqa.worker.runtime import structure_prepared_adapters
from ux_support import session

_BROWSERS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)

_NL = "로그인한 뒤 주문 내역에서 첫 주문을 열고, 주문번호와 결제 금액이 표시되는지 확인해줘."


def test_rx_55_structure_propose_compare_accept(tmp_path: Path) -> None:
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
        project = create_project(owner, ProjectCreate("구조화", "rx55", "제안", "web"))
    actor = Actor(owner.actor_id, project.project_id, True)
    with bind_secret_store(store):
        created = app.state.secret_resolver.put(
            actor, SecretInput(value="rx55-structure-key", name="structure")
        )
    with bind_model_store(store):
        save_model_binding_revision(
            ModelBindingInput(
                project_id=project.project_id,
                actor_id=actor.actor_id,
                name="structure",
                role="structure",
                provider="fixture",
                endpoint_kind="https",
                endpoint="https://model.example/v1",
                model="fixture-structure",
                key_ref=SecretRef(project.project_id, created.ref_id, created.revision),
                prompt_hash="sha256:" + ("cd" * 32),
                tariff_id="t1",
                compatibility_status="compatible",
                binding_id=None,
            )
        )
    store.close()
    project_id = str(project.project_id)
    database = root / "db" / "aiqa.sqlite"

    observed = asyncio.run(_flow(app, project_id, database))
    browser_ok = _browser_shot(tmp_path, observed["page_html"])

    assert "structure" in structure_prepared_adapters()
    assert observed["structure_status"] == 201
    assert observed["auto_applied"] is False
    assert observed["reject_delta"] == 0
    assert observed["accept_delta"] == 1
    assert observed["secret_status"] >= 400
    assert observed["stale_status"] == 409
    assert observed["page_has_diff"] is True
    assert observed["page_has_request"] is True
    assert observed["job_qa"] is None
    assert browser_ok is True


async def _flow(app: object, project_id: str, database: Path) -> dict[str, object]:
    transport = httpx.ASGITransport(app=app)
    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        headers = await session(client, project_id)
        headers["Idempotency-Key"] = "rx55-case"
        created = await client.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": "주문확인", "tc_reference": None},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        case_id = created.json()["case_id"]
        headers["Idempotency-Key"] = "rx55-draft"
        draft = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
            json={
                "definition": {
                    "raw_text": _NL,
                    "objective": "",
                    "preconditions": [],
                    "variables": {},
                    "secret_refs": {},
                    "steps": [],
                    "final_expected": [],
                    "path_policy": {"must_use": [], "forbidden": []},
                },
                "settings": {"target_kind": "web", "definition_buffer": _NL},
                "recorded_steps": [],
                "parent_version_id": None,
                "base_version_id": None,
                "reason": "draft",
                "expected_head": None,
                "branch": False,
            },
            headers=headers,
        )
        assert draft.status_code == 201, draft.text
        version_id = draft.json()["id"]
        base_hash = draft.json()["content_hash"]

        headers["Idempotency-Key"] = "rx55-structure"
        structured = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/versions/{version_id}/structure",
            json={},
            headers=headers,
        )
        assert structured.status_code == 201, structured.text
        structure_body = structured.json()
        proposal_id = structure_body["proposal_id"]

        with sqlite3.connect(database) as connection:
            before_reject = connection.execute(
                "SELECT COUNT(*) FROM case_versions WHERE case_id = ?",
                (case_id,),
            ).fetchone()[0]
            job = connection.execute(
                "SELECT purpose, status FROM jobs WHERE job_id = ?",
                (structure_body["job_id"],),
            ).fetchone()

        headers["Idempotency-Key"] = "rx55-reject"
        rejected = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/proposal-rejections",
            json={"proposal_id": proposal_id},
            headers=headers,
        )
        assert rejected.status_code == 200, rejected.text
        with sqlite3.connect(database) as connection:
            after_reject = connection.execute(
                "SELECT COUNT(*) FROM case_versions WHERE case_id = ?",
                (case_id,),
            ).fetchone()[0]

        headers["Idempotency-Key"] = "rx55-structure-2"
        again = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/versions/{version_id}/structure",
            json={},
            headers=headers,
        )
        assert again.status_code == 201, again.text
        accept_id = again.json()["proposal_id"]

        headers["Idempotency-Key"] = "rx55-secret"
        secret = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/proposals",
            json={
                "base_version_id": version_id,
                "base_hash": base_hash,
                "kind": "structure",
                "body": {
                    **structure_body_from_text(_NL),
                    "secret_plaintext": "do-not-store",
                },
                "source_job_id": again.json()["job_id"],
                "tc_version_id": None,
            },
            headers=headers,
        )

        headers["Idempotency-Key"] = "rx55-stale"
        stale = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/proposal-acceptances",
            json={"proposal_id": accept_id, "expected_head": str(uuid4())},
            headers=headers,
        )

        with sqlite3.connect(database) as connection:
            before_accept = connection.execute(
                "SELECT COUNT(*) FROM case_versions WHERE case_id = ?",
                (case_id,),
            ).fetchone()[0]
        headers["Idempotency-Key"] = "rx55-accept"
        accepted = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/proposal-acceptances",
            json={"proposal_id": accept_id, "expected_head": version_id},
            headers=headers,
        )
        assert accepted.status_code == 201, accepted.text
        with sqlite3.connect(database) as connection:
            after_accept = connection.execute(
                "SELECT COUNT(*) FROM case_versions WHERE case_id = ?",
                (case_id,),
            ).fetchone()[0]

        page = await client.get(f"/ui/projects/{project_id}/cases/{case_id}/steps")
        assert page.status_code == 200, page.text
        return {
            "structure_status": structured.status_code,
            "auto_applied": structure_body["auto_applied"],
            "reject_delta": after_reject - before_reject,
            "accept_delta": after_accept - before_accept,
            "secret_status": secret.status_code,
            "stale_status": stale.status_code,
            "page_html": page.text,
            "page_has_diff": "변경 필드" in page.text or "제안 차이" in page.text or "steps" in page.text,
            "page_has_request": "구조화 요청" in page.text and "명시 요청 시에만 구조화" in page.text,
            "job_qa": None if job is not None and job[0] == "structure" and job[1] == "completed" else job,
            "before_accept": before_accept,
        }


def _browser_shot(tmp_path: Path, html: str) -> bool:
    browser = next((path for path in _BROWSERS if path.exists()), None)
    if browser is None:
        return False
    page = tmp_path / "rx55.html"
    shot = tmp_path / "rx55.png"
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


def test_rx_55_fixture_structure_payload_has_no_secrets() -> None:
    body = structure_body_from_text(_NL, model_content=structured_fixture_content("structure"))
    assert "secret" not in body and "reasoning" not in body
    assert body["steps"] and body["objective"]
