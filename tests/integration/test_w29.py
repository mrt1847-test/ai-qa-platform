"""Package body validation. A missing mapping or a foreign source is not ready."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from aiqa.contracts.replay import ReplayPackageBody, StepMapping
from aiqa.replay.packages import validate_package_body
from aiqa.store.models import RecordingManifest


def test_w29_04(tmp_path: Path) -> None:
    import asyncio
    import sqlite3
    from dataclasses import replace
    from uuid import uuid4

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.recording.service import PreflightRejected, materialize_recording
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor

    root = tmp_path / "runtime"
    app = create_app(
        load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)})
    )
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.models import ProjectCreate

    with bind_store(store):
        project = create_project(owner, ProjectCreate("패키지", "w2904", "녹화", "web"))
    store.close()
    project_id = project.project_id
    database = root / "db" / "aiqa.sqlite"
    version_id, case_id = asyncio.run(_package_case(app, str(project_id)))
    ready_id, late_id, recording_id, job_id = uuid4(), uuid4(), uuid4(), uuid4()
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _recording(connection, str(project_id), case_id, version_id, str(recording_id))
        _manifest(connection, str(project_id), case_id, str(recording_id), str(ready_id), 1)
        _manifest(connection, str(project_id), case_id, str(recording_id), str(late_id), 2)
        connection.execute(
            """
            INSERT INTO jobs (
                project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
            ) VALUES (?, ?, 'recording', ?, NULL, 'hash', '[]', '{}', 'queued')
            """,
            (str(project_id), str(job_id), str(recording_id)),
        )
        connection.execute(
            """
            INSERT INTO attempts (project_id, attempt_id, job_id, generation, physical_key_id)
            VALUES (?, 'attempt-w2904', ?, 1, NULL)
            """,
            (str(project_id), str(job_id)),
        )
        connection.execute(
            """
            INSERT INTO artifact_refs (project_id, artifact_id, attempt_id, recording_id)
            VALUES (?, 'art-w2904', 'attempt-w2904', ?)
            """,
            (str(project_id), str(recording_id)),
        )
        connection.execute(
            """
            INSERT INTO artifact_objects (
                project_id, artifact_id, object_key, content_hash, byte_length, media_type,
                owner_id, status, acked, owner_kind, attempt_id, role, job_id, generation
            ) VALUES (?, 'art-w2904', 'art-w2904', 'hash-w2904', 4, 'image/png', ?, 'ready', 1,
                'REC', 'attempt-w2904', 'source', ?, 1)
            """,
            (str(project_id), str(recording_id), str(job_id)),
        )
    compiled = _compiled(ready_id, ("art-w2904",))
    actor = Actor(actor_id=owner.actor_id, project_scope=project_id, is_local_owner=True)
    store = app.state.open_store()
    try:
        with store.transaction() as connection:
            try:
                materialize_recording(connection, actor, project_id, ready_id, replace(compiled, ready_artifact_ids=("missing",)))
            except PreflightRejected:
                refused = True
            else:
                refused = False
        try:
            with store.transaction() as connection:
                materialize_recording(connection, actor, project_id, ready_id, compiled)
                raise RuntimeError("crash")
        except RuntimeError:
            crashed = True
        with store.transaction() as connection:
            first = materialize_recording(connection, actor, project_id, ready_id, compiled)
        with store.transaction() as connection:
            second = materialize_recording(connection, actor, project_id, ready_id, compiled)
        with store.transaction() as connection:
            materialize_recording(connection, actor, project_id, late_id, None)
        with store.transaction() as connection:
            materialize_recording(connection, actor, project_id, late_id, _compiled(late_id, ("art-w2904",)))
        deferred_failed = False
        try:
            with store.transaction() as connection:
                _dangling_version(connection, str(project_id), case_id, str(ready_id))
        except sqlite3.IntegrityError:
            deferred_failed = True
    finally:
        store.close()
    with sqlite3.connect(database) as connection:
        packages = connection.execute("SELECT COUNT(*) FROM replay_packages WHERE ready = 1").fetchone()[0]
        partial = connection.execute(
            "SELECT COUNT(*) FROM replay_packages WHERE package_id = 'missing'"
        ).fetchone()[0]
        versions = connection.execute(
            "SELECT COUNT(*) FROM case_versions WHERE source_manifest_id = ?",
            (str(ready_id),),
        ).fetchone()[0]
        late_package = connection.execute(
            """
            SELECT versions.replay_package_id
            FROM materialization_receipts AS receipts
            JOIN case_versions AS versions ON versions.version_id = receipts.produced_version_id
            WHERE receipts.manifest_id = ?
            """,
            (str(late_id),),
        ).fetchone()[0]
    observed = {
        "ready_package_count": packages,
        "partial_commit_rows": partial,
        "duplicate_manifest_versions": versions,
        "late_attach_allowed": late_package is not None,
    }
    assert refused and crashed and deferred_failed
    assert first.receipt_id == second.receipt_id and first.replayed is False and second.replayed is True
    assert observed == {
        "ready_package_count": 1,
        "partial_commit_rows": 0,
        "duplicate_manifest_versions": 1,
        "late_attach_allowed": False,
    }


def test_w29_02() -> None:
    import hashlib
    from uuid import uuid4

    from aiqa.replay.compiler import CompileRejected, CompilerRef, compile_replay_package
    from aiqa.store.models import RecordingManifest

    source_text = '"로그인"\nqa_runtime.click("#login")\nqa_runtime.fill("#name", "ada")\n'
    raw_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    manifest = RecordingManifest(
        project_id=uuid4(),
        case_id=uuid4(),
        recording_id=uuid4(),
        manifest_id=uuid4(),
        revision=1,
        kind="original",
        prior_manifest_id=None,
        input_version_hash="input-hash",
        source_artifact_hashes=f'["{raw_hash}"]',
        action_mapping="{}",
        evidence_completeness="complete",
        request_key="w2902",
        body_hash="manifest-hash",
    )
    compiled = compile_replay_package(manifest, CompilerRef("web-ipc-subset", "lock-1", source_text))
    rejected = []
    for sample in (
        'import playwright\nqa_runtime.click("#login")\n',
        'getattr(qa_runtime, "click")("#login")\n',
        'def helper():\n    return 1\nqa_runtime.click("#login")\n',
        'page.click("#login")\n',
        'qa_runtime.click(qa_runtime.fill("#name", "ada"))\n',
    ):
        try:
            compile_replay_package(
                RecordingManifest(
                    project_id=manifest.project_id,
                    case_id=manifest.case_id,
                    recording_id=manifest.recording_id,
                    manifest_id=manifest.manifest_id,
                    revision=1,
                    kind="original",
                    prior_manifest_id=None,
                    input_version_hash="input-hash",
                    source_artifact_hashes=f'["{hashlib.sha256(sample.encode("utf-8")).hexdigest()}"]',
                    action_mapping="{}",
                    evidence_completeness="complete",
                    request_key="w2902",
                    body_hash="manifest-hash",
                ),
                CompilerRef("web-ipc-subset", "lock-1", sample),
            )
        except CompileRejected:
            rejected.append(True)
    observed = {
        "unsupported_rejected": len(rejected) == 5 and all(rejected),
        "semantic_expectations_changed": compiled.expectations != ("로그인",)
        or compiled.steps[0].selector != "#login"
        or compiled.steps[1].value != "ada",
        "every_action_mapped": all(step.call.startswith("qa_runtime.") for step in compiled.steps)
        and len(compiled.steps) == 2,
    }
    assert compiled.body.compiled_hash is None
    assert observed == {
        "unsupported_rejected": True,
        "semantic_expectations_changed": False,
        "every_action_mapped": True,
    }


def test_w29_01() -> None:
    manifest_id = uuid4()
    source = RecordingManifest(
        project_id=uuid4(),
        case_id=uuid4(),
        recording_id=uuid4(),
        manifest_id=manifest_id,
        revision=1,
        kind="original",
        prior_manifest_id=None,
        input_version_hash="input-hash",
        source_artifact_hashes='["raw-source"]',
        action_mapping="{}",
        evidence_completeness="complete",
        request_key="w2901",
        body_hash="manifest-hash",
    )
    step = StepMapping("step-1", "action-1", 3)
    helper = StepMapping("helper-1", "action-2", 4)
    ready = validate_package_body(_body(source, (step, helper), ("helper-1",)), source)
    cycle = validate_package_body(
        _body(source, (step, helper), ("helper-1",), produced_version_hash="version-hash", compiled_hash="compiled"),
        source,
    )
    unmapped = validate_package_body(_body(source, (step,), ("helper-1",)), source)
    foreign = validate_package_body(
        _body(source, (step, helper), ("helper-1",), source_manifest_hash="other-hash"),
        source,
    )
    unsupported = validate_package_body(_body(source, (step, helper), ("helper-1",), runtime_ref="cuda"), source)
    observed = {
        "hash_cycle_allowed": cycle.ready,
        "unmapped_ready": unmapped.ready,
        "foreign_source_allowed": foreign.ready,
    }
    assert ready.ready is True
    assert "produced_version_hash" not in ready.body_hash and "compiled" not in ready.body_hash
    assert unsupported.ready is False
    assert observed == {
        "hash_cycle_allowed": False,
        "unmapped_ready": False,
        "foreign_source_allowed": False,
    }


def _body(
    source: RecordingManifest,
    mappings: tuple[StepMapping, ...],
    helpers: tuple[str, ...],
    source_manifest_hash: str | None = None,
    runtime_ref: str = "web",
    produced_version_hash: str | None = None,
    compiled_hash: str | None = None,
) -> ReplayPackageBody:
    from aiqa.replay.packages import _mapping_hash

    return ReplayPackageBody(
        schema_version="replay-package-v1",
        source_manifest_id=source.manifest_id,
        source_manifest_hash=source.body_hash if source_manifest_hash is None else source_manifest_hash,
        raw_source_hash="raw-source",
        approved_code_or_plan_hash="code-hash",
        runtime_ref=runtime_ref,
        compiler_ref="compiler-1",
        lock_hash="lock-hash",
        step_mapping_hash=_mapping_hash(mappings),
        mappings=mappings,
        helpers=helpers,
        produced_version_hash=produced_version_hash,
        compiled_hash=compiled_hash,
    )


async def _package_case(app: object, project_id: str) -> tuple[str, str]:
    import httpx

    origin = "http://127.0.0.1"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=origin) as client:
        issued = await client.post(
            "/api/v1/session/nonces",
            json={"origin": origin, "project_id": project_id},
            headers={"Idempotency-Key": "w2904-nonce", "Origin": origin},
        )
        booted = await client.post(
            "/api/v1/session/bootstrap",
            json={"nonce": issued.json()["nonce"]},
            headers={"Idempotency-Key": "w2904-boot", "Origin": origin},
        )
        client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])
        headers = {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"], "Idempotency-Key": "w2904-case"}
        created = await client.post(
            f"/api/v1/projects/{project_id}/cases",
            json={"name": "로그인", "tc_reference": None},
            headers=headers,
        )
        headers["Idempotency-Key"] = "w2904-version"
        version = await client.post(
            f"/api/v1/projects/{project_id}/cases/{created.json()['case_id']}/versions",
            json={"definition": _draft_definition(), "settings": {"target_kind": "web"}},
            headers=headers,
        )
    assert version.status_code == 201, version.text
    return version.json()["id"], created.json()["case_id"]


def _draft_definition() -> dict[str, object]:
    return {
        "raw_text": "",
        "objective": "",
        "preconditions": [],
        "variables": {},
        "secret_refs": {},
        "steps": [],
        "final_expected": [{"id": "exp-1", "kind": "text", "expected": ""}],
        "path_policy": {"must_use": [], "forbidden": []},
    }


def _recording(connection: object, project_id: str, case_id: str, version_id: str, recording_id: str) -> None:
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO recordings (
            project_id, case_id, recording_id, creation_kind, input_case_version_id,
            base_case_version_id, parent_recording_id, source_recording_id,
            storage_status, stop_status, completion_status, evidence_status
        ) VALUES (?, ?, ?, 'recorded', ?, NULL, NULL, NULL, 'local', 'stopped', 'completed', 'complete')
        """,
        (project_id, case_id, recording_id, version_id),
    )


