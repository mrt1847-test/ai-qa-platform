"""Healing stays off until an approved snapshot exists, and a running snapshot stays put."""

from __future__ import annotations

from uuid import uuid4

from aiqa.contracts.cases import CaseDefinition, CaseVersion, PathPolicy
from aiqa.contracts.healing import ApprovedHealingPolicy, HealingRequest, Limits
from aiqa.healing.policy import resolve_healing_policy


def test_w31_01() -> None:
    denied = resolve_healing_policy(_version(False, False, "screen"), _request(True, "regression", "screen"), Limits())
    default = resolve_healing_policy(_version(False, False, ""), HealingRequest(False), Limits())
    trial = resolve_healing_policy(_version(True, True, "screen"), _request(True, "trial", "screen"), Limits())
    missing_key = resolve_healing_policy(_version(True, False, "screen"), _request(True, "regression", "screen"), Limits())
    wider = resolve_healing_policy(_version(True, True, "screen"), _request(True, "regression", "device"), Limits())
    accepted = resolve_healing_policy(
        _version(True, True, "screen"),
        _request(True, "regression", "screen"),
        Limits(max_model_calls_per_item=1),
    )
    changed = resolve_healing_policy(
        _version(True, True, "device", calls=2),
        HealingRequest(True, "device", 1, 2, 30, "regression", True, accepted),
        Limits(max_model_calls_per_item=2),
    )
    observed = {
        "default_enabled": default.default_enabled,
        "capability_false_on_rejected": denied.rejected is True and denied.effective_enabled is False,
        "trial_enabled": trial.effective_enabled,
        "running_snapshot_mutated": changed.resolution_hash != accepted.resolution_hash,
    }
    assert missing_key.rejected is True and missing_key.effective_enabled is False
    assert wider.rejected is True and wider.effective_enabled is False
    assert accepted.effective_enabled is True
    assert accepted.effective_limits["max_model_calls_per_item"] == 1
    assert observed == {
        "default_enabled": False,
        "capability_false_on_rejected": True,
        "trial_enabled": False,
        "running_snapshot_mutated": False,
    }


def _version(allowed: bool, key_present: bool, scope: str, calls: int = 2) -> CaseVersion:
    return CaseVersion(
        id=uuid4(),
        project_id=uuid4(),
        case_id=uuid4(),
        definition=CaseDefinition("", "", (), {}, {}, (), (), PathPolicy()),
        replay_package_id=None,
        approval_id=uuid4(),
        creation_kind="recorded",
        content_hash="version-hash",
        verification_digest="digest",
        approved_healing=ApprovedHealingPolicy(
            allowed=allowed,
            scope=scope,
            model_binding_ref="bind-1" if key_present else "",
            binding_revision="rev-1" if key_present else "",
            healer_key_present=key_present,
            max_model_calls_per_item=calls,
            default_enabled=False,
        ),
    )


def _request(enabled: bool, purpose: str, scope: str) -> HealingRequest:
    return HealingRequest(enabled, scope, 1, 2, 30, purpose, False, None)


