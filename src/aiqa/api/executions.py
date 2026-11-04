"""Trial preview, admission, and execution list routes. These routes do not open a device or a model."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.routing import APIRouter

from aiqa.api.auth import (
    AuthRequired,
    CsrfRejected,
    OriginRejected,
    ProjectHidden,
    authorize_browser,
    authorize_page,
    bound_auth_store,
)
from aiqa.contracts.jobs import IdempotencyKey
from aiqa.domain.executions import (
    ExecutionMissing,
    ExecutionRejected,
    cancel_case_run,
    cancel_execution,
    enqueue_execution,
    preview_execution,
    preview_rerun,
    rerun_targets,
    skip_case_run,
)
from aiqa.store.database import migrate_store
from aiqa.store.models import Transaction
from aiqa.store.queue import JobConflict
from aiqa.web.routes import render_template

router = APIRouter(prefix="/api/v1")
pages = APIRouter()


def install_executions(application: FastAPI) -> None:
    """Attach trial routes once. This does not open SQLite."""

    if getattr(application.state, "executions_installed", False):
        return
    application.include_router(router)
    application.include_router(pages)
    application.state.executions_installed = True


@router.post("/projects/{project_id}/execution-previews")
async def post_preview(project_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    with _bound(request) as store:
        try:
            actor = authorize_browser(request, project, "execution_preview")
            with store.transaction() as connection:
                preview = preview_execution(Transaction(connection), actor, project, payload)
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "trial was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except ExecutionRejected:
            return _error(422, "validation", "trial is not ready", {})
    return JSONResponse(status_code=200, content=_preview_json(preview))


@router.post("/projects/{project_id}/executions")
async def post_execution(project_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    with _bound(request) as store:
        try:
            actor = authorize_browser(request, project, "enqueue_execution")
            key = IdempotencyKey(actor.actor_id, project, "enqueue_execution", request.headers.get("idempotency-key", "").strip())
            with store.transaction() as connection:
                receipt = enqueue_execution(Transaction(connection), actor, project, payload, key)
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "trial was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except JobConflict:
            return _error(409, "conflict", "idempotency body does not match", {})
        except ExecutionRejected:
            return _error(422, "validation", "trial is not ready", {})
    return JSONResponse(status_code=200 if receipt.replayed else 201, content=_receipt_json(receipt))


@pages.get("/ui/projects/{project_id}/cases/{case_id}/execution-setup", response_class=HTMLResponse)
async def execution_setup_page(project_id: str, case_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    parsed = _uuid(case_id)
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return HTMLResponse(status_code=404, content="케이스를 찾지 못했습니다.")
    with _bound(request) as store:
        try:
            authorize_page(request, project)
        except (AuthRequired, OriginRejected, ProjectHidden):
            return HTMLResponse(status_code=403, content="이 화면을 볼 권한이 없습니다.")
        with store.transaction() as connection:
            case = connection.execute('SELECT name FROM automation_cases WHERE project_id=? AND case_id=?',(str(project),str(parsed))).fetchone()
            if case is None:
                return HTMLResponse(status_code=404,content="케이스를 찾지 못했습니다.")
            versions = [dict(id=row[0],revision=row[1],package_id=row[2]) for row in connection.execute('SELECT version_id,revision,replay_package_id FROM case_versions WHERE project_id=? AND case_id=? ORDER BY revision DESC',(str(project),str(parsed)))]
        from aiqa.domain.environments import bind_environment_store, list_environment_profiles
        from aiqa.domain.datasets import bind_dataset_store, list_datasets
        from aiqa.worker.resources import bind_inventory_store, list_resources
        with bind_environment_store(store), bind_dataset_store(store), bind_inventory_store(store):
            profiles=list_environment_profiles(project)
            datasets=list_datasets(project)
            resources=list_resources(project)
    return render_template(
        request,
        "execution_setup.html",
        {"project_id": str(project), "case_id": str(parsed), "case_name": str(case[0]), "versions": versions, "profiles": profiles, "datasets": datasets, "resources": resources, "shell": True, "crumbs": ((str(case[0]),f'/ui/projects/{project}/cases/{parsed}'),('시범 준비',''))},
    )


@router.get("/projects/{project_id}/executions")
async def get_executions(project_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return project
    with _bound(request) as store:
        try:
            authorize_browser(request, project, "read_executions")
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "trial was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        with store.transaction() as connection:
            listed = read_execution_list(connection, project, request.query_params)
    return JSONResponse(status_code=200, content={"items": listed["items"], "page": listed["page"], "empty": listed["empty"]})


@router.get("/executions/{execution_id}")
async def get_execution(execution_id: str, request: Request) -> JSONResponse:
    project = _uuid(request.query_params.get("project_id", ""))
    parsed = _uuid(execution_id)
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return _error(404, "not_found", "trial was not found", {})
    with _bound(request) as store:
        try:
            authorize_browser(request, project, "read_execution")
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "trial was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        with store.transaction() as connection:
            view = read_execution_detail(connection, project, parsed, request.query_params)
    if view is None:
        return _error(404, "not_found", "trial was not found", {})
    return JSONResponse(status_code=200, content=view)


@router.get("/case-runs/{case_run_id}")
async def get_case_run(case_run_id: str, request: Request) -> JSONResponse:
    project = _uuid(request.query_params.get("project_id", ""))
    parsed = _uuid(case_run_id)
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return _error(404, "not_found", "trial was not found", {})
    with _bound(request) as store:
        try:
            authorize_browser(request, project, "read_case_run")
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "trial was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        with store.transaction() as connection:
            view = read_case_run_detail(connection, project, parsed)
            if view is not None:
                from aiqa.api.case_runs import read_case_run_facts

                view.update(read_case_run_facts(connection, project, parsed, request.query_params.get("attempt", "")))
    if view is None:
        return _error(404, "not_found", "trial was not found", {})
    return JSONResponse(status_code=200, content=view)


@router.post("/executions/{execution_id}/cancel")
async def post_execution_cancel(execution_id: str, request: Request) -> JSONResponse:
    return await _cancel_response(request, execution_id, None)


@router.post("/case-runs/{case_run_id}/cancel")
async def post_case_run_cancel(case_run_id: str, request: Request) -> JSONResponse:
    return await _cancel_response(request, None, case_run_id)


@router.post("/executions/{execution_id}/reruns")
async def post_rerun(execution_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(request.query_params.get("project_id", ""))
    parsed = _uuid(execution_id)
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return _error(404, "not_found", "trial was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    with _bound(request) as store:
        try:
            actor = authorize_browser(request, project, "rerun_execution")
            key = IdempotencyKey(actor.actor_id, project, "rerun_execution", request.headers.get("idempotency-key", "").strip())
            with store.transaction() as connection:
                before = _rerun_count(connection, project, parsed)
                preview = preview_rerun(Transaction(connection), actor, parsed, payload, key)
                created = _rerun_count(connection, project, parsed) > before
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "trial was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except ExecutionMissing:
            return _error(404, "not_found", "trial was not found", {})
        except JobConflict:
            return _error(409, "conflict", "rerun was rejected", {})
        except ExecutionRejected:
            return _error(422, "validation", "rerun was rejected", {})
    return JSONResponse(status_code=201 if created else 200, content=_preview_json(preview))


def _rerun_count(connection: object, project_id: UUID, execution_id: UUID) -> int:
    rows = connection.execute(  # type: ignore[attr-defined]
        "SELECT limits FROM jobs WHERE project_id = ?",
        (str(project_id),),
    ).fetchall()
    return sum(1 for row in rows if f'"original_execution_id":"{execution_id}"' in str(row[0]))


@router.post("/case-runs/{case_run_id}/skip")
async def post_case_run_skip(case_run_id: str, request: Request) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(request.query_params.get("project_id", ""))
    parsed = _uuid(case_run_id)
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return _error(404, "not_found", "trial was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    reason = payload.get("reason")
    if type(reason) is not str:
        return _error(422, "validation", "skip reason is required", {"reason": ["required"]})
    with _bound(request) as store:
        try:
            actor = authorize_browser(request, project, "skip_case_run")
            key = IdempotencyKey(actor.actor_id, project, "skip_case_run", request.headers.get("idempotency-key", "").strip())
            with store.transaction() as connection:
                view = skip_case_run(Transaction(connection), actor, parsed, reason, key)
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "trial was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except ExecutionMissing:
            return _error(404, "not_found", "trial was not found", {})
        except JobConflict:
            return _error(409, "conflict", "skip was rejected", {})
        except ExecutionRejected:
            return _error(422, "validation", "skip was rejected", {})
    return JSONResponse(
        status_code=200 if view.replayed else 202,
        content={
            "case_run_id": str(view.case_run_id),
            "result": view.result,
            "reason": view.reason,
            "actor_id": str(view.actor_id),
            "replayed": view.replayed,
        },
    )


async def _cancel_response(request: Request, execution_id: str | None, case_run_id: str | None) -> JSONResponse:
    rejected = _idempotency(request)
    if rejected is not None:
        return rejected
    project = _uuid(request.query_params.get("project_id", ""))
    parsed = _uuid(execution_id or case_run_id or "")
    if isinstance(project, JSONResponse) or isinstance(parsed, JSONResponse):
        return _error(404, "not_found", "trial was not found", {})
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    with _bound(request) as store:
        try:
            actor = authorize_browser(request, project, "cancel_execution" if case_run_id is None else "cancel_case_run")
            operation = "cancel_execution" if case_run_id is None else "cancel_case_run"
            key = IdempotencyKey(actor.actor_id, project, operation, request.headers.get("idempotency-key", "").strip())
            with store.transaction() as connection:
                if case_run_id is None:
                    receipt = cancel_execution(Transaction(connection), actor, parsed, key)
                else:
                    receipt = cancel_case_run(Transaction(connection), actor, parsed, key)
        except CsrfRejected:
            return _error(403, "permission", "csrf token was rejected", {})
        except OriginRejected:
            return _error(403, "permission", "origin was rejected", {})
        except ProjectHidden:
            return _error(404, "not_found", "trial was not found", {})
        except AuthRequired:
            return _error(401, "unauthorized", "session is missing", {})
        except ExecutionMissing:
            return _error(404, "not_found", "trial was not found", {})
        except JobConflict:
            return _error(409, "conflict", "cancel was rejected", {})
        except ExecutionRejected:
            return _error(422, "validation", "cancel was rejected", {})
    return JSONResponse(status_code=200 if receipt.replayed else 202, content=_cancel_json(receipt))


def _cancel_json(receipt: object) -> dict[str, object]:
    from aiqa.domain.executions import CancellationReceipt

    assert isinstance(receipt, CancellationReceipt)
    return {
        "execution_id": str(receipt.execution_id),
        "case_run_id": None if receipt.case_run_id is None else str(receipt.case_run_id),
        "phase": receipt.phase,
        "effects": receipt.effects,
        "replayed": receipt.replayed,
        "preserved_result": receipt.preserved_result,
    }


@pages.get("/ui/projects/{project_id}/executions", response_class=HTMLResponse)
async def executions_page(project_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    if isinstance(project, JSONResponse):
        return HTMLResponse(status_code=404, content="수행을 찾지 못했습니다.")
    with _bound(request) as store:
        try:
            authorize_page(request, project)
        except (AuthRequired, OriginRejected, ProjectHidden):
            return HTMLResponse(status_code=403, content="이 화면을 볼 권한이 없습니다.")
        with store.transaction() as connection:
            listed = read_execution_list(connection, project, request.query_params)
    return render_template(
        request,
        "executions.html",
        {
            "shell": False,
            "project_id": str(project),
            "crumbs": (("테스트 수행", ""),),
            **listed,
        },
    )


_PAGE_SIZE = 20
_WAITING = {"queued", "preparing"}
_RUNNING = {"running", "finalizing", "cancel_requested"}
_DONE = {"completed", "cancelled", "error", "lost"}


def read_execution_list(
    connection: object, project_id: UUID, query: Mapping[str, str]
) -> dict[str, object]:
    """Read one page of runs. This does not insert a job."""

    rows = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT execution_id, name, purpose, source, scope_requested_at
        FROM executions
        WHERE project_id = ?
        ORDER BY scope_requested_at, execution_id
        """,
        (str(project_id),),
    ).fetchall()
    views = [_execution_summary(connection, project_id, row) for row in rows]
    selected = [item for item in views if _matches(item, query)]
    page = _page(query)
    start = (page - 1) * _PAGE_SIZE
    window = selected[start : start + _PAGE_SIZE]
    return {
        "items": window,
        "page": page,
        "empty": len(window) == 0,
        "status": query.get("status", "all"),
        "purpose": query.get("purpose", ""),
        "source": query.get("source", ""),
        "requester": query.get("requester", ""),
        "environment": query.get("env", ""),
        "build": query.get("build", ""),
        "result": query.get("result", ""),
        "since": query.get("since", ""),
        "until": query.get("until", ""),
    }


