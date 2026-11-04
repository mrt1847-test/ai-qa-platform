"""The one product ASGI app. Health is process liveness, not engine or QA readiness."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from starlette.staticfiles import StaticFiles

from aiqa.api.artifacts import install_artifacts
from aiqa.api.retention import install_retention
from aiqa.api.backups import install_backups
from aiqa.api.case_runs import install_case_runs
from aiqa.api.executions import install_executions
from aiqa.api.suites import install_suites
from aiqa.api.healing import install_healing
from aiqa.api.auth import install_auth
from aiqa.api.cases import install_cases
from aiqa.api.catalog import install_catalog, install_taxonomy
from aiqa.api.https_boundary import install_https_boundary
from aiqa.api.mutations import current_mutation_store
from aiqa.api.jobs import install_jobs
from aiqa.api.recordings import install_recordings
from aiqa.api.reports import install_reports
from aiqa.api.resources import install_resources
from aiqa.api.model_bindings import install_model_bindings
from aiqa.api.secret_refs import install_secret_refs
from aiqa.api.settings import install_settings
from aiqa.api.tcs import install_tcs
from aiqa.api.worker import install_worker
from aiqa.api.oidc_login import assemble_hosted_oidc_runtime
from aiqa.config import AppSettings, SettingsError, load_settings
from aiqa.models.broker import build_model_gateway
from aiqa.models.provider_http import ProviderHttpPort, build_provider_from_settings
from aiqa.security.oidc import FixtureIdP
from aiqa.security.secrets import SecretBackend, build_server_secret_resolver
from aiqa.store.database import StorageConfig, open_store
from aiqa.api.lifecycle import install_local
from aiqa.web.routes import (
    ensure_css_media_type,
    install_shell,
    render_bootstrap,
    render_hosted_login,
    static_directory,
)


def health() -> dict[str, str]:
    return {"status": "ok", "component": "api"}


def create_app(
    settings: AppSettings | None = None,
    *,
    secret_backend: SecretBackend | None = None,
    oidc_idp: FixtureIdP | None = None,
    oidc_token_transport=None,
    model_provider: ProviderHttpPort | None = None,
) -> FastAPI:
    resolved = load_settings() if settings is None else settings
    if not isinstance(resolved, AppSettings):
        raise SettingsError("settings must be AppSettings")
    application = FastAPI(title="AI QA", version="0.0.0")
    application.state.settings = resolved
    application.state.secret_resolver = build_server_secret_resolver(
        resolved, backend=secret_backend
    )
    # Fixture by default; operational HTTPS is selected only from approved settings.
    application.state.model_gateway = build_model_gateway(
        application.state.secret_resolver,
        provider=(
            model_provider
            if model_provider is not None
            else build_provider_from_settings(resolved)
        ),
    )
    application.state.oidc_runtime = assemble_hosted_oidc_runtime(
        resolved,
        application.state.secret_resolver,
        idp=oidc_idp,
        token_transport=oidc_token_transport,
    )
    if application.state.oidc_runtime is not None:
        application.state.oidc_idp = application.state.oidc_runtime.idp
        application.state.oidc_config = application.state.oidc_runtime.config
    else:
        application.state.oidc_idp = None
        application.state.oidc_config = None

    def open_configured_store():
        borrowed = current_mutation_store()
        return borrowed if borrowed is not None else open_store(StorageConfig.from_settings(resolved))

    application.state.open_store = open_configured_store
    install_https_boundary(application)
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
    install_retention(application)
    install_backups(application)
    install_recordings(application)
    install_healing(application)
    install_executions(application)
    install_case_runs(application)
    install_reports(application)
    install_suites(application)
    install_local(application)
    application.add_api_route("/api/v1/health", health, methods=["GET"])
    install_shell(application)
    ensure_css_media_type()
    application.mount("/static", StaticFiles(directory=str(static_directory())), name="static")
    application.add_api_route("/", render_bootstrap, methods=["GET"], response_class=HTMLResponse)
    application.add_api_route(
        "/ui/login", render_hosted_login, methods=["GET"], response_class=HTMLResponse
    )
    return application