def test_w31_02(tmp_path) -> None:
    import sqlite3
    import threading
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    from aiqa.api.app import create_app
    from aiqa.config import load_settings
    from aiqa.contracts.healing import HealingTrigger
    from aiqa.domain.projects import bind_store, create_project
    from aiqa.healing.service import HealingRejected, reserve_healing_episode
    from aiqa.store.database import migrate_store
    from aiqa.store.models import Actor, ProjectCreate
    from aiqa.worker.control import RunControl

    root = Path(tmp_path) / "runtime"
    app = create_app(load_settings({"AIQA_HOST": "127.0.0.1", "AIQA_PORT": "8000", "AIQA_RUNTIME_ROOT": str(root)}))
    owner = Actor(uuid4(), None, True)
    store = app.state.open_store()
    migrate_store(store)
    with bind_store(store):
        project = create_project(owner, ProjectCreate("예약", "w3102", "heal", "web"))
    store.close()
    database = root / "db" / "aiqa.sqlite"
    project_id = str(project.project_id)
    graph = _graph(database, project_id, str(owner.actor_id))
    enabled = _policy(True)
    disabled = _policy(False)
    main = _control(database, project_id, graph["main"])
    first = reserve_healing_episode(_trigger(graph["main"], enabled, "one", 600, 120), main)
    again = reserve_healing_episode(_trigger(graph["main"], enabled, "one", 600, 120), main)
    other = reserve_healing_episode(_trigger(graph["main"], enabled, "two", 600, 120), main)
    off = reserve_healing_episode(_trigger(graph["off"], disabled, "off", 600, 120), _control(database, project_id, graph["off"]))
    _mark_dispatch(database, project_id, graph["dispatched"])
    blocked = reserve_healing_episode(
        _trigger(graph["dispatched"], enabled, "late", 600, 120),
        _control(database, project_id, graph["dispatched"]),
    )
    short = reserve_healing_episode(
        _trigger(graph["short"], enabled, "short", 600, 120),
        _control(database, project_id, graph["short"]),
    )
    refused = _refused(database, project_id, graph["violation"], enabled, "bad", True, enabled.binding_revision)
    rotated = _refused(database, project_id, graph["rotated"], enabled, "rot", False, "rev-2")
    _race(database, project_id, graph["race"], enabled)
    with sqlite3.connect(database) as connection:
        main_count = _episodes(connection, graph["main"]["run"])
        race_count = _episodes(connection, graph["race"]["run"])
        off_count = _episodes(connection, graph["off"]["run"])
    observed = {
        "episodes_per_item_max": max(main_count, race_count),
        "post_dispatch_eligible": blocked.eligible,
        "off_model_calls": off.reserved_calls if off_count == 0 else off.reserved_calls + 1,
        "duplicate_trigger_extra_episodes": main_count - 1,
    }
    assert first.eligible is True and first.reserved_calls == 2 and first.reserved_seconds == 30
    assert again.replayed is True and again.episode_id == first.episode_id
    assert other.replayed is True and other.episode_id == first.episode_id
    assert short.eligible is False and short.reserved_calls == 0
    assert refused is True and rotated is True
    assert observed == {
        "episodes_per_item_max": 1,
        "post_dispatch_eligible": False,
        "off_model_calls": 0,
        "duplicate_trigger_extra_episodes": 0,
    }


def _policy(enabled: bool):
    version = CaseVersion(
        id=uuid4(),
        project_id=uuid4(),
        case_id=uuid4(),
        definition=CaseDefinition("", "", (), {}, {}, (), (), PathPolicy()),
        replay_package_id=None,
        approval_id=None,
        creation_kind="recorded",
        content_hash="hash",
        verification_digest="digest",
        approved_healing=ApprovedHealingPolicy(
            allowed=enabled,
            scope="screen",
            model_binding_ref="bind-1" if enabled else "",
            binding_revision="rev-1",
            healer_key_present=enabled,
        ),
    )
    return resolve_healing_policy(version, HealingRequest(enabled, "screen", 1, 2, 30, "regression"), Limits())


