"""Secret reference HTTP. Responses contain revision metadata and never the secret."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter
from aiqa.api.mutations import BrowserMutationRoute

from aiqa.api.auth import (
    AuthRequired,
    CsrfRejected,
    OriginRejected,
    ProjectHidden,
    authorize_browser,
    bound_auth_store,
)
from aiqa.security.secrets import (
    SecretScopeDenied,
    SecretUnavailable,
    SecretValidationError,
    bind_secret_store,
    latest_secret,
    put_secret,
)
from aiqa.store.database import migrate_store
from aiqa.store.models import SecretInput, SecretRefView

router = APIRouter(prefix="/api/v1", route_class=BrowserMutationRoute)


def install_secret_refs(application: FastAPI) -> None:
    """Attach secret routes. This does not open SQLite."""

    application.include_router(router)


@router.post("/projects/{project_id}/secret-refs")
async def post_secret(project_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    parsed = _project(project_id)
    if isinstance(parsed, JSONResponse):
        return parsed
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    with _bound(request):
        try:
            actor = authorize_browser(request, parsed, "secret")
            view = put_secret(
                actor,
                SecretInput(value=_text(payload.get("value")), name=_text(payload.get("name"))),
            )
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except (ProjectHidden, SecretScopeDenied):
            return _error(404, "not_found", "secret ref was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except SecretValidationError as exc:
            return _error(422, "validation", "invalid secret", exc.fields)
        except SecretUnavailable:
            return _error(500, "unavailable", "os secret store rejected the write", {})
    return JSONResponse(status_code=201, content=_view_json(view))


@router.post("/projects/{project_id}/secret-refs/{ref_id}/rotations")
async def post_rotation(project_id: str, ref_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    parsed = _pair(project_id, ref_id)
    if isinstance(parsed, JSONResponse):
        return parsed
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    project, ref = parsed
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "secret")
            view = put_secret(actor, SecretInput(value=_text(payload.get("value")), ref_id=ref))
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except (ProjectHidden, SecretScopeDenied):
            return _error(404, "not_found", "secret ref was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except SecretValidationError as exc:
            return _error(422, "validation", "invalid secret", exc.fields)
        except SecretUnavailable:
            return _error(500, "unavailable", "os secret store rejected the write", {})
    return JSONResponse(status_code=201, content=_view_json(view))


@router.get("/projects/{project_id}/secret-refs")
async def list_secret_choices(project_id: str, request: Request) -> JSONResponse:
    """Return reference metadata without resolving any secret bytes."""
    project = _project(project_id)
    if isinstance(project, JSONResponse):
        return project
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            authorize_browser(request, project, "secret")
        rows = store._connection.execute(
            """SELECT r.ref_id,r.revision,r.name,r.availability FROM secret_refs r
            WHERE r.project_id=? AND NOT EXISTS (
                SELECT 1 FROM secret_refs newer WHERE newer.project_id=r.project_id
                AND newer.ref_id=r.ref_id AND newer.revision>r.revision)
            ORDER BY r.name,r.ref_id""", (str(project),)
        ).fetchall()
    except (CsrfRejected, OriginRejected):
        return _error(403, "permission", "request was rejected", {})
    except AuthRequired:
        return _error(401, "unauthorized", "session is missing", {})
    except ProjectHidden:
        return _error(404, "not_found", "secret refs were not found", {})
    finally:
        store.close()
    return JSONResponse(content={"refs": [{"project_id":str(project),"ref_id":str(row[0]),"revision":int(row[1]),"name":str(row[2]),"availability":str(row[3])} for row in rows]})


@router.get("/projects/{project_id}/secret-refs/{ref_id}")
async def read_secret(project_id: str, ref_id: str, request: Request) -> JSONResponse:
    parsed = _pair(project_id, ref_id)
    if isinstance(parsed, JSONResponse):
        return parsed
    project, ref = parsed
    with _bound(request):
        try:
            authorize_browser(request, project, "secret")
            view = latest_secret(project, ref)
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except (ProjectHidden, SecretScopeDenied):
            return _error(404, "not_found", "secret ref was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
    if view is None:
        return _error(404, "not_found", "secret ref was not found", {})
    return JSONResponse(status_code=200, content=_view_json(view))


@contextmanager
def _bound(request: Request) -> Iterator[None]:
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bind_secret_store(store):
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


def _text(value: object) -> str:
    if type(value) is not str:
        return ""
    return value


def _project(project_id: str) -> UUID | JSONResponse:
    try:
        return UUID(project_id)
    except ValueError:
        return _error(404, "not_found", "secret ref was not found", {})


def _pair(project_id: str, ref_id: str) -> tuple[UUID, UUID] | JSONResponse:
    try:
        return UUID(project_id), UUID(ref_id)
    except ValueError:
        return _error(404, "not_found", "secret ref was not found", {})


def _idempotency(request: Request) -> JSONResponse | None:
    if not request.headers.get("idempotency-key"):
        return _error(422, "validation", "Idempotency-Key is required", {"Idempotency-Key": ["required"]})
    return None


def _view_json(view: SecretRefView) -> dict[str, object]:
    body = {
        "project_id": str(view.project_id),
        "ref_id": str(view.ref_id),
        "revision": view.revision,
        "name": view.name,
        "availability": view.availability,
    }
    return {key: value for key, value in body.items() if key != "value"}


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
