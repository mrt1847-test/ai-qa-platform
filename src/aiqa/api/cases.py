"""Case draft routes. Content revisions are insert-only."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlencode
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.routing import APIRouter
from aiqa.api.mutations import BrowserMutationRoute

from aiqa.api.auth import (
    AuthRequired,
    CsrfRejected,
    OriginRejected,
    ProjectHidden,
    authorize_browser,
    authorize_page,
    bound_auth_store,
)
from aiqa.contracts.cases import (
    CaseDefinition,
    CaseRevisionInput,
    CaseSettings,
    CaseVersionView,
    CheckSpec,
    PathPolicy,
    StepSpec,
)
from aiqa.web.routes import UiQueryState, render_template
from aiqa.domain.catalog import (
    ActiveRecording,
    CatalogNotFound,
    StaleRevision,
    archive_case,
    bind_catalog_actor,
    bind_catalog_store,
    clone_case,
    list_cases,
    update_case_metadata,
)
from aiqa.domain.proposals import (
    ProposalNotFound,
    ProposalSource,
    accept_case_proposal,
    bind_proposal_store,
    create_case_proposal,
    get_case_proposal,
    pending_proposal_text,
    reject_case_proposal,
)
from aiqa.recording.structure import (
    StructureRejected,
    definition_field_diff,
    request_structure,
)
from aiqa.store.queue import JobConflict
from aiqa.domain.hashing import CanonicalJsonError
from aiqa.recording.review_manifest import (
    ReviewConflict,
    ReviewRejected,
    request_review,
    review_action,
    review_board,
    review_notice,
    review_offline_gate,
)
from aiqa.domain.approvals import (
    ApprovalConflict,
    ApprovalInput,
    ApprovalRejected,
    RejectionInput,
    RevokeInput,
    approve_case,
    bind_approval_store,
    case_decision,
    reject_case,
    revoke_case,
    revoke_preview,
)
from aiqa.store.artifacts import ArtifactRejected, extend_review_retention, review_protection
from aiqa.domain.versions import (
    CaseNotFound,
    ForeignParent,
    ForeignSecretRef,
    SettingsRejected,
    StaleHead,
    bind_case_store,
    create_case,
    latest_draft,
    parse_case_settings,
    save_case_revision,
)
from aiqa.domain.versions import StepEditCommand, apply_step_edit
from aiqa.store.models import CaseListQuery, CaseProposalInput, CaseView, CloneCaseInput
from aiqa.store.database import migrate_store
from aiqa.store.models import SecretRef

router = APIRouter(prefix="/api/v1", route_class=BrowserMutationRoute)
pages = APIRouter(route_class=BrowserMutationRoute)


def install_cases(application: FastAPI) -> None:
    """Attach case routes once. This does not open SQLite."""

    if getattr(application.state, "cases_installed", False):
        return
    application.include_router(router)
    application.include_router(pages)
    application.state.cases_installed = True


@router.post("/projects/{project_id}/cases")
async def post_case(project_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    name = payload.get("name")
    if type(name) is not str or name.strip() == "":
        return _error(422, "validation", "invalid case", {"name": ["required"]})
    tc_reference = payload.get("tc_reference")
    if tc_reference is not None and type(tc_reference) is not str:
        return _error(422, "validation", "invalid case", {"tc_reference": ["invalid"]})
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "case")
            created = create_case(actor, name, tc_reference)
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except (ProjectHidden, CaseNotFound):
            return _error(404, "not_found", "case was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
    return JSONResponse(
        status_code=201,
        content={
            "case_id": str(created.case_id),
            "name": created.name,
            "tc_reference": created.tc_reference,
            "latest_draft_version_id": None,
        },
    )


@router.post("/projects/{project_id}/cases/{case_id}/versions")
async def post_version(project_id: str, case_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    parsed_case = _uuid(case_id)
    if isinstance(project, JSONResponse) or isinstance(parsed_case, JSONResponse):
        return _error(404, "not_found", "case was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    if "source_manifest_id" in payload or "proposal_id" in payload:
        return _error(422, "validation", "provenance is assigned by the server", {})
    try:
        revision = _revision(payload, project)
        expected_head = _optional_uuid(payload.get("expected_head"))
    except SettingsRejected as exc:
        return _settings_error(str(exc), exc.submitted)
    except ValueError:
        return _error(422, "validation", "invalid revision", {})
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "case")
            view = save_case_revision(actor, parsed_case, revision, expected_head)
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except (ProjectHidden, CaseNotFound):
            return _error(404, "not_found", "case was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except StaleHead:
            return _conflict(actor, parsed_case, payload)
        except ForeignParent:
            return _error(422, "validation", "parent version belongs to another case", {})
        except ForeignSecretRef:
            return _error(422, "validation", "secret ref was rejected", {})
        except CanonicalJsonError:
            return _error(422, "validation", "invalid variable", {})
    return JSONResponse(status_code=201, content=_view_json(view))



def _parse_editor_settings(payload, project):
    bindings=payload.get('verifier_bindings', [{'method':payload.get('verifier_method','deterministic'),'binding_id':payload.get('verifier_binding_id',''),'allow_unknown_supplement':payload.get('allow_unknown_supplement',False)}])
    if type(bindings) is not list or not bindings or any(type(item) is not dict for item in bindings):
        raise ValueError('invalid verifier bindings')
    for binding in bindings:
        flattened=dict(payload)
        flattened.update(verifier_method=binding.get('method','deterministic'),verifier_binding_id=binding.get('binding_id',''),allow_unknown_supplement=binding.get('allow_unknown_supplement',False))
        parsed=parse_case_settings(flattened,project)
    document=dict(payload)
    target=document.pop('target_kind')
    mode=document.pop('execution_mode','recorded_replay')
    # Preserve untouched extensions while canonicalizing the fields the server owns.
    for name,value in parsed.document.items():
        if name == 'verifier_bindings':
            document[name] = bindings
        elif name in {'limits','healing_policy'}:
            document[name] = {**(document.get(name,{}) if type(document.get(name,{})) is dict else {}), **value}
        else:
            document[name] = value
    return CaseSettings(target,mode,document)


def _pending_proposals(actor, case_id):
    from aiqa.domain.versions import _bound_store
    with _bound_store().transaction() as connection:
        rows=connection.execute("""SELECT p.proposal_id,p.body,p.base_version_id,p.kind FROM case_edit_proposals p
        WHERE p.project_id=? AND p.case_id=? AND NOT EXISTS(SELECT 1 FROM case_proposal_decisions d
        WHERE d.project_id=p.project_id AND d.proposal_id=p.proposal_id) ORDER BY p.rowid""",(str(actor.project_scope),str(case_id))).fetchall()
        head = connection.execute(
            "SELECT latest_draft_version_id FROM automation_cases WHERE project_id=? AND case_id=?",
            (str(actor.project_scope), str(case_id)),
        ).fetchone()
        current: dict[str, object] = {}
        if head is not None and head[0] is not None:
            definition = connection.execute(
                "SELECT definition_json FROM case_versions WHERE project_id=? AND version_id=?",
                (str(actor.project_scope), str(head[0])),
            ).fetchone()
            if definition is not None:
                try:
                    parsed = json.loads(str(definition[0]))
                except json.JSONDecodeError:
                    parsed = {}
                if type(parsed) is dict:
                    current = parsed
    items = []
    for row in rows:
        body = json.loads(row[1]) if type(row[1]) is str else row[1]
        if type(body) is not dict:
            body = {}
        items.append(
            {
                "proposal_id": str(row[0]),
                "body": body,
                "base_version_id": str(row[2]),
                "kind": str(row[3]),
                "changed_fields": definition_field_diff(current, body),
            }
        )
    return items


def _revision(payload: dict[str, object], project: UUID | None = None) -> CaseRevisionInput:
    definition = payload.get("definition")
    settings = payload.get("settings")
    if type(definition) is not dict or type(settings) is not dict:
        raise ValueError("invalid revision")
    if settings.get("wizard") is True:
        from aiqa.api.resources import apply_recording_wizard

        settings = apply_recording_wizard(settings)
        if definition.get("raw_text", "") == "" and type(settings.get("definition_buffer")) is str:
            definition = dict(definition)
            definition["raw_text"] = str(settings["definition_buffer"])
    target = settings.get("target_kind")
    if target not in {"web", "android"}:
        raise ValueError("invalid settings")
    recorded = payload.get("recorded_steps", [])
    if type(recorded) is not list:
        raise ValueError("invalid steps")
    parent = _optional_uuid(payload.get("parent_version_id"))
    base = _optional_uuid(payload.get("base_version_id"))
    reason = payload.get("reason", "")
    if type(reason) is not str:
        raise ValueError("invalid reason")
    branch = payload.get("branch", False)
    if type(branch) is not bool:
        raise ValueError("invalid branch")
    return CaseRevisionInput(
        definition=_definition(definition),
        settings=_parse_editor_settings(settings, project),
        recorded_steps=tuple(item for item in recorded if type(item) is dict),
        parent_version_id=parent,
        base_version_id=base,
        reason=reason,
        branch=branch,
    )


def _definition(payload: dict[str, object]) -> CaseDefinition:
    steps_raw = payload.get("steps", [])
    final_raw = payload.get("final_expected", [])
    policy = payload.get("path_policy", {})
    if type(steps_raw) is not list or type(final_raw) is not list or type(policy) is not dict:
        raise ValueError("invalid definition")
    raw_text = payload.get("raw_text", "")
    objective = payload.get("objective", "")
    preconditions = payload.get("preconditions", [])
    variables = payload.get("variables", {})
    secret_refs = payload.get("secret_refs", {})
    if type(raw_text) is not str or type(objective) is not str:
        raise ValueError("invalid definition")
    if type(preconditions) is not list or type(variables) is not dict or type(secret_refs) is not dict:
        raise ValueError("invalid definition")
    return CaseDefinition(
        raw_text=raw_text,
        objective=objective,
        preconditions=tuple(str(item) for item in preconditions),
        variables=dict(variables),
        secret_refs=_secret_refs(secret_refs),
        steps=tuple(_step(item) for item in steps_raw),
        final_expected=tuple(_check(item) for item in final_raw),
        path_policy=PathPolicy(
            must_use=tuple(str(item) for item in policy.get("must_use", [])),
            forbidden=tuple(str(item) for item in policy.get("forbidden", [])),
        ),
    )


def _step(payload: object) -> StepSpec:
    if type(payload) is not dict:
        raise ValueError("invalid step")
    expected = payload.get("expected", [])
    if type(expected) is not list or type(payload.get("id")) is not str or type(payload.get("instruction")) is not str:
        raise ValueError("invalid step")
    point = payload.get("point")
    parsed_point = None
    if point is not None:
        if type(point) is not list or len(point) != 2:
            raise ValueError("invalid point")
        parsed_point = (int(point[0]), int(point[1]))
    return StepSpec(
        id=str(payload["id"]),
        instruction=str(payload["instruction"]),
        expected=tuple(_check(item) for item in expected),
        point=parsed_point,
    )


def _check(payload: object) -> CheckSpec:
    if type(payload) is not dict:
        raise ValueError("invalid check")
    if type(payload.get("id")) is not str or type(payload.get("kind")) is not str or type(payload.get("expected")) is not str:
        raise ValueError("invalid check")
    return CheckSpec(id=str(payload["id"]), kind=str(payload["kind"]), expected=str(payload["expected"]))


def _secret_refs(payload: dict[str, object]) -> dict[str, SecretRef]:
    refs: dict[str, SecretRef] = {}
    for name, value in payload.items():
        if type(value) is not dict:
            raise ValueError("invalid secret ref")
        if any(key in value for key in ("value", "secret", "secret_plaintext", "secret_value")):
            raise ValueError("invalid secret ref")
        refs[str(name)] = SecretRef(
            project_id=UUID(str(value.get("project_id"))),
            ref_id=UUID(str(value.get("ref_id"))),
            revision=int(value.get("revision")),
        )
    return refs


def _optional_uuid(value: object) -> UUID | None:
    if value is None:
        return None
    return UUID(str(value))


def _conflict(actor: object, case_id: UUID, payload: dict[str, object]) -> JSONResponse:
    from aiqa.store.models import Actor

    assert isinstance(actor, Actor)
    server = latest_draft(actor, case_id) or {"version_id": None, "raw_text": "", "objective": ""}
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": "conflict",
                "message": "draft head changed",
                "fields": {},
                "retryable": False,
                "request_id": str(uuid4()),
            },
            "submitted": _public_definition(payload.get("definition")),
            "server_snapshot": _editor_snapshot(actor, case_id),
            "server": {
                "version_id": server["version_id"],
                "raw_text": server["raw_text"],
                "objective": server["objective"],
            },
        },
    )


def _public_definition(value: object) -> dict[str, object]:
    if type(value) is not dict:
        return {}
    secret_refs = value.get("secret_refs", {})
    public_refs: dict[str, object] = {}
    if type(secret_refs) is dict:
        for name, ref in secret_refs.items():
            if type(ref) is not dict:
                continue
            public_refs[str(name)] = {
                "project_id": ref.get("project_id"),
                "ref_id": ref.get("ref_id"),
                "revision": ref.get("revision"),
            }
    return {
        "raw_text": value.get("raw_text", ""),
        "objective": value.get("objective", ""),
        "preconditions": value.get("preconditions", []),
        "variables": value.get("variables", {}),
        "secret_refs": public_refs,
        "steps": value.get("steps", []),
        "final_expected": value.get("final_expected", []),
        "path_policy": value.get("path_policy", {}),
    }


def _view_json(view: CaseVersionView) -> dict[str, object]:
    return {
        "project_id": str(view.project_id),
        "case_id": str(view.case_id),
        "id": str(view.id),
        "revision": view.revision,
        "creation_kind": view.creation_kind,
        "parent_version_id": None if view.parent_version_id is None else str(view.parent_version_id),
        "base_version_id": None if view.base_version_id is None else str(view.base_version_id),
        "content_hash": view.content_hash,
        "verification_digest": view.verification_digest,
        "replay_package_id": None,
        "readiness": {
            "saved": view.readiness.saved,
            "recordable": view.readiness.recordable,
            "replayable": view.readiness.replayable,
            "reviewable": view.readiness.reviewable,
            "formal_runnable": view.readiness.formal_runnable,
            "reasons": [{"code": reason.code, "message": reason.message} for reason in view.readiness.reasons],
        },
    }


@router.post("/projects/{project_id}/cases/{case_id}/versions/{version_id}/structure")
async def post_structure(project_id: str, case_id: str, version_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    parsed_case = _uuid(case_id)
    parsed_version = _uuid(version_id)
    if isinstance(project, JSONResponse) or isinstance(parsed_case, JSONResponse) or isinstance(parsed_version, JSONResponse):
        return _error(404, "not_found", "case was not found", {})
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "case")
            from aiqa.domain.versions import _bound_store as _case_store

            row = _case_store()._connection.execute(
                "SELECT case_id FROM case_versions WHERE project_id=? AND version_id=?",
                (str(project), str(parsed_version)),
            ).fetchone()
            if row is None or str(row[0]) != str(parsed_case):
                return _error(404, "not_found", "case was not found", {})
            gateway = getattr(request.app.state, "model_gateway", None)
            provider = getattr(gateway, "provider", None) if gateway is not None else None
            receipt = request_structure(
                actor,
                project,
                parsed_version,
                request_key=request.headers.get("idempotency-key", "").strip(),
                provider=provider,
                secret_resolver=getattr(request.app.state, "secret_resolver", None),
                store=_case_store(),
            )
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "case was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except JobConflict:
            return _error(409, "conflict", "idempotency body does not match", {})
        except StructureRejected as exc:
            message = str(exc) or "structure was rejected"
            status = exc.status if type(exc.status) is int else 422
            if "hidden" in message:
                message = "proposal source was rejected"
                status = 422
            code = "validation"
            if status in {401, 403}:
                code = "permission"
            elif status == 429:
                code = "quota"
            elif status >= 500:
                code = "upstream"
            return JSONResponse(
                status_code=status,
                content={
                    "error": {
                        "code": code,
                        "message": message,
                        "fields": {},
                        "retryable": bool(exc.retryable) or status in {401, 403, 429} or status >= 500,
                        "request_id": str(uuid4()),
                    }
                },
            )
    return JSONResponse(
        status_code=201,
        content={
            "job_id": str(receipt.job_id),
            "proposal_id": str(receipt.proposal_id),
            "base_version_id": str(receipt.base_version_id),
            "auto_applied": receipt.auto_applied,
        },
    )


@router.post("/projects/{project_id}/cases/{case_id}/proposals")
async def post_proposal(project_id: str, case_id: str, request: Request) -> JSONResponse:
    return await _create_proposal(project_id, case_id, request, None)


@router.post("/projects/{project_id}/cases/{case_id}/tc-import-proposals")
async def post_tc_import_proposal(project_id: str, case_id: str, request: Request) -> JSONResponse:
    return await _create_proposal(project_id, case_id, request, "tc_import")


@router.post("/projects/{project_id}/cases/{case_id}/proposal-acceptances")
async def post_proposal_acceptance(project_id: str, case_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    parsed_case = _uuid(case_id)
    if isinstance(project, JSONResponse) or isinstance(parsed_case, JSONResponse):
        return _error(404, "not_found", "proposal was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    try:
        proposal_id = UUID(str(payload.get("proposal_id")))
        expected_head = UUID(str(payload.get("expected_head")))
    except (TypeError, ValueError):
        return _error(422, "validation", "invalid proposal acceptance", {})
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "case")
            view = accept_case_proposal(actor, proposal_id, expected_head)
            if view.case_id != parsed_case:
                return _error(404, "not_found", "proposal was not found", {})
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except (ProjectHidden, ProposalNotFound, CaseNotFound):
            return _error(404, "not_found", "proposal was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except StaleHead:
            return _error(409, "conflict", "draft head changed", {})
        except ProposalSource:
            return _error(422, "validation", "proposal source was rejected", {})
    return JSONResponse(status_code=201, content=_view_json(view))


@router.post("/projects/{project_id}/cases/{case_id}/proposal-rejections")
async def post_proposal_rejection(project_id: str, case_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    parsed_case = _uuid(case_id)
    if isinstance(project, JSONResponse) or isinstance(parsed_case, JSONResponse):
        return _error(404, "not_found", "proposal was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    try:
        proposal_id = UUID(str(payload.get("proposal_id")))
    except (TypeError, ValueError):
        return _error(422, "validation", "invalid proposal rejection", {})
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "case")
            stored = get_case_proposal(actor, proposal_id)
            if stored.case_id != parsed_case:
                return _error(404, "not_found", "proposal was not found", {})
            reject_case_proposal(actor, proposal_id)
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except (ProjectHidden, ProposalNotFound):
            return _error(404, "not_found", "proposal was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
    return JSONResponse(status_code=200, content={"proposal_id": str(proposal_id), "produced_version_id": None})


@router.get("/projects/{project_id}/cases/{case_id}/proposals/{proposal_id}")
async def get_proposal(project_id: str, case_id: str, proposal_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    parsed_case = _uuid(case_id)
    parsed_proposal = _uuid(proposal_id)
    if isinstance(project, JSONResponse) or isinstance(parsed_case, JSONResponse) or isinstance(parsed_proposal, JSONResponse):
        return _error(404, "not_found", "proposal was not found", {})
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "case")
            stored = get_case_proposal(actor, parsed_proposal)
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except (ProjectHidden, ProposalNotFound):
            return _error(404, "not_found", "proposal was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
    if stored.case_id != parsed_case:
        return _error(404, "not_found", "proposal was not found", {})
    return JSONResponse(status_code=200, content=_proposal_json(stored))


async def _create_proposal(
    project_id: str, case_id: str, request: Request, forced_kind: str | None
) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    parsed_case = _uuid(case_id)
    if isinstance(project, JSONResponse) or isinstance(parsed_case, JSONResponse):
        return _error(404, "not_found", "proposal was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    body = payload.get("body")
    kind = forced_kind if forced_kind is not None else payload.get("kind")
    if type(body) is not dict or kind not in {"structure", "tc_import"}:
        return _error(422, "validation", "invalid proposal", {})
    try:
        proposal = CaseProposalInput(
            case_id=parsed_case,
            base_version_id=UUID(str(payload.get("base_version_id"))),
            base_hash=str(payload.get("base_hash")),
            kind=str(kind),
            body=body,
            source_job_id=None if payload.get("source_job_id") is None else UUID(str(payload.get("source_job_id"))),
            tc_version_id=None if payload.get("tc_version_id") is None else UUID(str(payload.get("tc_version_id"))),
        )
    except (TypeError, ValueError):
        return _error(422, "validation", "invalid proposal", {})
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "case")
            created = create_case_proposal(actor, proposal)
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except (ProjectHidden, ProposalNotFound, CaseNotFound):
            return _error(404, "not_found", "proposal was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except ProposalSource:
            return _error(422, "validation", "proposal source was rejected", {})
    return JSONResponse(status_code=201, content=_proposal_json(created))


def _proposal_json(proposal: object) -> dict[str, object]:
    from aiqa.store.models import CaseProposalView

    assert isinstance(proposal, CaseProposalView)
    return {
        "proposal_id": str(proposal.proposal_id),
        "case_id": str(proposal.case_id),
        "base_version_id": str(proposal.base_version_id),
        "base_hash": proposal.base_hash,
        "kind": proposal.kind,
        "body": proposal.body,
        "body_hash": proposal.body_hash,
        "source_job_id": None if proposal.source_job_id is None else str(proposal.source_job_id),
        "tc_version_id": None if proposal.tc_version_id is None else str(proposal.tc_version_id),
    }


@pages.get("/ui/projects/{project_id}/cases/run", response_class=HTMLResponse)
async def case_run_page(project_id: str, request: Request) -> HTMLResponse:
    return _entry_page(project_id, request, "run", "실행", "이 화면은 실행을 시작하지 않습니다.")


@pages.post("/ui/projects/{project_id}/cases/bulk")
async def case_bulk_page(project_id: str, request: Request) -> JSONResponse:
    return await _bulk(project_id, request, page=True)


@pages.get("/ui/projects/{project_id}/cases", response_class=HTMLResponse)
async def case_list_page(project_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return HTMLResponse(status_code=404, content="프로젝트를 찾지 못했습니다.")
    query = _case_query(project, request)
    if isinstance(query, JSONResponse):
        return HTMLResponse(status_code=422, content="목록 조건을 다시 확인해 주세요.")
    with _bound(request):
        try:
            actor = authorize_page(request, project)
            with bind_catalog_actor(actor):
                page = list_cases(query)
        except AuthRequired:
            return _case_screen(request, project, query, (), "forbidden")
        except _CATALOG_ERRORS:
            return _case_screen(request, project, query, (), "forbidden")
    context = _case_context(request, project, query, page.items, "empty" if page.items == () else "ready", page.next_cursor)
    context.update(total=page.total, range_start=page.start, range_end=page.end, previous_cursor=page.previous_cursor)
    scope = {"q": query.text, "sort": query.sort, "view": query.view, "limit":query.limit,"archived":str(query.archived).lower()}
    context["first_href"] = f"/ui/projects/{project}/cases?" + urlencode(scope)
    context["next_href"] = context["first_href"] + "&cursor=" + (page.next_cursor or "")
    context["previous_href"] = context["first_href"] + ("&cursor=" + page.previous_cursor if page.previous_cursor else "")
    return render_template(request, "cases.html", context)


@pages.get("/ui/projects/{project_id}/cases/{case_id}", response_class=HTMLResponse)
async def case_place_page(project_id: str, case_id: str, request: Request) -> HTMLResponse:
    return await case_definition_page(project_id, case_id, request)


@pages.get("/ui/projects/{project_id}/cases/{case_id}/run", response_class=HTMLResponse)
async def case_single_run_page(project_id: str, case_id: str, request: Request) -> HTMLResponse:
    return _entry_page(project_id, request, "run", "실행", "이 화면은 실행을 시작하지 않습니다.", case_id)


@router.get("/case-versions/{version_id}/replay-package")
async def get_replay_package(version_id: str, request: Request) -> JSONResponse:
    parsed = _uuid(version_id)
    if isinstance(parsed, JSONResponse):
        return _error(404, "not_found", "package was not found", {})
    from aiqa.domain.versions import _bound_store
    from aiqa.replay.packages import load_replay_package_view

    with _bound(request):
        with _bound_store().transaction() as connection:
            owner = connection.execute(
                "SELECT project_id FROM case_versions WHERE version_id = ?",
                (str(parsed),),
            ).fetchone()
        if owner is None:
            return _error(404, "not_found", "package was not found", {})
        try:
            actor = authorize_browser(request, UUID(str(owner[0])), "replay_package")
            with _bound_store().transaction() as connection:
                view = load_replay_package_view(connection, actor.project_scope, parsed)
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "package was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
    if view is None:
        return _error(404, "not_found", "package was not found", {})
    return JSONResponse(status_code=200, content=_package_json(view))


@router.post("/case-versions/{version_id}/review-requests")
async def post_review_request(version_id: str, request: Request) -> JSONResponse:
    parsed = _uuid(version_id)
    if isinstance(parsed, JSONResponse):
        return parsed
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    actor = getattr(request.state, "browser_actor", None)
    if actor is None or actor.project_scope is None:
        return _error(401, "unauthorized", "session is missing", {})
    with _bound(request):
        try:
            store = request.app.state.open_store()
            try:
                with store.transaction() as connection:
                    snapshot = request_review(connection, actor.project_scope, parsed, payload)
            finally:
                store.close()
        except ReviewRejected as exc:
            return _error(422, "validation", exc.reason, {})
        except ProjectHidden:
            return _error(404, "not_found", "review was not found", {})
    return JSONResponse(
        status_code=201,
        content={
            "id": str(snapshot.review_id),
            "case_version_id": str(snapshot.case_version_id),
            "version_hash": snapshot.version_hash,
            "source_manifest_id": str(snapshot.source_manifest_id),
            "source_manifest_hash": snapshot.source_manifest_hash,
            "trial_case_run_id": str(snapshot.trial_case_run_id),
            "final_result_hash": snapshot.final_result_hash,
            "evidence_set_hash": snapshot.evidence_set_hash,
            "created_commit_seq": snapshot.created_commit_seq,
            "retain_days": snapshot.retain_days,
        },
    )


@router.post("/case-versions/{version_id}/action-reviews")
async def post_action_review(version_id: str, request: Request) -> JSONResponse:
    parsed = _uuid(version_id)
    if isinstance(parsed, JSONResponse):
        return parsed
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    actor = getattr(request.state, "browser_actor", None)
    if actor is None or actor.project_scope is None:
        return _error(401, "unauthorized", "session is missing", {})
    with _bound(request):
        try:
            store = request.app.state.open_store()
            try:
                with store.transaction() as connection:
                    view = review_action(connection, actor.project_scope, parsed, actor.actor_id, payload)
            finally:
                store.close()
        except ReviewConflict as exc:
            return _error(409, "conflict", exc.reason, {})
        except ReviewRejected as exc:
            return _error(422, "validation", exc.reason, {})
        except ProjectHidden:
            return _error(404, "not_found", "review was not found", {})
    return JSONResponse(
        status_code=201,
        content={
            "review_id": str(view.review_id),
            "entry_id": str(view.entry_id),
            "owner_kind": view.owner_kind,
            "owner_id": view.owner_id,
            "attempt_id": view.attempt_id,
            "action_id": view.action_id,
            "evidence_digest": view.evidence_digest,
            "state": view.state,
            "actor_id": str(view.actor_id),
            "created_at": view.created_at,
            "comment": view.comment,
            "history_count": view.history_count,
            "latest_state": view.latest_state,
            "source_reviewed": view.source_reviewed,
            "source_total": view.source_total,
            "trial_reviewed": view.trial_reviewed,
            "trial_total": view.trial_total,
            "next_unreviewed_entry_id": view.next_unreviewed_entry_id,
        },
    )


@router.post("/review-requests/{review_id}/retention-extensions")
async def post_retention_extension(review_id: str, request: Request) -> JSONResponse:
    parsed = _uuid(review_id)
    if isinstance(parsed, JSONResponse):
        return parsed
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    actor = getattr(request.state, "browser_actor", None)
    if actor is None or actor.project_scope is None:
        return _error(401, "unauthorized", "session is missing", {})
    artifact_text = payload.get("artifact_id")
    reason = payload.get("reason")
    if type(artifact_text) is not str or type(reason) is not str:
        return _error(422, "validation", "retention extension is invalid", {})
    try:
        artifact_id = UUID(artifact_text)
    except ValueError:
        return _error(422, "validation", "retention extension is invalid", {})
    with _bound(request):
        try:
            store = request.app.state.open_store()
            try:
                with store.transaction() as connection:
                    receipt = extend_review_retention(
                        connection, actor.project_scope, parsed, artifact_id, reason
                    )
            finally:
                store.close()
        except ArtifactRejected as exc:
            return _error(422, "validation", str(exc), {})
        except ProjectHidden:
            return _error(404, "not_found", "review was not found", {})
    return JSONResponse(
        status_code=201,
        content={
            "protection_id": str(receipt.protection_id),
            "review_id": str(receipt.review_id),
            "artifact_id": str(receipt.artifact_id),
            "reason": receipt.reason,
            "expires_at": receipt.expires_at,
            "prior_expires_at": receipt.prior_expires_at,
            "event_count": receipt.event_count,
            "approve_allowed": receipt.approve_allowed,
            "temporary": receipt.temporary,
        },
    )


@router.post("/case-versions/{version_id}/approvals")
async def post_approval(version_id: str, request: Request) -> JSONResponse:
    parsed = _uuid(version_id)
    if isinstance(parsed, JSONResponse):
        return parsed
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    actor = getattr(request.state, "browser_actor", None)
    if actor is None or actor.project_scope is None:
        return _error(401, "unauthorized", "session is missing", {})
    approval = _approval_input(parsed, payload)
    if isinstance(approval, JSONResponse):
        return approval
    store = request.app.state.open_store()
    try:
        with bind_approval_store(store):
            receipt = approve_case(actor, approval)
    except ApprovalConflict as exc:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "conflict",
                    "message": exc.reason,
                    "fields": {},
                    "retryable": False,
                    "request_id": str(uuid4()),
                },
                "current_approval_id": exc.current_approval_id,
                "kept_input": True,
            },
        )
    except ApprovalRejected as exc:
        return _error(422, "validation", exc.reason, {})
    finally:
        store.close()
    return JSONResponse(
        status_code=201,
        content={
            "approval_id": str(receipt.approval_id),
            "review_id": str(receipt.review_id),
            "case_id": str(receipt.case_id),
            "case_version_id": str(receipt.case_version_id),
            "previous_default_id": None if receipt.previous_default_id is None else str(receipt.previous_default_id),
            "audit_id": str(receipt.audit_id),
            "protection_ids": [str(item) for item in receipt.protection_ids],
        },
    )


def _approval_input(version_id: UUID, payload: dict[str, object]) -> ApprovalInput | JSONResponse:
    review_text = payload.get("review_id")
    version_hash = payload.get("version_hash")
    evidence_hash = payload.get("evidence_set_hash")
    reason = payload.get("reason")
    if "expected_current_approval_id" not in payload:
        return _error(422, "validation", "approval input is invalid", {})
    expected_text = payload.get("expected_current_approval_id")
    if type(review_text) is not str or type(version_hash) is not str or type(evidence_hash) is not str or type(reason) is not str:
        return _error(422, "validation", "approval input is invalid", {})
    if expected_text is not None and type(expected_text) is not str:
        return _error(422, "validation", "approval input is invalid", {})
    try:
        review_id = UUID(review_text)
        expected = None if expected_text is None else UUID(expected_text)
    except ValueError:
        return _error(422, "validation", "approval input is invalid", {})
    return ApprovalInput(review_id, version_id, version_hash, evidence_hash, expected, reason)


@router.post("/case-versions/{version_id}/rejections")
async def post_rejection(version_id: str, request: Request) -> JSONResponse:
    parsed = _uuid(version_id)
    if isinstance(parsed, JSONResponse):
        return parsed
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    actor = getattr(request.state, "browser_actor", None)
    if actor is None or actor.project_scope is None:
        return _error(401, "unauthorized", "session is missing", {})
    review_text = payload.get("review_id")
    version_hash = payload.get("version_hash")
    reason = payload.get("reason")
    if type(review_text) is not str or type(version_hash) is not str or type(reason) is not str:
        return _error(422, "validation", "rejection input is invalid", {})
    try:
        rejection = RejectionInput(UUID(review_text), parsed, version_hash, reason)
    except ValueError:
        return _error(422, "validation", "rejection input is invalid", {})
    store = request.app.state.open_store()
    try:
        with bind_approval_store(store):
            receipt = reject_case(actor, rejection)
    except ApprovalConflict as exc:
        return _error(409, "conflict", exc.reason, {})
    except ApprovalRejected as exc:
        return _error(422, "validation", exc.reason, {})
    finally:
        store.close()
    return JSONResponse(
        status_code=201,
        content={
            "decision_id": str(receipt.decision_id),
            "review_id": str(receipt.review_id),
            "case_id": str(receipt.case_id),
            "case_version_id": str(receipt.case_version_id),
            "state": receipt.state,
            "reason": receipt.reason,
            "actor_id": str(receipt.actor_id),
            "created_at": receipt.created_at,
            "version_hash": receipt.version_hash,
            "current_approval_id": None if receipt.current_approval_id is None else str(receipt.current_approval_id),
        },
    )


@router.post("/approvals/{approval_id}/revoke")
async def post_revoke(approval_id: str, request: Request) -> JSONResponse:
    parsed = _uuid(approval_id)
    if isinstance(parsed, JSONResponse):
        return parsed
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    actor = getattr(request.state, "browser_actor", None)
    if actor is None or actor.project_scope is None:
        return _error(401, "unauthorized", "session is missing", {})
    reason = payload.get("reason")
    if "expected_current_approval_id" not in payload or type(reason) is not str:
        return _error(422, "validation", "revoke input is invalid", {})
    expected_text = payload.get("expected_current_approval_id")
    if expected_text is not None and type(expected_text) is not str:
        return _error(422, "validation", "revoke input is invalid", {})
    try:
        expected = None if expected_text is None else UUID(expected_text)
    except ValueError:
        return _error(422, "validation", "revoke input is invalid", {})
    store = request.app.state.open_store()
    try:
        with bind_approval_store(store):
            receipt = revoke_case(actor, RevokeInput(parsed, expected, reason))
    except ApprovalConflict as exc:
        return _error(409, "conflict", exc.reason, {})
    except ApprovalRejected as exc:
        return _error(422, "validation", exc.reason, {})
    finally:
        store.close()
    return JSONResponse(
        status_code=201,
        content={
            "revoke_id": str(receipt.revoke_id),
            "approval_id": str(receipt.approval_id),
            "case_id": str(receipt.case_id),
            "current_approval_id": None if receipt.current_approval_id is None else str(receipt.current_approval_id),
            "queued_blocked": receipt.queued_blocked,
            "running_cancelled": receipt.running_cancelled,
            "grace_until": receipt.grace_until,
            "fallback": receipt.fallback,
        },
    )


@pages.get("/ui/projects/{project_id}/cases/{case_id}/review", response_class=HTMLResponse)
async def case_review_page(project_id: str, case_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    parsed = _uuid(case_id) if case_id is not None else None
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse) or parsed is None:
        return HTMLResponse(status_code=404, content="케이스를 찾지 못했습니다.")
    query = _case_query(project, request)
    if isinstance(query, JSONResponse):
        return HTMLResponse(status_code=422, content="목록 조건을 다시 확인해 주세요.")
    notice = "화면 방문만으로 승인하지 않습니다. 저장된 기록을 확인한 뒤 명시적으로 검토·승인합니다."
    board = None
    readiness = None
    protection = None
    decision = None
    revoke = None
    offline_gate = None
    selected = request.query_params.get('entry', '')
    selection = None
    review_entry = None
    actions = ()
    candidates = []
    with _bound(request):
        try:
            authorize_page(request, project)
            store = request.app.state.open_store()
            try:
                with store.transaction() as connection:
                    case_row = connection.execute('SELECT name FROM automation_cases WHERE project_id=? AND case_id=?',(str(project),str(parsed))).fetchone()
                    if case_row is None:
                        return HTMLResponse(status_code=404,content='케이스를 찾지 못했습니다.')
                    extra = review_notice(connection, project, parsed)
                    latest = connection.execute(
                        """
                        SELECT version_id FROM case_versions
                        WHERE project_id = ? AND case_id = ?
                        ORDER BY revision DESC
                        LIMIT 1
                        """,
                        (str(project), str(parsed)),
                    ).fetchone()
                    if latest is not None:
                        try:
                            version_uuid = UUID(str(latest[0]))
                        except ValueError:
                            version_uuid = None
                        if version_uuid is not None:
                            readiness = load_review_readiness(connection, project, version_uuid)
                            board = review_board(connection, project, parsed, version_uuid)
                            from aiqa.web.review_context import review_candidates
                            candidates = review_candidates(connection, project, parsed, version_uuid)
                            offline_gate = review_offline_gate(connection, project, parsed, version_uuid)
                    if board and board.entries:
                        if selected and not any(entry.entry_id == selected for entry in board.entries):
                            return HTMLResponse(status_code=404,content='이 검토에 속한 단계가 아닙니다.')
                        selected = selected or board.next_unreviewed_entry_id or board.entries[0].entry_id
                        entry = next(entry for entry in board.entries if entry.entry_id == selected)
                        from aiqa.api.artifacts import EvidenceViewerSelection, _viewer
                        from datetime import datetime, timezone
                        selection = EvidenceViewerSelection(entry.owner_kind, entry.owner_id, entry.attempt_id, entry.action_id)
                        pinned_artifacts = frozenset(str(row[0]) for row in connection.execute('SELECT artifact_ref_id FROM review_evidence_entries WHERE project_id=? AND entry_id IN (SELECT entry_id FROM review_evidence_entries WHERE project_id=? AND review_id=(SELECT review_id FROM review_evidence_entries WHERE project_id=? AND entry_id=?)) AND owner_kind=? AND owner_id=? AND attempt_id=? AND action_id=?',(str(project),str(project),str(project),selected,entry.owner_kind,entry.owner_id,entry.attempt_id,entry.action_id)))
                        viewer = _viewer(connection, store.config.artifacts_dir, project, selection, datetime.now(timezone.utc), pinned_artifacts)
                        actions = tuple(action for action in viewer.actions if action.action_id == entry.action_id)
                        pinned = connection.execute('SELECT e.review_id,e.evidence_digest,r.case_version_id FROM review_evidence_entries e JOIN reviews r ON r.project_id=e.project_id AND r.review_id=e.review_id WHERE e.project_id=? AND e.entry_id=?',(str(project),selected)).fetchone()
                        review_entry = {'review_id':str(pinned[0]),'entry_key':selected,'evidence_digest':str(pinned[1]),'version_id':str(pinned[2])}
                    elif selected:
                        return HTMLResponse(status_code=404,content='검토할 저장 근거가 없습니다.')
                    try:
                        protection = review_protection(connection, project, parsed)
                    except ValueError:
                        protection = None
                    try:
                        decision = case_decision(connection, project, parsed)
                    except ValueError:
                        decision = None
                    try:
                        revoke = revoke_preview(connection, project, parsed)
                    except ValueError:
                        revoke = None
            finally:
                store.close()
        except _CATALOG_ERRORS:
            return _case_screen(request, project, query, (), "forbidden")
    if extra:
        notice = notice + " " + extra
    return render_template(
        request,
        "case_review.html",
        {
            "notice": notice,
            "board": board,
            "readiness": readiness,
            "protection": protection,
            "decision": decision,
            "revoke": revoke,
            "offline_gate": offline_gate,
            "selected": selected,
            "case_name":str(case_row[0]),"selection":selection,"actions":actions,"review_entry":review_entry,"embedded":True,
            "review_candidates": candidates,
            "crumbs":((str(case_row[0]),f'/ui/projects/{project}/cases/{parsed}'),('저장본 검토','')),
            "tab": request.query_params.get("tab", "input"),
            "intent": request.query_params.get("intent", ""),
            "case_id": str(parsed),
            "project_id": str(project),
        },
    )


@router.get("/case-versions/{version_id}/review-readiness")
async def get_review_readiness(version_id: str, request: Request) -> JSONResponse:
    parsed = _uuid(version_id)
    if isinstance(parsed, JSONResponse):
        return parsed
    with _bound(request):
        project = _project_of_version(parsed)
        if project is None:
            return _error(404, "not_found", "review was not found", {})
        try:
            actor = authorize_browser(request, project, "case")
            store = request.app.state.open_store()
            try:
                with store.transaction() as connection:
                    readiness = load_review_readiness(connection, actor.project_scope, parsed)
            finally:
                store.close()
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "review was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
    if readiness is None:
        return _error(404, "not_found", "review was not found", {})
    return JSONResponse(status_code=200, content=readiness)


@pages.get("/ui/projects/{project_id}/cases/{case_id}/definition", response_class=HTMLResponse)
async def case_definition_page(project_id: str, case_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    parsed = _uuid(case_id)
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return HTMLResponse(status_code=404, content="케이스를 찾지 못했습니다.")
    query = _case_query(project, request)
    if isinstance(query, JSONResponse):
        return HTMLResponse(status_code=422, content="목록 조건을 다시 확인해 주세요.")
    with _bound(request):
        try:
            actor = authorize_page(request, project)
            draft = latest_draft(actor, parsed)
            snapshot = _editor_snapshot(actor, parsed)
            selected = request.query_params.get("version")
            board = _case_board(actor, parsed, None if selected in {None, ""} else UUID(selected))
        except _CATALOG_ERRORS:
            return _case_screen(request, project, query, (), "forbidden")
        except ValueError:
            return HTMLResponse(status_code=422, content="버전을 다시 확인해 주세요.")
    if draft is None or board is None:
        return HTMLResponse(status_code=404, content="케이스를 찾지 못했습니다.")
    context = _case_context(request, project, query, (), "ready", None)
    context["draft"] = draft
    context["snapshot"] = snapshot
    context["case_id"] = str(parsed)
    context["tab"] = request.query_params.get("tab", "definition")
    if selected and selected != board['latest_draft_version_id']:
        context['tab'] = 'versions'
    context["board"] = board
    context["crumbs"] = (*context["crumbs"], (board["case_name"], ""))
    return render_template(request, "case_detail.html", context)


@pages.post("/ui/projects/{project_id}/cases/{case_id}/definition")
async def case_definition_save(project_id: str, case_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    parsed_case = _uuid(case_id)
    if isinstance(project, JSONResponse) or isinstance(parsed_case, JSONResponse):
        return _error(404, "not_found", "case was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    try:
        revision = _revision(payload, project)
        expected_head = _optional_uuid(payload.get("expected_head"))
    except SettingsRejected as exc:
        return _settings_error(str(exc), exc.submitted)
    except ValueError:
        return _error(422, "validation", "invalid revision", {})
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "case")
            view = save_case_revision(actor, parsed_case, revision, expected_head)
        except StaleHead:
            return _conflict(actor, parsed_case, payload)
        except ForeignSecretRef:
            return _error(422, "validation", "secret ref was rejected", {})
        except CanonicalJsonError:
            return _error(422, "validation", "invalid variable", {})
        except _CATALOG_ERRORS as exc:
            return _catalog_response(exc)
    return JSONResponse(status_code=201, content=_view_json(view))


@pages.get("/ui/projects/{project_id}/cases/{case_id}/settings", response_class=HTMLResponse)
async def case_settings_page(project_id: str, case_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    parsed = _uuid(case_id)
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return HTMLResponse(status_code=404, content="케이스를 찾지 못했습니다.")
    query = _case_query(project, request)
    if isinstance(query, JSONResponse):
        return HTMLResponse(status_code=422, content="목록 조건을 다시 확인해 주세요.")
    with _bound(request):
        try:
            actor = authorize_page(request, project)
            current = _settings_view(actor, parsed)
        except _CATALOG_ERRORS:
            return _case_screen(request, project, query, (), "forbidden")
    if current is None:
        return HTMLResponse(status_code=404, content="케이스를 찾지 못했습니다.")
    context = _case_context(request, project, query, (), "ready", None)
    context["case_id"] = str(parsed)
    context.update(current)
    from aiqa.api.resources import _bound as asset_bound
    from aiqa.domain.environments import list_environment_profiles
    from aiqa.domain.datasets import list_datasets
    from aiqa.api.settings import _read as read_project_settings
    with asset_bound(request):
        context['profiles'] = list_environment_profiles(project)
        context['datasets'] = list_datasets(project)
    with _bound(request):
        actor = authorize_page(request, project)
        context["snapshot"] = _editor_snapshot(actor, parsed)
        context['bindings'] = read_project_settings(project)['bindings']
    return render_template(request, "case_settings.html", context)


@pages.post("/ui/projects/{project_id}/cases/{case_id}/settings")
async def case_settings_save(project_id: str, case_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    parsed = _uuid(case_id)
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return _error(404, "not_found", "case was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "case")
            loaded = _stored_definition_for_settings(actor, parsed)
            if loaded is None:
                return _error(404, "not_found", "case was not found", {})
            definition, head = loaded
            snapshot = _editor_snapshot(actor, parsed)
            expected = _optional_uuid(payload.get("expected_head"))
            if expected is None:
                expected = head
            revision = CaseRevisionInput(
                definition=definition,
                settings=_parse_editor_settings(_merged_settings(snapshot["settings"], payload), project),
                recorded_steps=tuple(snapshot["recorded_steps"]),
                reason="settings",
            )
            view = save_case_revision(actor, parsed, revision, expected)
        except SettingsRejected as exc:
            return _settings_error(str(exc), exc.submitted)
        except StaleHead:
            response = _settings_error("draft head changed", _public_form(payload), 409)
            body=json.loads(response.body)
            body['server_snapshot']=_editor_snapshot(actor,parsed)
            return JSONResponse(status_code=409,content=body)
        except _CATALOG_ERRORS as exc:
            return _catalog_response(exc)
    return JSONResponse(status_code=201, content=_view_json(view))



def _editor_snapshot(actor, case_id):
    from aiqa.domain.versions import _bound_store
    with _bound_store().transaction() as connection:
        row=connection.execute("""SELECT v.version_id,v.definition_json,v.settings_json,v.recorded_steps_json
            FROM automation_cases c LEFT JOIN case_versions v ON v.project_id=c.project_id
            AND v.version_id=c.latest_draft_version_id WHERE c.project_id=? AND c.case_id=?""",
            (str(actor.project_scope),str(case_id))).fetchone()
    if row is None:
        return None
    definition={'raw_text':'','objective':'','preconditions':[],'variables':{},'secret_refs':{},'steps':[],'final_expected':[],'path_policy':{'must_use':[],'forbidden':[]}} if row[1] is None else json.loads(row[1])
    return {'definition':definition,'settings':{'target_kind':'web'} if row[2] is None else json.loads(row[2]),
            'recorded_steps':[] if row[3] is None else json.loads(row[3]),'expected_head':row[0],
            'parent_version_id':row[0],'base_version_id':None,'branch':False,'reason':'draft'}



def _merged_settings(stored, payload):
    merged=dict(stored)
    # Structured clients can edit the whole saved document. Legacy form fields
    # merge with the current snapshot rather than resetting omitted settings.
    flat=_settings_payload(payload)
    for name in ('target_kind','web_url','android_package','environment_revision_id','data_revision_id','secret_refs','install_policy','reset_policy','cleanup_policy','allow_unknown_supplement'):
        if name in payload:
            merged[name]=flat[name]
    for name in ('limits','healing_policy'):
        current=dict(merged.get(name,{}))
        if name in payload and type(payload[name]) is dict:
            current.update(payload[name])
        elif name=='limits' and 'timeout_seconds' in payload:
            current['timeout_seconds']=payload['timeout_seconds']
        elif name=='healing_policy':
            mapping={'healing_allowed':'allowed','healing_default_enabled':'default_enabled','healing_scope':'scope','healing_max_episodes':'max_episodes_per_item','healing_max_calls':'max_model_calls_per_item','healing_max_seconds':'max_seconds'}
            for source,target in mapping.items():
                if source in payload:
                    current[target]=payload[source]
        merged[name]=current
    if 'verifier_bindings' in payload:
        merged['verifier_bindings']=payload['verifier_bindings']
    elif 'verifier_method' in payload or 'verifier_binding_id' in payload:
        merged['verifier_method']=payload.get('verifier_method','deterministic')
        merged['verifier_binding_id']=payload.get('verifier_binding_id','')
        merged.pop('verifier_bindings',None)
    return merged


def _settings_payload(payload: dict[str, object]) -> dict[str, object]:
    healing = payload.get("healing_policy")
    if type(healing) is not dict:
        healing = {
            "allowed": payload.get("healing_allowed", False) is True,
            "default_enabled": payload.get("healing_default_enabled", False) is True,
            "scope": str(payload.get("healing_scope", "")),
            "max_episodes_per_item": payload.get("healing_max_episodes", 1),
            "max_model_calls_per_item": payload.get("healing_max_calls", 2),
            "max_seconds": payload.get("healing_max_seconds", 30),
        }
    limits = payload.get("limits")
    if type(limits) is not dict:
        limits = {"timeout_seconds": payload.get("timeout_seconds", 600)}
    return {
        "target_kind": payload.get("target_kind", "web"),
        "web_url": payload.get("web_url", ""),
        "android_package": payload.get("android_package", ""),
        "environment_revision_id": payload.get("environment_revision_id", ""),
        "data_revision_id": payload.get("data_revision_id", ""),
        "secret_refs": payload.get("secret_refs", {}),
        "install_policy": payload.get("install_policy", "none"),
        "reset_policy": payload.get("reset_policy", "none"),
        "cleanup_policy": payload.get("cleanup_policy", "none"),
        "limits": limits,
        "verifier_method": payload.get("verifier_method", "deterministic"),
        "verifier_binding_id": payload.get("verifier_binding_id", ""),
        "allow_unknown_supplement": payload.get("allow_unknown_supplement", False) is True,
        "healing_policy": healing,
    }


def _public_form(payload: dict[str, object]) -> dict[str, object]:
    return {
        "web_url": payload.get("web_url", ""),
        "environment_revision_id": payload.get("environment_revision_id", ""),
        "verifier_method": payload.get("verifier_method", ""),
    }


def _settings_view(actor: object, case_id: UUID) -> dict[str, object] | None:
    from aiqa.domain.versions import _bound_store
    from aiqa.store.models import Actor

    assert isinstance(actor, Actor)
    with _bound_store().transaction() as connection:
        row = connection.execute(
            """
            SELECT automation_cases.latest_draft_version_id, case_versions.settings_json
            FROM automation_cases
            LEFT JOIN case_versions
              ON case_versions.project_id = automation_cases.project_id
             AND case_versions.version_id = automation_cases.latest_draft_version_id
            WHERE automation_cases.project_id = ? AND automation_cases.case_id = ?
            """,
            (str(actor.project_scope), str(case_id)),
        ).fetchone()
    if row is None:
        return None
    stored = {} if row[1] is None else json.loads(str(row[1]))
    healing = stored.get("healing_policy", {})
    if type(healing) is not dict:
        healing = {}
    bindings = stored.get("verifier_bindings", [])
    method = "deterministic"
    binding = ""
    if type(bindings) is list and bindings and type(bindings[0]) is dict:
        method = str(bindings[0].get("method", method))
        binding = str(bindings[0].get("binding_id", ""))
    return {
        "head": "" if row[0] is None else str(row[0]),
        "web_url": str(stored.get("web_url", "")),
        "android_package": str(stored.get("android_package", "")),
        "environment_revision_id": str(stored.get("environment_revision_id", "")),
        "data_revision_id": str(stored.get("data_revision_id", "")),
        "install_policy": str(stored.get("install_policy", "none")),
        "reset_policy": str(stored.get("reset_policy", "none")),
        "cleanup_policy": str(stored.get("cleanup_policy", "none")),
        "verifier_method": method,
        "verifier_binding_id": binding,
        "healing_scope": str(healing.get("scope", "")),
        "healing_allowed": "false" if healing.get("allowed", False) is not True else "true",
    }


def _stored_definition_for_settings(actor: object, case_id: UUID) -> tuple[object, UUID] | None:
    from aiqa.domain.versions import _stored_definition
    from aiqa.store.models import Actor

    assert isinstance(actor, Actor)
    loaded = _stored_definition(actor, case_id)
    return None if loaded is None else loaded[:2]


def _settings_error(message: str, submitted: dict[str, object], status: int = 422) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": "conflict" if status == 409 else "validation",
                "message": message,
                "fields": {},
                "retryable": False,
                "request_id": str(uuid4()),
            },
            "submitted": submitted,
        },
    )


@pages.get("/ui/projects/{project_id}/cases/{case_id}/steps", response_class=HTMLResponse)
async def case_steps_page(project_id: str, case_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    parsed = _uuid(case_id)
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return HTMLResponse(status_code=404, content="케이스를 찾지 못했습니다.")
    query = _case_query(project, request)
    if isinstance(query, JSONResponse):
        return HTMLResponse(status_code=422, content="목록 조건을 다시 확인해 주세요.")
    with _bound(request):
        try:
            actor = authorize_page(request, project)
            loaded = _stored_steps(actor, parsed)
            proposal = pending_proposal_text(actor, parsed)
            proposals = _pending_proposals(actor, parsed)
        except _CATALOG_ERRORS:
            return _case_screen(request, project, query, (), "forbidden")
    if loaded is None:
        return HTMLResponse(status_code=404, content="케이스를 찾지 못했습니다.")
    head, steps = loaded
    context = _case_context(request, project, query, (), "ready", None)
    context["case_id"] = str(parsed)
    context["head"] = "" if head is None else str(head)
    context["steps"] = steps
    context["proposal_text"] = proposal
    context["proposals"] = proposals
    return render_template(request, "case_steps.html", context)


@pages.post("/ui/projects/{project_id}/cases/{case_id}/steps")
async def case_steps_save(project_id: str, case_id: str, request: Request) -> JSONResponse:
    return await _step_edit(project_id, case_id, request, page=True)


@router.post("/projects/{project_id}/cases/{case_id}/step-edits")
async def post_step_edit(project_id: str, case_id: str, request: Request) -> JSONResponse:
    return await _step_edit(project_id, case_id, request, page=False)


async def _step_edit(project_id: str, case_id: str, request: Request, page: bool) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    parsed = _uuid(case_id)
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return _error(404, "not_found", "case was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    try:
        command = StepEditCommand(
            action=str(payload.get("action", "")),
            step_id=str(payload.get("step_id", "")),
            instruction=str(payload.get("instruction", "")),
            expected=str(payload.get("expected", "")),
            direction=str(payload.get("direction", "down")),
            variable=str(payload.get("variable", "")),
            expected_head=_optional_uuid(payload.get("expected_head")),
        )
    except ValueError:
        return _error(422, "validation", "invalid step edit", {})
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "case")
            view, step_ids = apply_step_edit(actor, parsed, command)
        except StaleHead:
            return _error(409, "conflict", "draft head changed", {})
        except ValueError:
            return _error(422, "validation", "invalid step edit", {})
        except _CATALOG_ERRORS as exc:
            return _catalog_response(exc)
    content = _view_json(view)
    content["step_ids"] = list(step_ids)
    return JSONResponse(status_code=201, content=content)


def _stored_steps(actor: object, case_id: UUID) -> tuple[UUID | None, tuple[object, ...]] | None:
    from aiqa.domain.versions import _stored_definition
    from aiqa.store.models import Actor

    assert isinstance(actor, Actor)
    row = _bound_case_exists(actor, case_id)
    if row is False:
        return None
    loaded = _stored_definition(actor, case_id)
    if loaded is None:
        return None, ()
    definition, head = loaded[:2]
    return head, definition.steps


def _project_of_case(case_id: UUID) -> UUID | None:
    from aiqa.domain.versions import _bound_store

    with _bound_store().transaction() as connection:
        row = connection.execute(
            "SELECT project_id FROM automation_cases WHERE case_id = ?",
            (str(case_id),),
        ).fetchone()
    return None if row is None else UUID(str(row[0]))


def _project_of_version(version_id: UUID) -> UUID | None:
    from aiqa.domain.versions import _bound_store

    with _bound_store().transaction() as connection:
        row = connection.execute(
            "SELECT project_id FROM case_versions WHERE version_id = ?",
            (str(version_id),),
        ).fetchone()
    return None if row is None else UUID(str(row[0]))


def _case_board(actor: object, case_id: UUID, selected: UUID | None) -> dict[str, object] | None:
    from aiqa.domain.versions import _bound_store
    from aiqa.store.models import Actor

    assert isinstance(actor, Actor)
    with _bound_store().transaction() as connection:
        case = connection.execute(
            """
            SELECT latest_draft_version_id, current_approval_id, name
            FROM automation_cases
            WHERE project_id = ? AND case_id = ?
            """,
            (str(actor.project_scope), str(case_id)),
        ).fetchone()
        if case is None:
            return None
        approved_id = None
        if case[1] is not None:
            approved = connection.execute(
                """
                SELECT case_version_id FROM approval_events
                WHERE project_id = ? AND approval_id = ? AND case_id = ? AND event_kind = 'approved'
                """,
                (str(actor.project_scope), str(case[1]), str(case_id)),
            ).fetchone()
            approved_id = None if approved is None else str(approved[0])
        revoked = connection.execute(
            """
            SELECT approval_id FROM approval_events
            WHERE project_id = ? AND case_id = ? AND event_kind = 'revoked'
            LIMIT 1
            """,
            (str(actor.project_scope), str(case_id)),
        ).fetchone()
        stored = connection.execute(
            """
            SELECT version_id, definition_json, settings_json, replay_package_id, revision
            FROM case_versions
            WHERE project_id = ? AND case_id = ?
            ORDER BY revision
            """,
            (str(actor.project_scope), str(case_id)),
        ).fetchall()
        runs = connection.execute(
            """SELECT r.case_run_id,r.purpose,r.requested_at,f.core_result,j.status,t.attempt_id,
                (SELECT a.action_id FROM actions a WHERE a.project_id=r.project_id AND a.attempt_id=t.attempt_id ORDER BY a.action_seq LIMIT 1)
            FROM case_runs r LEFT JOIN item_finalizations f ON f.project_id=r.project_id AND f.case_run_id=r.case_run_id
            LEFT JOIN jobs j ON j.project_id=r.project_id AND j.case_run_id=r.case_run_id
            LEFT JOIN attempts t ON t.project_id=j.project_id AND t.job_id=j.job_id
                AND t.generation=(SELECT MAX(t2.generation) FROM attempts t2 WHERE t2.project_id=t.project_id AND t2.job_id=t.job_id)
            WHERE r.project_id = ? AND r.case_id = ? ORDER BY r.requested_at DESC,r.case_run_id DESC LIMIT 25""",
            (str(actor.project_scope), str(case_id)),
        ).fetchall()
        from aiqa.replay.packages import load_replay_package_view

        draft_id = None if case[0] is None else str(case[0])
        chosen = str(selected) if selected is not None else draft_id
        if selected is not None and not any(str(row[0]) == str(selected) for row in stored):
            return None
        package = None if chosen in {None, ""} else load_replay_package_view(connection, actor.project_scope, UUID(chosen))
    versions = tuple(_version_public(row) for row in stored)
    draft_row = next((item for item in versions if item["id"] == draft_id), None)
    approved_row = next((item for item in versions if item["id"] == approved_id), None)
    selected_row = next((item for item in versions if item["id"] == chosen), None)
    package_id = None if selected_row is None else selected_row["replay_package_id"]
    return {
        "case_id": str(case_id),
        "case_name": str(case[2]),
        "draft_revision": None if draft_row is None else draft_row["revision"],
        "approved_revision": None if approved_row is None else approved_row["revision"],
        "latest_draft_version_id": draft_id,
        "approved_version_id": approved_id,
        "draft_text": "" if draft_row is None else str(draft_row["raw_text"]),
        "approved_text": "" if approved_row is None else str(approved_row["raw_text"]),
        "selected_version_id": None if selected_row is None else selected_row["id"],
        "selected_text": "" if selected_row is None else str(selected_row["raw_text"]),
        "replay_package_id": package_id,
        "package": _package_json(package) if package is not None else _empty_package(chosen),
        "package_reason": None if package_id is not None else "패키지가 없습니다.",
        "history": [{"case_run_id":str(row[0]),"purpose":str(row[1]),"requested_at":str(row[2]),"result":row[3],"job_status":row[4],"attempt_id":row[5],"first_action":row[6]} for row in runs],
        "revoked_approval_id": None if revoked is None else str(revoked[0]),
        "snapshot_editable": False,
        "versions": list(versions),
    }


def _package_json(view: object) -> dict[str, object]:
    from aiqa.replay.packages import ReplayPackageView

    assert isinstance(view, ReplayPackageView)
    return {
        "version_id": str(view.version_id),
        "replay_package_id": None if view.replay_package_id is None else str(view.replay_package_id),
        "ready": view.ready,
        "raw_source_hash": view.raw_source_hash,
        "approved_code_hash": view.approved_code_hash,
        "runtime_ref": view.runtime_ref,
        "compiler_ref": view.compiler_ref,
        "lock_hash": view.lock_hash,
        "package_hash": view.package_hash,
        "steps": [
            {"step_id": step.step_id, "position": step.position, "step_hash": step.step_hash}
            for step in view.steps
        ],
        "reasons": list(view.reasons),
        "recording_ids": list(view.recording_ids),
        "editable": view.editable,
    }


def _empty_package(version_id: str | None) -> dict[str, object]:
    return {
        "version_id": version_id,
        "replay_package_id": None,
        "ready": False,
        "raw_source_hash": "",
        "approved_code_hash": "",
        "runtime_ref": "",
        "compiler_ref": "",
        "lock_hash": "",
        "package_hash": "",
        "steps": [],
        "reasons": ["package is missing"],
        "recording_ids": [],
        "editable": False,
    }


def _version_public(row: tuple[object, ...]) -> dict[str, object]:
    body = json.loads(str(row[1]))
    return {
        "id": str(row[0]),
        "revision": None if len(row) < 5 else int(row[4]),
        "raw_text": str(body.get("raw_text", "")),
        "objective": str(body.get("objective", "")),
        "settings": str(row[2]),
        "replay_package_id": None if row[3] is None else str(row[3]),
    }


_BLOCK_LABELS = {
    "recording is partial": "녹화가 일부만 저장되었습니다.",
    "evidence is incomplete": "증거가 완전하지 않습니다.",
    "package is missing": "패키지가 없습니다.",
    "lock is missing": "lock이 없습니다.",
    "mapping is missing": "mapping이 없습니다.",
    "trial is not off": "시범이 OFF가 아닙니다.",
    "trial hash is stale": "시범 hash가 오래되었습니다.",
    "action review is missing": "미검토 행동이 있습니다.",
}


def load_review_readiness(connection: object, project_id: UUID, version_id: UUID) -> dict[str, object] | None:
    """Read candidate blockers and the base diff. This does not copy a review or approve."""

    version = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT case_id, base_version_id, definition_json, settings_json, recorded_steps_json,
               content_hash, source_manifest_id, replay_package_id
        FROM case_versions
        WHERE project_id = ? AND version_id = ?
        """,
        (str(project_id), str(version_id)),
    ).fetchone()
    if version is None:
        return None
    case_id = str(version[0])
    base_id = None if version[1] is None else str(version[1])
    base = None
    if base_id is not None:
        base = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT definition_json, settings_json, recorded_steps_json, source_manifest_id
            FROM case_versions
            WHERE project_id = ? AND version_id = ?
            """,
            (str(project_id), base_id),
        ).fetchone()
    reasons = _readiness_reasons(connection, project_id, version_id, case_id, str(version[5]), version[6], version[7])
    copied = _review_was_copied(connection, project_id, str(version_id), base_id)
    source_owner, trial_owner, trial_off = _owners(connection, project_id, case_id, version_id, version[6])
    candidate_evidence = _recording_evidence(connection, project_id, version[6])
    base_evidence = "" if base is None else _recording_evidence(connection, project_id, base[3])
    return {
        "case_version_id": str(version_id),
        "base_version_id": base_id,
        "approve_allowed": reasons == [],
        "block_reasons": reasons,
        "block_labels": {reason: _BLOCK_LABELS[reason] for reason in reasons},
        "old_review_copied": copied,
        "trial_off": trial_off,
        "source_owner_id": source_owner,
        "trial_owner_id": trial_owner,
        "diffs": _candidate_diffs(version, base, base_evidence, candidate_evidence),
    }


def _field_text(raw: object, name: str) -> str:
    try:
        body = json.loads(str(raw))
    except json.JSONDecodeError:
        return ""
    if type(body) is not dict:
        return ""
    value = body.get(name, "")
    if type(value) is str:
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _candidate_diffs(
    version: tuple[object, ...],
    base: tuple[object, ...] | None,
    base_evidence: str,
    candidate_evidence: str,
) -> list[dict[str, object]]:
    candidate_definition = version[2]
    candidate_settings = str(version[3])
    candidate_steps = str(version[4])
    if base is None:
        base_definition: object = "{}"
        base_settings = ""
        base_steps = ""
    else:
        base_definition = base[0]
        base_settings = str(base[1])
        base_steps = str(base[2])
    pairs = (
        ("expected", "기대", _field_text(base_definition, "expected"), _field_text(candidate_definition, "expected")),
        ("path", "경로", _field_text(base_definition, "path"), _field_text(candidate_definition, "path")),
        ("procedure", "절차", base_steps, candidate_steps),
        ("target", "대상", _field_text(base_definition, "target"), _field_text(candidate_definition, "target")),
        ("settings", "설정", base_settings, candidate_settings),
        ("errors", "오류", _field_text(base_definition, "errors"), _field_text(candidate_definition, "errors")),
        ("evidence", "근거", base_evidence, candidate_evidence),
    )
    return [
        {"field": field, "label": label, "base": left, "candidate": right, "changed": left != right}
        for field, label, left, right in pairs
    ]


def _recording_evidence(connection: object, project_id: UUID, manifest_id: object) -> str:
    if manifest_id is None:
        return ""
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT recordings.storage_status, recordings.evidence_status
        FROM recording_manifests
        JOIN recordings
          ON recordings.project_id = recording_manifests.project_id
         AND recordings.recording_id = recording_manifests.recording_id
        WHERE recording_manifests.project_id = ? AND recording_manifests.manifest_id = ?
        """,
        (str(project_id), str(manifest_id)),
    ).fetchone()
    if row is None:
        return ""
    return str(row[0]) + "/" + str(row[1])