def _graph(database, project_id: str, actor_id: str) -> dict[str, dict[str, str]]:
    import sqlite3
    from datetime import datetime, timedelta, timezone

    case_id = str(uuid4())
    version_id = str(uuid4())
    recording_id = str(uuid4())
    manifest_id = str(uuid4())
    package_id = str(uuid4())
    names = ("main", "off", "dispatched", "short", "violation", "rotated", "race")
    items = {name: {"run": str(uuid4()), "job": str(uuid4()), "attempt": str(uuid4()), "package": package_id} for name in names}
    stamp = "2026-11-01T00:00:00+00:00"
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO automation_cases (
                project_id, case_id, name, folder_id, tc_reference, next_revision,
                latest_draft_version_id, current_approval_id, lock_version, archived_at
            ) VALUES (?, ?, '예약', NULL, NULL, 2, NULL, NULL, 0, NULL)
            """,
            (project_id, case_id),
        )
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind, parent_version_id, base_version_id,
                is_branch, definition_json, settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id, reason, created_at
            ) VALUES (?, ?, ?, 1, 'recorded', NULL, NULL, 0, '{}', '{}', '[]', 'hash', 'digest',
                ?, ?, '{}', ?, 'recorded', ?)
            """,
            (project_id, case_id, version_id, manifest_id, package_id, actor_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO recordings (
                project_id, case_id, recording_id, creation_kind, input_case_version_id, base_case_version_id,
                parent_recording_id, source_recording_id, storage_status, stop_status, completion_status, evidence_status
            ) VALUES (?, ?, ?, 'recorded', ?, NULL, NULL, NULL, 'stored', 'stopped', 'completed', 'complete')
            """,
            (project_id, case_id, recording_id, version_id),
        )
        connection.execute(
            """
            INSERT INTO recording_manifests (
                project_id, case_id, recording_id, manifest_id, revision, kind, prior_manifest_id,
                input_version_hash, source_artifact_hashes, action_mapping, evidence_completeness,
                request_key, body_hash
            ) VALUES (?, ?, ?, ?, 1, 'original', NULL, 'hash', '[]', '[]', 'complete', 'manifest', 'hash')
            """,
            (project_id, case_id, recording_id, manifest_id),
        )
        connection.execute(
            """
            INSERT INTO replay_packages (
                project_id, package_id, case_id, case_version_id, ready, schema_version, source_manifest_id,
                source_manifest_hash, raw_source_hash, approved_code_hash, runtime_ref, compiler_ref,
                lock_hash, step_mapping_hash, body_hash
            ) VALUES (?, ?, ?, ?, 1, 'v1', ?, 'hash', 'hash', 'hash', 'runtime', 'compiler', 'lock', 'map', 'hash')
            """,
            (project_id, package_id, case_id, version_id, manifest_id),
        )
        connection.execute(
            """
            INSERT INTO package_version_links (project_id, case_id, version_id, package_id)
            VALUES (?, ?, ?, ?)
            """,
            (project_id, case_id, version_id, package_id),
        )
        for name, item in items.items():
            execution_id = str(uuid4())
            expires = past if name == "short" else future
            connection.execute(
                """
                INSERT INTO executions (
                    project_id, execution_id, name, purpose, source, suite_version_id, scope_requested_at
                ) VALUES (?, ?, '수행', 'regression', 'single', NULL, ?)
                """,
                (project_id, execution_id, stamp),
            )
            connection.execute(
                """
                INSERT INTO case_runs (
                    project_id, execution_id, case_run_id, case_id, case_version_id, purpose, requested_at
                ) VALUES (?, ?, ?, ?, ?, 'regression', ?)
                """,
                (project_id, execution_id, item["run"], case_id, version_id, stamp),
            )
            connection.execute(
                """
                INSERT INTO jobs (
                    project_id, job_id, purpose, recording_id, case_run_id, payload_hash, source_refs, limits, status
                ) VALUES (?, ?, 'regression', NULL, ?, 'payload', '[]', '{}', 'running')
                """,
                (project_id, item["job"], item["run"]),
            )
            connection.execute(
                """
                INSERT INTO attempts (
                    project_id, attempt_id, job_id, generation, physical_key_id
                ) VALUES (?, ?, ?, 1, NULL)
                """,
                (project_id, item["attempt"], item["job"]),
            )
            connection.execute(
                """
                INSERT INTO leases (
                    project_id, job_id, generation, worker_id, physical_key_id, expires_at
                ) VALUES (?, ?, 1, 'worker-1', NULL, ?)
                """,
                (project_id, item["job"], expires),
            )
            item["case"] = case_id
            item["version"] = version_id
        connection.commit()
    return items


def _control(database, project_id: str, item: dict[str, str]):
    import sqlite3
    from uuid import UUID

    from aiqa.worker.control import RunControl

    connection = sqlite3.connect(database)
    connection.isolation_level = None
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=3000")
    return RunControl(connection, UUID(project_id), UUID(item["job"]), "before_lookup")


def _trigger(item: dict[str, str], policy, key: str, job_seconds: int, lease_seconds: int, violation: bool = False, revision: str | None = None):
    from uuid import UUID

    from aiqa.contracts.healing import HealingTrigger

    return HealingTrigger(
        UUID(item["run"]),
        UUID(item["attempt"]),
        UUID(item["package"]),
        key,
        "target_not_found",
        policy,
        job_seconds,
        lease_seconds,
        policy.binding_revision if revision is None else revision,
        violation,
    )


def _mark_dispatch(database, project_id: str, item: dict[str, str]) -> None:
    import sqlite3

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO actions (
                project_id, attempt_id, action_seq, step_id, action_id, package_step_id, proposal_hash,
                dispatch_state, case_id, case_version_id, outcome_known
            ) VALUES (?, ?, 1, 'step', ?, NULL, 'hash', 'dispatch_started', ?, ?, 0)
            """,
            (project_id, item["attempt"], str(uuid4()), item["case"], item["version"]),
        )
        connection.execute(
            """
            INSERT INTO dispatch_journal (
                project_id, attempt_id, action_seq, entry_seq, dispatch_state, recorded_at
            ) VALUES (?, ?, 1, 1, 'dispatch_started', '2026-11-01T00:00:01+00:00')
            """,
            (project_id, item["attempt"]),
        )
        connection.commit()


