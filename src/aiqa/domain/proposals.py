"""Case edit proposals. Accepting one is the only path that creates a version."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import UUID, uuid4

from aiqa.contracts.cases import (
    CaseDefinition,
    CaseReadiness,
    CaseVersionView,
    CheckSpec,
    PathPolicy,
    ReadinessReason,
    StepSpec,
)
from aiqa.domain.hashing import SCHEMA_VERSION, canonical_hash, canonical_json, execution_snapshot_hash
from aiqa.domain.projects import next_commit_seq
from aiqa.domain.versions import StaleHead, ensure_projection_tables, persist_projection, definition_from_document
from aiqa.store.database import Store
from aiqa.store.models import Actor, CaseProposalInput, CaseProposalView, Transaction

_store: ContextVar[Store] = ContextVar("aiqa_proposal_store")
_FORBIDDEN = {"reasoning", "secret", "secret_plaintext", "secret_value"}


class ProposalNotFound(Exception):
    """The proposal is not in this project."""


class ProposalSource(Exception):
    """The proposal source is not the same case or project."""


@contextmanager
def bind_proposal_store(store: Store) -> Iterator[None]:
    token = _store.set(store)
    try:
        yield
    finally:
        _store.reset(token)


def create_case_proposal(actor: Actor, proposal: CaseProposalInput) -> CaseProposalView:
    if actor.project_scope is None:
        raise ProposalNotFound("proposal was not found")
    if proposal.kind not in {"structure", "tc_import"}:
        raise ProposalSource("proposal kind is invalid")
    _reject_hidden(proposal.body)
    stored_body = canonical_json(proposal.body)
    body_hash = canonical_hash(proposal.body, SCHEMA_VERSION)
    proposal_id = uuid4()
    store = _bound_store()
    with store.transaction() as connection:
        _require_base(connection, actor.project_scope, proposal)
        if proposal.kind == "structure":
            _require_structure_job(connection, actor.project_scope, proposal)
        else:
            _require_tc(connection, actor.project_scope, proposal)
        connection.execute(
            """
            INSERT INTO case_edit_proposals (
                project_id, proposal_id, case_id, base_version_id, base_hash, kind,
                body, body_hash, source_job_id, tc_version_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(actor.project_scope),
                str(proposal_id),
                str(proposal.case_id),
                str(proposal.base_version_id),
                proposal.base_hash,
                proposal.kind,
                stored_body,
                body_hash,
                None if proposal.source_job_id is None else str(proposal.source_job_id),
                None if proposal.tc_version_id is None else str(proposal.tc_version_id),
            ),
        )
    return _view(actor.project_scope, proposal_id, proposal, stored_body, body_hash)