def read_execution_detail(
    connection: object, project_id: UUID, execution_id: UUID, query: Mapping[str, str]
) -> dict[str, object] | None:
    """Read one run, its items, and the saved selection. This does not insert a job."""

    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT execution_id, name, purpose, source, scope_requested_at
        FROM executions
        WHERE project_id = ? AND execution_id = ?
        """,
        (str(project_id), str(execution_id)),
    ).fetchone()
    if row is None:
        return None
    summary = _execution_summary(connection, project_id, row)
    items = _execution_items(connection, project_id, execution_id, query.get("item", ""))
    representative = next((item for item in items if item["list_state"] == "running"), items[0] if items else None)
    phase = "" if representative is None else str(representative["phase"])
    job_status = "" if representative is None else str(representative["job_status"])
    summary.update(execution_page_fields(connection, project_id, execution_id, query))
    summary["phase"] = phase
    summary["job_status"] = job_status
    return summary


def read_case_run_detail(connection: object, project_id: UUID, case_run_id: UUID) -> dict[str, object] | None:
    """Read one item. This does not insert a job."""

    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT execution_id FROM case_runs
        WHERE project_id = ? AND case_run_id = ?
        """,
        (str(project_id), str(case_run_id)),
    ).fetchone()
    if row is None:
        return None
    items = _execution_items(connection, project_id, UUID(str(row[0])), str(case_run_id))
    matched = next((item for item in items if item["case_run_id"] == str(case_run_id)), None)
    return matched