def _readiness_reasons(
    connection: object,
    project_id: UUID,
    version_id: UUID,
    case_id: str,
    content_hash: str,
    manifest_id: object,
    package_id: object,
) -> list[str]:
    reasons: list[str] = []
    recording = None
    if manifest_id is not None:
        recording = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT recordings.storage_status, recordings.evidence_status
            FROM recording_manifests
            JOIN recordings
              ON recordings.project_id = recording_manifests.project_id
             AND recordings.recording_id = recording_manifests.recording_id
            WHERE recording_manifests.project_id = ? AND recording_manifests.manifest_id = ?
            """,
            (str(project_id), str(manifest_id)),
        ).fetchone()
    if recording is None or str(recording[0]) != "stored":
        reasons.append("recording is partial")
    if recording is None or str(recording[1]) != "complete":
        reasons.append("evidence is incomplete")
    package = None
    if package_id is not None:
        package = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT ready, lock_hash, step_mapping_hash
            FROM replay_packages
            WHERE project_id = ? AND package_id = ?
            """,
            (str(project_id), str(package_id)),
        ).fetchone()
    if package is None or int(package[0]) != 1:
        reasons.append("package is missing")
    if package is None or str(package[1]) == "":
        reasons.append("lock is missing")
    if package is None or str(package[2]) == "":
        reasons.append("mapping is missing")
    trial = _readiness_trial(connection, project_id, case_id, version_id)
    if trial is None or not _trial_off(trial[3]):
        reasons.append("trial is not off")
    if trial is None or str(trial[1]) != str(version_id) or str(trial[2]) != content_hash:
        reasons.append("trial hash is stale")
    if _unreviewed_count(connection, project_id, version_id) != 0:
        reasons.append("action review is missing")
    return reasons