def _refused(database, project_id: str, item: dict[str, str], policy, key: str, violation: bool, revision: str) -> bool:
    from aiqa.healing.service import HealingRejected, reserve_healing_episode

    try:
        reserve_healing_episode(
            _trigger(item, policy, key, 600, 120, violation, revision),
            _control(database, project_id, item),
        )
    except HealingRejected:
        return True
    return False


def _race(database, project_id: str, item: dict[str, str], policy) -> None:
    import threading

    from aiqa.healing.service import reserve_healing_episode

    barrier = threading.Barrier(2)

    def once(key: str) -> None:
        barrier.wait()
        reserve_healing_episode(_trigger(item, policy, key, 600, 120), _control(database, project_id, item))

    first = threading.Thread(target=once, args=("race-a",))
    second = threading.Thread(target=once, args=("race-b",))
    first.start()
    second.start()
    first.join()
    second.join()


def test_w31_03() -> None:
    from aiqa.contracts.models import OwnedEpisode, RoleBinding
    from aiqa.healing.service import HealingService
    from aiqa.healing.targets import HealingContext, validate_healing_proposal
    from aiqa.models.broker import ModelBroker

    broker = ModelBroker(
        "item-1",
        (RoleBinding("healing", 1, "fixture-heal", "ref-1"),),
        (),
        (OwnedEpisode("episode-1", "item-1"),),
    )
    service = HealingService(broker)
    same = validate_healing_proposal(
        service.propose(_context("#old", "click", "", "/form", _payload("#new", "click", "", "/form", [20, 20]))),
        _screen([_element("#new", bounds=[10, 10, 40, 30])]),
    )
    ambiguous = validate_healing_proposal(
        service.propose(_context("#old", "click", "", "/form", _payload("#new", "click", "", "/form", None))),
        _screen([_element("#a"), _element("#b")]),
    )
    changed = validate_healing_proposal(
        service.propose(_context("#old", "click", "", "/form", _payload("#new", "submit", "", "/form", None))),
        _screen([_element("#new")]),
    )
    visual = service.propose(_context("#old", "click", "", "/form", _payload("#new", "click", "", "/form", None, "visual")))
    visual_decision = validate_healing_proposal(visual, _screen([_element("#new", kind="canvas")]))
    changed_input = validate_healing_proposal(
        service.propose(_context("#old", "click", "kept", "/form", _payload("#new", "click", "other", "/form", None))),
        _screen([_element("#new")]),
    )
    popup = validate_healing_proposal(
        service.propose(_context("#old", "click", "", "/form", _payload("#new", "dismiss", "", "/popup", None))),
        _screen([_element("#new")]),
    )
    outside = validate_healing_proposal(
        service.propose(_context("#old", "click", "", "/form", _payload("#new", "click", "", "/form", [1, 1]))),
        _screen([_element("#new", bounds=[10, 10, 40, 30])]),
    )
    assert changed_input.accepted is False
    assert popup.accepted is False
    assert outside.accepted is False
    canvas = validate_healing_proposal(
        service.propose(_context("#old", "click", "", "/form", _payload("#new", "click", "", "/form", None))),
        _screen([_element("#new", kind="canvas")]),
    )
    assert visual.admitted is False
    assert canvas.accepted is False
    observed = {
        "same_target_proven": same.accepted is True and same.same_target is True,
        "ambiguous_candidate_accepted": ambiguous.accepted,
        "changed_action_accepted": changed.accepted,
        "visual_only_accepted": visual_decision.accepted,
    }
    assert observed == {
        "same_target_proven": True,
        "ambiguous_candidate_accepted": False,
        "changed_action_accepted": False,
        "visual_only_accepted": False,
    }


