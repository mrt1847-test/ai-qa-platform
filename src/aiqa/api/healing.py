"""Repair proposal routes and the healing timeline. These routes do not call a model or open a device."""

from __future__ import annotations

import json
import sqlite3
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from aiqa.api.auth import (
    AuthRequired,
    CsrfRejected,
    OriginRejected,
    ProjectHidden,
    authorize_browser,
    authorize_page,
    bound_auth_store,
)
from aiqa.healing.proposals import ProposalRejected, read_repair_proposal, save_repair_proposal
from aiqa.store.database import migrate_store
from aiqa.store.queue import JobConflict
from aiqa.web.routes import UiQueryState, render_template


def install_healing(application: FastAPI) -> None:
    """Register proposal save, read, and the diff page."""

    async def post_proposal(episode_id: str, request: Request) -> JSONResponse:
        request_key = request.headers.get("idempotency-key", "").strip()
        if request_key == "":
            return _error(422, "validation", "Idempotency-Key is required", {"Idempotency-Key": ["required"]})
        parsed = _uuid(episode_id)
        payload = await _body(request)
        if parsed is None or isinstance(payload, JSONResponse):
            return _error(404, "not_found", "episode was not found", {}) if parsed is None else payload
        try:
            project_id = UUID(str(payload.get("project_id")))
        except (TypeError, ValueError):
            return _error(422, "validation", "proposal body is invalid", {})
        store = request.app.state.open_store()
        try:
            migrate_store(store)
            with bound_auth_store(store):
                try:
                    authorize_browser(request, project_id, "save_repair_proposal")
                except CsrfRejected:
                    return _error(403, "permission", "csrf token was rejected", {})
                except OriginRejected:
                    return _error(403, "permission", "origin was rejected", {})
                except ProjectHidden:
                    return _error(404, "not_found", "episode was not found", {})
                except AuthRequired:
                    return _error(401, "unauthorized", "session is missing", {})
                try:
                    with store.transaction() as connection:
                        view = save_repair_proposal(connection, project_id, parsed, payload, request_key)
                except ProposalRejected as exc:
                    return _error(422, "validation", exc.reason, {})
                except JobConflict:
                    return _error(409, "conflict", "idempotency body does not match", {})
        finally:
            store.close()
        return JSONResponse(status_code=200 if view.replayed else 201, content=_proposal_json(view))

    async def get_proposal(proposal_id: str, request: Request) -> JSONResponse:
        parsed = _uuid(proposal_id)
        project = _uuid(request.query_params.get("project_id", ""))
        if parsed is None or project is None:
            return _error(404, "not_found", "proposal was not found", {})
        store = request.app.state.open_store()
        try:
            migrate_store(store)
            with bound_auth_store(store):
                try:
                    authorize_browser(request, project, "read_repair_proposal")
                except CsrfRejected:
                    return _error(403, "permission", "csrf token was rejected", {})
                except OriginRejected:
                    return _error(403, "permission", "origin was rejected", {})
                except ProjectHidden:
                    return _error(404, "not_found", "proposal was not found", {})
                except AuthRequired:
                    return _error(401, "unauthorized", "session is missing", {})
                with store.transaction() as connection:
                    view = read_repair_proposal(connection, project, parsed)
        finally:
            store.close()
        if view is None:
            return _error(404, "not_found", "proposal was not found", {})
        return JSONResponse(status_code=200, content=_proposal_json(view))

    async def proposal_page(project_id: str, proposal_id: str, request: Request) -> HTMLResponse:
        project = _uuid(project_id)
        parsed = _uuid(proposal_id)
        if project is None or parsed is None:
            return HTMLResponse(status_code=404, content="제안을 찾지 못했습니다.")
        store = request.app.state.open_store()
        try:
            migrate_store(store)
            with bound_auth_store(store):
                try:
                    authorize_page(request, project)
                except (CsrfRejected, OriginRejected, ProjectHidden, AuthRequired):
                    return HTMLResponse(status_code=403, content="이 화면을 볼 권한이 없습니다.")
                with store.transaction() as connection:
                    view = read_repair_proposal(connection, project, parsed)
        finally:
            store.close()
        if view is None:
            return HTMLResponse(status_code=404, content="제안을 찾지 못했습니다.")
        return render_template(
            request,
            "components/repair_proposal.html",
            {
                "shell": True,
                "title": "불변 수정 제안",
                "heading": "불변 수정 제안",
                "section": "detail",
                "connected": True,
                "state": "ready",
                "dirty": False,
                "query": UiQueryState("", "name", "", "", ""),
                "crumbs": (("불변 수정 제안", f"/ui/projects/{project}/repair-proposals/{parsed}"),),
                "list_href": f"/ui/projects/{project}/cases/{view.case_id}/recordings",
                "detail_href": f"/ui/projects/{project}/repair-proposals/{parsed}",
                "request": request,
                "proposal_id": str(view.proposal_id),
                "diff_text": str(view.diff.get("text", "")),
            },
        )

    application.add_api_route(
        "/api/v1/healing-episodes/{episode_id}/repair-proposals",
        post_proposal,
        methods=["POST"],
    )
    application.add_api_route("/api/v1/repair-proposals/{proposal_id}", get_proposal, methods=["GET"])
    application.add_api_route(
        "/ui/projects/{project_id}/repair-proposals/{proposal_id}",
        proposal_page,
        methods=["GET"],
        response_class=HTMLResponse,
    )

    async def get_timeline(case_run_id: str, request: Request) -> JSONResponse:
        parsed = _uuid(case_run_id)
        project = _uuid(request.query_params.get("project_id", ""))
        if parsed is None or project is None:
            return _error(404, "not_found", "case run was not found", {})
        store = request.app.state.open_store()
        try:
            migrate_store(store)
            with bound_auth_store(store):
                try:
                    authorize_browser(request, project, "read_healing_timeline")
                except CsrfRejected:
                    return _error(403, "permission", "csrf token was rejected", {})
                except OriginRejected:
                    return _error(403, "permission", "origin was rejected", {})
                except ProjectHidden:
                    return _error(404, "not_found", "case run was not found", {})
                except AuthRequired:
                    return _error(401, "unauthorized", "session is missing", {})
                with store.transaction() as connection:
                    view = read_healing_timeline(connection, project, parsed)
        finally:
            store.close()
        if view is None:
            return _error(404, "not_found", "case run was not found", {})
        return JSONResponse(status_code=200, content=view)

    async def execution_page(project_id: str, execution_id: str, request: Request) -> HTMLResponse:
        project = _uuid(project_id)
        parsed = _uuid(execution_id)
        if project is None or parsed is None:
            return HTMLResponse(status_code=404, content="수행을 찾지 못했습니다.")
        store = request.app.state.open_store()
        try:
            migrate_store(store)
            with bound_auth_store(store):
                try:
                    authorize_page(request, project)
                except (CsrfRejected, OriginRejected, ProjectHidden, AuthRequired):
                    return HTMLResponse(status_code=403, content="이 화면을 볼 권한이 없습니다.")
                with store.transaction() as connection:
                    view = read_execution_healing(connection, project, parsed)
                    if view is not None:
                        from aiqa.api.executions import execution_page_fields

                        view.update(execution_page_fields(connection, project, parsed, request.query_params))
        finally:
            store.close()
        if view is None:
            return HTMLResponse(status_code=404, content="수행을 찾지 못했습니다.")
        return render_template(request, "execution.html", {"shell": False, **view})

    async def case_run_page(project_id: str, case_run_id: str, request: Request) -> HTMLResponse:
        project = _uuid(project_id)
        parsed = _uuid(case_run_id)
        if project is None or parsed is None:
            return HTMLResponse(status_code=404, content="항목을 찾지 못했습니다.")
        store = request.app.state.open_store()
        try:
            migrate_store(store)
            with bound_auth_store(store):
                try:
                    authorize_page(request, project)
                except (CsrfRejected, OriginRejected, ProjectHidden, AuthRequired):
                    return HTMLResponse(status_code=403, content="이 화면을 볼 권한이 없습니다.")
                with store.transaction() as connection:
                    view = read_healing_timeline(connection, project, parsed)
                    if view is not None:
                        from aiqa.api.case_runs import read_case_run_facts
                        from aiqa.api.executions import lineage_fields

                        view.update(read_case_run_facts(connection, project, parsed, request.query_params.get("attempt", "")))
                        view.update(lineage_fields(connection, project, UUID(str(view["execution_id"]))))
        finally:
            store.close()
        if view is None:
            return HTMLResponse(status_code=404, content="항목을 찾지 못했습니다.")
        return render_template(request, "case_run.html", {"shell": False, **view})

    application.add_api_route(
        "/api/v1/case-runs/{case_run_id}/healing-episodes",
        get_timeline,
        methods=["GET"],
    )
    application.add_api_route(
        "/ui/projects/{project_id}/executions/{execution_id}",
        execution_page,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    application.add_api_route(
        "/ui/projects/{project_id}/case-runs/{case_run_id}",
        case_run_page,
        methods=["GET"],
        response_class=HTMLResponse,
    )


def _proposal_json(view: object) -> dict[str, object]:
    from aiqa.healing.proposals import RepairProposalView

    assert isinstance(view, RepairProposalView)
    return {
        "proposal_id": str(view.proposal_id),
        "episode_id": str(view.episode_id),
        "package_id": str(view.package_id),
        "case_id": str(view.case_id),
        "diff_hash": view.diff_hash,
        "accepted_target": view.accepted_target,
        "diff": view.diff,
        "evidence_hash": view.evidence_hash,
        "replayed": view.replayed,
    }


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (TypeError, ValueError):
        return None


async def _body(request: Request) -> dict[str, object] | JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return _error(422, "validation", "proposal body is invalid", {})
    if type(payload) is not dict:
        return _error(422, "validation", "proposal body is invalid", {})
    return payload


def _error(status: int, code: str, message: str, fields: dict[str, list[str]]) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "fields": fields}})