def _readiness_trial(connection: object, project_id: UUID, case_id: str, version_id: UUID):
    """Keep readiness on the pinned review, or prefer a same-version unhealed trial."""
    pinned = connection.execute(
        """SELECT trial_case_run_id FROM reviews
        WHERE project_id=? AND case_id=? AND case_version_id=?
        ORDER BY created_commit_seq DESC LIMIT 1""",
        (str(project_id), case_id, str(version_id)),
    ).fetchone()
    rows = connection.execute(
        """SELECT r.case_run_id,r.case_version_id,v.content_hash,j.limits
        FROM case_runs r JOIN case_versions v
          ON v.project_id=r.project_id AND v.version_id=r.case_version_id
        LEFT JOIN jobs j ON j.project_id=r.project_id AND j.case_run_id=r.case_run_id AND j.purpose='trial'
        LEFT JOIN item_finalizations f ON f.project_id=r.project_id AND f.case_run_id=r.case_run_id
        WHERE r.project_id=? AND r.case_id=? AND (r.case_version_id=? OR r.case_run_id=?) AND r.purpose='trial'
        ORDER BY (f.case_run_id IS NOT NULL) DESC,r.requested_at DESC,r.case_run_id DESC""",
        (str(project_id), case_id, str(version_id), '' if pinned is None or pinned[0] is None else str(pinned[0])),
    ).fetchall()
    if pinned is not None and pinned[0] is not None:
        return next((row for row in rows if str(row[0]) == str(pinned[0])), None)
    return next((row for row in rows if _trial_off(row[3])), rows[0] if rows else None)


