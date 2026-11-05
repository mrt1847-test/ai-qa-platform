"""Structure a saved natural-language draft into a case edit proposal.

Importing this module does not open a device or a live model network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from aiqa.contracts.jobs import IdempotencyKey, JobSubmission
from aiqa.domain.hashing import canonical_json
from aiqa.domain.proposals import ProposalSource, create_case_proposal
from aiqa.domain.versions import definition_from_document
from aiqa.models.provider_http import FixtureProviderHttp, structured_fixture_content
from aiqa.store.models import Actor, CaseProposalInput, Transaction
from aiqa.store.queue import enqueue_job


class StructureRejected(Exception):
    """The structure request cannot become a proposal."""


@dataclass(frozen=True, slots=True)
class StructureReceipt:
    job_id: UUID
    proposal_id: UUID
    base_version_id: UUID
    auto_applied: bool = False


def structure_body_from_text(raw_text: str, *, model_content: str | None = None) -> dict[str, object]:
    """Parse a fixture/model payload into a proposal body. Secrets stay out."""

    if type(raw_text) is not str or raw_text.strip() == "":
        raise StructureRejected("natural language draft is required")
    content = structured_fixture_content("structure") if model_content is None else model_content
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise StructureRejected("structure model response is invalid") from exc
    if type(parsed) is not dict:
        raise StructureRejected("structure model response is invalid")
    body = dict(parsed)
    body["raw_text"] = raw_text.strip()
    if "secret" in body or "secret_plaintext" in body or "secret_value" in body or "reasoning" in body:
        raise StructureRejected("structure model response keeps hidden model text")
    try:
        definition_from_document(body)
    except (ValueError, KeyError, TypeError) as exc:
        raise StructureRejected("structure model response is invalid") from exc
    return body


def definition_field_diff(current: dict[str, object], proposed: dict[str, object]) -> list[str]:
    """List top-level definition fields that differ. Used only for review display."""

    keys = (
        "raw_text",
        "objective",
        "preconditions",
        "variables",
        "secret_refs",
        "steps",
        "final_expected",
        "path_policy",
    )
    return [key for key in keys if current.get(key) != proposed.get(key)]


def request_structure(
    actor: Actor,
    project_id: UUID,
    version_id: UUID,
    *,
    request_key: str,
    provider: object | None = None,
) -> StructureReceipt:
    """Enqueue one structure job, complete it with a fixture/mock model, and store a proposal."""

    from aiqa.domain.proposals import _bound_store

    if actor.project_scope != project_id:
        raise StructureRejected("case version was not found")
    store = _bound_store()
    with store.transaction() as connection:
        row = connection.execute(
            """
            SELECT case_id, content_hash, definition_json, settings_json
            FROM case_versions
            WHERE project_id = ? AND version_id = ?
            """,
            (str(project_id), str(version_id)),
        ).fetchone()
        if row is None:
            raise StructureRejected("case version was not found")
        case_id = UUID(str(row[0]))
        base_hash = str(row[1])
        try:
            definition = json.loads(str(row[2]))
            settings = json.loads(str(row[3]))
        except json.JSONDecodeError as exc:
            raise StructureRejected("case version was not found") from exc
        if type(definition) is not dict:
            definition = {}
        if type(settings) is not dict:
            settings = {}
        raw_text = definition.get("raw_text", "")
        if (type(raw_text) is not str or raw_text.strip() == "") and type(settings.get("definition_buffer")) is str:
            raw_text = str(settings.get("definition_buffer"))
        if type(raw_text) is not str or raw_text.strip() == "":
            raise StructureRejected("natural language draft is required")
        receipt = enqueue_job(
            Transaction(connection),
            JobSubmission(
                project_id,
                "structure",
                None,
                None,
                (str(case_id), str(version_id)),
                canonical_json({"purpose": "structure", "version_id": str(version_id)}),
            ),
            IdempotencyKey(actor.actor_id, project_id, "enqueue_job", request_key),
        )
        job_id = receipt.job_id
        current_definition = definition

    try:
        model_content = _model_content(provider, raw_text.strip())
        body = structure_body_from_text(raw_text, model_content=model_content)
        proposal = create_case_proposal(
            actor,
            CaseProposalInput(
                case_id=case_id,
                base_version_id=version_id,
                base_hash=base_hash,
                kind="structure",
                body=body,
                source_job_id=job_id,
                tc_version_id=None,
            ),
        )
    except (StructureRejected, ProposalSource) as exc:
        with store.transaction() as connection:
            connection.execute(
                "UPDATE jobs SET status = 'error' WHERE project_id = ? AND job_id = ?",
                (str(project_id), str(job_id)),
            )
        if isinstance(exc, ProposalSource):
            raise StructureRejected(str(exc) or "proposal source was rejected") from exc
        raise

    with store.transaction() as connection:
        connection.execute(
            "UPDATE jobs SET status = 'completed' WHERE project_id = ? AND job_id = ? AND status IN ('queued', 'error')",
            (str(project_id), str(job_id)),
        )
    _ = current_definition
    return StructureReceipt(job_id, proposal.proposal_id, version_id, False)


def _model_content(provider: object | None, raw_text: str) -> str:
    if provider is None:
        provider = FixtureProviderHttp()
    complete = getattr(provider, "complete", None)
    if complete is None:
        return structured_fixture_content("structure")
    result = complete(
        model="fixture-structure",
        role="structure",
        secret="fixture-structure-secret",
        sanitized_inputs=(raw_text[:200],),
        token_output_limit=512,
    )
    content = getattr(result, "content", None)
    if type(content) is not str or content.strip() == "":
        raise StructureRejected("structure model response is invalid")
    return content