def _heal_request() -> object:
    from uuid import uuid4

    from aiqa.contracts.models import ModelRequest

    return ModelRequest(uuid4(), "healing", "episode", "episode-1", 1, (), 20, "2026-11-01T00:00:00+00:00", None, "episode-1")


def _context(locator: str, action: str, value: str, path: str, payload: dict[str, object]) -> object:
    from aiqa.healing.targets import HealingContext

    return HealingContext("button", "저장", "form", "id.save", "저장", "main", locator, action, value, path, _heal_request(), payload)


def _payload(locator: str, action: str, value: str, path: str, point: list[int] | None, basis: str = "typed") -> dict[str, object]:
    body: dict[str, object] = {
        "basis": basis,
        "role": "button",
        "name": "저장",
        "container": "form",
        "resource_id": "id.save",
        "text": "저장",
        "context": "main",
        "locator": locator,
        "action": action,
        "input": value,
        "path": path,
    }
    if point is not None:
        body["coordinates"] = point
    return body


def _element(locator: str, bounds: list[int] | None = None, kind: str = "element") -> dict[str, object]:
    return {
        "role": "button",
        "name": "저장",
        "container": "form",
        "resource_id": "id.save",
        "text": "저장",
        "context": "main",
        "locator": locator,
        "visible": True,
        "enabled": True,
        "bounds": [10, 10, 40, 30] if bounds is None else bounds,
        "kind": kind,
    }


def _screen(elements: list[dict[str, object]]) -> object:
    import json

    from aiqa.contracts.actions import Observation

    return Observation("obs-1", "2026-11-01T00:00:00+00:00", None, b"", json.dumps({"elements": elements}), "", (), "", True, "web")


def _episodes(connection, case_run_id: str) -> int:
    row = connection.execute(
        "SELECT COUNT(*) FROM healing_episodes WHERE case_run_id = ?",
        (case_run_id,),
    ).fetchone()
    return 0 if row is None else int(row[0])


