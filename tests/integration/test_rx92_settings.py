"""Case settings edits keep fixed healer references and narrowed limits."""
import asyncio
import json
import sqlite3
from uuid import uuid4

import httpx
import pytest

from aiqa.domain.versions import SettingsRejected, parse_case_settings, settings_document
from ux_support import ux_app, session


POLICY = {"allowed": True, "default_enabled": False, "scope": "locator", "model_binding_ref": "healer-main", "binding_revision": "rev-7", "max_episodes_per_item": 1, "max_model_calls_per_item": 1, "max_seconds": 20}
LIMITS = {"timeout_seconds": 180, "budget": "0.75", "currency": "USD", "max_actions": 12, "max_model_calls": 3, "max_episodes_per_item": 1, "max_model_calls_per_item": 1, "max_seconds": 15}


def test_common_settings_serialization_keeps_healer_revision_and_limits():
    actual = json.loads(settings_document(parse_case_settings({"target_kind": "web", "healing_policy": POLICY, "limits": LIMITS}, uuid4())))
    assert actual["healing_policy"] == POLICY
    assert actual["limits"] == LIMITS
    assert actual["healing_policy"]["default_enabled"] is False
    legacy = json.loads(settings_document(parse_case_settings({"target_kind": "android"}, uuid4())))
    assert legacy["healing_policy"]["allowed"] is False
    assert "model_binding_ref" not in legacy["healing_policy"]


@pytest.mark.parametrize("field,value", [("model_binding_ref", True), ("binding_revision", 7), ("max_episodes_per_item", True), ("max_model_calls_per_item", 1.9), ("max_seconds", float("inf"))])
def test_healing_settings_reject_bad_reference_types_and_fractional_caps(field, value):
    with pytest.raises(SettingsRejected):
        parse_case_settings({"target_kind": "web", "healing_policy": {**POLICY, field: value}}, uuid4())


def test_settings_form_updates_fixed_refs_and_timeout_without_losing_other_limits(ux_app):
    app, project, database = ux_app
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            headers = await session(client, project)
            created = await client.post(f"/api/v1/projects/{project}/cases", json={"name": "Settings"}, headers=headers)
            case = created.json()["case_id"]
            version = await client.post(f"/api/v1/projects/{project}/cases/{case}/versions", json={"definition": {"objective": "Keep references"}, "settings": {"target_kind": "web", "healing_policy": POLICY, "limits": LIMITS}}, headers={**headers, "Idempotency-Key": "version"})
            assert version.status_code == 201, version.text
            original = version.json()["id"]
            url = f"/ui/projects/{project}/cases/{case}/settings"
            saved = await client.post(url, json={"expected_head": original, "timeout_seconds": 120, "healing_binding_id": "healer-next", "healing_binding_revision": "rev-8"}, headers={**headers, "Idempotency-Key": "edit"})
            assert saved.status_code == 201, saved.text
            with sqlite3.connect(database) as db:
                old = json.loads(db.execute("SELECT settings_json FROM case_versions WHERE version_id=?", (original,)).fetchone()[0])
                new = json.loads(db.execute("SELECT settings_json FROM case_versions WHERE version_id=?", (saved.json()["id"],)).fetchone()[0])
                approval = db.execute("SELECT current_approval_id FROM automation_cases WHERE case_id=?", (case,)).fetchone()[0]
            assert old["healing_policy"] == POLICY
            assert new["healing_policy"] == {**POLICY, "model_binding_ref": "healer-next", "binding_revision": "rev-8"}
            assert new["limits"] == {**LIMITS, "timeout_seconds": 120}
            assert approval is None
            page = await client.get(url)
            assert page.status_code == 200
            assert 'name="healing_binding_id"' in page.text and 'value="healer-next"' in page.text
            assert 'name="healing_binding_revision"' in page.text and 'value="rev-8"' in page.text
            conflict = await client.post(url, json={"expected_head": original, "healing_binding_id": "stale"}, headers={**headers, "Idempotency-Key": "stale"})
            assert conflict.status_code == 409
            assert conflict.json()["server_snapshot"]["settings"]["healing_policy"]["binding_revision"] == "rev-8"
    asyncio.run(scenario())


@pytest.mark.parametrize("limits", [{"budget": "NaN"}, {"budget": "Infinity"}, {"budget": "-0.01"}, {"budget": True}, {"currency": "KRW"}, {"max_actions": -1}, {"max_model_calls": 2.5}, {"timeout_seconds": True}, {"max_seconds": 31}])
def test_invalid_settings_limits_are_422_without_a_new_version(ux_app, limits):
    app, project, database = ux_app
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            headers = await session(client, project)
            created = await client.post(f"/api/v1/projects/{project}/cases", json={"name": "Invalid limits"}, headers=headers)
            case = created.json()["case_id"]
            version = await client.post(f"/api/v1/projects/{project}/cases/{case}/versions", json={"definition": {}, "settings": {"target_kind": "web"}}, headers={**headers, "Idempotency-Key": "initial"})
            assert version.status_code == 201, version.text
            with sqlite3.connect(database) as db:
                before = db.execute("SELECT COUNT(*) FROM case_versions").fetchone()[0]
            result = await client.post(f"/ui/projects/{project}/cases/{case}/settings", json={"expected_head": version.json()["id"], "limits": limits}, headers={**headers, "Idempotency-Key": "invalid"})
            assert result.status_code == 422, result.text
            with sqlite3.connect(database) as db:
                assert db.execute("SELECT COUNT(*) FROM case_versions").fetchone()[0] == before
                assert db.execute("SELECT latest_draft_version_id FROM automation_cases WHERE case_id=?", (case,)).fetchone()[0] == version.json()["id"]
    asyncio.run(scenario())


@pytest.mark.parametrize("scope",[None,False,[],{}])
def test_healing_scope_must_be_a_string(scope):
    with pytest.raises(SettingsRejected):
        parse_case_settings({"target_kind":"web","healing_policy":{**POLICY,"scope":scope}},uuid4())


@pytest.mark.parametrize("section,value",[("limits",[]),("limits",None),("healing_policy",[]),("healing_policy",None)])
def test_malformed_settings_sections_are_rejected_without_writing(ux_app,section,value):
    app,project,database=ux_app
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://127.0.0.1") as client:
            headers=await session(client,project)
            created=await client.post(f"/api/v1/projects/{project}/cases",json={"name":"Malformed sections"},headers=headers)
            case=created.json()["case_id"]
            version=await client.post(f"/api/v1/projects/{project}/cases/{case}/versions",json={"definition":{},"settings":{"target_kind":"web"}},headers={**headers,"Idempotency-Key":"initial"})
            assert version.status_code==201
            result=await client.post(f"/ui/projects/{project}/cases/{case}/settings",json={"expected_head":version.json()["id"],section:value},headers={**headers,"Idempotency-Key":"invalid"})
            assert result.status_code==422,result.text
            with sqlite3.connect(database) as db:
                assert db.execute("SELECT COUNT(*) FROM case_versions WHERE case_id=?",(case,)).fetchone()[0]==1
                assert db.execute("SELECT latest_draft_version_id FROM automation_cases WHERE case_id=?",(case,)).fetchone()[0]==version.json()["id"]
    asyncio.run(scenario())