def _trial_off(raw: object) -> bool:
    if raw is None:
        return False
    try:
        limits = json.loads(str(raw))
    except json.JSONDecodeError:
        return False
    if type(limits) is not dict:
        return False
    return limits.get("self_healing_enabled") is False and limits.get("actor") == 0


def _unreviewed_count(connection: object, project_id: UUID, version_id: UUID) -> int:
    rows = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT review_evidence_entries.entry_id
        FROM reviews
        JOIN review_evidence_entries
          ON review_evidence_entries.project_id = reviews.project_id
         AND review_evidence_entries.review_id = reviews.review_id
        WHERE reviews.project_id = ? AND reviews.case_version_id = ?
        """,
        (str(project_id), str(version_id)),
    ).fetchall()
    if not rows:
        return 1
    missing = 0
    for row in rows:
        latest = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT state FROM action_reviews
            WHERE project_id = ? AND entry_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
            (str(project_id), str(row[0])),
        ).fetchone()
        if latest is None or str(latest[0]) != "reviewed":
            missing += 1
    return missing


def _review_was_copied(connection: object, project_id: UUID, version_id: str, base_id: str | None) -> bool:
    if base_id is None:
        return False
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT COUNT(*)
        FROM reviews AS candidate
        JOIN reviews AS base
          ON base.project_id = candidate.project_id
         AND base.case_version_id = ?
         AND base.evidence_set_hash = candidate.evidence_set_hash
         AND IFNULL(base.source_manifest_id, '') = IFNULL(candidate.source_manifest_id, '')
         AND IFNULL(base.trial_case_run_id, '') = IFNULL(candidate.trial_case_run_id, '')
        WHERE candidate.project_id = ? AND candidate.case_version_id = ?
        """,
        (base_id, str(project_id), version_id),
    ).fetchone()
    return row is not None and int(row[0]) > 0


