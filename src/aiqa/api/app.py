"""The one product ASGI app. Health is process liveness, not engine or QA readiness."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from starlette.staticfiles import StaticFiles

from aiqa.api.artifacts import install_artifacts
from aiqa.api.auth import install_auth
from aiqa.api.cases import install_cases
from aiqa.api.catalog import install_catalog, install_taxonomy
from aiqa.api.mutations import current_mutation_store
from aiqa.api.jobs import install_jobs
from aiqa.api.recordings import install_recordings
from aiqa.api.resources import install_resources
from aiqa.api.model_bindings import install_model_bindings
from aiqa.api.secret_refs import install_secret_refs
from aiqa.api.settings import install_settings
from aiqa.api.tcs import install_tcs
from aiqa.api.worker import install_worker
from aiqa.config import AppSettings, SettingsError, load_settings
from aiqa.store.database import StorageConfig, open_store
from aiqa.web.routes import ensure_css_media_type, install_shell, render_bootstrap, static_directory


def health() -> dict[str, str]:
    return {"status": "ok", "component": "api"}


def create_app(settings: AppSettings | None = None) -> FastAPI:
    resolved = load_settings() if settings is None else settings
    if not isinstance(resolved, AppSettings):
        raise SettingsError("settings must be AppSettings")
    application = FastAPI(title="AI QA", version="0.0.0")
    application.state.settings = resolved

    def open_configured_store():
        borrowed = current_mutation_store()
        return borrowed if borrowed is not None else open_store(StorageConfig.from_settings(resolved))

    application.state.open_store = open_configured_store
    install_auth(application)
    install_secret_refs(application)
    install_model_bindings(application)
    install_settings(application)
    install_cases(application)
    install_catalog(application)
    install_taxonomy(application)
    install_tcs(application)
    install_resources(application)
    install_jobs(application)
    install_worker(application)
    install_artifacts(application)
    install_recordings(application)
    application.add_api_route("/api/v1/health", health, methods=["GET"])
    install_shell(application)
    ensure_css_media_type()
    application.mount("/static", StaticFiles(directory=str(static_directory())), name="static")
    application.add_api_route("/", render_bootstrap, methods=["GET"], response_class=HTMLResponse)
    return application
