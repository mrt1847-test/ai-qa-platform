"""Immutable repair proposals. Adoption starts a new full recording and leaves the source alone."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from aiqa.domain.hashing import canonical_hash
from aiqa.recording.service import RerecordInput, RecordingReceipt, start_rerecording
from aiqa.store.models import Actor
from aiqa.store.queue import JobConflict


class ProposalRejected(Exception):
    """The proposal cannot be stored or adopted."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class RepairProposalView:
    proposal_id: UUID
    episode_id: UUID
    package_id: UUID
    case_id: UUID
    diff_hash: str
    accepted_target: dict[str, object]
    diff: dict[str, object]
    evidence_hash: str
    replayed: bool


def save_repair_proposal(
    connection: sqlite3.Connection,
    project_id: UUID,
    episode_id: UUID,
    payload: dict[str, object],
    request_key: str,
) -> RepairProposalView:
    """Store one proposal for the episode, or return the stored proposal."""

    if request_key.strip() == "":
        raise ProposalRejected("idempotency key is required")
    episode = connection.execute(
        """
        SELECT episodes.case_run_id, episodes.attempt_id, episodes.package_id, runs.case_id
        FROM healing_episodes AS episodes
        JOIN case_runs AS runs
          ON runs.project_id = episodes.project_id AND runs.case_run_id = episodes.case_run_id
        WHERE episodes.project_id = ? AND episodes.episode_id = ?
        """,
        (str(project_id), str(episode_id)),
    ).fetchone()
    if episode is None:
        raise ProposalRejected("episode is missing")
    target = payload.get("accepted_target")
    diff = payload.get("diff")
    evidence_hash = payload.get("evidence_hash")
    if type(target) is not dict or type(diff) is not dict or type(evidence_hash) is not str or evidence_hash.strip() == "":
        raise ProposalRejected("proposal body is invalid")
    if str(payload.get("package_id", "")) != str(episode[2]):
        raise ProposalRejected("package does not match the episode")
    digest = canonical_hash(
        {
            "accepted_target": target,
            "diff": diff,
            "episode_id": str(episode_id),
            "evidence_hash": evidence_hash,
            "package_id": str(episode[2]),
        },
        "canon-json-v1",
    )
    existing = connection.execute(
        """
        SELECT proposal_id, request_key, diff_hash, accepted_target_json, diff_json, evidence_hash
        FROM repair_proposals
        WHERE project_id = ? AND episode_id = ?
        """,
        (str(project_id), str(episode_id)),
    ).fetchone()
    if existing is not None:
        if str(existing[2]) != digest:
            raise JobConflict("idempotency body does not match")
        return _view(existing[0], episode_id, episode[2], episode[3], existing[2], existing[3], existing[4], existing[5], True)
    proposal_id = uuid4()
    connection.execute(
        """
        INSERT INTO repair_proposals (
            project_id, proposal_id, episode_id, case_run_id, attempt_id, package_id, request_key, diff_hash,
            accepted_target_json, diff_json, evidence_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(project_id),
            str(proposal_id),
            str(episode_id),
            str(episode[0]),
            str(episode[1]),
            str(episode[2]),
            request_key,
            digest,
            json.dumps(target, ensure_ascii=False, sort_keys=True),
            json.dumps(diff, ensure_ascii=False, sort_keys=True),
            evidence_hash,
        ),
    )
    return RepairProposalView(
        proposal_id,
        episode_id,
        UUID(str(episode[2])),
        UUID(str(episode[3])),
        digest,
        target,
        diff,
        evidence_hash,
        False,
    )


def read_repair_proposal(connection: sqlite3.Connection, project_id: UUID, proposal_id: UUID) -> RepairProposalView | None:
    """Return the stored proposal. This does not create a recording."""

    row = connection.execute(
        """
        SELECT proposals.episode_id, proposals.package_id, runs.case_id, proposals.diff_hash,
               proposals.accepted_target_json, proposals.diff_json, proposals.evidence_hash
        FROM repair_proposals AS proposals
        JOIN healing_episodes AS episodes
          ON episodes.project_id = proposals.project_id AND episodes.episode_id = proposals.episode_id
        JOIN case_runs AS runs
          ON runs.project_id = episodes.project_id AND runs.case_run_id = episodes.case_run_id
        WHERE proposals.project_id = ? AND proposals.proposal_id = ?
        """,
        (str(project_id), str(proposal_id)),
    ).fetchone()
    if row is None:
        return None
    return _view(proposal_id, row[0], row[1], row[2], row[3], row[4], row[5], row[6], True)


def adopt_repair_proposal(
    connection: sqlite3.Connection,
    actor: Actor,
    project_id: UUID,
    case_id: UUID,
    proposal_id: UUID,
    spec: RerecordInput,
    request_key: str,
) -> RecordingReceipt:
    """Adopt a confirmed diff as a new full recording. The original source stays in place."""

    proposal = read_repair_proposal(connection, project_id, proposal_id)
    if proposal is None:
        raise ProposalRejected("proposal is missing")
    if proposal.case_id != case_id:
        raise ProposalRejected("proposal is for another case")
    if spec.reason.strip() == "":
        raise ProposalRejected("reason is required")
    receipt = start_rerecording(connection, actor, project_id, spec, request_key)
    if receipt.replayed:
        return receipt
    try:
        connection.execute(
            """
            INSERT INTO repair_adoptions (
                project_id, adoption_id, proposal_id, case_id, recording_id, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(project_id),
                str(uuid4()),
                str(proposal_id),
                str(case_id),
                str(receipt.recording_id),
                spec.reason,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ProposalRejected("proposal is already adopted") from exc
    return receipt


def _view(
    proposal_id: object,
    episode_id: object,
    package_id: object,
    case_id: object,
    diff_hash: object,
    target_json: object,
    diff_json: object,
    evidence_hash: object,
    replayed: bool,
) -> RepairProposalView:
    target = json.loads(str(target_json))
    diff = json.loads(str(diff_json))
    if type(target) is not dict or type(diff) is not dict:
        raise ProposalRejected("proposal body is invalid")
    return RepairProposalView(
        UUID(str(proposal_id)),
        UUID(str(episode_id)),
        UUID(str(package_id)),
        UUID(str(case_id)),
        str(diff_hash),
        target,
        diff,
        str(evidence_hash),
        replayed,
    )