def _owners(connection: object, project_id: UUID, case_id: str, version_id: UUID, manifest_id: object) -> tuple[str, str, bool]:
    source = ""
    if manifest_id is not None:
        row = connection.execute(  # type: ignore[attr-defined]
            "SELECT recording_id FROM recording_manifests WHERE project_id = ? AND manifest_id = ?",
            (str(project_id), str(manifest_id)),
        ).fetchone()
        if row is not None:
            source = str(row[0])
    trial = _readiness_trial(connection, project_id, case_id, version_id)
    if trial is None:
        return source, "", False
    return source, str(trial[0]), _trial_off(trial[3])


def _version_diff(actor: object, version_id: UUID, base_id: UUID) -> dict[str, object] | None:
    from aiqa.domain.versions import _bound_store
    from aiqa.store.models import Actor

    assert isinstance(actor, Actor)
    with _bound_store().transaction() as connection:
        rows = connection.execute(
            """
            SELECT version_id, definition_json, settings_json, replay_package_id
            FROM case_versions
            WHERE project_id = ? AND version_id IN (?, ?)
            """,
            (str(actor.project_scope), str(version_id), str(base_id)),
        ).fetchall()
    found = {str(row[0]): _version_public(row) for row in rows}
    selected = found.get(str(version_id))
    base = found.get(str(base_id))
    if selected is None or base is None:
        return None
    return {
        "version_id": selected["id"],
        "base_version_id": base["id"],
        "raw_text": {"base": base["raw_text"], "selected": selected["raw_text"]},
        "objective": {"base": base["objective"], "selected": selected["objective"]},
        "settings": {"base": base["settings"], "selected": selected["settings"]},
        "replay_package_id": {"base": base["replay_package_id"], "selected": selected["replay_package_id"]},
    }


