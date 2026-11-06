"""Structure a saved natural-language draft into a case edit proposal.

Importing this module does not open a device or a live model network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from aiqa.contracts.jobs import IdempotencyKey, JobSubmission
from aiqa.domain.hashing import canonical_json
from aiqa.domain.model_bindings import BindingNotFound, bind_model_store, load_latest_binding_for_role
from aiqa.domain.proposals import ProposalSource, create_case_proposal
from aiqa.domain.versions import definition_from_document
from aiqa.models.provider_http import ProviderHttpError, structured_fixture_content
from aiqa.security.secrets import SecretScopeDenied, SecretUnavailable, bind_secret_store
from aiqa.store.models import Actor, CaseProposalInput, RuntimeScope, SecretRef, Transaction
from aiqa.store.queue import enqueue_job

_STRUCTURE_ROLE = "structure"
_STRUCTURE_BUDGET = 8
_structure_calls: dict[str, int] = {}


class StructureRejected(Exception):
    """The structure request cannot become a proposal."""

    def __init__(self, message: str = "", *, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


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
    content = (
        structured_fixture_content("structure", sanitized_inputs=(raw_text.strip(),))
        if model_content is None
        else model_content
    )
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
    secret_resolver: object | None = None,
    store: object | None = None,
) -> StructureReceipt:
    """Enqueue one structure job, complete it via project model binding, and store a proposal."""

    from aiqa.domain.proposals import _bound_store

    if actor.project_scope != project_id:
        raise StructureRejected("case version was not found")
    bound = store if store is not None else _bound_store()
    with bound.transaction() as connection:
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
        if receipt.replayed:
            existing = connection.execute(
                """
                SELECT proposal_id FROM case_edit_proposals
                WHERE project_id = ? AND source_job_id = ? AND kind = 'structure'
                ORDER BY rowid DESC LIMIT 1
                """,
                (str(project_id), str(job_id)),
            ).fetchone()
            if existing is not None:
                return StructureReceipt(job_id, UUID(str(existing[0])), version_id, False)

    try:
        model_content = _model_content(
            provider,
            raw_text.strip(),
            project_id=project_id,
            actor_id=actor.actor_id,
            secret_resolver=secret_resolver,
            store=bound,
        )
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
        with bound.transaction() as connection:
            connection.execute(
                "UPDATE jobs SET status = 'error' WHERE project_id = ? AND job_id = ?",
                (str(project_id), str(job_id)),
            )
        if isinstance(exc, ProposalSource):
            raise StructureRejected(str(exc) or "proposal source was rejected") from exc
        raise

    with bound.transaction() as connection:
        connection.execute(
            "UPDATE jobs SET status = 'completed' WHERE project_id = ? AND job_id = ? AND status IN ('queued', 'error')",
            (str(project_id), str(job_id)),
        )
    return StructureReceipt(job_id, proposal.proposal_id, version_id, False)


def _model_content(
    provider: object | None,
    raw_text: str,
    *,
    project_id: UUID,
    actor_id: UUID,
    secret_resolver: object | None,
    store: object,
) -> str:
    """Call the project structure binding through the server secret resolver. No fixture defaults."""

    if secret_resolver is None:
        raise StructureRejected(
            "model secret is unavailable",
            status=503,
            retryable=True,
        )
    if provider is None or getattr(provider, "complete", None) is None:
        raise StructureRejected(
            "model provider is not configured",
            status=503,
            retryable=True,
        )
    used = _structure_calls.get(str(project_id), 0)
    if used >= _STRUCTURE_BUDGET:
        raise StructureRejected("structure model budget is exhausted", status=429, retryable=True)
    with bind_model_store(store):  # type: ignore[arg-type]
        try:
            binding = load_latest_binding_for_role(project_id, _STRUCTURE_ROLE)
        except BindingNotFound as exc:
            raise StructureRejected(
                "structure model binding is required",
                status=422,
                retryable=True,
            ) from exc
    secret_ref = SecretRef(project_id, binding["key_ref_id"], int(binding["key_revision"]))  # type: ignore[arg-type]
    with bind_secret_store(store):  # type: ignore[arg-type]
        try:
            secret = secret_resolver.resolve_for_server(  # type: ignore[union-attr]
                secret_ref,
                RuntimeScope(project_id, actor_id),
            )
        except SecretScopeDenied as exc:
            raise StructureRejected("model secret is unavailable", status=403, retryable=True) from exc
        except SecretUnavailable as exc:
            raise StructureRejected("model secret is unavailable", status=503, retryable=True) from exc
    value = getattr(secret, "value", None)
    if type(value) is not str or value.strip() == "":
        raise StructureRejected("model secret is unavailable", status=503, retryable=True)
    try:
        result = provider.complete(  # type: ignore[union-attr]
            model=str(binding["model"]),
            role=_STRUCTURE_ROLE,
            secret=value,
            sanitized_inputs=(raw_text[:200],),
            token_output_limit=512,
        )
    except ProviderHttpError as exc:
        status = exc.status if type(exc.status) is int else 502
        retryable = status in {401, 403, 429, 502, 503} or status >= 500
        raise StructureRejected(
            str(exc.reason) or "structure model request failed",
            status=status,
            retryable=retryable,
        ) from exc
    except ValueError as exc:
        raise StructureRejected(str(exc) or "structure model request failed", status=422, retryable=True) from exc
    content = getattr(result, "content", None)
    if type(content) is not str or content.strip() == "":
        raise StructureRejected("structure model response is invalid", status=502, retryable=True)
    # Reject only explicit secret field echoes; substring matches on short keys are false positives.
    if len(value) >= 16 and value in content:
        raise StructureRejected("structure model response keeps hidden model text", status=422)
    _structure_calls[str(project_id)] = used + 1
    return content
