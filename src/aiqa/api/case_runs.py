"""Case run detail and attempt list. This does not open a device or a model."""

from __future__ import annotations

import json
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
from aiqa.domain.analysis import (
    AnalysisConflict,
    AnalysisMissing,
    AnalysisRecord,
    AnalysisRejected,
    append_analysis_record,
    list_analysis_records,
    read_original_verdict,
)
from aiqa.store.database import migrate_store
from aiqa.store.models import Transaction
from aiqa.web.routes import render_template


def install_case_runs(application: FastAPI) -> None:
    """Attach the attempt list once. This does not open SQLite."""

    if getattr(application.state, "case_runs_installed", False):
        return
    application.add_api_route("/api/v1/case-runs/{case_run_id}/attempts", get_attempts, methods=["GET"])
    application.add_api_route("/api/v1/case-runs/{case_run_id}/analysis-records", get_analysis, methods=["GET"])
    application.add_api_route("/api/v1/case-runs/{case_run_id}/analysis-records", post_analysis, methods=["POST"])
    application.add_api_route(
        "/ui/projects/{project_id}/case-runs/{case_run_id}/analysis",
        analysis_page,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    application.state.case_runs_installed = True


async def get_attempts(case_run_id: str, request: Request) -> JSONResponse:
    project = _uuid(request.query_params.get("project_id", ""))
    parsed = _uuid(case_run_id)
    if project is None or parsed is None:
        return _error(404, "not_found", "trial was not found")
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                authorize_browser(request, project, "read_case_run")
            except CsrfRejected:
                return _error(403, "permission", "csrf token was rejected")
            except OriginRejected:
                return _error(403, "permission", "origin was rejected")
            except ProjectHidden:
                return _error(404, "not_found", "trial was not found")
            except AuthRequired:
                return _error(401, "unauthorized", "session is missing")
            with store.transaction() as connection:
                items = read_case_run_attempts(connection, project, parsed)
    finally:
        store.close()
    if items is None:
        return _error(404, "not_found", "trial was not found")
    return JSONResponse(status_code=200, content={"items": items})


async def get_analysis(case_run_id: str, request: Request) -> JSONResponse:
    project = _uuid(request.query_params.get("project_id", ""))
    parsed = _uuid(case_run_id)
    if project is None or parsed is None:
        return _error(404, "not_found", "trial was not found")
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_browser(request, project, "read_analysis")
                with store.transaction() as connection:
                    page = list_analysis_records(Transaction(connection), actor, project, parsed)
            except CsrfRejected:
                return _error(403, "permission", "csrf token was rejected")
            except OriginRejected:
                return _error(403, "permission", "origin was rejected")
            except ProjectHidden:
                return _error(404, "not_found", "trial was not found")
            except AuthRequired:
                return _error(401, "unauthorized", "session is missing")
            except AnalysisMissing:
                return _error(404, "not_found", "trial was not found")
            except AnalysisRejected:
                return _error(422, "validation", "analysis is not ready")
    finally:
        store.close()
    return JSONResponse(status_code=200, content={"items": [_record_json(item) for item in page.items], "next_cursor": page.next_cursor})


async def post_analysis(case_run_id: str, request: Request) -> JSONResponse:
    if not request.headers.get("idempotency-key", "").strip():
        return _error(422, "validation", "Idempotency-Key is required")
    project = _uuid(request.query_params.get("project_id", ""))
    parsed = _uuid(case_run_id)
    if project is None or parsed is None:
        return _error(404, "not_found", "trial was not found")
    payload = await _body(request)
    if isinstance(payload, JSONResponse):
        return payload
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_browser(request, project, "append_analysis")
                with store.transaction() as connection:
                    record, replayed = append_analysis_record(
                        Transaction(connection), actor, project, parsed, payload, request.headers.get("idempotency-key", "").strip()
                    )
            except CsrfRejected:
                return _error(403, "permission", "csrf token was rejected")
            except OriginRejected:
                return _error(403, "permission", "origin was rejected")
            except ProjectHidden:
                return _error(404, "not_found", "trial was not found")
            except AuthRequired:
                return _error(401, "unauthorized", "session is missing")
            except AnalysisMissing:
                return _error(404, "not_found", "trial was not found")
            except AnalysisRejected:
                return _error(422, "validation", "analysis is not ready")
            except AnalysisConflict:
                return _error(409, "conflict", "idempotency body does not match")
    finally:
        store.close()
    response = JSONResponse(status_code=200 if replayed else 201, content=_record_json(record))
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return response


async def analysis_page(project_id: str, case_run_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    parsed = _uuid(case_run_id)
    if project is None or parsed is None:
        return HTMLResponse(status_code=404, content="항목을 찾지 못했습니다.")
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_page(request, project)
            except (AuthRequired, OriginRejected, ProjectHidden):
                return HTMLResponse(status_code=403, content="이 화면을 볼 권한이 없습니다.")
            with store.transaction() as connection:
                tx = Transaction(connection)
                try:
                    page = list_analysis_records(tx, actor, project, parsed)
                    verdict = read_original_verdict(tx, project, parsed)
                except AnalysisMissing:
                    return HTMLResponse(status_code=404, content="항목을 찾지 못했습니다.")
    finally:
        store.close()
    return render_template(
        request,
        "components/analysis.html",
        {
            "shell": False,
            "original_verdict": verdict,
            "records": [_view(item) for item in page.items],
        },
    )


def read_case_run_facts(connection: object, project_id: UUID, case_run_id: UUID, attempt_id: str) -> dict[str, object]:
    """Read the exact item facts. A missing capture stays missing."""

    run = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT case_runs.case_id, case_runs.case_version_id, automation_cases.name,
               case_versions.verification_digest, case_versions.replay_package_id, case_versions.settings_json,
               jobs.limits, jobs.job_id
        FROM case_runs
        JOIN automation_cases
          ON automation_cases.project_id = case_runs.project_id
         AND automation_cases.case_id = case_runs.case_id
        JOIN case_versions
          ON case_versions.project_id = case_runs.project_id
         AND case_versions.case_id = case_runs.case_id
         AND case_versions.version_id = case_runs.case_version_id
        LEFT JOIN jobs
          ON jobs.project_id = case_runs.project_id
         AND jobs.case_run_id = case_runs.case_run_id
        WHERE case_runs.project_id = ? AND case_runs.case_run_id = ?
        """,
        (str(project_id), str(case_run_id)),
    ).fetchone()
    if run is None:
        return {}
    attempts = _attempts(connection, project_id, str(run[7]) if run[7] is not None else "")
    selected = _selected(attempts, attempt_id)
    failure = next((item for item in attempts if item["failed"]), None)
    limits = _limits(str(run[6]) if run[6] is not None else "{}")
    action = _action(connection, project_id, "" if selected is None else str(selected["attempt_id"]))
    capture = _capture(connection, project_id, str(case_run_id), "" if selected is None else str(selected["attempt_id"]), action)
    evidence = _evidence(connection, project_id, str(case_run_id))
    return {
        "case_id": str(run[0]),
        "case_name": str(run[2]),
        "case_version_id": str(run[1]),
        "verification_digest": str(run[3]),
        "package_id": "" if run[4] is None else str(run[4]),
        "policy": str(run[5]),
        "data_name": limits.get("data_name", ""),
        "environment_revision_id": limits.get("environment_revision_id", ""),
        "build_id": limits.get("build_id", ""),
        "device": limits.get("device", ""),
        "engine": limits.get("engine", ""),
        "model_name": limits.get("model", ""),
        "step_id": "" if action is None else str(action[0]),
        "action_id": "" if action is None else str(action[1]),
        "check_status": "" if action is None else str(action[2]),
        "check_reason": "" if action is None else str(action[3]),
        "dispatch_state": "" if action is None else str(action[4]),
        "first_attempt_id": "" if not attempts else str(attempts[0]["attempt_id"]),
        "latest_attempt_id": "" if not attempts else str(attempts[-1]["attempt_id"]),
        "selected_attempt_id": "" if selected is None else str(selected["attempt_id"]),
        "first_failure_attempt_id": "" if failure is None else str(failure["attempt_id"]),
        "first_failure_reason": "" if failure is None else str(failure["reason"]),
        "verdict_reason": "" if action is None else str(action[3]),
        "capture_state": capture[0],
        "capture_substituted": False,
        "capture_reason": capture[1],
        "evidence_reason": evidence,
        "recovery": "원래 lookup은 그대로입니다" if action is not None and action[4] == "lookup_failed" else "",
        **_assistance(connection, project_id, case_run_id),
    }


def _assistance(connection: object, project_id: UUID, case_run_id: UUID) -> dict[str, str]:
    from aiqa.domain.reporting import describe_item
    from aiqa.store.models import Transaction

    return describe_item(Transaction(connection), project_id, str(case_run_id))


def read_case_run_attempts(connection: object, project_id: UUID, case_run_id: UUID) -> list[dict[str, object]] | None:
    """List attempts for one item. Another project's item stays hidden."""

    job = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT job_id FROM jobs
        WHERE project_id = ? AND case_run_id = ?
        """,
        (str(project_id), str(case_run_id)),
    ).fetchone()
    owned = connection.execute(  # type: ignore[attr-defined]
        "SELECT 1 FROM case_runs WHERE project_id = ? AND case_run_id = ?",
        (str(project_id), str(case_run_id)),
    ).fetchone()
    if owned is None:
        return None
    return _attempts(connection, project_id, "" if job is None else str(job[0]))


def _attempts(connection: object, project_id: UUID, job_id: str) -> list[dict[str, object]]:
    if job_id == "":
        return []
    rows = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT attempt_id, generation FROM attempts
        WHERE project_id = ? AND job_id = ?
        ORDER BY generation, attempt_id
        """,
        (str(project_id), job_id),
    ).fetchall()
    found: list[dict[str, object]] = []
    for row in rows:
        action = _action(connection, project_id, str(row[0]))
        failed = action is not None and action[2] == "violated"
        found.append(
            {
                "attempt_id": str(row[0]),
                "generation": int(row[1]),
                "action_id": "" if action is None else str(action[1]),
                "check_status": "" if action is None else str(action[2]),
                "failed": failed,
                "reason": "" if action is None else str(action[3]),
            }
        )
    return found


def _selected(attempts: list[dict[str, object]], attempt_id: str) -> dict[str, object] | None:
    if attempt_id != "":
        matched = next((item for item in attempts if item["attempt_id"] == attempt_id), None)
        if matched is not None:
            return matched
    return None if not attempts else attempts[-1]


def _action(connection: object, project_id: UUID, attempt_id: str) -> tuple[object, ...] | None:
    if attempt_id == "":
        return None
    return connection.execute(  # type: ignore[attr-defined]
        """
        SELECT actions.step_id, actions.action_id, COALESCE(check_results.status, ''),
               COALESCE(check_results.reason, ''), actions.dispatch_state
        FROM actions
        LEFT JOIN check_results
          ON check_results.project_id = actions.project_id
         AND check_results.attempt_id = actions.attempt_id
         AND check_results.action_id = actions.action_id
        WHERE actions.project_id = ? AND actions.attempt_id = ?
        ORDER BY actions.action_seq
        LIMIT 1
        """,
        (str(project_id), attempt_id),
    ).fetchone()


def _capture(connection: object, project_id: UUID, case_run_id: str, attempt_id: str, action: tuple[object, ...] | None) -> tuple[str, str]:
    if attempt_id == "" or action is None:
        return "missing", "대상 화면이 없습니다."
    rows = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT media_type FROM artifact_objects
        WHERE project_id = ? AND owner_kind = 'ITEM' AND owner_id = ? AND attempt_id = ? AND action_id = ? AND role = 'before'
        """,
        (str(project_id), case_run_id, attempt_id, str(action[1])),
    ).fetchall()
    captures = [row for row in rows if not str(row[0]).startswith("model/")]
    if not captures:
        return "missing", "대상 화면이 없습니다."
    return "stored", ""


def _evidence(connection: object, project_id: UUID, case_run_id: str) -> str:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT review_retention_events.reason
        FROM review_retention_events
        JOIN artifact_refs
          ON artifact_refs.project_id = review_retention_events.project_id
         AND artifact_refs.artifact_id = review_retention_events.artifact_id
        JOIN actions
          ON actions.project_id = artifact_refs.project_id
         AND actions.attempt_id = artifact_refs.attempt_id
         AND actions.action_id = artifact_refs.action_id
        JOIN attempts
          ON attempts.project_id = actions.project_id
         AND attempts.attempt_id = actions.attempt_id
        JOIN jobs
          ON jobs.project_id = attempts.project_id
         AND jobs.job_id = attempts.job_id
        WHERE review_retention_events.project_id = ? AND jobs.case_run_id = ?
        ORDER BY review_retention_events.created_at
        LIMIT 1
        """,
        (str(project_id), case_run_id),
    ).fetchone()
    return "" if row is None else str(row[0])