def execution_page_fields(
    connection: object, project_id: UUID, execution_id: UUID, query: Mapping[str, str]
) -> dict[str, object]:
    """Template fields for one run. Missing selection stays blank."""

    selected = query.get("item", "")
    items = _execution_items(connection, project_id, execution_id, selected)
    summary_row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT execution_id, name, purpose, source, scope_requested_at
        FROM executions
        WHERE project_id = ? AND execution_id = ?
        """,
        (str(project_id), str(execution_id)),
    ).fetchone()
    summary = None if summary_row is None else _execution_summary(connection, project_id, summary_row)
    link = query.get("link", "")
    if link == "down":
        connection_label = "연결이 끊겼습니다"
    elif link == "restored":
        connection_label = "다시 연결되었습니다"
    else:
        connection_label = "연결 확인"
    known = {str(item["case_run_id"]) for item in items}
    return {
        "finished_count": 0 if summary is None else summary["finished_count"],
        "pass_count": 0 if summary is None else summary["pass_count"],
        "waiting_count": 0 if summary is None else summary["waiting_count"],
        "running_count": 0 if summary is None else summary["running_count"],
        "done_count": 0 if summary is None else summary["done_count"],
        "items": items,
        "selected_item_id": selected if selected in known else "",
        "connection_label": connection_label,
        "stale_label": "연결이 오래되었습니다" if link == "stale" else "",
        "run_name": "" if summary is None else summary["name"],
        "run_purpose": "" if summary is None else summary["purpose"],
        "run_source": "" if summary is None else summary["source"],
        "requester": "" if summary is None else summary["requester"],
        "environment": "" if summary is None else summary["environment"],
        "build": "" if summary is None else summary["build"],
        "requested_at": "" if summary is None else summary["requested_at"],
        "execution_id": str(execution_id),
        "project_id": str(project_id),
        **lineage_fields(connection, project_id, execution_id),
    }


def lineage_fields(connection: object, project_id: UUID, execution_id: UUID) -> dict[str, object]:
    """Original, root, and reason copied onto a rerun. An ordinary run leaves them blank."""

    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT jobs.limits
        FROM case_runs
        JOIN jobs
          ON jobs.project_id = case_runs.project_id
         AND jobs.case_run_id = case_runs.case_run_id
        WHERE case_runs.project_id = ? AND case_runs.execution_id = ?
        ORDER BY case_runs.rowid
        LIMIT 1
        """,
        (str(project_id), str(execution_id)),
    ).fetchone()
    limits: dict[str, object] = {}
    if row is not None:
        try:
            parsed = json.loads(str(row[0]))
        except json.JSONDecodeError:
            parsed = {}
        if type(parsed) is dict:
            limits = parsed
    original_case = limits.get("original_case_run_id")
    result = ""
    if type(original_case) is str and original_case != "":
        stored = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT core_result FROM item_finalizations
            WHERE project_id = ? AND case_run_id = ?
            """,
            (str(project_id), original_case),
        ).fetchone()
        result = "" if stored is None or stored[0] is None else str(stored[0])
    original = limits.get("original_execution_id")
    root = limits.get("root_execution_id")
    reason = limits.get("rerun_reason")
    return {
        "rerun_targets": rerun_targets(connection, project_id, execution_id),
        "original_execution_id": original if type(original) is str else "",
        "root_execution_id": root if type(root) is str else "",
        "rerun_reason": reason if type(reason) is str else "",
        "original_result": result,
        "configuration_label": "구성 변경을 명시했습니다" if limits.get("configuration_changed") is True else "같은 구성입니다",
    }


def _execution_summary(connection: object, project_id: UUID, row: tuple[object, ...]) -> dict[str, object]:
    execution_id = str(row[0])
    jobs = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT jobs.job_id, jobs.status, jobs.limits
        FROM case_runs
        JOIN jobs
          ON jobs.project_id = case_runs.project_id
         AND jobs.case_run_id = case_runs.case_run_id
        WHERE case_runs.project_id = ? AND case_runs.execution_id = ?
        ORDER BY case_runs.case_run_id
        """,
        (str(project_id), execution_id),
    ).fetchall()
    statuses = [str(job[1]) for job in jobs]
    waiting = sum(1 for status in statuses if status in _WAITING)
    running = sum(1 for status in statuses if status in _RUNNING)
    done = sum(1 for status in statuses if status in _DONE)
    finished = done
    success = sum(1 for job in jobs if _is_success(connection, project_id, str(job[0]), str(job[1])))
    environment, build = "", ""
    for job in jobs:
        environment, build = _limits(str(job[2]))
        if environment != "" or build != "":
            break
    if running:
        list_state = "running"
    elif waiting and done == 0:
        list_state = "waiting"
    elif waiting:
        list_state = "running"
    elif done:
        list_state = "done"
    else:
        list_state = "waiting"
    return {
        "execution_id": execution_id,
        "name": str(row[1]),
        "purpose": str(row[2]),
        "source": str(row[3]),
        "requester": _requester(connection, project_id, execution_id),
        "environment": environment,
        "build": build,
        "finished_count": finished,
        "pass_count": success,
        "waiting_count": waiting,
        "running_count": running,
        "done_count": done,
        "requested_at": str(row[4]),
        "list_state": list_state,
    }