def accept_case_proposal(actor: Actor, proposal_id: UUID, expected_head: UUID) -> CaseVersionView:
    if actor.project_scope is None:
        raise ProposalNotFound("proposal was not found")
    store = _bound_store()
    ensure_projection_tables(store._connection)
    with store.transaction() as connection:
        existing = _accepted_version(connection, actor.project_scope, proposal_id)
        if existing is not None:
            return existing
        proposal = _load(connection, actor.project_scope, proposal_id)
        case_row = connection.execute(
            """
            SELECT next_revision, latest_draft_version_id, lock_version
            FROM automation_cases
            WHERE project_id = ? AND case_id = ?
            """,
            (str(actor.project_scope), str(proposal.case_id)),
        ).fetchone()
        if case_row is None or case_row[1] is None or str(case_row[1]) != str(expected_head):
            raise StaleHead("draft head changed")
        if str(proposal.base_version_id) != str(case_row[1]):
            raise StaleHead("proposal base is stale")
        base = connection.execute(
            "SELECT content_hash FROM case_versions WHERE project_id=? AND case_id=? AND version_id=?",
            (str(actor.project_scope), str(proposal.case_id), str(proposal.base_version_id)),
        ).fetchone()
        if base is None or str(base[0]) != proposal.base_hash:
            raise StaleHead("proposal base hash changed")
        version_id = uuid4()
        definition = _definition(json.loads(proposal.body))
        if any(ref.project_id != actor.project_scope for ref in definition.secret_refs.values()):
            raise ProposalSource('secret reference is outside the proposal project')
        readiness = _readiness(definition)
        persist_projection(connection, str(version_id), definition)
        stored = connection.execute(
            "SELECT content_hash, verification_digest, body_json FROM definition_documents WHERE version_id = ?",
            (str(version_id),),
        ).fetchone()
        if stored is None:
            raise RuntimeError("projection was not stored")
        settings = connection.execute(
            """
            SELECT settings_json, recorded_steps_json FROM case_versions
            WHERE project_id = ? AND case_id = ? AND version_id = ?
            """,
            (str(actor.project_scope), str(proposal.case_id), str(proposal.base_version_id)),
        ).fetchone()
        if settings is None:
            raise ProposalSource("proposal base is missing")
        content_hash = execution_snapshot_hash(
            json.loads(str(stored[2])), json.loads(str(settings[0])), json.loads(str(settings[1]))
        )
        created_at = datetime.now(timezone.utc).isoformat()
        creation_kind = "import" if proposal.kind == "tc_import" else "edit"
        connection.execute(
            """
            INSERT INTO case_versions (
                project_id, case_id, version_id, revision, creation_kind,
                parent_version_id, base_version_id, is_branch, definition_json,
                settings_json, recorded_steps_json, content_hash, verification_digest,
                source_manifest_id, replay_package_id, readiness_json, actor_id,
                reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, 'proposal', ?)
            """,
            (
                str(actor.project_scope),
                str(proposal.case_id),
                str(version_id),
                int(case_row[0]),
                creation_kind,
                str(proposal.base_version_id),
                str(proposal.base_version_id),
                str(stored[2]),
                str(settings[0]),
                str(settings[1]),
                content_hash,
                str(stored[1]),
                json.dumps(_readiness_json(readiness), separators=(",", ":")),
                str(actor.actor_id),
                created_at,
            ),
        )
        commit_seq = next_commit_seq(Transaction(connection), actor.project_scope)
        connection.execute(
            """
            INSERT INTO case_revision_audits (
                project_id, case_id, version_id, commit_seq, actor_id, action, created_at
            ) VALUES (?, ?, ?, ?, ?, 'proposal_accept', ?)
            """,
            (
                str(actor.project_scope),
                str(proposal.case_id),
                str(version_id),
                commit_seq,
                str(actor.actor_id),
                created_at,
            ),
        )
        updated = connection.execute(
            """
            UPDATE automation_cases
            SET latest_draft_version_id = ?, next_revision = ?, lock_version = lock_version + 1
            WHERE project_id = ? AND case_id = ? AND lock_version = ? AND latest_draft_version_id = ?
            """,
            (
                str(version_id),
                int(case_row[0]) + 1,
                str(actor.project_scope),
                str(proposal.case_id),
                int(case_row[2]),
                str(expected_head),
            ),
        )
        if updated.rowcount != 1:
            raise StaleHead("draft head changed")
        connection.execute(
            """
            INSERT INTO case_proposal_decisions (
                project_id, decision_id, proposal_id, decision, produced_version_id,
                actor_id, commit_seq, created_at
            ) VALUES (?, ?, ?, 'accepted', ?, ?, ?, ?)
            """,
            (
                str(actor.project_scope),
                str(uuid4()),
                str(proposal_id),
                str(version_id),
                str(actor.actor_id),
                commit_seq,
                created_at,
            ),
        )
        return CaseVersionView(
            project_id=actor.project_scope,
            case_id=proposal.case_id,
            id=version_id,
            revision=int(case_row[0]),
            creation_kind=creation_kind,
            parent_version_id=proposal.base_version_id,
            base_version_id=proposal.base_version_id,
            content_hash=content_hash,
            verification_digest=str(stored[1]),
            replay_package_id=None,
            readiness=readiness,
        )


def reject_case_proposal(actor: Actor, proposal_id: UUID) -> None:
    if actor.project_scope is None:
        raise ProposalNotFound("proposal was not found")
    store = _bound_store()
    with store.transaction() as connection:
        proposal = _load(connection, actor.project_scope, proposal_id)
        already = connection.execute(
            """
            SELECT decision FROM case_proposal_decisions
            WHERE project_id = ? AND proposal_id = ? AND decision = 'rejected'
            """,
            (str(actor.project_scope), str(proposal_id)),
        ).fetchone()
        if already is not None:
            return
        created_at = datetime.now(timezone.utc).isoformat()
        commit_seq = next_commit_seq(Transaction(connection), actor.project_scope)
        connection.execute(
            """
            INSERT INTO case_proposal_decisions (
                project_id, decision_id, proposal_id, decision, produced_version_id,
                actor_id, commit_seq, created_at
            ) VALUES (?, ?, ?, 'rejected', NULL, ?, ?, ?)
            """,
            (
                str(actor.project_scope),
                str(uuid4()),
                str(proposal.proposal_id),
                str(actor.actor_id),
                commit_seq,
                created_at,
            ),
        )


