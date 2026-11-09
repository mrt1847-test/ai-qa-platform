"""Report list and one execution report. These routes do not open a device or a model."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections.abc import Mapping
from urllib.parse import urlencode
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
from aiqa.contracts.jobs import IdempotencyKey
from aiqa.contracts.reports import AnalyticsQuery
from aiqa.domain.analytics import AnalyticsRejected, query_observations, read_analytics
from aiqa.domain.comparisons import ComparisonMissing, ComparisonRejected, compare_executions
from aiqa.domain.exports import (
    ExportConflict,
    ExportInput,
    ExportMissing,
    ExportRejected,
    ExportView,
    read_export,
    read_export_by_id,
    request_export,
)
from aiqa.domain.reporting import ExecutionReport, ReportMissing, ReportRejected, list_reports, read_report
from aiqa.store.database import migrate_store
from aiqa.store.models import Transaction
from aiqa.web.routes import render_template


def install_reports(application: FastAPI) -> None:
    """Attach report routes once. This does not open SQLite."""

    if getattr(application.state, "reports_installed", False):
        return
    application.add_api_route("/api/v1/projects/{project_id}/reports", get_reports, methods=["GET"])
    application.add_api_route("/api/v1/projects/{project_id}/observations", get_observations, methods=["GET"])
    application.add_api_route("/api/v1/projects/{project_id}/analytics", get_analytics, methods=["GET"])
    application.add_api_route(
        "/api/v1/projects/{project_id}/execution-comparisons",
        get_comparison,
        methods=["GET"],
    )
    application.add_api_route("/api/v1/executions/{execution_id}/report", get_report, methods=["GET"])
    application.add_api_route("/api/v1/executions/{execution_id}/exports", post_export, methods=["POST"])
    application.add_api_route(
        "/api/v1/executions/{execution_id}/exports/{job_id}",
        get_export,
        methods=["GET"],
    )
    application.add_api_route("/api/v1/exports/{export_id}", get_export_by_id, methods=["GET"])
    application.add_api_route(
        "/ui/projects/{project_id}/reports",
        reports_page,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    application.add_api_route(
        "/ui/projects/{project_id}/analytics",
        analytics_page,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    application.add_api_route(
        "/ui/projects/{project_id}/execution-comparisons",
        comparison_page,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    application.add_api_route(
        "/ui/projects/{project_id}/executions/{execution_id}/report",
        report_page,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    application.add_api_route(
        "/ui/projects/{project_id}/executions/{execution_id}/report/print",
        report_print_page,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    application.state.reports_installed = True


async def get_observations(project_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    if project is None:
        return _error(404, "not_found", "trial was not found")
    try:
        _analytics_as_of(request.query_params.get("as_of", ""))
    except AnalyticsRejected:
        return _error(422, "validation", "observation filter is invalid")
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_browser(request, project, "read_observations")
                query = _analytics_query(project, request)
                with store.transaction() as connection:
                    page = query_observations(Transaction(connection), actor, query)
            except CsrfRejected:
                return _error(403, "permission", "csrf token was rejected")
            except OriginRejected:
                return _error(403, "permission", "origin was rejected")
            except ProjectHidden:
                return _error(404, "not_found", "trial was not found")
            except AuthRequired:
                return _error(401, "unauthorized", "session is missing")
            except AnalyticsRejected:
                return _error(422, "validation", "observation filter is invalid")
    finally:
        store.close()
    return JSONResponse(
        status_code=200,
        content={
            "items": [
                {
                    "case_run_id": str(item.case_run_id),
                    "execution_id": str(item.execution_id),
                    "source": item.source,
                    "purpose": item.purpose,
                    "in_denominator": item.in_denominator,
                    "terminal": item.terminal,
                    "result": item.result,
                    "attempt_count": item.attempt_count,
                }
                for item in page.items
            ]
        },
    )


async def get_analytics(project_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    if project is None:
        return _error(404, "not_found", "trial was not found")
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_browser(request, project, "read_analytics")
                query = _analytics_query(project, request)
                with store.transaction() as connection:
                    report = read_analytics(Transaction(connection), actor, query)
            except CsrfRejected:
                return _error(403, "permission", "csrf token was rejected")
            except OriginRejected:
                return _error(403, "permission", "origin was rejected")
            except ProjectHidden:
                return _error(404, "not_found", "trial was not found")
            except AuthRequired:
                return _error(401, "unauthorized", "session is missing")
            except AnalyticsRejected:
                return _error(422, "validation", "analytics filter is invalid")
    finally:
        store.close()
    return JSONResponse(status_code=200, content=_analytics_json(report))


async def analytics_page(project_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    if project is None:
        return HTMLResponse(status_code=404, content="프로젝트를 찾지 못했습니다.")
    store = request.app.state.open_store()
    report = None
    error = ""
    observations = []
    pagination = {"total": 0, "start": 0, "end": 0, "previous": "", "next": ""}
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_page(request, project)
            except (AuthRequired, OriginRejected, ProjectHidden):
                return HTMLResponse(status_code=403, content="이 화면을 볼 권한이 없습니다.")
            with store.transaction() as connection:
                clock = connection.execute(
                    "SELECT commit_seq FROM project_commit_clock WHERE project_id=?", (str(project),)
                ).fetchone()
                today = datetime.now(timezone(timedelta(hours=9))).date()
                filters = {name: "" for name in (
                    "purpose", "include_trial", "case", "version", "verification",
                    "data", "env", "build", "model", "release_label",
                )}
                filters.update({
                    "from": (today - timedelta(days=29)).isoformat(),
                    "to": (today + timedelta(days=1)).isoformat(),
                    "as_of": str(clock[0] if clock else 0), "criteria": "all_observations",
                    "page": "1", "limit": "50",
                })
                filters.update(dict(request.query_params))
                try:
                    query = _analytics_query(project, request, filters)
                    page_number = _analytics_as_of(filters["page"])
                    page_size = _analytics_as_of(filters["limit"])
                    if page_number < 1 or page_size not in {25, 50, 100}:
                        raise AnalyticsRejected("observation page is invalid")
                    all_items = query_observations(Transaction(connection), actor, query).items
                    total = len(all_items)
                    if page_number > max(1, (total + page_size - 1) // page_size):
                        raise AnalyticsRejected("observation page is invalid")
                    offset = (page_number - 1) * page_size
                    window = all_items[offset:offset + page_size]
                    names = {}
                    if window:
                        marks = ",".join("?" for _ in window)
                        names = dict(connection.execute(
                            f"""SELECT r.case_run_id,c.name FROM case_runs r
                                JOIN automation_cases c USING(project_id,case_id)
                                WHERE r.project_id=? AND r.case_run_id IN ({marks})""",
                            (str(project), *(str(item.case_run_id) for item in window)),
                        ).fetchall())
                    observations = [{
                        "case_run_id": str(item.case_run_id), "execution_id": str(item.execution_id),
                        "name": names.get(str(item.case_run_id), str(item.case_run_id)[:8]),
                        "purpose": item.purpose, "result": item.result,
                        "in_denominator": item.in_denominator, "terminal": item.terminal,
                        "attempt_count": item.attempt_count,
                    } for item in window]
                    def page_href(number: int) -> str:
                        return f"/ui/projects/{project}/analytics?" + urlencode({**filters, "page": str(number)})
                    pagination = {
                        "total": total, "start": offset + 1 if total else 0,
                        "end": min(offset + page_size, total),
                        "previous": page_href(page_number - 1) if page_number > 1 else "",
                        "next": page_href(page_number + 1) if offset + page_size < total else "",
                    }
                    report = read_analytics(Transaction(connection), actor, query)
                except AnalyticsRejected:
                    error = "분석 조건이 올바르지 않습니다. 날짜·기준 기록 번호·페이지와 표시 개수(25/50/100)를 확인하세요. 조건으로 다시 조회하면 첫 페이지를 엽니다."
    finally:
        store.close()
    refresh = urlencode({key: value for key, value in filters.items() if key not in {"as_of", "page"}})
    response = render_template(request, "analytics.html", {
        "shell": False, "project_id": str(project), "report": report, "filters": filters,
        "observations": observations, "pagination": pagination,
        "error": error, "refresh_href": f"/ui/projects/{project}/analytics?{refresh}",
        "crumbs": (("리포트", f"/ui/projects/{project}/reports"), ("누적 분석", "")),
    })
    response.status_code = 422 if error else 200
    return response


def _analytics_as_of(raw: str) -> int:
    if not raw.isascii() or not raw.isdigit() or len(raw) > 19:
        raise AnalyticsRejected("analytics query is invalid")
    value = int(raw)
    if value > 2**63 - 1:
        raise AnalyticsRejected("analytics query is invalid")
    return value


def _analytics_query(
    project: UUID, request: Request, filters: Mapping[str, str] | None = None
) -> AnalyticsQuery:
    params = request.query_params if filters is None else filters
    as_of = _analytics_as_of(params.get("as_of", ""))
    return AnalyticsQuery(
        project,
        params.get("from", ""),
        params.get("to", ""),
        as_of,
        params.get("purpose", ""),
        params.get("include_trial", "") == "1",
        params.get("criteria", "all_observations"),
        params.get("case", ""),
        params.get("version", ""),
        params.get("verification", ""),
        params.get("data", ""),
        params.get("env", ""),
        params.get("build", ""),
        params.get("model", ""),
        params.get("release_label", ""),
    )


def _analytics_json(report: object) -> dict[str, object]:
    from aiqa.contracts.reports import AnalyticsReport

    assert isinstance(report, AnalyticsReport)
    return {
        "sample_count": report.sample_count,
        "denominator": report.denominator,
        "unverified": report.unverified,
        "as_of": report.as_of,
        "criteria": report.criteria,
        "rates": None if report.rates is None else list(report.rates),
        "p50": report.p50,
        "p95": report.p95,
        "not_run_duration": report.not_run_duration,
        "cost": report.cost,
        "storage_count": report.storage_count,
        "trend_dates": list(report.trend_dates),
        "repeated_checks": report.repeated_checks,
        "analysis_count": report.analysis_count,
        "first_satisfied": report.first_satisfied,
        "recovery_count": report.recovery_count,
        "condition_count": report.condition_count,
        "period_from": report.period_from,
        "period_to": report.period_to,
        "purpose": report.purpose,
        "case_id": report.case_id,
    }


async def get_comparison(project_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    baseline = _uuid(request.query_params.get("baseline", ""))
    candidate = _uuid(request.query_params.get("candidate", ""))
    if project is None or baseline is None or candidate is None:
        return _error(404, "not_found", "trial was not found")
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_browser(request, project, "read_comparison")
                with store.transaction() as connection:
                    compared = compare_executions(
                        Transaction(connection), actor, project, baseline, candidate, _comparison_as_of(request)
                    )
            except CsrfRejected:
                return _error(403, "permission", "csrf token was rejected")
            except OriginRejected:
                return _error(403, "permission", "origin was rejected")
            except ProjectHidden:
                return _error(404, "not_found", "trial was not found")
            except AuthRequired:
                return _error(401, "unauthorized", "session is missing")
            except ComparisonMissing:
                return _error(404, "not_found", "trial was not found")
            except ComparisonRejected:
                return _error(422, "validation", "comparison is invalid")
    finally:
        store.close()
    return JSONResponse(status_code=200, content=_comparison_json(compared))


async def comparison_page(project_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    baseline = _uuid(request.query_params.get("baseline", ""))
    candidate = _uuid(request.query_params.get("candidate", ""))
    if project is None or baseline is None or candidate is None:
        return HTMLResponse(status_code=404, content="수행을 찾지 못했습니다.")
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_page(request, project)
            except (AuthRequired, OriginRejected, ProjectHidden):
                return HTMLResponse(status_code=403, content="이 화면을 볼 권한이 없습니다.")
            with store.transaction() as connection:
                try:
                    compared = compare_executions(
                        Transaction(connection), actor, project, baseline, candidate, _comparison_as_of(request)
                    )
                except ComparisonMissing:
                    return HTMLResponse(status_code=404, content="수행을 찾지 못했습니다.")
                except ComparisonRejected:
                    return HTMLResponse(status_code=422, content="비교 조건이 올바르지 않습니다.")
    finally:
        store.close()
    return render_template(
        request,
        "comparison.html",
        {"shell": False, "project_id": str(project), "comparison": compared},
    )


def _comparison_as_of(request: Request) -> int:
    raw = request.query_params.get("as_of", "0")
    if not raw.isdigit():
        raise ComparisonRejected("comparison is invalid")
    return int(raw)


def _comparison_json(compared: object) -> dict[str, object]:
    from aiqa.domain.comparisons import ExecutionComparison

    assert isinstance(compared, ExecutionComparison)
    return {
        "baseline_id": compared.baseline_id,
        "candidate_id": compared.candidate_id,
        "mixed": compared.mixed,
        "constituent_count": compared.constituent_count,
        "confirmed_improvements": compared.confirmed_improvements,
        "confirmed_regressions": compared.confirmed_regressions,
        "original_fail_preserved": compared.original_fail_preserved,
        "pairs": [
            {
                "case_id": pair.case_id,
                "data": pair.data,
                "target": pair.target,
                "kind": pair.kind,
                "separate_series": pair.separate_series,
                "condition_fields": list(pair.condition_fields),
                "baseline": None if pair.baseline is None else _comparison_side(pair.baseline),
                "candidate": None if pair.candidate is None else _comparison_side(pair.candidate),
            }
            for pair in compared.pairs
        ],
    }


def _comparison_side(side: object) -> dict[str, str]:
    from aiqa.domain.comparisons import ComparisonSide

    assert isinstance(side, ComparisonSide)
    return {
        "case_run_id": side.case_run_id,
        "result_label": side.result_label,
        "environment": side.environment,
        "build": side.build,
        "data": side.data,
        "expected": side.expected,
        "verification": side.verification,
        "healing": side.healing,
        "step": side.step,
        "observed": side.observed,
        "duration": side.duration,
        "cost": side.cost,
        "capture": side.capture,
    }


async def post_export(execution_id: str, request: Request) -> JSONResponse:
    project = _uuid(request.query_params.get("project_id", ""))
    execution = _uuid(execution_id)
    if project is None or execution is None:
        return _error(404, "not_found", "trial was not found")
    payload = await _json_object(request)
    if payload is None:
        return _error(422, "validation", "export is invalid")
    incoming = _export_input(execution, payload)
    if incoming is None:
        return _error(422, "validation", "export is invalid")
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_browser(request, project, "export_execution")
                key = IdempotencyKey(
                    actor.actor_id, project, "export_execution", request.headers.get("idempotency-key", "").strip()
                )
                with store.transaction() as connection:
                    view = request_export(
                        Transaction(connection),
                        actor,
                        project,
                        incoming,
                        key,
                        store.config.artifacts_dir,
                        datetime.now(timezone.utc),
                    )
            except CsrfRejected:
                return _error(403, "permission", "csrf token was rejected")
            except OriginRejected:
                return _error(403, "permission", "origin was rejected")
            except ProjectHidden:
                return _error(404, "not_found", "trial was not found")
            except AuthRequired:
                return _error(401, "unauthorized", "session is missing")
            except ExportMissing:
                return _error(404, "not_found", "trial was not found")
            except ExportConflict:
                return _error(409, "conflict", "export body does not match")
            except ExportRejected:
                return _error(422, "validation", "export is invalid")
    finally:
        store.close()
    return JSONResponse(status_code=200 if view.replayed else 201, content=_export_json(view))


async def get_export(execution_id: str, job_id: str, request: Request) -> JSONResponse:
    project = _uuid(request.query_params.get("project_id", ""))
    execution = _uuid(execution_id)
    parsed_job = _uuid(job_id)
    if project is None or execution is None or parsed_job is None:
        return _error(404, "not_found", "trial was not found")
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_browser(request, project, "read_export")
                with store.transaction() as connection:
                    view = read_export(
                        Transaction(connection),
                        actor,
                        project,
                        execution,
                        parsed_job,
                        store.config.artifacts_dir,
                        datetime.now(timezone.utc),
                    )
            except CsrfRejected:
                return _error(403, "permission", "csrf token was rejected")
            except OriginRejected:
                return _error(403, "permission", "origin was rejected")
            except ProjectHidden:
                return _error(404, "not_found", "trial was not found")
            except AuthRequired:
                return _error(401, "unauthorized", "session is missing")
            except ExportMissing:
                return _error(404, "not_found", "trial was not found")
            except ExportRejected:
                return _error(422, "validation", "export is invalid")
    finally:
        store.close()
    return JSONResponse(status_code=200, content=_export_json(view))


async def get_export_by_id(export_id: str, request: Request) -> JSONResponse:
    project = _uuid(request.query_params.get("project_id", ""))
    parsed = _uuid(export_id)
    if project is None or parsed is None:
        return _error(404, "not_found", "trial was not found")
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_browser(request, project, "read_export")
                with store.transaction() as connection:
                    view = read_export_by_id(
                        Transaction(connection),
                        actor,
                        project,
                        parsed,
                        store.config.artifacts_dir,
                        datetime.now(timezone.utc),
                    )
                    status_row = connection.execute(
                        "SELECT status FROM jobs WHERE project_id = ? AND job_id = ?",
                        (str(project), str(parsed)),
                    ).fetchone()
            except CsrfRejected:
                return _error(403, "permission", "csrf token was rejected")
            except OriginRejected:
                return _error(403, "permission", "origin was rejected")
            except ProjectHidden:
                return _error(404, "not_found", "trial was not found")
            except AuthRequired:
                return _error(401, "unauthorized", "session is missing")
            except ExportMissing:
                return _error(404, "not_found", "trial was not found")
            except ExportRejected:
                return _error(422, "validation", "export is invalid")
    finally:
        store.close()
    body = _export_json(view)
    status = "" if status_row is None else str(status_row[0])
    body["phase"] = _export_phase(status, view.expired_reason is not None)
    return JSONResponse(status_code=200, content=body)


def _export_phase(status: str, expired: bool) -> str:
    if expired:
        return "만료"
    if status == "completed":
        return "완료"
    if status in {"error", "lost", "cancelled"}:
        return "실패"
    return "진행"


async def report_print_page(project_id: str, execution_id: str, request: Request) -> HTMLResponse:
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
            except (AuthRequired, OriginRejected, ProjectHidden):
                return HTMLResponse(status_code=403, content="이 화면을 볼 권한이 없습니다.")
            row = None
            with store.transaction() as connection:
                row = connection.execute(
                    "SELECT 1 FROM executions WHERE project_id = ? AND execution_id = ?",
                    (str(project), str(parsed)),
                ).fetchone()
    finally:
        store.close()
    if row is None:
        return HTMLResponse(status_code=404, content="수행을 찾지 못했습니다.")
    return render_template(
        request,
        "report_print.html",
        {
            "shell": False,
            "project_id": str(project),
            "execution_id": str(parsed),
            "criteria": request.query_params.get("criteria", "criteria-1"),
            "as_of": request.query_params.get("as_of", "15"),
            "interim_label": "중간 보고",
            "expires_label": request.query_params.get("expires", "고정"),
            "body": request.query_params.get("body", ""),
        },
    )


def _export_input(execution_id: UUID, payload: dict[str, object]) -> ExportInput | None:
    export_format = payload.get("format")
    criteria = payload.get("criteria_version")
    cohort = payload.get("cohort")
    expires_at = payload.get("expires_at")
    as_of = payload.get("as_of")
    filters = payload.get("filters", {})
    if type(export_format) is not str or type(criteria) is not str or type(cohort) is not str or type(expires_at) is not str:
        return None
    if type(as_of) is not int or type(filters) is not dict:
        return None
    pairs: list[tuple[str, str]] = []
    for key, value in filters.items():
        if type(key) is not str or type(value) is not str:
            return None
        pairs.append((key, value))
    return ExportInput(execution_id, export_format, as_of, criteria, tuple(sorted(pairs)), cohort, expires_at)


def _export_json(view: ExportView) -> dict[str, object]:
    return {
        "job_id": str(view.job_id),
        "replayed": view.replayed,
        "verdict": view.verdict,
        "as_of": view.as_of,
        "criteria_version": view.criteria_version,
        "interim": view.interim,
        "expires_at": view.expires_at,
        "expired_reason": view.expired_reason,
        "artifact_ready": view.artifact_ready,
        "source_ids": list(view.source_ids),
        "created_at": view.created_at,
        "cost": view.cost,
        "format": view.export_format,
    }


async def _json_object(request: Request) -> dict[str, object] | None:
    try:
        payload = await request.json()
    except Exception:
        return None
    if type(payload) is not dict:
        return None
    return payload


async def get_reports(project_id: str, request: Request) -> JSONResponse:
    project = _uuid(project_id)
    if project is None:
        return _error(404, "not_found", "trial was not found")
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_browser(request, project, "read_reports")
                with store.transaction() as connection:
                    page = list_reports(Transaction(connection), actor, project, dict(request.query_params))
            except CsrfRejected:
                return _error(403, "permission", "csrf token was rejected")
            except OriginRejected:
                return _error(403, "permission", "origin was rejected")
            except ProjectHidden:
                return _error(404, "not_found", "trial was not found")
            except AuthRequired:
                return _error(401, "unauthorized", "session is missing")
            except ReportRejected:
                return _error(422, "validation", "report filter is invalid")
    finally:
        store.close()
    return JSONResponse(
        status_code=200,
        content={
            "items": [
                {
                    "execution_id": str(item.execution_id),
                    "name": item.name,
                    "source": item.source,
                    "purpose": item.purpose,
                    "interim": item.interim,
                    "n": item.n,
                }
                for item in page.items
            ],
            "next_cursor": page.next_cursor,
        },
    )


async def get_report(execution_id: str, request: Request) -> JSONResponse:
    project = _uuid(request.query_params.get("project_id", ""))
    parsed = _uuid(execution_id)
    if project is None or parsed is None:
        return _error(404, "not_found", "trial was not found")
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_browser(request, project, "read_report")
                with store.transaction() as connection:
                    report = read_report(Transaction(connection), actor, project, parsed, _as_of(request))
            except CsrfRejected:
                return _error(403, "permission", "csrf token was rejected")
            except OriginRejected:
                return _error(403, "permission", "origin was rejected")
            except ProjectHidden:
                return _error(404, "not_found", "trial was not found")
            except AuthRequired:
                return _error(401, "unauthorized", "session is missing")
            except ReportMissing:
                return _error(404, "not_found", "trial was not found")
            except ReportRejected:
                return _error(422, "validation", "report filter is invalid")
    finally:
        store.close()
    return JSONResponse(status_code=200, content=_report_json(report))


async def reports_page(project_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    if project is None:
        return HTMLResponse(status_code=404, content="수행을 찾지 못했습니다.")
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_page(request, project)
            except (AuthRequired, OriginRejected, ProjectHidden):
                return HTMLResponse(status_code=403, content="이 화면을 볼 권한이 없습니다.")
            with store.transaction() as connection:
                page = list_reports(Transaction(connection), actor, project, dict(request.query_params))
    finally:
        store.close()
    return render_template(
        request,
        "reports.html",
        {
            "shell": False,
            "project_id": str(project),
            "purpose": request.query_params.get("purpose", ""),
            "include_trial": request.query_params.get("include_trial", ""),
            "trial_included": request.query_params.get("include_trial", "") == "1",
            "period_label": "요청 기간",
            "items": page.items,
            "crumbs": (("리포트", ""),),
        },
    )


async def report_page(project_id: str, execution_id: str, request: Request) -> HTMLResponse:
    project = _uuid(project_id)
    parsed = _uuid(execution_id)
    if project is None or parsed is None:
        return HTMLResponse(status_code=404, content="수행을 찾지 못했습니다.")
    store = request.app.state.open_store()
    try:
        migrate_store(store)
        with bound_auth_store(store):
            try:
                actor = authorize_page(request, project)
            except (AuthRequired, OriginRejected, ProjectHidden):
                return HTMLResponse(status_code=403, content="이 화면을 볼 권한이 없습니다.")
            with store.transaction() as connection:
                try:
                    report = read_report(Transaction(connection), actor, project, parsed, _as_of(request))
                except ReportMissing:
                    return HTMLResponse(status_code=404, content="수행을 찾지 못했습니다.")
                from aiqa.api.executions import lineage_fields

                lineage = lineage_fields(connection, project, parsed)
    finally:
        store.close()
    return render_template(
        request,
        "report.html",
        {
            "shell": False,
            "project_id": str(project),
            "execution_id": str(parsed),
            "purpose_filter": request.query_params.get("purpose", ""),
            "include_trial": request.query_params.get("include_trial", ""),
            "name": report.name,
            "source": report.source,
            "purpose": report.purpose,
            "settings_text": report.settings_text,
            "period_label": report.period_label,
            "interim": report.interim,
            "n": report.n,
            "rates": report.rates,
            "unverified": report.unverified,
            "counts": report.counts,
            "analysis_count": report.analysis_count,
            "issue_url": report.issue_url,
            "first_attempt_id": report.first_attempt_id,
            "latest_attempt_id": report.latest_attempt_id,
            "evidence_status": report.evidence_status,
            "exclusion_outside": report.exclusion_outside,
            "pass_bucket": report.pass_bucket,
            "healed_pass": report.healed_pass,
            "unassisted_pass": report.unassisted_pass,
            "action_retry": report.action_retry,
            "verifier_used": report.verifier_used,
            "terminal_bucket_count": report.terminal_bucket_count,
            "missing_usage_display": report.missing_usage_display,
            **lineage,
            "usage_cost": report.usage_cost,
            "episode_result": report.episode_result,
        },
    )


def _report_json(report: ExecutionReport) -> dict[str, object]:
    return {
        "execution_id": str(report.execution_id),
        "name": report.name,
        "source": report.source,
        "purpose": report.purpose,
        "settings_text": report.settings_text,
        "interim": report.interim,
        "n": report.n,
        "rates": None if report.rates is None else list(report.rates),
        "unverified": report.unverified,
        "counts": report.counts,
        "analysis_count": report.analysis_count,
        "issue_url": report.issue_url,
        "first_attempt_id": report.first_attempt_id,
        "latest_attempt_id": report.latest_attempt_id,
        "evidence_status": report.evidence_status,
        "period_label": report.period_label,
        "exclusion_outside": report.exclusion_outside,
        "pass_bucket": report.pass_bucket,
        "healed_pass": report.healed_pass,
        "unassisted_pass": report.unassisted_pass,
        "action_retry": report.action_retry,
        "verifier_used": report.verifier_used,
        "terminal_bucket_count": report.terminal_bucket_count,
        "missing_usage_display": report.missing_usage_display,
        "usage_cost": report.usage_cost,
        "episode_result": report.episode_result,
    }


def _as_of(request: Request) -> int | None:
    raw = request.query_params.get("as_of", "")
    if raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (TypeError, ValueError):
        return None


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "fields": {}, "retryable": False}},
    )