def _execution_items(
    connection: object, project_id: UUID, execution_id: UUID, selected: str
) -> list[dict[str, object]]:
    from aiqa.api.healing import read_healing_timeline

    rows = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT case_run_id FROM case_runs
        WHERE project_id = ? AND execution_id = ?
        ORDER BY case_run_id
        """,
        (str(project_id), str(execution_id)),
    ).fetchall()
    items: list[dict[str, object]] = []
    for row in rows:
        case_run_id = UUID(str(row[0]))
        timeline = read_healing_timeline(connection, project_id, case_run_id)
        if timeline is None:
            continue
        job = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT job_id, status FROM jobs
            WHERE project_id = ? AND case_run_id = ?
            """,
            (str(project_id), str(case_run_id)),
        ).fetchone()
        attempt = None
        if job is not None:
            attempt = connection.execute(  # type: ignore[attr-defined]
                """
                SELECT attempt_id, physical_key_id FROM attempts
                WHERE project_id = ? AND job_id = ?
                ORDER BY generation
                LIMIT 1
                """,
                (str(project_id), str(job[0])),
            ).fetchone()
        events: list[tuple[object, ...]] = []
        if attempt is not None:
            events = connection.execute(  # type: ignore[attr-defined]
                """
                SELECT event_type FROM attempt_events
                WHERE project_id = ? AND attempt_id = ?
                ORDER BY local_seq
                """,
                (str(project_id), str(attempt[0])),
            ).fetchall()
        resource = "자원 없음"
        if attempt is not None and attempt[1] is not None:
            alias = connection.execute(  # type: ignore[attr-defined]
                """
                SELECT display_name FROM resource_aliases
                WHERE project_id = ? AND physical_key_id = ?
                """,
                (str(project_id), str(attempt[1])),
            ).fetchone()
            resource = str(attempt[1]) if alias is None else str(alias[0])
        status = "" if job is None else str(job[1])
        cancel_label = "유지" if status in _DONE else ""
        if job is not None:
            flags = connection.execute(  # type: ignore[attr-defined]
                """
                SELECT runner_stopped, cleanup_completed FROM job_cancellations
                WHERE project_id = ? AND job_id = ?
                """,
                (str(project_id), str(job[0])),
            ).fetchone()
            if flags is not None:
                if int(flags[1]) == 1:
                    cancel_label = "정리"
                elif int(flags[0]) == 1:
                    cancel_label = "정지"
                else:
                    cancel_label = "취소 요청"
        skip = None
        if job is not None:
            skip = connection.execute(  # type: ignore[attr-defined]
                """
                SELECT actor_id, status FROM job_receipts
                WHERE project_id = ? AND case_run_id = ? AND operation = 'skip_case_run'
                """,
                (str(project_id), str(case_run_id)),
            ).fetchone()
        items.append(
            {
                "case_run_id": str(case_run_id),
                "execution_id": str(execution_id),
                "phase": str(timeline["phase"]),
                "job_status": str(timeline["job_status"]),
                "calls": timeline["call_count"],
                "screen": "화면 없음" if not events else str(events[-1][0]),
                "event_count": len(events),
                "elapsed": "0" if not events else "기록됨",
                "resource": resource,
                "selected": selected == str(case_run_id),
                "cancel_label": cancel_label,
                "skip_reason": "" if skip is None else str(skip[1]),
                "skip_actor": "" if skip is None else str(skip[0]),
                "list_state": "running" if status in _RUNNING else "done" if status in _DONE else "waiting",
                "finished_count": 1 if status in _DONE else 0,
                "pass_count": 1 if job is not None and _is_success(connection, project_id, str(job[0]), status) else 0,
            }
        )
    return items


