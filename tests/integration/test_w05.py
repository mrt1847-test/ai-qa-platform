"""W05-01: canonical JSON hash and step/check projection in one transaction."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from uuid import UUID

import httpx

from aiqa.contracts.cases import CaseDefinition, CheckSpec, PathPolicy, StepSpec
from aiqa.domain.hashing import SCHEMA_VERSION, canonical_hash, content_body
from aiqa.domain.versions import ensure_projection_tables, persist_projection, verification_digest
from aiqa.store.models import SecretRef

_SECRET = "plain-secret-not-in-content-hash"


def _point_definition(expected: str, point: tuple[int, int] | None) -> CaseDefinition:
    return CaseDefinition(
        raw_text="pay the invoice",
        objective="pay",
        preconditions=("logged in",),
        variables={"amount": "1.10"},
        secret_refs={
            "login": SecretRef(
                project_id=UUID("22222222-2222-4222-8222-222222222222"),
                ref_id=UUID("33333333-3333-4333-8333-333333333333"),
                revision=1,
            )
        },
        steps=(
            StepSpec(
                id="step-1",
                instruction="press pay",
                expected=(CheckSpec(id="check-1", kind="text", expected=expected),),
                point=point,
            ),
        ),
        final_expected=(CheckSpec(id="final-1", kind="text", expected="receipt visible"),),
        path_policy=PathPolicy(must_use=("pay",), forbidden=("cancel",)),
    )


def test_w05_01(tmp_path: Path) -> None:
    assert callable(canonical_hash)
    assert callable(verification_digest)
    left = {"z": 1, "a": {"b": 2, "a": "가"}}
    right = {"a": {"a": "가", "b": 2}, "z": 1}
    first = canonical_hash(left, SCHEMA_VERSION)
    second = canonical_hash(right, SCHEMA_VERSION)
    assert first.startswith("sha256:") and len(first) == 71

    nan_rejected = False
    try:
        canonical_hash({"value": float("nan")}, SCHEMA_VERSION)
    except ValueError:
        nan_rejected = True
    try:
        canonical_hash({"value": float("inf")}, SCHEMA_VERSION)
    except ValueError:
        pass
    else:
        nan_rejected = False

    excluded_left = content_body(
        {
            "objective": "pay",
            "secret": _SECRET,
            "name": "A",
            "tags": ["one"],
            "tc_reference": "TC-1",
            "availability": "ready",
        }
    )
    excluded_right = content_body(
        {
            "tags": ["two"],
            "name": "B",
            "availability": "missing",
            "tc_reference": "TC-2",
            "secret": "another-secret-value",
            "objective": "pay",
        }
    )
    assert canonical_hash(excluded_left, SCHEMA_VERSION) == canonical_hash(excluded_right, SCHEMA_VERSION)
    assert _SECRET not in str(excluded_left)
    assert canonical_hash({"amount": "1.10"}, SCHEMA_VERSION) != canonical_hash(
        {"amount": "1.1"}, SCHEMA_VERSION
    )

    original = _point_definition("balance updated", (10, 20))
    moved = _point_definition("balance updated", (80, 90))
    changed = _point_definition("balance mismatch", (10, 20))
    original_digest = verification_digest(original)
    assert verification_digest(moved) == original_digest

    database = tmp_path / "projection.sqlite"
    connection = sqlite3.connect(database)
    connection.isolation_level = None
    connection.execute("PRAGMA foreign_keys=ON")
    ensure_projection_tables(connection)
    connection.execute("BEGIN")
    persist_projection(connection, "ver-open", original)
    inside = connection.execute("SELECT COUNT(*) FROM step_projections").fetchone()
    connection.execute("ROLLBACK")
    after = connection.execute("SELECT COUNT(*) FROM definition_documents").fetchone()
    assert inside is not None and int(inside[0]) == 1
    assert after is not None and int(after[0]) == 0

    connection.execute("BEGIN")
    persist_projection(connection, "ver-1", original)
    persist_projection(connection, "ver-2", moved)
    persist_projection(connection, "ver-3", changed)
    connection.execute("COMMIT")
    hashes = {
        row[0]: row[1]
        for row in connection.execute("SELECT version_id, semantic_hash FROM step_projections")
    }
    connection.close()
    assert hashes["ver-1"] == hashes["ver-2"]
    assert hashes["ver-1"] != hashes["ver-3"]
    assert _SECRET.encode() not in database.read_bytes()

    observed = {
        "key_order_same_hash": first == second,
        "nan_rejected": nan_rejected,
        "expected_change_new_digest": verification_digest(changed) != original_digest,
    }
    assert observed == {
        "key_order_same_hash": True,
        "nan_rejected": True,
        "expected_change_new_digest": True,
    }


def _version_body(expected_head: str | None, parent: str | None = None, branch: bool = False) -> dict[str, object]:
    return {
        "definition": {
            "raw_text": "pay",
            "objective": "pay",
            "preconditions": ["logged in"],
            "variables": {"amount": "1.10"},
            "secret_refs": {},
            "steps": [
                {
                    "id": "step-1",
                    "instruction": "press pay",
                    "expected": [{"id": "check-1", "kind": "text", "expected": "ok"}],
                }
            ],
            "final_expected": [],
            "path_policy": {"must_use": ["pay"], "forbidden": []},
        },
        "settings": {"target_kind": "web"},
        "recorded_steps": [],
        "parent_version_id": parent,
        "base_version_id": None,
        "reason": "draft",
        "expected_head": expected_head,
        "branch": branch,
    }


def test_w05_02(tmp_path: Path) -> None:
    from aiqa.api.app import create_app
    from aiqa.api.cases import install_cases
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.domain.versions import save_case_revision
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    assert callable(save_case_revision)
    root = tmp_path / "runtime"
    app = create_app(
        load_settings(
            {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
        )
    )
    install_cases(app)
    actor = Actor(
        actor_id=UUID("11111111-1111-4111-8111-111111111111"),
        project_scope=None,
        is_local_owner=True,
    )
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(actor, ProjectCreate("A", "case-proj", "a", "web"))
    store.close()
    origin = "http://127.0.0.1:8000"
    result = asyncio.run(_case_http(app, origin, project.project_id))
    created = result["created"]
    first = result["first"]
    second = result["second"]
    stale = result["stale"]
    foreign = result["foreign"]
    ambiguous = result["ambiguous"]
    branch = result["branch"]
    assert created.status_code == 201, created.text
    assert created.json()["tc_reference"] is None
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert ambiguous.status_code == 201, ambiguous.text
    assert any(item["code"] == "DEFINITION_AMBIGUOUS" for item in ambiguous.json()["readiness"]["reasons"])
    assert branch.status_code == 201, branch.text
    database = root / "db" / "aiqa.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        head = connection.execute(
            "SELECT latest_draft_version_id, tc_reference FROM automation_cases WHERE case_id = ?",
            (created.json()["case_id"],),
        ).fetchone()
        denied = False
        try:
            connection.execute(
                "UPDATE case_versions SET definition_json = ? WHERE version_id = ?",
                ("changed", first.json()["id"]),
            )
        except sqlite3.IntegrityError:
            denied = True
    assert head is not None
    assert head[0] == ambiguous.json()["id"]
    assert head[0] != branch.json()["id"]
    assert head[1] is None
    observed = {
        "null_tc_saved": first.status_code == 201 and head[1] is None,
        "stale_head_status": stale.status_code,
        "foreign_parent_denied": foreign.status_code == 422,
        "content_update_denied": denied,
    }
    assert observed == {
        "null_tc_saved": True,
        "stale_head_status": 409,
        "foreign_parent_denied": True,
        "content_update_denied": True,
    }


async def _case_http(app: object, origin: str, project_id: UUID) -> dict[str, httpx.Response]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        issued = await client.post(
            "/api/v1/session/nonces",
            json={"origin": origin, "project_id": str(project_id)},
            headers={"Idempotency-Key": "case-nonce", "Origin": origin},
        )
        booted = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": issued.json()["nonce"]},
            headers={"Idempotency-Key": "case-boot", "Origin": origin},
        )
        client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
        headers = {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"]}
        created = await client.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": "Checkout", "tc_reference": None},
            headers={**headers, "Idempotency-Key": "case-create"},
        )
        case_id = created.json()["case_id"]
        other = await client.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": "Other", "tc_reference": None},
            headers={**headers, "Idempotency-Key": "case-other"},
        )
        first = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
            json=_version_body(None),
            headers={**headers, "Idempotency-Key": "case-v1"},
        )
        second = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
            json=_version_body(first.json()["id"]),
            headers={**headers, "Idempotency-Key": "case-v2"},
        )
        stale = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
            json=_version_body(first.json()["id"]),
            headers={**headers, "Idempotency-Key": "case-stale"},
        )
        foreign = await client.post(
            f"/api/v1/projects/{project_id}/cases/{other.json()['case_id']}/versions",
            json=_version_body(None, parent=first.json()["id"]),
            headers={**headers, "Idempotency-Key": "case-foreign"},
        )
        ambiguous_body = _version_body(second.json().get("id"))
        ambiguous_body["definition"]["objective"] = ""
        ambiguous = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
            json=ambiguous_body,
            headers={**headers, "Idempotency-Key": "case-ambiguous"},
        )
        branch = await client.post(
            f"/api/v1/projects/{project_id}/cases/{case_id}/versions",
            json=_version_body(None, parent=first.json()["id"], branch=True),
            headers={**headers, "Idempotency-Key": "case-branch"},
        )
    return {
        "created": created,
        "first": first,
        "second": second,
        "stale": stale,
        "foreign": foreign,
        "ambiguous": ambiguous,
        "branch": branch,
    }


def test_w05_03() -> None:
    from dataclasses import FrozenInstanceError
    from uuid import uuid4

    from aiqa.contracts.cases import CaseDefinition, CaseVersion, CheckSpec, PathPolicy, ReadinessFacts, StepSpec
    from aiqa.domain.readiness import compute_case_readiness, draft_after_meaning_edit, same_source_rebuild

    project_id = uuid4()
    case_id = uuid4()
    package_id = uuid4()
    approval_id = uuid4()
    ambiguous = _case_version(project_id, case_id, _definition(""), None, None, "input")
    bare = _case_version(project_id, case_id, _definition("pay"), None, None, "input")
    candidate = _case_version(project_id, case_id, _definition("pay"), package_id, None, "recorded")
    approved = _case_version(project_id, case_id, _definition("pay"), package_id, approval_id, "recorded")
    draft = compute_case_readiness(ambiguous, ReadinessFacts())
    missing_package = compute_case_readiness(bare, ReadinessFacts())
    unapproved = compute_case_readiness(
        candidate,
        ReadinessFacts(package_ready=True, package_valid=True),
    )
    formal = compute_case_readiness(
        approved,
        ReadinessFacts(
            package_ready=True,
            package_valid=True,
            evidence_complete=True,
            trial_present=True,
            trial_clean=True,
            trial_passed=True,
            review_complete=True,
            approval_valid=True,
        ),
    )
    edited = draft_after_meaning_edit(approved, _definition("pay", expected="changed"))
    rebuilt = same_source_rebuild(approved)
    try:
        approved.replay_package_id = None  # type: ignore[misc]
        frozen = False
    except FrozenInstanceError:
        frozen = True
    observed = {
        "draft_save_allowed": draft.saved,
        "no_package_trial": missing_package.replayable,
        "unapproved_trial": unapproved.replayable,
        "unapproved_formal": unapproved.formal_runnable,
        "edited_package": edited.replay_package_id,
    }
    assert observed == {
        "draft_save_allowed": True,
        "no_package_trial": False,
        "unapproved_trial": True,
        "unapproved_formal": False,
        "edited_package": None,
    }
    assert draft.recordable is False
    assert any(reason.code == "DEFINITION_AMBIGUOUS" for reason in draft.reasons)
    assert any(reason.code == "PACKAGE_MISSING" for reason in missing_package.reasons)
    assert any(reason.code == "APPROVAL_MISSING" for reason in unapproved.reasons)
    assert formal.formal_runnable is True
    assert formal.reasons == ()
    assert edited.creation_kind == "edit"
    assert edited.rebuild is False
    assert edited.approval_id is None
    assert edited.verification_digest != approved.verification_digest
    assert approved.replay_package_id == package_id
    assert approved.approval_id == approval_id
    assert rebuilt.rebuild is True
    assert rebuilt.creation_kind == "recorded"
    assert rebuilt.verification_digest == approved.verification_digest
    assert rebuilt.replay_package_id is None
    assert frozen is True


def test_w05_04(tmp_path: Path) -> None:
    from aiqa.api.app import create_app
    from aiqa.api.tcs import install_tcs
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.domain.tcs import save_tc_revision, set_tc_reference
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    assert callable(save_tc_revision)
    assert callable(set_tc_reference)
    root = tmp_path / "runtime"
    app = create_app(
        load_settings(
            {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
        )
    )
    install_tcs(app)
    owner = Actor(
        actor_id=UUID("11111111-1111-4111-8111-111111111111"),
        project_scope=None,
        is_local_owner=True,
    )
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        home = create_project(owner, ProjectCreate("A", "tc-home", "a", "web"))
        other = create_project(owner, ProjectCreate("B", "tc-other", "b", "web"))
    store.close()
    result = asyncio.run(_tc_http(app, root / "db" / "aiqa.sqlite", home.project_id, other.project_id))
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        versions = connection.execute(
            "SELECT COUNT(*), MIN(content_hash) FROM case_versions WHERE case_id = ?",
            (result["case_id"],),
        ).fetchone()
        approval = connection.execute(
            "SELECT current_approval_id, latest_draft_version_id, tc_reference FROM automation_cases WHERE case_id = ?",
            (result["case_id"],),
        ).fetchone()
    assert versions is not None and approval is not None
    assert result["linked"].status_code == 200, result["linked"].text
    assert result["linked"].json()["tc_reference"] == result["first_tc"]
    assert result["edited"].status_code == 201, result["edited"].text
    assert result["edited"].json()["id"] != result["first_tc"]
    assert result["pinned_after_edit"] == result["first_tc"]
    assert result["archived"].status_code == 200, result["archived"].text
    assert result["unlinked"].status_code == 200, result["unlinked"].text
    assert approval[0] == result["approval_id"]
    assert approval[1] == result["case_version_id"]
    assert approval[2] is None
    assert versions[1] == result["content_hash"]
    observed = {
        "reference_only_new_case_versions": int(versions[0]) - result["versions_before"],
        "approval_unchanged": approval[0] == result["approval_id"],
        "foreign_tc_reference_denied": result["foreign"].status_code == 404,
    }
    assert observed == {
        "reference_only_new_case_versions": 0,
        "approval_unchanged": True,
        "foreign_tc_reference_denied": True,
    }


async def _tc_http(app: object, database: Path, home: UUID, other: UUID) -> dict[str, object]:
    origin = "http://127.0.0.1:8000"
    approval_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        home_session = await _session(client, origin, home, "home")
        other_session = await _session(client, origin, other, "other")
        created = await _send(
            client,
            home_session,
            "POST",
            f"/api/v1/projects/{home}/cases",
            {"name": "Checkout", "tc_reference": None},
            "tc-case",
        )
        case_id = created.json()["case_id"]
        version = await _send(
            client,
            home_session,
            "POST",
            f"/api/v1/projects/{home}/cases/{case_id}/versions",
            _version_body(None),
            "tc-case-v1",
        )
        with sqlite3.connect(database) as connection:
            _approval_fixture(connection, case_id, approval_id)
            connection.execute(
                "UPDATE automation_cases SET current_approval_id = ? WHERE case_id = ?",
                (approval_id, case_id),
            )
            before = connection.execute(
                "SELECT COUNT(*), content_hash FROM case_versions WHERE case_id = ?",
                (case_id,),
            ).fetchone()
        assert before is not None
        tc = await _send(
            client,
            home_session,
            "POST",
            f"/api/v1/projects/{home}/tcs",
            {"name": "Pay", "body": {"title": "pay", "steps": ["press pay"]}, "reason": "create"},
            "tc-create",
        )
        first_tc = tc.json()["id"]
        linked = await _send(
            client,
            home_session,
            "PUT",
            f"/api/v1/projects/{home}/cases/{case_id}/tc-reference",
            {"tc_version_id": first_tc},
            "tc-link",
        )
        edited = await _send(
            client,
            home_session,
            "POST",
            f"/api/v1/projects/{home}/tcs/{tc.json()['tc_id']}/versions",
            {"body": {"title": "pay", "steps": ["press pay twice"]}, "reason": "edit"},
            "tc-edit",
        )
        pinned = await _send(
            client,
            home_session,
            "GET",
            f"/api/v1/projects/{home}/cases/{case_id}/tc-reference",
            None,
            "tc-read",
        )
        archived = await _send(
            client,
            home_session,
            "POST",
            f"/api/v1/projects/{home}/tcs/{tc.json()['tc_id']}/archive",
            {},
            "tc-archive",
        )
        unlinked = await _send(
            client,
            home_session,
            "DELETE",
            f"/api/v1/projects/{home}/cases/{case_id}/tc-reference",
            None,
            "tc-unlink",
        )
        foreign_tc = await _send(
            client,
            other_session,
            "POST",
            f"/api/v1/projects/{other}/tcs",
            {"name": "Other", "body": {"title": "other", "steps": ["wait"]}, "reason": "create"},
            "tc-foreign-create",
        )
        foreign = await _send(
            client,
            home_session,
            "PUT",
            f"/api/v1/projects/{home}/cases/{case_id}/tc-reference",
            {"tc_version_id": foreign_tc.json()["id"]},
            "tc-foreign-link",
        )
        cloned = await _send(
            client,
            home_session,
            "POST",
            f"/api/v1/projects/{home}/tcs/{tc.json()['tc_id']}/clone",
            {},
            "tc-clone",
        )
    return {
        "case_id": case_id,
        "approval_id": approval_id,
        "case_version_id": version.json()["id"],
        "content_hash": before[1],
        "versions_before": int(before[0]),
        "first_tc": first_tc,
        "linked": linked,
        "edited": edited,
        "pinned_after_edit": pinned.json().get("tc_reference"),
        "archived": archived,
        "unlinked": unlinked,
        "foreign": foreign,
        "cloned": cloned,
    }


async def _session(client: httpx.AsyncClient, origin: str, project_id: UUID, name: str) -> dict[str, str]:
    issued = await client.post(
        "/api/v1/session/nonces",
        json={"origin": origin, "project_id": str(project_id)},
        headers={"Idempotency-Key": f"{name}-nonce", "Origin": origin},
    )
    booted = await client.post(
        "/api/v1/session/bootstrap",
        json={"nonce": issued.json()["nonce"]},
        headers={"Idempotency-Key": f"{name}-boot", "Origin": origin},
    )
    return {
        "Origin": origin,
        "X-CSRF-Token": booted.json()["csrf_token"],
        "cookie": booted.cookies["aiqa_session"],
    }


async def _send(
    client: httpx.AsyncClient,
    session: dict[str, str],
    method: str,
    path: str,
    payload: dict[str, object] | None,
    key: str,
) -> httpx.Response:
    client.cookies.set("aiqa_session", session["cookie"])
    headers = {"Origin": session["Origin"], "X-CSRF-Token": session["X-CSRF-Token"], "Idempotency-Key": key}
    if method == "GET":
        return await client.get(path, headers=headers)
    if method == "DELETE":
        return await client.delete(path, headers=headers)
    if method == "PUT":
        return await client.put(path, json=payload, headers=headers)
    if method == "PATCH":
        return await client.patch(path, json=payload, headers=headers)
    return await client.post(path, json=payload, headers=headers)


def _definition(objective: str, expected: str = "ok") -> CaseDefinition:
    return CaseDefinition(
        raw_text=objective,
        objective=objective,
        preconditions=("logged in",),
        variables={"amount": "1.10"},
        secret_refs={},
        steps=(StepSpec("step-1", "press pay", (CheckSpec("check-1", "text", expected),)),),
        final_expected=(),
        path_policy=PathPolicy(("pay",), ()),
    )


def _case_version(
    project_id: UUID,
    case_id: UUID,
    definition: CaseDefinition,
    package_id: UUID | None,
    approval_id: UUID | None,
    creation_kind: str,
) -> CaseVersion:
    from uuid import uuid4

    from aiqa.contracts.cases import CaseVersion
    from aiqa.domain.hashing import SCHEMA_VERSION, canonical_hash
    from aiqa.domain.versions import verification_digest

    digest = verification_digest(definition)
    return CaseVersion(
        id=uuid4(),
        project_id=project_id,
        case_id=case_id,
        definition=definition,
        replay_package_id=package_id,
        approval_id=approval_id,
        creation_kind=creation_kind,
        content_hash=canonical_hash({"verification_digest": digest}, SCHEMA_VERSION),
        verification_digest=digest,
    )


def test_w05_05(tmp_path: Path) -> None:
    from aiqa.api.app import create_app
    from aiqa.api.resources import install_resources
    from aiqa.config import load_settings
    from aiqa.domain.datasets import save_dataset_revision
    from aiqa.domain.environments import save_environment_revision
    from aiqa.domain.model_bindings import save_model_binding_revision
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.security.secrets import discard_os_secret
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate, SecretRef

    assert callable(save_dataset_revision)
    assert callable(save_environment_revision)
    assert callable(save_model_binding_revision)
    root = tmp_path / "runtime"
    app = create_app(
        load_settings(
            {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
        )
    )
    install_resources(app)
    owner = Actor(
        actor_id=UUID("11111111-1111-4111-8111-111111111111"),
        project_scope=None,
        is_local_owner=True,
    )
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        home = create_project(owner, ProjectCreate("A", "asset-home", "a", "web"))
        other = create_project(owner, ProjectCreate("B", "asset-other", "b", "web"))
    store.close()
    created: list[SecretRef] = []
    try:
        result = asyncio.run(_asset_http(app, home.project_id, other.project_id, created))
        with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
            immutable = False
            try:
                connection.execute(
                    "UPDATE binding_revisions SET model = ? WHERE revision_id = ?",
                    ("changed", result["binding_id"]),
                )
            except sqlite3.IntegrityError:
                immutable = True
            stored_model = connection.execute(
                "SELECT model FROM binding_revisions WHERE revision_id = ?",
                (result["binding_id"],),
            ).fetchone()
        assert stored_model is not None and stored_model[0] == "none"
        assert _HOME_SECRET.encode() not in (root / "db" / "aiqa.sqlite").read_bytes()
        observed = {
            "invalid_rows_status": result["invalid"].status_code,
            "foreign_secret_denied": result["foreign"].status_code == 404,
            "old_revisions_unchanged": result["old_data"].json()["content_hash"] == result["first_data_hash"]
            and result["old_env"].json()["locale"] == "ko-KR",
            "model_binding_revisions_immutable": immutable,
        }
        assert observed == {
            "invalid_rows_status": 422,
            "foreign_secret_denied": True,
            "old_revisions_unchanged": True,
            "model_binding_revisions_immutable": True,
        }
    finally:
        for ref in created:
            discard_os_secret(ref)


_HOME_SECRET = "dataset-secret-w05-05-VALUE-9f3a"
_OTHER_SECRET = "dataset-secret-w05-05-VALUE-c2e1"


async def _asset_http(app: object, home: UUID, other: UUID, created: list[object]) -> dict[str, object]:
    from aiqa.store.models import SecretRef

    origin = "http://127.0.0.1:8000"
    schema = {"columns": [{"name": "amount", "type": "string"}]}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        home_session = await _session(client, origin, home, "asset-home")
        other_session = await _session(client, origin, other, "asset-other")
        home_secret = await _send(
            client,
            home_session,
            "POST",
            f"/api/v1/projects/{home}/secret-refs",
            {"name": "home-key", "value": _HOME_SECRET},
            "asset-secret-home",
        )
        other_secret = await _send(
            client,
            other_session,
            "POST",
            f"/api/v1/projects/{other}/secret-refs",
            {"name": "other-key", "value": _OTHER_SECRET},
            "asset-secret-other",
        )
        home_ref = SecretRef(home, UUID(home_secret.json()["ref_id"]), int(home_secret.json()["revision"]))
        other_ref = SecretRef(other, UUID(other_secret.json()["ref_id"]), int(other_secret.json()["revision"]))
        created.append(home_ref)
        created.append(other_ref)
        first = await _send(
            client,
            home_session,
            "POST",
            f"/api/v1/projects/{home}/datasets",
            {
                "name": "Payments",
                "row_schema": schema,
                "rows": [{"id": "row-1", "values": {"amount": "1.10"}}],
                "secret_ref": _ref_json(home_ref),
            },
            "asset-data-1",
        )
        invalid = await _send(
            client,
            home_session,
            "POST",
            f"/api/v1/projects/{home}/datasets/{first.json()['dataset_id']}/revisions",
            {"row_schema": schema, "rows": [{"id": "row-1", "values": {"amount": 1}}], "secret_ref": _ref_json(home_ref)},
            "asset-data-bad",
        )
        foreign = await _send(
            client,
            home_session,
            "POST",
            f"/api/v1/projects/{home}/datasets/{first.json()['dataset_id']}/revisions",
            {
                "row_schema": schema,
                "rows": [{"id": "row-1", "values": {"amount": "1.10"}}],
                "secret_ref": _ref_json(other_ref),
            },
            "asset-data-foreign",
        )
        second = await _send(
            client,
            home_session,
            "POST",
            f"/api/v1/projects/{home}/datasets/{first.json()['dataset_id']}/revisions",
            {
                "row_schema": schema,
                "rows": [{"id": "row-1", "values": {"amount": "2.00"}}],
                "secret_ref": _ref_json(home_ref),
            },
            "asset-data-2",
        )
        old_data = await _send(
            client,
            home_session,
            "GET",
            f"/api/v1/projects/{home}/datasets/{first.json()['dataset_id']}/revisions/{first.json()['id']}",
            None,
            "asset-data-read",
        )
        env = await _send(
            client,
            home_session,
            "POST",
            f"/api/v1/projects/{home}/environments",
            _env_body("ko-KR"),
            "asset-env-1",
        )
        await _send(
            client,
            home_session,
            "POST",
            f"/api/v1/projects/{home}/environments/{env.json()['environment_id']}/revisions",
            _env_body("en-US"),
            "asset-env-2",
        )
        old_env = await _send(
            client,
            home_session,
            "GET",
            f"/api/v1/projects/{home}/environments/{env.json()['environment_id']}/revisions/{env.json()['id']}",
            None,
            "asset-env-read",
        )
        binding = await _send(
            client,
            home_session,
            "POST",
            f"/api/v1/projects/{home}/model-bindings",
            {
                "name": "Verifier",
                "role": "verification",
                "provider": "local",
                "endpoint_kind": "loopback",
                "endpoint": "http://127.0.0.1:9",
                "model": "none",
                "key_ref": _ref_json(home_ref),
                "prompt_hash": "sha256:" + ("ab" * 32),
                "tariff_id": "tariff-1",
                "compatibility_status": "unchecked",
            },
            "asset-model-1",
        )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert env.status_code == 201, env.text
    assert binding.status_code == 201, binding.text
    return {
        "invalid": invalid,
        "foreign": foreign,
        "old_data": old_data,
        "old_env": old_env,
        "first_data_hash": first.json()["content_hash"],
        "binding_id": binding.json()["id"],
    }


def _ref_json(ref: object) -> dict[str, object]:
    from aiqa.store.models import SecretRef

    assert isinstance(ref, SecretRef)
    return {"project_id": str(ref.project_id), "ref_id": str(ref.ref_id), "revision": ref.revision}


def _env_body(locale: str) -> dict[str, object]:
    return {
        "name": "Local web",
        "target_kind": "web",
        "allowlist": ["http://127.0.0.1"],
        "viewport": {"width": 1280, "height": 720},
        "locale": locale,
        "reset_policy": "clear",
        "limits": {"timeout_seconds": 600, "max_actions": 50, "budget": "2.00", "currency": "USD"},
    }


def test_w05_06(tmp_path: Path) -> None:
    from aiqa.api.app import create_app
    from aiqa.api.catalog import install_taxonomy
    from aiqa.config import load_settings
    from aiqa.domain.catalog import archive_case, clone_case, list_cases
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate

    assert callable(list_cases) and callable(clone_case) and callable(archive_case)
    root = tmp_path / "runtime"
    app = create_app(
        load_settings(
            {"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}
        )
    )
    install_taxonomy(app)
    owner = Actor(
        actor_id=UUID("11111111-1111-4111-8111-111111111111"),
        project_scope=None,
        is_local_owner=True,
    )
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("A", "catalog", "a", "web"))
    store.close()
    result = asyncio.run(_catalog_http(app, root / "db" / "aiqa.sqlite", project.project_id, owner.actor_id))
    with sqlite3.connect(root / "db" / "aiqa.sqlite") as connection:
        history = connection.execute(
            "SELECT COUNT(*), MIN(content_hash) FROM case_versions WHERE case_id = ?",
            (result["clone_id"],),
        ).fetchone()
        source_versions = connection.execute(
            "SELECT COUNT(*) FROM case_versions WHERE case_id = ?",
            (result["source_id"],),
        ).fetchone()
        source_approval = connection.execute(
            "SELECT current_approval_id, archived_at FROM automation_cases WHERE case_id = ?",
            (result["source_id"],),
        ).fetchone()
    assert history is not None and source_versions is not None and source_approval is not None
    assert result["cycle"].status_code == 422, result["cycle"].text
    assert result["page"].status_code == 200, result["page"].text
    assert result["page"].json()["items"][0]["name"] == "Alpha"
    assert result["page"].json()["next_cursor"]
    assert result["filtered"].json()["items"][0]["case_id"] == result["source_id"]
    assert int(history[0]) == 1
    assert history[1] == result["source_hash"]
    assert int(source_versions[0]) == result["source_versions"]
    assert source_approval[0] == result["approval_id"]
    assert source_approval[1] is None
    observed = {
        "clone_approvals": 0 if result["cloned"].json()["current_approval_id"] is None else 1,
        "archived_history_readable": result["archived_list"].status_code == 200
        and result["archived_list"].json()["items"][0]["case_id"] == result["clone_id"]
        and int(history[0]) == 1,
        "active_recording_archive_status": result["blocked"].status_code,
    }
    assert observed == {
        "clone_approvals": 0,
        "archived_history_readable": True,
        "active_recording_archive_status": 409,
    }


async def _catalog_http(app: object, database: Path, project_id: UUID, actor_id: UUID) -> dict[str, object]:
    origin = "http://127.0.0.1:8000"
    approval_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        session = await _session(client, origin, project_id, "catalog")
        parent = await _send(
            client, session, "POST", f"/api/v1/projects/{project_id}/folders", {"name": "Parent"}, "cat-folder"
        )
        child = await _send(
            client,
            session,
            "POST",
            f"/api/v1/projects/{project_id}/folders",
            {"name": "Child", "parent_folder_id": parent.json()["folder_id"]},
            "cat-child",
        )
        cycle = await _send(
            client,
            session,
            "PATCH",
            f"/api/v1/projects/{project_id}/folders/{parent.json()['folder_id']}",
            {"parent_folder_id": child.json()["folder_id"]},
            "cat-cycle",
        )
        tag = await _send(client, session, "POST", f"/api/v1/projects/{project_id}/tags", {"name": "pay"}, "cat-tag")
        created = await _send(
            client,
            session,
            "POST",
            f"/api/v1/projects/{project_id}/cases",
            {"name": "Alpha", "tc_reference": None},
            "cat-case",
        )
        source_id = created.json()["case_id"]
        version = await _send(
            client,
            session,
            "POST",
            f"/api/v1/projects/{project_id}/cases/{source_id}/versions",
            _version_body(None),
            "cat-version",
        )
        patched = await _send(
            client,
            session,
            "PATCH",
            f"/api/v1/projects/{project_id}/cases/{source_id}",
            {
                "folder_id": parent.json()["folder_id"],
                "tags": ["pay"],
                "priority": "high",
                "assignee_id": str(actor_id),
                "expected_revision": 1,
            },
            "cat-meta",
        )
        await _send(
            client,
            session,
            "POST",
            f"/api/v1/projects/{project_id}/cases",
            {"name": "Zulu", "tc_reference": None},
            "cat-other",
        )
        with sqlite3.connect(database) as connection:
            _approval_fixture(connection, source_id, approval_id)
            connection.execute(
                "UPDATE automation_cases SET current_approval_id = ? WHERE case_id = ?",
                (approval_id, source_id),
            )
            before = connection.execute(
                "SELECT COUNT(*) FROM case_versions WHERE case_id = ?",
                (source_id,),
            ).fetchone()
        assert before is not None
        page = await _send(
            client,
            session,
            "GET",
            f"/api/v1/projects/{project_id}/cases?sort=name&limit=1",
            None,
            "cat-page",
        )
        filtered = await _send(
            client,
            session,
            "GET",
            f"/api/v1/projects/{project_id}/cases?q=Alpha&folder_id={parent.json()['folder_id']}&tag=pay&priority=high",
            None,
            "cat-filter",
        )
        cloned = await _send(
            client,
            session,
            "POST",
            f"/api/v1/projects/{project_id}/cases/{source_id}/clone",
            {"name": "Alpha copy"},
            "cat-clone",
        )
        archived = await _send(
            client,
            session,
            "POST",
            f"/api/v1/projects/{project_id}/cases/{cloned.json()['case_id']}/archive",
            {"expected_revision": cloned.json()["lock_version"]},
            "cat-archive",
        )
        archived_list = await _send(
            client,
            session,
            "GET",
            f"/api/v1/projects/{project_id}/cases?archived=true",
            None,
            "cat-archived",
        )
        with sqlite3.connect(database) as connection:
            connection.execute(
                """
                INSERT INTO case_open_recordings (project_id, recording_id, case_id, status)
                VALUES (?, ?, ?, 'active')
                """,
                (str(project_id), "rec-open", source_id),
            )
        assert patched.status_code == 200, patched.text
        blocked = await _send(
            client,
            session,
            "POST",
            f"/api/v1/projects/{project_id}/cases/{source_id}/archive",
            {"expected_revision": patched.json()["lock_version"]},
            "cat-blocked",
        )
    assert parent.status_code == 201, parent.text
    assert tag.status_code == 201, tag.text
    assert version.status_code == 201, version.text
    assert patched.status_code == 200, patched.text
    assert archived.status_code == 200, archived.text
    return {
        "cycle": cycle,
        "page": page,
        "filtered": filtered,
        "cloned": cloned,
        "archived_list": archived_list,
        "blocked": blocked,
        "source_id": source_id,
        "clone_id": cloned.json()["case_id"],
        "source_hash": version.json()["content_hash"],
        "source_versions": int(before[0]),
        "approval_id": approval_id,
    }


def _approval_fixture(connection: sqlite3.Connection, case_id: str, approval_id: str) -> None:
    """Build real same-case review and approval rows before assigning a pointer."""
    from uuid import uuid4

    connection.execute("PRAGMA foreign_keys=ON")
    project, version, content_hash = connection.execute(
        "SELECT project_id,version_id,content_hash FROM case_versions WHERE case_id=? ORDER BY revision DESC LIMIT 1",
        (case_id,),
    ).fetchone()
    review = str(uuid4())
    connection.execute(
        "INSERT INTO reviews VALUES (?,?,?,?,?,NULL,NULL,'evidence',NULL,1)",
        (project, review, case_id, version, content_hash),
    )
    connection.execute(
        "INSERT INTO approval_events VALUES (?,?,?,?,?,'approved',NULL,?,'evidence','fixture')",
        (project, approval_id, case_id, version, review, content_hash),
    )
