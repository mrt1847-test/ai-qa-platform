"""API process start. Factory creation stays free of SQLite; start reconciles jobs."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from aiqa.config import AppSettings
from aiqa.launcher import read_local_status, read_stop_notice

_boot_id: str | None = None
_SYSTEM_TIMEOFDAY_INFORMATION = 3


class _TimeOfDay(ctypes.Structure):
    _fields_ = (
        ("boot_time", ctypes.c_longlong),
        ("current_time", ctypes.c_longlong),
        ("timezone_bias", ctypes.c_longlong),
        ("timezone_id", wintypes.ULONG),
        ("reserved", wintypes.ULONG),
        ("boot_time_bias", ctypes.c_ulonglong),
        ("sleep_time_bias", ctypes.c_ulonglong),
    )


def host_boot_id() -> str:
    """Stable id of this PC boot. An API process restart does not change it."""

    global _boot_id
    if _boot_id is not None:
        return _boot_id
    info = _TimeOfDay()
    status = ctypes.WinDLL("ntdll").NtQuerySystemInformation(
        _SYSTEM_TIMEOFDAY_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
        None,
    )
    if status != 0:
        raise OSError("host boot id is unavailable")
    _boot_id = str(int(info.boot_time))
    return _boot_id


def start_api(settings: AppSettings, now: datetime) -> FastAPI:
    """Open one API process and reconcile queued jobs against the current boot."""

    from aiqa.api.app import create_app
    from aiqa.store.database import migrate_store
    from aiqa.worker.service import bind_claim_store, reconcile_jobs

    application = create_app(settings)
    store = application.state.open_store()
    try:
        migrate_store(store)
        with bind_claim_store(store):
            reconcile_jobs(now)
    finally:
        store.close()
    return application


def install_local(application: FastAPI) -> None:
    """Attach the local status page. This does not start a process or open SQLite."""

    application.add_api_route("/api/v1/local-status", local_status, methods=["GET"])
    application.add_api_route("/ui/local", local_page, methods=["GET"], response_class=HTMLResponse)
    from aiqa.api.events import install_events

    install_events(application)


def local_status(request: Request) -> JSONResponse:
    if request.url.hostname not in {"127.0.0.1", "localhost"}:
        return JSONResponse(status_code=403, content={"error": {"code": "permission", "message": "origin was rejected"}})
    status = read_local_status(str(request.app.state.settings.runtime_root))
    return JSONResponse(
        status_code=200,
        content={
            "api_instances": status.api_instances,
            "worker_instances": status.worker_instances,
            "state": status.state,
            "explanation": status.explanation,
            "command": status.command,
            "publish": status.publish,
            "tab_close_cancels": status.tab_close_cancels,
        },
    )


def local_page(request: Request) -> HTMLResponse:
    from aiqa.web.routes import UiQueryState, render_template

    if request.url.hostname not in {"127.0.0.1", "localhost"}:
        return HTMLResponse(status_code=403, content="이 화면을 볼 권한이 없습니다.")
    root = str(request.app.state.settings.runtime_root)
    status = read_local_status(root)
    project = request.query_params.get("project", "")
    attempt = request.query_params.get("attempt", "")
    return render_template(
        request,
        "connection.html",
        {
            "shell": True,
            "title": "로컬 연결",
            "heading": "로컬 연결",
            "section": "list",
            "connected": status.api_instances == 1,
            "state": "ready",
            "dirty": False,
            "query": UiQueryState("", "name", "", "", ""),
            "crumbs": (("연결", "/ui/local"),),
            "list_href": "/ui/local",
            "detail_href": "/ui/local",
            "request": request,
            "status": status,
            "project_events_url": "" if project == "" else f"/api/v1/projects/{project}/events",
            "attempt_events_url": "" if attempt == "" else f"/api/v1/attempts/{attempt}/events",
            "selected_rec": request.query_params.get("rec", ""),
            "selected_item": request.query_params.get("item", ""),
            "selected_action": request.query_params.get("action", ""),
            "stop_notice": read_stop_notice(root),
        },
    )