def _manifest(
    connection: object, project_id: str, case_id: str, recording_id: str, manifest_id: str, revision: int
) -> None:
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO recording_manifests (
            project_id, case_id, recording_id, manifest_id, revision, kind, prior_manifest_id,
            input_version_hash, source_artifact_hashes, action_mapping, evidence_completeness,
            request_key, body_hash
        ) VALUES (?, ?, ?, ?, ?, 'original', NULL, 'input-hash', '["raw-source"]', '{}', 'complete', ?, 'manifest-hash')
        """,
        (project_id, case_id, recording_id, manifest_id, revision, manifest_id),
    )


def _compiled(manifest_id: object, artifact_ids: tuple[str, ...]):
    from uuid import UUID

    from aiqa.replay.compiler import CompiledPackage, CompiledStep
    from aiqa.replay.packages import _mapping_hash

    step = StepMapping("step-1", "action-1", 1)
    body = ReplayPackageBody(
        schema_version="replay-package-v1",
        source_manifest_id=manifest_id if isinstance(manifest_id, UUID) else UUID(str(manifest_id)),
        source_manifest_hash="manifest-hash",
        raw_source_hash="raw-source",
        approved_code_or_plan_hash="code-hash",
        runtime_ref="web",
        compiler_ref="web-ipc-subset",
        lock_hash="lock-1",
        step_mapping_hash=_mapping_hash((step,)),
        mappings=(step,),
    )
    source = RecordingManifest(
        project_id=UUID(int=0),
        case_id=UUID(int=0),
        recording_id=UUID(int=0),
        manifest_id=body.source_manifest_id,
        revision=1,
        kind="original",
        prior_manifest_id=None,
        input_version_hash="input-hash",
        source_artifact_hashes='["raw-source"]',
        action_mapping="{}",
        evidence_completeness="complete",
        request_key="w2904",
        body_hash="manifest-hash",
    )
    checked = validate_package_body(body, source)
    return CompiledPackage(
        body,
        checked.body_hash,
        artifact_ids,
        (CompiledStep("step-1", "action-1", 1, 'qa_runtime.click("#login")', "#login", ""),),
        (),
    )


def _dangling_version(connection: object, project_id: str, case_id: str, manifest_id: str) -> None:
    from uuid import uuid4

    names = [item[1] for item in connection.execute("PRAGMA table_info(case_versions)")]  # type: ignore[attr-defined]
    source = connection.execute(  # type: ignore[attr-defined]
        "SELECT * FROM case_versions WHERE case_id = ? ORDER BY revision LIMIT 1",
        (case_id,),
    ).fetchone()
    values = dict(zip(names, source, strict=True))
    values["version_id"] = str(uuid4())
    values["revision"] = 99
    values["source_manifest_id"] = manifest_id
    values["replay_package_id"] = str(uuid4())
    columns = ", ".join(names)
    connection.execute(  # type: ignore[attr-defined]
        f"INSERT INTO case_versions ({columns}) VALUES ({', '.join('?' for _ in names)})",
        tuple(values[name] for name in names),
    )


def test_w29_06(tmp_path: Path) -> None:
    import asyncio
    import sqlite3

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.store.models import Actor
    from aiqa.replay.packages import PackageStepView, stored_mapping_hash
    from aiqa.store.database import migrate_store
    from aiqa.store.models import ProjectCreate

    root = tmp_path / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(actor_id=uuid4(), project_scope=None, is_local_owner=True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("조회", "w2906", "패키지", "web"))
        other = create_project(owner, ProjectCreate("다른", "w2906b", "다른", "web"))
    store.close()
    project_id, other_id = str(project.project_id), str(other.project_id)
    bare_version, case_id = asyncio.run(_package_case(app, project_id))
    ready_version, mismatch_version, expired_version = _view_packages(root / "db" / "aiqa.sqlite", project_id, case_id, bare_version)
    bare = asyncio.run(_package_get(app, project_id, bare_version))
    ready = asyncio.run(_package_get(app, project_id, ready_version))
    mismatch = asyncio.run(_package_get(app, project_id, mismatch_version))
    expired = asyncio.run(_package_get(app, project_id, expired_version))
    denied = asyncio.run(_package_status(app, other_id, ready_version))
    page = asyncio.run(_package_page(app, project_id, case_id))
    section = page.split('id="snapshot"', 1)[1].split("</section>", 1)[0]
    expected_steps = [{"step_id": "step-1", "position": 1, "step_hash": "step-hash"}]
    observed = {
        "null_package_record_visible": bare["replay_package_id"] is None and bare["recording_ids"] != [],
        "raw_code_inplace_edit": ready["editable"] is True or "<textarea" in section or "<input" in section,
        "mapping_links_exact": ready["steps"] == expected_steps
        and ready["package_hash"] != ""
        and stored_mapping_hash((PackageStepView("step-1", 1, "step-hash"),)) != "",
        "cross_project_denied": denied == 404,
    }
    assert "compiler is missing" in expired["reasons"]
    assert "mapping does not match" in mismatch["reasons"] and mismatch["ready"] is False
    assert "artifact is expired" in expired["reasons"] and expired["ready"] is False
    assert "패키지가 없습니다." in page and "code는 읽기 전용입니다." in section and "<button" not in section
    assert observed == {
        "null_package_record_visible": True,
        "raw_code_inplace_edit": False,
        "mapping_links_exact": True,
        "cross_project_denied": True,
    }


async def _package_get(app: object, project_id: str, version_id: str) -> dict[str, object]:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _view_session(client, origin, project_id, "w2906-get-" + version_id[:8])
        response = await client.get(f"/api/v1/case-versions/{version_id}/replay-package", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert type(body) is dict
    return body


async def _package_status(app: object, project_id: str, version_id: str) -> int:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        headers = await _view_session(client, origin, project_id, "w2906-other")
        response = await client.get(f"/api/v1/case-versions/{version_id}/replay-package", headers=headers)
    return response.status_code


async def _package_page(app: object, project_id: str, case_id: str) -> str:
    import httpx

    origin = "http://127.0.0.1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
        await _view_session(client, origin, project_id, "w2906-page")
        detail = await client.get(f"/ui/projects/{project_id}/cases/{case_id}/definition")
        review = await client.get(f"/ui/projects/{project_id}/cases/{case_id}/definition?tab=review")
    assert detail.status_code == 200 and review.status_code == 200
    assert "code는 읽기 전용입니다." in review.text
    return detail.text


async def _view_session(client: object, origin: str, project_id: str, key: str) -> dict[str, str]:
    issued = await client.post(  # type: ignore[attr-defined]
        "/api/v1/session/nonces",
        json={"origin": origin, "project_id": project_id},
        headers={"Idempotency-Key": key + "-nonce", "Origin": origin},
    )
    booted = await client.post(  # type: ignore[attr-defined]
        "/api/v1/session/bootstrap",
        json={"nonce": issued.json()["nonce"]},
        headers={"Idempotency-Key": key + "-boot", "Origin": origin},
    )
    client.cookies.set("aiqa_session", booted.cookies["aiqa_session"])  # type: ignore[attr-defined]
    return {"Origin": origin, "X-CSRF-Token": booted.json()["csrf_token"]}


def _view_packages(database: Path, project_id: str, case_id: str, bare_version: str) -> tuple[str, str, str]:
    import sqlite3

    from aiqa.replay.packages import PackageStepView, stored_mapping_hash

    ready_version, mismatch_version, expired_version = str(uuid4()), str(uuid4()), str(uuid4())
    ready_package, mismatch_package = str(uuid4()), str(uuid4())
    manifest_id, recording_id, expired_recording = str(uuid4()), str(uuid4()), str(uuid4())
    mapping = stored_mapping_hash((PackageStepView("step-1", 1, "step-hash"),))
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO recordings (
                project_id, case_id, recording_id, creation_kind, input_case_version_id,
                base_case_version_id, parent_recording_id, source_recording_id,
                storage_status, stop_status, completion_status, evidence_status
            ) VALUES (?, ?, ?, 'recorded', ?, NULL, NULL, NULL, 'stored', 'stopped', 'completed', 'complete')
            """,
            (project_id, case_id, recording_id, bare_version),
        )
        connection.execute(
            """
            INSERT INTO recording_manifests (
                project_id, case_id, recording_id, manifest_id, revision, kind, prior_manifest_id,
                input_version_hash, source_artifact_hashes, action_mapping, evidence_completeness,
                request_key, body_hash
            ) VALUES (?, ?, ?, ?, 1, 'original', NULL, 'input-hash', '[]', '{}', 'complete', ?, 'manifest-hash')
            """,
            (project_id, case_id, recording_id, manifest_id, manifest_id),
        )
        names = [item[1] for item in connection.execute("PRAGMA table_info(case_versions)")]
        source = connection.execute("SELECT * FROM case_versions WHERE version_id = ?", (bare_version,)).fetchone()
        values = dict(zip(names, source, strict=True))
        _copy_version(connection, names, values, ready_version, 2, manifest_id, ready_package, "package ready")
        _copy_version(connection, names, values, mismatch_version, 3, manifest_id, mismatch_package, "package ready")
        _copy_version(connection, names, values, expired_version, 4, None, None, "compiler is missing")
        _view_package(connection, project_id, case_id, ready_version, ready_package, manifest_id, mapping)
        _view_package(connection, project_id, case_id, mismatch_version, mismatch_package, manifest_id, "mismatch")
        connection.execute(
            """
            INSERT INTO recordings (
                project_id, case_id, recording_id, creation_kind, input_case_version_id,
                base_case_version_id, parent_recording_id, source_recording_id,
                storage_status, stop_status, completion_status, evidence_status
            ) VALUES (?, ?, ?, 'recorded', ?, NULL, NULL, NULL, 'stored', 'stopped', 'completed', 'complete')
            """,
            (project_id, case_id, expired_recording, expired_version),
        )
        connection.execute(
            """
            INSERT INTO artifact_objects (
                project_id, artifact_id, object_key, content_hash, byte_length, media_type,
                owner_id, status, acked, custody
            ) VALUES (?, 'art-expired', 'art-expired', 'hash-expired', 4, 'image/png', ?, 'quarantine', 0, 'expired')
            """,
            (project_id, expired_recording),
        )
    return ready_version, mismatch_version, expired_version


