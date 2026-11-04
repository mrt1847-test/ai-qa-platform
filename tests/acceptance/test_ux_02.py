"""UX-02: suite create / clone / archive UI against existing APIs."""

from __future__ import annotations

import asyncio
from html.parser import HTMLParser

import httpx
from ux_support import session, ux_app


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.names: list[str] = []
        self.has_create = False
        self.has_script = False
        self.has_confirm = False
        self.clone_buttons = 0
        feedback = False
        self._feedback = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and attrs.get("id") == "suite-create":
            self.has_create = True
        if tag == "script" and "suites.js" in attrs.get("src", ""):
            self.has_script = True
        if tag == "dialog" and attrs.get("id") == "suite-confirm":
            self.has_confirm = True
        if tag == "button" and "data-suite-clone" in attrs:
            self.clone_buttons += 1
        if tag == "input" and attrs.get("name"):
            self.names.append(attrs["name"])
        if tag == "textarea" and attrs.get("name"):
            self.names.append(attrs["name"])
        if tag == "select" and attrs.get("name"):
            self.names.append(attrs["name"])
        if tag == "section" and attrs.get("data-form-feedback") is not None:
            self._feedback = True

    @property
    def has_feedback(self) -> bool:
        return self._feedback


def test_suite_create_clone_archive_ui_flows(ux_app) -> None:
    app, project_id, database = ux_app
    asyncio.run(_exercise(app, project_id, database))


async def _exercise(app, project_id: str, database) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        headers = await session(client, project_id)
        page = await client.get(f"/ui/projects/{project_id}/suites")
        assert page.status_code == 200
        parsed = _Page()
        parsed.feed(page.text)
        assert parsed.has_create and parsed.has_script and parsed.has_confirm
        for field in ("name", "description", "target_kind", "owner_name", "classification"):
            assert field in parsed.names

        # 422 preserves validation fields for the create form
        bad = await client.post(
            f"/api/v1/projects/{project_id}/suites",
            json={
                "name": "",
                "description": "x",
                "target_kind": "web",
                "owner_name": "a",
                "classification": "b",
            },
            headers={**headers, "Idempotency-Key": "ux02-bad"},
        )
        assert bad.status_code == 422
        assert "name" in bad.json()["error"]["fields"]

        created = await client.post(
            f"/api/v1/projects/{project_id}/suites",
            json={
                "name": "회귀 묶음",
                "description": "설명",
                "target_kind": "web",
                "owner_name": "담당",
                "classification": "회귀",
            },
            headers={**headers, "Idempotency-Key": "ux02-create"},
        )
        assert created.status_code == 201, created.text
        suite = created.json()
        source_version = suite["version_id"]
        listed = await client.get(f"/ui/projects/{project_id}/suites")
        assert "회귀 묶음" in listed.text
        assert 'data-suite-clone' in listed.text
        assert suite["suite_id"] in listed.text
        assert source_version in listed.text

        # 409 different body with same key
        conflict = await client.post(
            f"/api/v1/projects/{project_id}/suites",
            json={
                "name": "다른 이름",
                "description": "설명",
                "target_kind": "web",
                "owner_name": "담당",
                "classification": "회귀",
            },
            headers={**headers, "Idempotency-Key": "ux02-create"},
        )
        assert conflict.status_code == 409

        # Same key/body receipt replay does not add a second suite
        replay = await client.post(
            f"/api/v1/projects/{project_id}/suites",
            json={
                "name": "회귀 묶음",
                "description": "설명",
                "target_kind": "web",
                "owner_name": "담당",
                "classification": "회귀",
            },
            headers={**headers, "Idempotency-Key": "ux02-create"},
        )
        assert replay.status_code == 200
        assert replay.json()["suite_id"] == suite["suite_id"]

        cloned = await client.post(
            f"/api/v1/suites/{suite['suite_id']}/clone",
            json={"project_id": project_id, "name": "회귀 묶음 복사"},
            headers={**headers, "Idempotency-Key": "ux02-clone"},
        )
        assert cloned.status_code == 201, cloned.text
        assert cloned.json()["suite_id"] != suite["suite_id"]
        assert cloned.json()["name"] == "회귀 묶음 복사"

        archived = await client.post(
            f"/api/v1/suites/{suite['suite_id']}/archive",
            json={"project_id": project_id},
            headers={**headers, "Idempotency-Key": "ux02-archive"},
        )
        assert archived.status_code == 200
        assert archived.json()["archived_at"]

        after = await client.get(f"/ui/projects/{project_id}/suites")
        assert "회귀 묶음 복사" in after.text
        assert "보관됨" in after.text or archived.json()["archived_at"]

    # Source head version unchanged by clone/archive
    import sqlite3

    con = sqlite3.connect(database)
    row = con.execute(
        "SELECT head_version_id FROM suites WHERE suite_id = ?", (suite["suite_id"],)
    ).fetchone()
    clone_row = con.execute(
        "SELECT head_version_id FROM suites WHERE suite_id = ?", (cloned.json()["suite_id"],)
    ).fetchone()
    runs = con.execute(
        "SELECT count(*) FROM executions WHERE project_id = ?", (project_id,)
    ).fetchone()
    con.close()
    assert row[0] == source_version
    assert clone_row[0] != source_version or clone_row[0] == cloned.json()["version_id"]
    assert int(runs[0]) == 0