def _matches(item: dict[str, object], query: Mapping[str, str]) -> bool:
    status = query.get("status", "all")
    if status not in {"", "all"} and item["list_state"] != status:
        return False
    purpose = query.get("purpose", "")
    if purpose != "" and item["purpose"] != purpose:
        return False
    source = query.get("source", "")
    if source != "" and item["source"] != source:
        return False
    requester = query.get("requester", "")
    if requester != "" and requester not in str(item["requester"]):
        return False
    environment = query.get("env", "")
    if environment != "" and environment not in str(item["environment"]):
        return False
    build = query.get("build", "")
    if build != "" and build not in str(item["build"]):
        return False
    result = query.get("result", "")
    if result == "failure" and not (int(item["finished_count"]) > int(item["pass_count"])):
        return False
    if result == "success" and not (
        int(item["finished_count"]) > 0 and int(item["finished_count"]) == int(item["pass_count"]) and item["list_state"] == "done"
    ):
        return False
    since = query.get("since", "")
    if since != "" and str(item["requested_at"]) < since:
        return False
    until = query.get("until", "")
    if until != "" and str(item["requested_at"]) > until:
        return False
    return True


def _requester(connection: object, project_id: UUID, execution_id: str) -> str:
    receipt = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT actor_id FROM job_receipts
        WHERE project_id = ? AND execution_id = ?
        ORDER BY created_at
        LIMIT 1
        """,
        (str(project_id), execution_id),
    ).fetchone()
    if receipt is not None:
        return str(receipt[0])
    owner = connection.execute(  # type: ignore[attr-defined]
        "SELECT actor_id FROM projects WHERE project_id = ?",
        (str(project_id),),
    ).fetchone()
    return "" if owner is None else str(owner[0])


def _limits(raw: str) -> tuple[str, str]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return "", ""
    if type(parsed) is not dict:
        return "", ""
    environment = parsed.get("environment_revision_id", "")
    build = parsed.get("build_id", "")
    return (environment if type(environment) is str else "", build if type(build) is str else "")


def _is_success(connection: object, project_id: UUID, job_id: str, status: str) -> bool:
    if status != "completed":
        return False
    fact = connection.execute(  # type: ignore[attr-defined]
        "SELECT verdict FROM job_finish_facts WHERE project_id = ? AND job_id = ?",
        (str(project_id), job_id),
    ).fetchone()
    if fact is not None and fact[0] in {"FAIL", "INCONCLUSIVE"}:
        return False
    violated = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT 1
        FROM attempts
        JOIN check_results
          ON check_results.project_id = attempts.project_id
         AND check_results.attempt_id = attempts.attempt_id
        WHERE attempts.project_id = ? AND attempts.job_id = ? AND check_results.status = 'violated'
        LIMIT 1
        """,
        (str(project_id), job_id),
    ).fetchone()
    return violated is None


