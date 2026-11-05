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
_UI_ASSET_VERSION = "20261105-rx58"
_templates: Jinja2Templates | None = None


def approved_replay_requires_model_check() -> bool:
    """Shell/settings copy: deterministic approved replay does not need a model check."""

    from aiqa.domain.model_bindings import approved_deterministic_replay_requires_model_check

    return approved_deterministic_replay_requires_model_check()


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
        _templates.env.globals['ui_asset_version'] = _UI_ASSET_VERSION
        _templates.env.globals['approved_replay_requires_model_check'] = approved_replay_requires_model_check()
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


def hosted_login_path() -> str:
    """UI entry for hosted OIDC. Local bootstrap nonce stays on the local profile."""

    return "/ui/login"


def render_hosted_login(request: Request) -> HTMLResponse:
    """Hosted browser login: start OIDC and follow the registered redirect URI."""

    from html import escape

    settings = getattr(request.app.state, "settings", None)
    profile = getattr(settings, "profile", "local")
    if profile != "hosted":
        return HTMLResponse(status_code=403, content="hosted login only")
    project_id = escape(str(request.query_params.get("project_id") or ""))
    return HTMLResponse(
        content=(
            "<!DOCTYPE html><html lang='ko'><head><meta charset='utf-8'>"
            "<title>관리 서버 로그인</title></head><body>"
            "<h1>관리 서버 로그인</h1>"
            "<p>OIDC authorization code + PKCE로 로그인합니다. "
            "콜백은 등록 redirect URI에서 처리합니다.</p>"
            "<form id='oidc-login' data-oidc-start='/api/v1/auth/oidc/start' "
            "data-oidc-callback='/api/v1/auth/oidc/callback'>"
            "<label>프로젝트 ID "
            f"<input name='project_id' value='{project_id}' required "
            "autocomplete='off'></label> "
            "<button type='submit'>OIDC 로그인</button>"
            "</form>"
            "<p id='oidc-status' data-oidc-status></p>"
            "<script>"
            "(function(){"
            "var form=document.getElementById('oidc-login');"
            "var status=document.getElementById('oidc-status');"
            "form.addEventListener('submit',async function(ev){"
            "ev.preventDefault();"
            "status.textContent='로그인 시작 중';"
            "var projectId=String(form.project_id.value||'').trim();"
            "var res=await fetch(form.dataset.oidcStart,{"
            "method:'POST',"
            "headers:{'Content-Type':'application/json',"
            "'Idempotency-Key':'ui-login-'+Date.now(),"
            "'Origin':window.location.origin},"
            "body:JSON.stringify({project_id:projectId})"
            "});"
            "if(!res.ok){status.textContent='시작 실패 '+res.status;return;}"
            "var body=await res.json();"
            "if(!body.authorize_url){status.textContent='authorize_url 없음';return;}"
            "window.location.assign(body.authorize_url);"
            "});"
            "})();"
            "</script>"
            "</body></html>"
        )
    )


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
    """Render a product page with its authorized project navigation."""

    from aiqa.web.context import project_navigation
    context = dict(context)
    navigation = project_navigation(request, context)
    if navigation is not None:
        context["project_nav"] = navigation
        context["shell"] = True
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
