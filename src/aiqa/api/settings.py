"""Project defaults and the settings page. Approved case rows are not rewritten here."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
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
from aiqa.domain.model_bindings import bind_model_store, save_model_binding_revision
from aiqa.security.secrets import bind_secret_store, put_secret
from aiqa.store.database import migrate_store
from aiqa.store.models import ModelBindingInput, SecretInput, SecretRef
from aiqa.web.routes import UiQueryState, render_template

router = APIRouter(prefix="/api/v1", route_class=BrowserMutationRoute)
pages = APIRouter(route_class=BrowserMutationRoute)
_ROLES = ("authoring", "verification", "healing", "maintenance")


def install_settings(application: FastAPI) -> None:
    """Attach settings routes. This does not open SQLite."""

    application.include_router(router)
    application.include_router(pages)
    from aiqa.api.audit import install_audit

    install_audit(application)


@router.get("/projects/{project_id}/settings")
async def get_settings(project_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    with _bound(request):
        try:
            authorize_browser(request, project, "settings")
            view = _read(project)
        except (CsrfRejected, OriginRejected):
            return _error(403, "permission", "request was rejected", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except ProjectHidden:
            return _error(404, "not_found", "settings were not found", {})
    return JSONResponse(status_code=200, content=view)


@router.patch("/projects/{project_id}/settings")
async def patch_settings(project_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    if payload.get("expand_approved_case_id"):
        return _error(422, "validation", "approved scope needs a new version", {})
    try:
        expected, timeout = _validated_limits(payload)
    except (TypeError, ValueError):
        return JSONResponse(status_code=422, content={"error":{"code":"validation","message":"invalid settings","fields":{"timeout_seconds":["integer 1..600 required"]},"retryable":False,"request_id":str(uuid4())},"submitted":{key:payload[key] for key in ("expected_lock","timeout_seconds","failure_policy","retention","healing_scope") if key in payload}})
    if timeout < 1 or timeout > 600:
        return _error(422, "validation", "invalid settings", {})
    failure = str(payload.get("failure_policy", "stop_on_non_pass"))
    retention = str(payload.get("retention", "default"))
    scope = str(payload.get("healing_scope", ""))
    with _bound(request):
        try:
            authorize_browser(request, project, "settings")
            stored = _write(project, expected, failure, retention, timeout, scope)
        except (CsrfRejected, OriginRejected):
            return _error(403, "permission", "request was rejected", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except ProjectHidden:
            return _error(404, "not_found", "settings were not found", {})
        except _StaleLock:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "code": "conflict",
                        "message": "settings changed",
                        "fields": {},
                        "retryable": False,
                        "request_id": str(uuid4()),
                    },
                    "submitted": {"failure_policy": failure, "healing_scope": scope, "timeout_seconds": timeout},
                },
            )
    return JSONResponse(status_code=200, content=stored)


@pages.get("/ui/projects/{project_id}/settings", response_class=HTMLResponse)
async def settings_page(project_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return HTMLResponse(status_code=404, content="설정을 찾지 못했습니다.")
    with _bound(request):
        try:
            authorize_page(request, project)
            view = _read(project)
            from aiqa.api.audit import list_audit, list_workers, storage_view

            audits = list_audit(project, "", "", 25)
            workers = list_workers(project)
            storage = storage_view(project)
            from aiqa.web.usage_context import usage_view
            from aiqa.domain.versions import _bound_store
            usage = usage_view(_bound_store()._connection,project)
            space = storage
        except (OriginRejected, ProjectHidden, AuthRequired):
            return HTMLResponse(status_code=401, content="이 화면을 볼 권한이 없습니다.")
    context = {
        "shell": True,
        "title": "기본 설정",
        "heading": "기본 설정",
        "section": "list",
        "connected": True,
        "state": "ready",
        "dirty": False,
        "query": UiQueryState("", "name", "", "", ""),
        "crumbs": (("설정", f"/ui/projects/{project}/settings"),),
        "list_href": "/ui/projects",
        "detail_href": f"/ui/projects/{project}/settings",
        "request": request,
        "project_id": str(project),
        "settings": view,
        "roles": _ROLES,
        "audits": audits["items"],
        "workers": workers,
        "storage": storage,
        "usage":usage,
        "space": space,
    }
    return render_template(request, "settings.html", context)


@pages.post("/ui/projects/{project_id}/settings")
async def settings_save(project_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    if payload.get("expand_approved_case_id"):
        return _error(422, "validation", "approved scope needs a new version", {})
    roles = payload.get("roles", [])
    if type(roles) is not list:
        return _error(422, "validation", "invalid settings", {})
    fields = {}
    seen = set()
    for item in roles:
        if type(item) is not dict or item.get('role') not in _ROLES or item.get('role') in seen:
            return _error(422, "validation", "역할을 다시 확인해 주세요.", {})
        role = item['role']
        seen.add(role)
        if item.get('mode') not in {None, 'keep', 'replace'}:
            return _error(422, "validation", "연결 해제는 아직 지원하지 않습니다.", {})
        if item.get('mode') == 'replace':
            from urllib.parse import urlsplit
            for key in ('endpoint', 'model', 'key'):
                if type(item.get(key)) is not str or not item[key].strip():
                    fields[f'{key}-{role}'] = ['교체할 연결의 값을 입력해 주세요.']
            if f'endpoint-{role}' not in fields:
                try:
                    parsed_endpoint = urlsplit(item['endpoint'])
                    if parsed_endpoint.scheme != 'https' or not parsed_endpoint.hostname or parsed_endpoint.username or parsed_endpoint.password:
                        fields[f'endpoint-{role}'] = ['사용자 정보가 없는 HTTPS 주소를 입력해 주세요.']
                except ValueError:
                    fields[f'endpoint-{role}'] = ['HTTPS 주소를 확인해 주세요.']
    if fields:
        return _error(422, 'validation', '모델 연결 입력을 확인해 주세요.', fields)
    try:
        expected, timeout = _validated_limits(payload)
    except (TypeError, ValueError):
        return JSONResponse(status_code=422, content={"error":{"code":"validation","message":"invalid settings","fields":{"timeout_seconds":["integer 1..600 required"]},"retryable":False,"request_id":str(uuid4())},"submitted":{key:payload[key] for key in ("expected_lock","timeout_seconds","failure_policy","retention","healing_scope") if key in payload}})
    with _bound(request):
        try:
            actor = authorize_browser(request, project, "settings")
            prior = _read(project)
            for item in roles:
                if type(item) is not dict:
                    continue
                if item.get('mode') == 'keep':
                    continue
                key = item.get("key", "")
                model = item.get("model", "")
                if type(key) is not str or key == "" or type(model) is not str or model == "":
                    continue
                secret = put_secret(actor, SecretInput(value=key, name=str(item.get("role", ""))))
                save_model_binding_revision(
                    ModelBindingInput(
                        project_id=project,
                        actor_id=actor.actor_id,
                        name=str(item.get("role", "")),
                        role=str(item.get("role", "")),
                        provider="local",
                        endpoint_kind="https",
                        endpoint=str(item.get("endpoint", "https://model.local")),
                        model=model,
                        key_ref=SecretRef(project, secret.ref_id, secret.revision),
                        prompt_hash="sha256:" + ("ab" * 32),
                        tariff_id="t1",
                        compatibility_status="unchecked",
                        binding_id=next((UUID(binding['binding_id']) for binding in reversed(prior['bindings']) if binding['role'] == item.get('role')), None),
                    )
                )
            stored = _write(
                project,
                expected,
                str(payload.get("failure_policy", "stop_on_non_pass")),
                str(payload.get("retention", "default")),
                timeout,
                str(payload.get("healing_scope", "")),
            )
        except (CsrfRejected, OriginRejected):
            return _error(403, "permission", "request was rejected", {})
        except (ProjectHidden, AuthRequired):
            return _error(401, "unauthorized", "session is missing", {})
        except _StaleLock:
            return _error(409, "conflict", "settings changed", {})
    return JSONResponse(status_code=201, content=stored)


def _validated_limits(payload):
    expected=payload.get('expected_lock',0)
    timeout=payload.get('timeout_seconds',600)
    if type(expected) is not int or expected < 0 or type(timeout) is not int or not 1 <= timeout <= 600:
        raise ValueError('invalid limits')
    return expected,timeout


def _read(project: UUID) -> dict[str, object]:
    from aiqa.domain.versions import _bound_store

    with _bound_store().transaction() as connection:
        row = connection.execute(
            """
            SELECT lock_version, failure_policy, retention, timeout_seconds, healing_scope
            FROM project_settings
            WHERE project_id = ?
            """,
            (str(project),),
        ).fetchone()
        bindings = connection.execute(
            """
            SELECT binding_revisions.role, binding_revisions.model, binding_revisions.endpoint,
                   binding_revisions.binding_id, binding_revisions.revision_id, binding_revisions.revision
            FROM binding_revisions
            JOIN model_bindings
              ON model_bindings.project_id = binding_revisions.project_id
             AND model_bindings.binding_id = binding_revisions.binding_id
             AND model_bindings.latest_revision_id = binding_revisions.revision_id
            WHERE binding_revisions.project_id = ?
            ORDER BY binding_revisions.role
            """,
            (str(project),),
        ).fetchall()
    if row is None:
        stored = {"lock_version": 0, "failure_policy": "stop_on_non_pass", "retention": "default", "timeout_seconds": 600, "healing_scope": ""}
    else:
        stored = {
            "lock_version": int(row[0]),
            "failure_policy": str(row[1]),
            "retention": str(row[2]),
            "timeout_seconds": int(row[3]),
            "healing_scope": str(row[4]),
        }
    stored["bindings"] = [
        {"role": str(item[0]), "model": str(item[1]), "endpoint": str(item[2]), "binding_id": str(item[3]), "revision_id": str(item[4]), "revision": int(item[5])}
        for item in bindings
    ]
    return stored


def _write(project: UUID, expected: int, failure: str, retention: str, timeout: int, scope: str) -> dict[str, object]:
    from aiqa.domain.versions import _bound_store

    with _bound_store().transaction() as connection:
        exists = connection.execute(
            "SELECT 1 FROM projects WHERE project_id = ?",
            (str(project),),
        ).fetchone()
        if exists is None:
            raise ProjectHidden("settings were not found")
        current = connection.execute(
            "SELECT lock_version FROM project_settings WHERE project_id = ?",
            (str(project),),
        ).fetchone()
        if current is None:
            if expected != 0:
                raise _StaleLock()
            connection.execute(
                """
                INSERT INTO project_settings (
                    project_id, lock_version, failure_policy, retention, timeout_seconds, healing_scope
                ) VALUES (?, 1, ?, ?, ?, ?)
                """,
                (str(project), failure, retention, timeout, scope),
            )
        else:
            updated = connection.execute(
                """
                UPDATE project_settings
                SET lock_version = lock_version + 1, failure_policy = ?, retention = ?,
                    timeout_seconds = ?, healing_scope = ?
                WHERE project_id = ? AND lock_version = ?
                """,
                (failure, retention, timeout, scope, str(project), expected),
            )
            if updated.rowcount != 1:
                raise _StaleLock()
    return _read(project)


class _StaleLock(Exception):
    """Another settings write landed first."""


@contextmanager
def _bound(request: Request) -> Iterator[None]:
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        from aiqa.domain.versions import bind_case_store

        from aiqa.api.audit import bind_audit_store

        with bind_case_store(store):
            with bind_secret_store(store):
                with bind_model_store(store):
                    with bind_audit_store(store):
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
        return _error(404, "not_found", "settings were not found", {})


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