def _copy_version(
    connection: object,
    names: list[str],
    values: dict[str, object],
    version_id: str,
    revision: int,
    manifest_id: str | None,
    package_id: str | None,
    reason: str,
) -> None:
    copied = dict(values)
    copied["version_id"] = version_id
    copied["revision"] = revision
    copied["source_manifest_id"] = manifest_id
    copied["replay_package_id"] = package_id
    copied["reason"] = reason
    copied["is_branch"] = 1
    connection.execute(  # type: ignore[attr-defined]
        f"INSERT INTO case_versions ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
        tuple(copied[name] for name in names),
    )


def _view_package(
    connection: object,
    project_id: str,
    case_id: str,
    version_id: str,
    package_id: str,
    manifest_id: str,
    mapping_hash: str,
) -> None:
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO replay_packages (
            project_id, package_id, case_id, case_version_id, ready, schema_version,
            source_manifest_id, source_manifest_hash, raw_source_hash, approved_code_hash,
            runtime_ref, compiler_ref, lock_hash, step_mapping_hash, body_hash
        ) VALUES (?, ?, ?, ?, 1, 'replay-package-v1', ?, 'manifest-hash', 'raw-source', 'code-hash',
            'web', 'web-ipc-subset', 'lock-hash', ?, ?)
        """,
        (project_id, package_id, case_id, version_id, manifest_id, mapping_hash, "pkg-" + package_id[:8]),
    )
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO package_version_links (project_id, case_id, version_id, package_id)
        VALUES (?, ?, ?, ?)
        """,
        (project_id, case_id, version_id, package_id),
    )
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO package_steps (project_id, package_id, step_id, position, step_hash)
        VALUES (?, ?, 'step-1', 1, 'step-hash')
        """,
        (project_id, package_id),
    )
