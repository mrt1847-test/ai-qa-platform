"""RX-49: recording detail timeline shows ACK'd action order and step evidence."""

from __future__ import annotations

import asyncio
import binascii
import hashlib
import re
import sqlite3
import struct
import subprocess
import zlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from aiqa.api.app import create_app
from aiqa.config import load_settings
from aiqa.domain.projects import bind_store, create_project
from aiqa.store.artifacts import publish_durable
from aiqa.store.database import migrate_store
from aiqa.store.models import Actor, ProjectCreate
from ux_support import session

_BROWSERS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)


def _png(width: int = 8, height: int = 8, shade: int = 40) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", binascii.crc32(kind + body) & 0xFFFFFFFF)
        )

    row = b"\x00" + bytes([shade, shade, shade]) * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def _draft() -> dict[str, object]:
    return {
        "definition": {
            "raw_text": "로그인",
            "objective": "로그인",
            "preconditions": [],
            "variables": {},
            "secret_refs": {},
            "steps": [{"id": "s1", "instruction": "tap", "point": [10, 20], "expected": []}],
            "final_expected": [],
            "path_policy": {"must_use": [], "forbidden": []},
        },
        "settings": {"target_kind": "android", "android_package": "com.example.app"},
    }


def _place(
    connection: sqlite3.Connection,
    *,
    artifacts_dir: Path,
    project_id: str,
    recording_id: str,
    attempt_id: str,
    job_id: str,
    action_id: str,
    role: str,
    body: bytes,
    media: str,
    suffix: str,
    stored_at: str,
) -> str:
    artifact_id = uuid4()
    durable = publish_durable(artifacts_dir, UUID(project_id), artifact_id, suffix, body)
    connection.execute(
        """
        INSERT INTO artifact_refs (project_id, artifact_id, attempt_id, action_id)
        VALUES (?, ?, ?, ?)
        """,
        (project_id, str(artifact_id), attempt_id, action_id),
    )
    connection.execute(
        """
        INSERT INTO artifact_objects (
            project_id, artifact_id, object_key, content_hash, byte_length, media_type,
            owner_id, status, acked, custody, stored_at,
            owner_kind, attempt_id, action_id, check_id, role, job_id, generation
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ready', 1, 'stored', ?, 'REC', ?, ?, NULL, ?, ?, 1)
        """,
        (
            project_id,
            str(artifact_id),
            durable.object_key,
            durable.content_hash,
            len(body),
            media,
            recording_id,
            stored_at,
            attempt_id,
            action_id,
            role,
            job_id,
        ),
    )
    return str(artifact_id)


def seed_recording_evidence(
    *,
    database: Path,
    artifacts_dir: Path,
    project_id: str,
    case_id: str,
    version_id: str,
) -> tuple[str, str, str]:
    recording_id = str(uuid4())
    job_id = str(uuid4())
    attempt_id = str(uuid4())
    action_a = "action-rx49-a"
    action_b = "action-rx49-b"
    t0 = datetime(2026, 11, 5, 8, 0, 0, tzinfo=timezone.utc).isoformat()
    t1 = datetime(2026, 11, 5, 8, 0, 12, tzinfo=timezone.utc).isoformat()
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO recordings (
                project_id, case_id, recording_id, creation_kind, input_case_version_id,
                storage_status, stop_status, completion_status, evidence_status
            ) VALUES (?, ?, ?, 'recorded', ?, 'stored', 'running', 'open', 'incomplete')
            """,
            (project_id, case_id, recording_id, version_id),
        )
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, payload_hash, source_refs, limits, status
            ) VALUES (?, ?, 'recording', ?, 'hash-rx49', '[]', '{}', 'running')
            """,
            (project_id, job_id, recording_id),
        )
        connection.execute(
            """
            INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id)
            VALUES (?, ?, ?, 1, NULL)
            """,
            (project_id, attempt_id, job_id),
        )
        for seq, action_id in ((1, action_a), (2, action_b)):
            connection.execute(
                """
                INSERT INTO actions (
                    project_id, attempt_id, action_seq, step_id, action_id, proposal_hash,
                    dispatch_state, case_id, case_version_id, outcome_known
                ) VALUES (?, ?, ?, ?, ?, ?, 'observed', ?, ?, 1)
                """,
                (
                    project_id,
                    attempt_id,
                    seq,
                    f"step-{seq}",
                    action_id,
                    "sha256:" + hashlib.sha256(action_id.encode()).hexdigest(),
                    case_id,
                    version_id,
                ),
            )
        _place(
            connection,
            artifacts_dir=artifacts_dir,
            project_id=project_id,
            recording_id=recording_id,
            attempt_id=attempt_id,
            job_id=job_id,
            action_id=action_a,
            role="before",
            body=_png(shade=20),
            media="image/png",
            suffix=".png",
            stored_at=t0,
        )
        _place(
            connection,
            artifacts_dir=artifacts_dir,
            project_id=project_id,
            recording_id=recording_id,
            attempt_id=attempt_id,
            job_id=job_id,
            action_id=action_a,
            role="after",
            body=_png(shade=90),
            media="image/png",
            suffix=".png",
            stored_at=t0,
        )
        _place(
            connection,
            artifacts_dir=artifacts_dir,
            project_id=project_id,
            recording_id=recording_id,
            attempt_id=attempt_id,
            job_id=job_id,
            action_id=action_a,
            role="log",
            body=b"first step log\n",
            media="text/plain",
            suffix=".log",
            stored_at=t0,
        )
        _place(
            connection,
            artifacts_dir=artifacts_dir,
            project_id=project_id,
            recording_id=recording_id,
            attempt_id=attempt_id,
            job_id=job_id,
            action_id=action_b,
            role="before",
            body=_png(shade=55),
            media="image/png",
            suffix=".png",
            stored_at=t1,
        )
        _place(
            connection,
            artifacts_dir=artifacts_dir,
            project_id=project_id,
            recording_id=recording_id,
            attempt_id=attempt_id,
            job_id=job_id,
            action_id=action_b,
            role="log",
            body=b"second step log\n",
            media="text/plain",
            suffix=".log",
            stored_at=t1,
        )
        connection.execute(
            """
            INSERT INTO check_results (
                project_id, attempt_id, action_id, check_id, status, method,
                expected_snapshot, sanitized_observed, reason, artifact_refs, observed_at
            ) VALUES (?, ?, ?, 'check-rx49', 'violated', 'deterministic', '{}', '{}', '좌표 불일치', '[]', ?)
            """,
            (project_id, attempt_id, action_b, t1),
        )
        connection.commit()
    return recording_id, action_a, action_b