def pending_proposal_text(actor: Actor, case_id: UUID) -> str:
    """Return the first undecided proposal instruction. An empty string means none."""

    if actor.project_scope is None:
        return ""
    row = _bound_store()._connection.execute(
        """
        SELECT body FROM case_edit_proposals
        WHERE project_id = ? AND case_id = ?
          AND NOT EXISTS (
            SELECT 1 FROM case_proposal_decisions
            WHERE case_proposal_decisions.project_id = case_edit_proposals.project_id
              AND case_proposal_decisions.proposal_id = case_edit_proposals.proposal_id
          )
        ORDER BY rowid DESC
        LIMIT 1
        """,
        (str(actor.project_scope), str(case_id)),
    ).fetchone()
    if row is None:
        return ""
    body = json.loads(str(row[0]))
    steps = body.get("steps", [])
    if type(steps) is not list or not steps or type(steps[0]) is not dict:
        return ""
    return str(steps[0].get("instruction", ""))


def get_case_proposal(actor: Actor, proposal_id: UUID) -> CaseProposalView:
    if actor.project_scope is None:
        raise ProposalNotFound("proposal was not found")
    store = _bound_store()
    row = store._connection.execute(
        """
        SELECT proposal_id, project_id, case_id, base_version_id, base_hash, kind,
               body, body_hash, source_job_id, tc_version_id
        FROM case_edit_proposals
        WHERE project_id = ? AND proposal_id = ?
        """,
        (str(actor.project_scope), str(proposal_id)),
    ).fetchone()
    if row is None:
        raise ProposalNotFound("proposal was not found")
    return _view_row(row)


def _require_base(connection: sqlite3.Connection, project_id: UUID, proposal: CaseProposalInput) -> None:
    row = connection.execute(
        """
        SELECT content_hash FROM case_versions
        WHERE project_id = ? AND case_id = ? AND version_id = ?
        """,
        (str(project_id), str(proposal.case_id), str(proposal.base_version_id)),
    ).fetchone()
    if row is None or str(row[0]) != proposal.base_hash:
        raise ProposalSource("base version does not match the case")


def _require_structure_job(connection: sqlite3.Connection, project_id: UUID, proposal: CaseProposalInput) -> None:
    if proposal.source_job_id is None or proposal.tc_version_id is not None:
        raise ProposalSource("structure proposal needs the case job")
    row = connection.execute(
        """
        SELECT source_refs FROM jobs
        WHERE project_id = ? AND job_id = ? AND purpose = 'structure'
        """,
        (str(project_id), str(proposal.source_job_id)),
    ).fetchone()
    if row is None:
        raise ProposalSource("structure job is not in this project")
    refs = json.loads(str(row[0]))
    if str(proposal.case_id) not in refs:
        raise ProposalSource("structure job belongs to another case")


def _require_tc(connection: sqlite3.Connection, project_id: UUID, proposal: CaseProposalInput) -> None:
    if proposal.tc_version_id is None or proposal.source_job_id is not None:
        raise ProposalSource("tc import needs a project TC")
    row = connection.execute(
        "SELECT version_id FROM tc_versions WHERE project_id = ? AND version_id = ?",
        (str(project_id), str(proposal.tc_version_id)),
    ).fetchone()
    if row is None:
        raise ProposalSource("tc version belongs to another project")