def _page(query: Mapping[str, str]) -> int:
    try:
        page = int(query.get("page", "1"))
    except ValueError:
        return 1
    return 1 if page < 1 else page


def _preview_json(preview: object) -> dict[str, object]:
    from aiqa.domain.executions import ExecutionPreview

    assert isinstance(preview, ExecutionPreview)
    return {
        "preview_hash": preview.preview_hash,
        "proposed_n": preview.proposed_n,
        "self_healing_enabled": preview.self_healing_enabled,
        "ready": preview.ready,
        "reserved": preview.reserved,
        "silent_exclusions": preview.silent_exclusions,
        "release_label": preview.release_label,
        "release_floor_runs": preview.release_floor_runs,
        "exclusions": [{"entry_id": item.entry_id, "reason": item.reason} for item in preview.exclusions],
        "blockers": [{"code": blocker.code, "message": blocker.message} for blocker in preview.blockers],
        "resolved_items": [
            {
                "entry_id": item.entry_id,
                "case_version_id": str(item.case_version_id),
                "manifest_hash": item.manifest_hash,
                "replay_package_id": None if item.replay_package_id is None else str(item.replay_package_id),
                "replay_package_hash": item.replay_package_hash,
                "healing_policy_hash": item.healing_policy_hash,
                "environment_revision_id": str(item.environment_revision_id),
                "dataset_version_id":None if item.dataset_version_id is None else str(item.dataset_version_id),
                "resource_id": str(item.resource_id),
                "approval_id": None if item.approval_id is None else str(item.approval_id),
            }
            for item in preview.resolved_items
        ],
    }


def _receipt_json(receipt: object) -> dict[str, object]:
    from aiqa.domain.executions import ExecutionReceipt

    assert isinstance(receipt, ExecutionReceipt)
    return {
        "execution_id": str(receipt.execution_id),
        "item_ids": [str(item_id) for item_id in receipt.item_ids],
        "job_ids": [str(job_id) for job_id in receipt.job_ids],
        "committed_seq": receipt.committed_seq,
        "replayed": receipt.replayed,
    }


@contextmanager
def _bound(request: Request) -> Iterator[object]:
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            yield store
    finally:
        store.close()


async def _body(request: Request) -> dict[str, object] | JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return _error(422, "validation", "body must be JSON", {})
    if type(payload) is not dict:
        return _error(422, "validation", "body must be an object", {})
    return payload


def _uuid(value: str) -> UUID | JSONResponse:
    try:
        return UUID(value)
    except ValueError:
        return _error(404, "not_found", "trial was not found", {})


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