def test_w31_04(tmp_path) -> None:
    from aiqa.contracts.actions import ActionProposal, Observation, PreparedAction
    from aiqa.contracts.checks import CheckSpec
    from aiqa.contracts.jobs import ControlDecision
    from aiqa.healing.service import AcceptedHealingProposal, apply_runtime_override, item_overrides
    from aiqa.worker.dispatch_journal import DispatchJournal

    success = _Calls("acknowledged")
    timeout = _Calls("timeout")
    limited = _Calls("acknowledged")
    redacted = _Calls("acknowledged")
    violated = _Calls("acknowledged")
    control = _Gate(True)
    blocked = _Gate(False)
    matched = _dom("보임")
    apply_runtime_override(
        _accepted(tmp_path, "success", success, control, matched, False, True, "lookup-miss"),
        control,
    )
    apply_runtime_override(
        _accepted(tmp_path, "success", success, control, matched, False, True, "lookup-miss"),
        control,
    )
    mismatch = apply_runtime_override(
        _accepted(tmp_path, "mismatch", _Calls("acknowledged"), control, _dom("다름"), False, True, "lookup-miss", "다른 문구"),
        control,
    )
    apply_runtime_override(
        _accepted(tmp_path, "redacted", redacted, control, matched, False, False, "redaction-failed"),
        control,
    )
    apply_runtime_override(
        _accepted(tmp_path, "timeout", timeout, control, matched, False, True, "lookup-miss"),
        control,
    )
    apply_runtime_override(
        _accepted(tmp_path, "limited", limited, blocked, matched, False, True, "lookup-miss"),
        blocked,
    )
    apply_runtime_override(
        _accepted(tmp_path, "violation", violated, control, matched, True, True, "lookup-miss"),
        control,
    )
    apply_runtime_override(
        _accepted(tmp_path, "violation", violated, control, matched, False, True, "lookup-miss"),
        control,
    )
    done = item_overrides("success")[0]
    failure = item_overrides("violation")[0]
    observed = {
        "original_action_dispatches": done.dispatches,
        "success_result": done.result,
        "healing_used": done.healing_used,
        "required_violation_result": failure.result,
        "unassisted_pass": done.result == "PASS" and done.healing_used is False,
    }
    assert item_overrides("redacted")[0].lookup_error == "redaction-failed"
    assert item_overrides("redacted")[0].dispatches == 0
    assert timeout.calls == 1 and limited.calls == 0
    assert item_overrides("mismatch")[0].result != "PASS"
    assert mismatch.command_result == "" or mismatch.outcome == "unknown"
    assert len(item_overrides("violation")) == 1
    assert observed == {
        "original_action_dispatches": 1,
        "success_result": "PASS",
        "healing_used": True,
        "required_violation_result": "FAIL",
        "unassisted_pass": False,
    }


class _Gate:
    attempt_id = "attempt-1"

    def __init__(self, allowed: bool) -> None:
        self._allowed = allowed

    def checkpoint(self) -> object:
        from aiqa.contracts.jobs import ControlDecision

        return ControlDecision(self._allowed, "before_dispatch")

    def authorize_dispatch(self) -> object:
        return self.checkpoint()


class _Calls:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.calls = 0

    def lookup(self, prepared: object) -> bool:
        return True

    def execute(self, prepared: object) -> str:
        self.calls += 1
        if self.mode == "timeout":
            raise TimeoutError("command timed out")
        return "acknowledged"


def _accepted(tmp_path, item_id: str, command: object, control: object, observation: object, required: bool, allowed: bool, lookup: str, expected: str = "보임") -> object:
    from aiqa.contracts.actions import ActionProposal, PreparedAction
    from aiqa.contracts.checks import CheckSpec
    from aiqa.healing.service import AcceptedHealingProposal
    from aiqa.worker.dispatch_journal import DispatchJournal

    proposal = ActionProposal(item_id, item_id, "click", "click", "/form", "typed")
    prepared = PreparedAction(proposal, item_id, None, allowed, control.attempt_id)
    return AcceptedHealingProposal(
        item_id,
        True,
        prepared,
        DispatchJournal(tmp_path / f"{item_id}.jsonl"),
        command,
        (CheckSpec("check-1", "text", expected, subject="#save", required=required),),
        observation,
        lookup,
        "rejected-before",
        "kept-rejection",
        2,
        required,
    )


def _dom(text: str) -> object:
    from aiqa.contracts.actions import Observation

    return Observation(
        "obs-1",
        "2026-11-01T00:00:00+00:00",
        None,
        b"",
        '{"nodes":[{"locator":"#save","text":"' + text + '","value":"","state":"visible"}]}',
        "",
        (),
        "",
        True,
        "web",
    )