def _find_browser() -> Path | None:
    for path in _BROWSERS:
        if path.is_file():
            return path
    return None


def _browser_screenshot(browser: Path, url: str, work: Path) -> Path:
    shot = work / "rx49-timeline.png"
    profile = work / "browser-profile"
    profile.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile}",
            "--force-device-scale-factor=1",
            "--window-size=1280,720",
            f"--screenshot={shot}",
            "--default-background-color=FFFFFFFF",
            url,
        ],
        cwd=work,
        check=False,
        capture_output=True,
        text=True,
        timeout=40,
    )
    return shot


def test_rx_49_timeline_order_selection_offline_and_cross_project(tmp_path: Path) -> None:
    asyncio.run(_exercise(tmp_path))


async def _exercise(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(Actor(uuid4(), None, True), ProjectCreate("타임라인", "rx49", "녹화", "android"))
        other = create_project(Actor(uuid4(), None, True), ProjectCreate("다른프로젝트", "rx49b", "녹화", "android"))
    artifacts_dir = store.config.artifacts_dir
    store.close()
    project_id = str(project.project_id)
    other_id = str(other.project_id)
    database = root / "db" / "aiqa.sqlite"

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
        headers = await session(client, project_id)
        created = await client.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": "로그인", "tc_reference": None},
            headers={**headers, "Idempotency-Key": "rx49-case"},
        )
        assert created.status_code == 201, created.text
        case_id = created.json()["case_id"]
        version = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
            json=_draft(),
            headers={**headers, "Idempotency-Key": "rx49-version"},
        )
        assert version.status_code == 201, version.text
        version_id = version.json()["id"]
        recording_id, action_a, action_b = seed_recording_evidence(
            database=database,
            artifacts_dir=artifacts_dir,
            project_id=project_id,
            case_id=case_id,
            version_id=version_id,
        )

        page = await client.get(f"/ui/projects/{project_id}/recordings/{recording_id}")
        assert page.status_code == 200, page.text
        assert 'id="recording-timeline"' in page.text
        assert 'id="evidence-viewer"' in page.text
        assert 'data-keynav="true"' in page.text
        positions = [
            page.text.find(f'data-timeline-action="{action_a}"'),
            page.text.find(f'data-timeline-action="{action_b}"'),
        ]
        assert positions[0] != -1 and positions[1] != -1 and positions[0] < positions[1]
        assert "순서 1" in page.text and "순서 2" in page.text
        assert "first step log" in page.text
        assert "파일이 없습니다." in page.text
        assert "좌표 불일치" in page.text
        assert page.text.count('data-timeline-action="') == 2
        assert "recording_timeline.js" in page.text
        assert "evidence_viewer.js" in page.text

        selected = await client.get(
            f"/ui/projects/{project_id}/recordings/{recording_id}",
            params={"action_id": action_b},
        )
        assert selected.status_code == 200
        assert f'data-action-id="{action_b}"' in selected.text
        match = re.search(r'<article data-action="action-rx49-b"[^>]*>', selected.text)
        assert match is not None
        assert "hidden" not in match.group(0)
        hidden_a = re.search(r'<article data-action="action-rx49-a"[^>]*>', selected.text)
        assert hidden_a is not None and "hidden" in hidden_a.group(0)

        timeline = await client.get(
            f"/api/v1/projects/{project_id}/recordings/{recording_id}/timeline",
            headers=headers,
        )
        assert timeline.status_code == 200, timeline.text
        body = timeline.json()
        assert [item["action_id"] for item in body["actions"]] == [action_a, action_b]
        assert body["actions"][0]["before"] == "stored"
        assert body["actions"][0]["after"] == "stored"
        assert body["actions"][1]["after"] == "missing"
        assert body["actions"][1]["error_text"] == "좌표 불일치"

        foreign = await client.get(f"/ui/projects/{other_id}/recordings/{recording_id}")
        assert foreign.status_code in (401, 404)
        foreign_api = await client.get(
            f"/api/v1/projects/{other_id}/recordings/{recording_id}/timeline",
            headers=headers,
        )
        assert foreign_api.status_code in (401, 403, 404)

        browser = _find_browser()
        assert browser is not None, "local browser required for RX-49 environment"
        work = tmp_path / "browser"
        work.mkdir()
        rendered = work / "recording.html"
        rendered.write_text(selected.text, encoding="utf-8")
        shot = _browser_screenshot(browser, rendered.resolve().as_uri(), work)
        assert shot.is_file() and shot.stat().st_size > 1000