def _bound_case_exists(actor: object, case_id: UUID) -> bool:
    from aiqa.domain.versions import _bound_store
    from aiqa.store.models import Actor

    assert isinstance(actor, Actor)
    with _bound_store().transaction() as connection:
        row = connection.execute(
            "SELECT 1 FROM automation_cases WHERE project_id = ? AND case_id = ?",
            (str(actor.project_scope), str(case_id)),
        ).fetchone()
    return row is not None


@router.post("/projects/{project_id}/cases/bulk")
async def post_bulk(project_id: str, request: Request) -> JSONResponse:
    return await _bulk(project_id, request, page=False)


@router.get("/cases/{case_id}")
async def get_case(case_id: str, request: Request) -> JSONResponse:
    return await _case_document(case_id, request, versions_only=False)


@router.get("/cases/{case_id}/versions")
async def get_case_versions(case_id: str, request: Request) -> JSONResponse:
    return await _case_document(case_id, request, versions_only=True)


@router.get("/case-versions/{version_id}/diff")
async def get_case_diff(version_id: str, request: Request) -> JSONResponse:
    selected = _uuid(version_id)
    base = _uuid(request.query_params.get("base", ""))
    if isinstance(selected, JSONResponse) or isinstance(base, JSONResponse):
        return _error(404, "not_found", "case was not found", {})
    with _bound(request):
        project = _project_of_version(selected)
        if project is None:
            return _error(404, "not_found", "case was not found", {})
        try:
            actor = authorize_browser(request, project, "case")
            diff = _version_diff(actor, selected, base)
        except _CATALOG_ERRORS as exc:
            return _catalog_response(exc)
    if diff is None:
        return _error(404, "not_found", "case was not found", {})
    return JSONResponse(status_code=200, content=diff)