def _accepted_version(connection: sqlite3.Connection, project_id: UUID, proposal_id: UUID) -> CaseVersionView | None:
    row = connection.execute(
        """
        SELECT produced_version_id FROM case_proposal_decisions
        WHERE project_id = ? AND proposal_id = ? AND decision = 'accepted'
        """,
        (str(project_id), str(proposal_id)),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    stored = connection.execute(
        """
        SELECT project_id, case_id, version_id, revision, creation_kind, parent_version_id,
               base_version_id, content_hash, verification_digest, readiness_json
        FROM case_versions
        WHERE project_id = ? AND version_id = ?
        """,
        (str(project_id), str(row[0])),
    ).fetchone()
    if stored is None:
        raise ProposalNotFound("proposal was not found")
    readiness = json.loads(str(stored[9]))
    return CaseVersionView(
        project_id=UUID(str(stored[0])),
        case_id=UUID(str(stored[1])),
        id=UUID(str(stored[2])),
        revision=int(stored[3]),
        creation_kind=str(stored[4]),
        parent_version_id=None if stored[5] is None else UUID(str(stored[5])),
        base_version_id=None if stored[6] is None else UUID(str(stored[6])),
        content_hash=str(stored[7]),
        verification_digest=str(stored[8]),
        replay_package_id=None,
        readiness=CaseReadiness(
            saved=bool(readiness["saved"]),
            recordable=bool(readiness["recordable"]),
            replayable=bool(readiness["replayable"]),
            reviewable=bool(readiness["reviewable"]),
            formal_runnable=bool(readiness["formal_runnable"]),
            reasons=tuple(ReadinessReason(item["code"], item["message"]) for item in readiness["reasons"]),
        ),
    )


def _load(connection: sqlite3.Connection, project_id: UUID, proposal_id: UUID) -> CaseProposalView:
    row = connection.execute(
        """
        SELECT proposal_id, project_id, case_id, base_version_id, base_hash, kind,
               body, body_hash, source_job_id, tc_version_id
        FROM case_edit_proposals
        WHERE project_id = ? AND proposal_id = ?
        """,
        (str(project_id), str(proposal_id)),
    ).fetchone()
    if row is None:
        raise ProposalNotFound("proposal was not found")
    return _view_row(row)


def _view(project_id: UUID, proposal_id: UUID, proposal: CaseProposalInput, body: str, body_hash: str) -> CaseProposalView:
    return CaseProposalView(
        proposal_id=proposal_id,
        project_id=project_id,
        case_id=proposal.case_id,
        base_version_id=proposal.base_version_id,
        base_hash=proposal.base_hash,
        kind=proposal.kind,
        body=body,
        body_hash=body_hash,
        source_job_id=proposal.source_job_id,
        tc_version_id=proposal.tc_version_id,
    )


def _view_row(row: sqlite3.Row | tuple[object, ...]) -> CaseProposalView:
    return CaseProposalView(
        proposal_id=UUID(str(row[0])),
        project_id=UUID(str(row[1])),
        case_id=UUID(str(row[2])),
        base_version_id=UUID(str(row[3])),
        base_hash=str(row[4]),
        kind=str(row[5]),
        body=str(row[6]),
        body_hash=str(row[7]),
        source_job_id=None if row[8] is None else UUID(str(row[8])),
        tc_version_id=None if row[9] is None else UUID(str(row[9])),
    )


def _definition(payload: dict[str, object]) -> CaseDefinition:
    try:
        return definition_from_document(payload)
    except (ValueError, KeyError, TypeError) as exc:
        raise ProposalSource('proposal body is invalid') from exc


def _step(payload: object) -> StepSpec:
    if type(payload) is not dict:
        raise ProposalSource("proposal body is invalid")
    expected = payload.get("expected", [])
    if type(expected) is not list:
        raise ProposalSource("proposal body is invalid")
    return StepSpec(str(payload.get("id")), str(payload.get("instruction")), tuple(_check(item) for item in expected))


def _check(payload: object) -> CheckSpec:
    if type(payload) is not dict:
        raise ProposalSource("proposal body is invalid")
    return CheckSpec(str(payload.get("id")), str(payload.get("kind")), str(payload.get("expected")))


def _readiness(definition: CaseDefinition) -> CaseReadiness:
    reasons: list[ReadinessReason] = []
    if definition.objective.strip() == "" or not definition.steps:
        reasons.append(ReadinessReason("DEFINITION_AMBIGUOUS", "definition is incomplete"))
    return CaseReadiness(True, False, False, False, False, tuple(reasons))


def _readiness_json(readiness: CaseReadiness) -> dict[str, object]:
    return {
        "formal_runnable": readiness.formal_runnable,
        "reasons": [{"code": reason.code, "message": reason.message} for reason in readiness.reasons],
        "recordable": readiness.recordable,
        "replayable": readiness.replayable,
        "reviewable": readiness.reviewable,
        "saved": readiness.saved,
    }


def _reject_hidden(value: object) -> None:
    if type(value) is dict:
        for key, item in value.items():
            if str(key) in _FORBIDDEN:
                raise ProposalSource("proposal body keeps hidden model text")
            _reject_hidden(item)
    elif type(value) is list:
        for item in value:
            _reject_hidden(item)


def _bound_store() -> Store:
    try:
        return _store.get()
    except LookupError as exc:
        raise RuntimeError("proposal store is not bound") from exc
