"""Authorized display context shared by product pages."""

from uuid import UUID

from aiqa.api.auth import AuthRequired, OriginRejected, ProjectHidden, authorize_page, bound_auth_store


def project_navigation(request, context):
    raw = context.get("project_id") or request.path_params.get("project_id")
    if not raw:
        return None
    project = UUID(str(raw))
    store = request.app.state.open_store()
    try:
        with bound_auth_store(store):
            authorize_page(request, project)
        row = store._connection.execute(
            "SELECT name FROM projects WHERE project_id=?", (str(project),)
        ).fetchone()
        if row is None:
            return None
        path = request.url.path
        base = f"/ui/projects/{project}"
        section = _section_for_path(path)
        total = store._connection.execute(
            "SELECT count(*) FROM automation_cases WHERE project_id=? AND archived_at IS NULL",
            (str(project),),
        ).fetchone()[0]
        return {
            "id": str(project),
            "name": str(row[0]),
            "section": section,
            "base": base,
            "case_total": int(total),
            "search": request.query_params.get("q", ""),
            "links": [
                {"key": "overview", "label": "개요", "href": f"{base}/overview"},
                {"key": "cases", "label": "자동화 케이스", "href": f"{base}/cases"},
                {"key": "suites", "label": "테스트 묶음", "href": f"{base}/suites"},
                {"key": "runs", "label": "테스트 수행", "href": f"{base}/executions"},
                {"key": "reports", "label": "리포트", "href": f"{base}/reports"},
                {"key": "environment", "label": "실행 환경", "href": f"{base}/environments"},
                {"key": "settings", "label": "프로젝트 설정", "href": f"{base}/settings"},
            ],
        }
    except (AuthRequired, OriginRejected, ProjectHidden):
        return None
    finally:
        store.close()


def _section_for_path(path: str) -> str:
    if any(part in path for part in ("/environments", "/datasets", "/app-builds", "/environment")):
        return "environment"
    if "/settings" in path and "/cases/" not in path:
        return "settings"
    if "/suites" in path:
        return "suites"
    if path.endswith("/report") or "/report/" in path or "/reports" in path:
        return "reports"
    if "/executions" in path:
        return "runs"
    if any(part in path for part in ("/cases", "/recordings", "/tcs")):
        return "cases"
    return "overview"