async def _case_document(case_id: str, request: Request, versions_only: bool) -> JSONResponse:
    parsed = _uuid(case_id)
    if isinstance(parsed, JSONResponse):
        return _error(404, "not_found", "case was not found", {})
    with _bound(request):
        project = _project_of_case(parsed)
        if project is None:
            return _error(404, "not_found", "case was not found", {})
        try:
            actor = authorize_browser(request, project, "case")
            board = _case_board(actor, parsed, None)
        except _CATALOG_ERRORS as exc:
            return _catalog_response(exc)
    if board is None:
        return _error(404, "not_found", "case was not found", {})
    if versions_only:
        return JSONResponse(status_code=200, content={"items": board["versions"]})
    return JSONResponse(status_code=200, content=board)


@router.get("/projects/{project_id}/cases")
async def get_cases(project_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return _error(404, "not_found", "case was not found", {})
    try:
        limit = int(request.query_params.get("limit", "25"))
        folder = request.query_params.get("folder_id")
        assignee = request.query_params.get("assignee_id")
        query = CaseListQuery(
            project_id=project,
            text=request.query_params.get("q", ""),
            folder_id=None if folder is None else UUID(folder),
            tag=request.query_params.get("tag"),
            priority=request.query_params.get("priority"),
            assignee_id=None if assignee is None else UUID(assignee),
            archived=request.query_params.get("archived", "false") == "true",
            view=request.query_params.get("view", ""),
            sort=request.query_params.get("sort", "name"),
            limit=limit,
            cursor=request.query_params.get("cursor"),
        )
    except ValueError:
        return _error(422, "validation", "invalid list query", {})
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "case")
            with bind_catalog_actor(actor):
                page = list_cases(query)
        except _CATALOG_ERRORS as exc:
            return _catalog_response(exc)
    return JSONResponse(
        status_code=200,
        content={
            "items": [
                {
                    "case_id": str(item.case_id),
                    "name": item.name,
                    "folder_id": None if item.folder_id is None else str(item.folder_id),
                    "priority": item.priority,
                    "current_approval_id": None if item.current_approval_id is None else str(item.current_approval_id),
                    "lock_version": item.lock_version,
                    "tc_reference": None if item.tc_reference is None else str(item.tc_reference),
                    "target_kind": item.target_kind,
                    "draft_revision": item.draft_revision,
                    "approved_revision": item.approved_revision,
                    "latest_result": item.latest_result,
                    "latest_run_at": item.latest_run_at,
                }
                for item in page.items
            ],
            "next_cursor": page.next_cursor,
            "snapshot_seq": page.snapshot_seq,
            "total": page.total, "start": page.start, "end": page.end, "previous_cursor": page.previous_cursor,
        },
    )


