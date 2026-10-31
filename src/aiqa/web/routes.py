"""Bootstrap page and the shared management shell."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from starlette.templating import Jinja2Templates

_PACKAGE = "aiqa.web"
_templates: Jinja2Templates | None = None


def _resource_dir(name: str) -> Path:
    location = Path(str(files(_PACKAGE).joinpath(name)))
    if not location.is_dir():
        raise FileNotFoundError(f"aiqa.web package data is missing: {name}")
    return location


def static_directory() -> Path:
    return _resource_dir("static")


def _jinja() -> Jinja2Templates:
    global _templates
    if _templates is None:
        _templates = Jinja2Templates(directory=str(_resource_dir("templates")))
    return _templates


def render_bootstrap(request: Request) -> Response:
    from aiqa.api.app import health

    try:
        payload = health()
    except Exception:
        payload = None
    connected = (
        isinstance(payload, dict)
        and payload.get("status") == "ok"
        and payload.get("component") == "api"
    )
    context = {
        "connection_error": not connected,
        "health_status": payload["status"] if connected else "",
        "health_component": payload["component"] if connected else "",
    }
    return _jinja().TemplateResponse(request, "bootstrap.html", context)


def ensure_css_media_type() -> None:
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("text/javascript", ".js")


@dataclass(frozen=True, slots=True)
class UiQueryState:
    """URL query for the shell. Scroll stays out of the address."""

    filter: str
    sort: str
    cursor: str
    selected_id: str
    scroll: str


@dataclass(frozen=True, slots=True)
class PageContext:
    """One shell page. The request is only used to render the template."""

    request: Request
    title: str
    heading: str
    section: str
    connected: bool
    state: str
    dirty: bool
    query: UiQueryState
    crumbs: tuple[tuple[str, str], ...]
    items: tuple[tuple[str, str], ...]


def render_template(request: Request, name: str, context: dict[str, object]) -> HTMLResponse:
    """Render one template. This does not open a database."""

    return _jinja().TemplateResponse(request, name, context)


def render_page(context: PageContext) -> HTMLResponse:
    """Render the management shell. This does not open a database."""

    query = _query_string(context.query)
    listed = "/ui/shell"
    if query:
        listed = f"{listed}?{query}"
    detail = f"/ui/shell/items/{context.query.selected_id or 'item-1'}"
    if query:
        detail = f"{detail}?{query}"
    payload = {
        "shell": True,
        "title": context.title,
        "heading": context.heading,
        "section": context.section,
        "connected": context.connected,
        "state": context.state,
        "dirty": context.dirty,
        "query": context.query,
        "crumbs": context.crumbs,
        "items": tuple((item_id, label, f"/ui/shell/items/{item_id}?{query}" if query else f"/ui/shell/items/{item_id}") for item_id, label in context.items),
        "list_href": listed,
        "detail_href": detail,
    }
    return _jinja().TemplateResponse(context.request, "manage.html", payload)


def install_shell(application: FastAPI) -> None:
    """Attach the shell pages once. This does not open SQLite."""

    if getattr(application.state, "shell_installed", False):
        return
    application.add_api_route("/ui/shell", shell_list, methods=["GET"], response_class=HTMLResponse)
    application.add_api_route(
        "/ui/shell/items/{item_id}",
        shell_detail,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    application.state.shell_installed = True


def shell_list(request: Request) -> HTMLResponse:
    query = _query_from_request(request)
    state = _notice(request)
    return render_page(
        PageContext(
            request=request,
            title="목록",
            heading="목록",
            section="list",
            connected=state != "stale",
            state=state,
            dirty=request.query_params.get("dirty") == "1",
            query=query,
            crumbs=(("목록", _list_href(query)),),
            items=(("item-1", "항목 1"),),
        )
    )


def shell_detail(request: Request, item_id: str) -> HTMLResponse:
    query = _query_from_request(request)
    if item_id:
        query = UiQueryState(query.filter, query.sort, query.cursor, item_id, "")
    state = _notice(request)
    return render_page(
        PageContext(
            request=request,
            title="상세",
            heading="상세",
            section="detail",
            connected=state != "stale",
            state=state,
            dirty=False,
            query=query,
            crumbs=(("목록", _list_href(query)), ("상세", "")),
            items=(),
        )
    )


def _query_from_request(request: Request) -> UiQueryState:
    return UiQueryState(
        filter=request.query_params.get("filter", ""),
        sort=request.query_params.get("sort", "name"),
        cursor=request.query_params.get("page", ""),
        selected_id=request.query_params.get("selected", ""),
        scroll="",
    )


def _notice(request: Request) -> str:
    notice = request.query_params.get("notice", "ready")
    if notice not in {"ready", "loading", "empty", "invalid", "forbidden", "conflict", "stale"}:
        return "ready"
    return notice


def _query_string(query: UiQueryState) -> str:
    return urlencode(
        (
            ("filter", query.filter),
            ("sort", query.sort),
            ("page", query.cursor),
            ("selected", query.selected_id),
        )
    )


def _list_href(query: UiQueryState) -> str:
    text = _query_string(query)
    if text == "":
        return "/ui/shell"
    return f"/ui/shell?{text}"