def _limits(raw: str) -> dict[str, str]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if type(parsed) is not dict:
        return {}
    return {str(key): value for key, value in parsed.items() if type(value) is str}


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (TypeError, ValueError):
        return None


async def _body(request: Request) -> dict[str, object] | JSONResponse:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return _error(422, "validation", "analysis is not ready")
    if type(payload) is not dict:
        return _error(422, "validation", "analysis is not ready")
    return payload


def _record_json(record: AnalysisRecord) -> dict[str, object]:
    return {
        "record_id": str(record.record_id),
        "case_run_id": str(record.case_run_id),
        "status": record.status,
        "classification": record.classification,
        "assignee": record.assignee,
        "comment": record.comment,
        "issue_url": record.issue_url,
        "record_kind": record.record_kind,
        "prior_record_id": record.prior_record_id,
        "commit_seq": record.commit_seq,
        "issue_created": record.issue_created,
    }


def _view(record: AnalysisRecord) -> dict[str, str]:
    statuses = {"unclassified": "미분류", "in_progress": "진행", "resolved": "해결"}
    classes = {"product": "제품", "automation": "자동화", "environment": "환경", "data": "데이터", "unclassified": "미분류"}
    return {
        "status_label": statuses.get(record.status, record.status),
        "classification_label": classes.get(record.classification, record.classification),
        "assignee": record.assignee,
        "comment": record.comment,
        "issue_url": record.issue_url,
    }


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "fields": {}, "retryable": False}},
    )