@router.patch("/projects/{project_id}/cases/{case_id}")
async def patch_case(project_id: str, case_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    parsed = _uuid(case_id)
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return _error(404, "not_found", "case was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    try:
        tags = payload.get("tags", [])
        if type(tags) is not list or any(type(item) is not str for item in tags):
            raise ValueError("invalid tags")
        folder = payload.get("folder_id")
        assignee = payload.get("assignee_id")
        priority = payload.get("priority")
        if priority is not None and type(priority) is not str:
            raise ValueError("invalid priority")
        expected = int(payload["expected_revision"])
    except (ValueError, KeyError, TypeError):
        return _error(422, "validation", "invalid metadata", {})
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "case")
            with bind_catalog_actor(actor):
                view = update_case_metadata(
                    parsed,
                    expected,
                    None if folder is None else UUID(str(folder)),
                    tuple(str(item) for item in tags),
                    None if priority is None else str(priority),
                    None if assignee is None else UUID(str(assignee)),
                )
        except _CATALOG_ERRORS as exc:
            return _catalog_response(exc)
    return JSONResponse(status_code=200, content=_case_view_json(view))


@router.post("/projects/{project_id}/cases/{case_id}/clone")
async def post_clone(project_id: str, case_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    parsed = _uuid(case_id)
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return _error(404, "not_found", "case was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    name = payload.get("name")
    if type(name) is not str:
        return _error(422, "validation", "invalid clone", {})
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "case")
            view = clone_case(CloneCaseInput(project, actor.actor_id, parsed, name))
        except _CATALOG_ERRORS as exc:
            return _catalog_response(exc)
    return JSONResponse(status_code=201, content=_case_view_json(view))


@router.post("/projects/{project_id}/cases/{case_id}/archive")
async def post_archive(project_id: str, case_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    parsed = _uuid(case_id)
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return _error(404, "not_found", "case was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    try:
        expected = int(payload["expected_revision"])
    except (KeyError, TypeError, ValueError):
        return _error(422, "validation", "invalid archive", {})
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "case")
            with bind_catalog_actor(actor):
                view = archive_case(parsed, expected)
        except _CATALOG_ERRORS as exc:
            return _catalog_response(exc)
    return JSONResponse(status_code=200, content=_case_view_json(view))


async def _bulk(project_id: str, request: Request, page: bool) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return _error(404, "not_found", "case was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    items = payload.get("items")
    if type(items) is not list:
        return _error(422, "validation", "invalid bulk", {})
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "case")
        except _CATALOG_ERRORS as exc:
            return _catalog_response(exc)
        results = _bulk_results(project, actor, items)
    return JSONResponse(status_code=200, content={"items": results})


def _bulk_results(project: UUID, actor: object, items: list[object]) -> list[dict[str, object]]:
    from aiqa.store.models import Actor

    assert isinstance(actor, Actor)
    results: list[dict[str, object]] = []
    with bind_catalog_actor(actor):
        for item in items:
            results.append(_bulk_one(project, actor, item))
    return results


def _bulk_one(project: UUID, actor: object, item: object) -> dict[str, object]:
    from aiqa.store.models import Actor

    assert isinstance(actor, Actor)
    if type(item) is not dict or type(item.get("case_id")) is not str:
        return _bulk_row("", "blocked", "항목을 확인하지 못했습니다", None)
    case_id = str(item.get("case_id"))
    action = item.get("action")
    try:
        parsed = UUID(case_id)
    except ValueError:
        return _bulk_row(case_id, "blocked", "케이스를 찾지 못했습니다", None)
    try:
        if action == "clone":
            name = item.get("name")
            if type(name) is not str:
                return _bulk_row(case_id, "blocked", "이름을 입력해 주세요", None)
            view = clone_case(CloneCaseInput(project, actor.actor_id, parsed, name))
            return _bulk_row(case_id, "cloned", None, view)
        if action == "archive":
            view = archive_case(parsed, int(item["expected_revision"]))
            return _bulk_row(case_id, "archived", None, view)
        return _bulk_row(case_id, "blocked", "요청을 확인하지 못했습니다", None)
    except ActiveRecording:
        return _bulk_row(case_id, "blocked", "진행 중인 녹화가 있습니다", None)
    except StaleRevision:
        return _bulk_row(case_id, "blocked", "서버의 최신 상태와 다릅니다", None)
    except (CatalogNotFound, CaseNotFound):
        return _bulk_row(case_id, "blocked", "케이스를 찾지 못했습니다", None)
    except (KeyError, TypeError, ValueError):
        return _bulk_row(case_id, "blocked", "항목을 확인하지 못했습니다", None)


def _bulk_row(case_id: str, outcome: str, reason: str | None, view: CaseView | None) -> dict[str, object]:
    return {
        "case_id": case_id,
        "outcome": outcome,
        "reason": reason,
        "approval_id": None if view is None or view.current_approval_id is None else str(view.current_approval_id),
        "history_deleted": 0,
        "view": None if view is None else _case_view_json(view),
    }


def _entry_page(
    project_id: str,
    request: Request,
    step: str,
    title: str,
    message: str,
    case_id: str | None = None,
) -> HTMLResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return HTMLResponse(status_code=404, content="프로젝트를 찾지 못했습니다.")
    if case_id is not None and isinstance(_uuid(case_id), JSONResponse):
        return HTMLResponse(status_code=404, content="케이스를 찾지 못했습니다.")
    query = _case_query(project, request)
    if isinstance(query, JSONResponse):
        return HTMLResponse(status_code=422, content="목록 조건을 다시 확인해 주세요.")
    with _bound(request):
        try:
            authorize_page(request, project)
        except _CATALOG_ERRORS:
            return _case_screen(request, project, query, (), "forbidden")
    context = _case_context(request, project, query, (), "ready", None)
    context["step"] = step
    context["entry_title"] = title
    context["entry_message"] = message
    return render_template(request, "cases.html", context)


def _case_view_json(view: CaseView) -> dict[str, object]:
    return {
        "project_id": str(view.project_id),
        "case_id": str(view.case_id),
        "name": view.name,
        "current_approval_id": None if view.current_approval_id is None else str(view.current_approval_id),
        "latest_draft_version_id": None if view.latest_draft_version_id is None else str(view.latest_draft_version_id),
        "archived_at": view.archived_at,
        "lock_version": view.lock_version,
    }


_CATALOG_ERRORS = (
    CsrfRejected,
    OriginRejected,
    ProjectHidden,
    AuthRequired,
    CatalogNotFound,
    CaseNotFound,
    StaleRevision,
    ActiveRecording,
    ValueError,
)


def _catalog_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, CsrfRejected | OriginRejected):
        return _error(403, "permission", "request was rejected", {})
    if isinstance(exc, AuthRequired):
        return _error(401, "unauthorized", "session is missing", {})
    if isinstance(exc, StaleRevision | ActiveRecording):
        return _error(409, "conflict", "case could not be archived", {})
    if isinstance(exc, ValueError):
        return _error(422, "validation", "invalid catalog request", {})
    return _error(404, "not_found", "case was not found", {})


def _case_query(project: UUID, request: Request) -> CaseListQuery | JSONResponse:
    try:
        limit = int(request.query_params.get("limit", "25"))
        return CaseListQuery(
            project_id=project,
            text=request.query_params.get("q", ""),
            archived=request.query_params.get("archived", "false") == "true",
            view=request.query_params.get("view", ""),
            sort=request.query_params.get("sort", "name"),
            limit=limit,
            cursor=request.query_params.get("cursor") or None,
        )
    except ValueError:
        return _error(422, "validation", "invalid list query", {})


def _case_screen(
    request: Request,
    project: UUID,
    query: CaseListQuery,
    items: tuple[object, ...],
    state: str,
    next_cursor: str | None = None,
) -> HTMLResponse:
    return render_template(request, "cases.html", _case_context(request, project, query, items, state, next_cursor))


def _case_context(
    request: Request,
    project: UUID,
    query: CaseListQuery,
    items: tuple[object, ...],
    state: str,
    next_cursor: str | None,
) -> dict[str, object]:
    selected = request.query_params.get("selected", "")
    pairs = [("q", query.text), ("sort", query.sort), ("view", query.view), ("selected", selected),('limit',str(query.limit)),('archived',str(query.archived).lower())]
    if query.cursor:
        pairs.append(("cursor", query.cursor))
    suffix = urlencode(pairs)
    base = f"/ui/projects/{project}/cases"
    return {
        "shell": True,
        "title": "케이스",
        "heading": "케이스",
        "section": "list",
        "connected": True,
        "state": state,
        "dirty": False,
        "query": UiQueryState(query.text, query.sort, query.cursor or "", selected, ""),
        "crumbs": (("케이스", base),),
        "list_href": f"{base}?{suffix}",
        "detail_href": base,
        "items": items,
        "q": query.text,
        "sort": query.sort,
        "view": query.view,
        "archived":query.archived,
        "selected": selected,
        "next_cursor": next_cursor or "",
        "page_size": query.limit,
        "project_id": str(project),
        "list_href_full": f"{base}?{suffix}",
        "step": "list",
        "request": request,
    }


@contextmanager
def _bound(request: Request) -> Iterator[None]:
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bind_case_store(store):
            with bind_catalog_store(store):
                with bind_proposal_store(store):
                    with bound_auth_store(store):
                        yield
    finally:
        store.close()


async def _body(request: Request) -> dict[str, object] | JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return _error(422, "validation", "body must be JSON", {"body": ["invalid"]})
    if type(payload) is not dict:
        return _error(422, "validation", "body must be an object", {"body": ["invalid"]})
    return payload


def _uuid(value: str) -> UUID | JSONResponse:
    try:
        return UUID(value)
    except ValueError:
        return _error(404, "not_found", "case was not found", {})


def _idempotency(request: Request) -> JSONResponse | None:
    if not request.headers.get("idempotency-key"):
        return _error(422, "validation", "Idempotency-Key is required", {"Idempotency-Key": ["required"]})
    return None


def _error(status: int, code: str, message: str, fields: dict[str, list[str]]) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "fields": fields,
                "retryable": False,
                "request_id": str(uuid4()),
            }
        },
    )
