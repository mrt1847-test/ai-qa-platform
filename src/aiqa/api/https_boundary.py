"""Hosted reverse-proxy HTTPS boundary. Importing this module opens no sockets."""

from __future__ import annotations

from ipaddress import ip_address, ip_network

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from aiqa.config import PROFILE_HOSTED, AppSettings


def install_https_boundary(application: FastAPI) -> None:
    """Reject forged Forwarded headers and public HTTP for the hosted profile."""

    application.add_middleware(HostedHttpsBoundaryMiddleware)


class HostedHttpsBoundaryMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = request.app.state.settings
        if not isinstance(settings, AppSettings) or settings.profile != PROFILE_HOSTED:
            return await call_next(request)

        client_host = request.client.host if request.client is not None else None
        forwarded = _has_forwarded(request)
        trusted = client_host is not None and is_trusted_proxy(client_host, settings.trusted_proxies)

        if forwarded and not trusted:
            return _refuse(403, "permission", "forwarded headers were refused")
        if not trusted:
            return _refuse(403, "permission", "direct access was refused")

        proto = request.headers.get("x-forwarded-proto", "").strip().lower()
        if proto != "https":
            return _refuse(403, "permission", "public HTTP was refused")

        return await call_next(request)


def is_trusted_proxy(client_host: str, trusted_proxies: tuple[str, ...]) -> bool:
    try:
        address = ip_address(client_host)
    except ValueError:
        return False
    for entry in trusted_proxies:
        try:
            if "/" in entry:
                if address in ip_network(entry, strict=False):
                    return True
            elif address == ip_address(entry):
                return True
        except ValueError:
            continue
    return False


def _has_forwarded(request: Request) -> bool:
    return any(
        name in request.headers
        for name in ("forwarded", "x-forwarded-for", "x-forwarded-proto", "x-forwarded-host")
    )


def _refuse(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "fields": {},
                "retryable": False,
                "request_id": "https-boundary",
            }
        },
    )