_RUNNING = {"queued", "preparing", "running", "finalizing", "cancel_requested"}
_STATUS_LABEL = {
    "queued": "대기",
    "preparing": "준비",
    "running": "진행 중",
    "finalizing": "마무리",
    "completed": "완료",
    "cancel_requested": "취소 요청",
    "cancelled": "취소",
    "error": "오류",
    "lost": "유실",
}
_ERROR_LABEL = {
    "target_not_found": "대상을 찾지 못했습니다",
    "ambiguous": "대상이 여럿입니다",
    "layout_shift": "화면이 바뀌었습니다",
}


def read_execution_healing(
    connection: sqlite3.Connection, project_id: UUID, execution_id: UUID
) -> dict[str, object] | None:
    """Read the first item of one execution for the progress screen."""

    row = connection.execute(
        """
        SELECT case_run_id FROM case_runs
        WHERE project_id = ? AND execution_id = ?
        ORDER BY case_run_id
        LIMIT 1
        """,
        (str(project_id), str(execution_id)),
    ).fetchone()
    if row is None:
        return None
    return read_healing_timeline(connection, project_id, UUID(str(row[0])))


def read_healing_timeline(
    connection: sqlite3.Connection, project_id: UUID, case_run_id: UUID
) -> dict[str, object] | None:
    """Assemble one item timeline from stored episode facts. This does not reserve or call a model."""

    run = connection.execute(
        """
        SELECT case_runs.case_id, case_runs.execution_id, jobs.status
        FROM case_runs
        LEFT JOIN jobs
          ON jobs.project_id = case_runs.project_id
         AND jobs.case_run_id = case_runs.case_run_id
        WHERE case_runs.project_id = ? AND case_runs.case_run_id = ?
        """,
        (str(project_id), str(case_run_id)),
    ).fetchone()
    if run is None:
        return None
    status = "" if run[2] is None else str(run[2])
    episode = connection.execute(
        """
        SELECT episode_id, attempt_id FROM healing_episodes
        WHERE project_id = ? AND case_run_id = ?
        """,
        (str(project_id), str(case_run_id)),
    ).fetchone()
    reason = ""
    proposal_id = ""
    same_target = False
    override_id = ""
    dispatch_state = ""
    call_count = 0
    satisfied = False
    violated = False
    if episode is not None:
        reservation = connection.execute(
            """
            SELECT reason FROM healing_reservations
            WHERE project_id = ? AND episode_id = ?
            """,
            (str(project_id), str(episode[0])),
        ).fetchone()
        if reservation is not None:
            reason = _ERROR_LABEL.get(str(reservation[0]), str(reservation[0]))
        proposal = connection.execute(
            """
            SELECT proposal_id, accepted_target_json FROM repair_proposals
            WHERE project_id = ? AND episode_id = ?
            """,
            (str(project_id), str(episode[0])),
        ).fetchone()
        if proposal is not None:
            proposal_id = str(proposal[0])
            same_target = _same_target(str(proposal[1]))
        override = connection.execute(
            """
            SELECT override_id FROM runtime_overrides
            WHERE project_id = ? AND episode_id = ?
            """,
            (str(project_id), str(episode[0])),
        ).fetchone()
        if override is not None:
            override_id = str(override[0])
        action = connection.execute(
            """
            SELECT dispatch_state FROM actions
            WHERE project_id = ? AND attempt_id = ?
            ORDER BY action_seq DESC
            LIMIT 1
            """,
            (str(project_id), str(episode[1])),
        ).fetchone()
        if action is not None:
            dispatch_state = str(action[0])
        checks = connection.execute(
            """
            SELECT status FROM check_results
            WHERE project_id = ? AND attempt_id = ?
            """,
            (str(project_id), str(episode[1])),
        ).fetchall()
        satisfied = any(str(item[0]) == "satisfied" for item in checks)
        violated = any(str(item[0]) == "violated" for item in checks)
        counted = connection.execute(
            """
            SELECT COUNT(*) FROM model_call_facts
            WHERE project_id = ? AND attempt_id = ? AND role = 'healing'
            """,
            (str(project_id), str(episode[1])),
        ).fetchone()
        call_count = 0 if counted is None else int(counted[0])
    running = status in _RUNNING
    if violated:
        qa_label = "실패"
    elif satisfied:
        qa_label = "만족"
    else:
        qa_label = "대기"
    if running and episode is not None:
        phase = "치유"
    elif running and (satisfied or violated):
        phase = "검증"
    else:
        phase = "재생" if episode is None else "치유"
    finished = status not in _RUNNING and status != ""
    terminal_failed = finished and episode is not None and (violated or status in {"error", "cancelled", "lost"})
    case_id = str(run[0])
    return {
        "project_id": str(project_id),
        "case_id": case_id,
        "execution_id": str(run[1]),
        "case_run_id": str(case_run_id),
        "job_status": _STATUS_LABEL.get(status, "대기"),
        "running": running,
        "toggle_enabled": not running,
        "default_enabled": False,
        "phase": phase,
        "episode_count": 0 if episode is None else 1,
        "call_count": call_count,
        "max_episodes": 1,
        "max_calls": 2,
        "max_seconds": 30,
        "original_error": reason,
        "proposal_id": proposal_id,
        "same_target": same_target,
        "override_id": override_id,
        "dispatch_state": dispatch_state,
        "qa_label": qa_label,
        "badge": override_id != "" and satisfied and not violated,
        "terminal_failed": terminal_failed,
        "new_run_href": f"/ui/projects/{project_id}/cases/{case_id}/execution-setup",
    }


def _same_target(raw: str) -> bool:
    if raw.strip() == "":
        return False
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return type(parsed) is dict and parsed.get("same_target") is True
