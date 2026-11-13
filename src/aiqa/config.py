"""Process settings for the single local API. This module opens no clients."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_WORKER_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_ACTIVE_SLOTS = 1
PROFILE_LOCAL = "local"
PROFILE_HOSTED = "hosted"
LOCAL_SECRET_ACCOUNT = "aiqa-local"
HOSTED_SECRET_ACCOUNT = "aiqa-server"
_PORT_TEXT = re.compile(r"[0-9]+")


class SettingsError(ValueError):
    """AIQA_HOST, AIQA_PORT, or the runtime root was refused."""


@dataclass(frozen=True, slots=True)
class OidcHostedSettings:
    """Approved hosted IdP surface. Client secret stays in the server secret store."""

    issuer: str
    audience: str
    client_id: str
    authorize_endpoint: str
    token_endpoint: str

    def __post_init__(self) -> None:
        if type(self.issuer) is not str or not self.issuer.startswith("https://"):
            raise SettingsError("AIQA_OIDC_ISSUER must be an https issuer")
        if type(self.audience) is not str or self.audience.strip() == "":
            raise SettingsError("AIQA_OIDC_AUDIENCE is empty")
        if type(self.client_id) is not str or self.client_id.strip() == "":
            raise SettingsError("AIQA_OIDC_CLIENT_ID is empty")
        if type(self.authorize_endpoint) is not str or not self.authorize_endpoint.startswith("https://"):
            raise SettingsError("AIQA_OIDC_AUTHORIZE_ENDPOINT must be https")
        if type(self.token_endpoint) is not str or not self.token_endpoint.startswith("https://"):
            raise SettingsError("AIQA_OIDC_TOKEN_ENDPOINT must be https")


MODEL_PROVIDER_FIXTURE = "fixture"
MODEL_PROVIDER_OPERATIONAL = "operational"
DEFAULT_MODEL_PROVIDER_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class ModelProviderSettings:
    """Approved outbound model provider surface. Keys stay in the server secret store."""

    mode: str = MODEL_PROVIDER_FIXTURE
    base_url: str | None = None
    ca_bundle: Path | None = None
    verify_tls: bool = True
    timeout_seconds: float = DEFAULT_MODEL_PROVIDER_TIMEOUT_SECONDS
    complete_path: str = "/v1/complete"

    def __post_init__(self) -> None:
        if self.mode not in {MODEL_PROVIDER_FIXTURE, MODEL_PROVIDER_OPERATIONAL}:
            raise SettingsError(
                f"AIQA_MODEL_PROVIDER_MODE must be fixture or operational; refused {self.mode!r}"
            )
        if type(self.timeout_seconds) is not float and type(self.timeout_seconds) is not int:
            raise SettingsError("AIQA_MODEL_PROVIDER_TIMEOUT_SECONDS is invalid")
        if float(self.timeout_seconds) <= 0:
            raise SettingsError("AIQA_MODEL_PROVIDER_TIMEOUT_SECONDS is invalid")
        if type(self.complete_path) is not str or not self.complete_path.startswith("/"):
            raise SettingsError("AIQA_MODEL_PROVIDER_COMPLETE_PATH is invalid")
        if self.mode == MODEL_PROVIDER_FIXTURE:
            return
        if type(self.base_url) is not str or self.base_url.strip() == "":
            raise SettingsError("AIQA_MODEL_PROVIDER_BASE_URL is required for operational mode")
        parsed = urlparse(self.base_url)
        if (
            parsed.scheme != "https"
            or parsed.netloc == ""
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise SettingsError("AIQA_MODEL_PROVIDER_BASE_URL must be an https origin")
        if self.ca_bundle is not None and not isinstance(self.ca_bundle, Path):
            raise SettingsError("AIQA_MODEL_PROVIDER_CA_BUNDLE must be a path")


@dataclass(frozen=True, slots=True)
class AppSettings:
    host: str
    port: int
    runtime_root: Path
    profile: str = PROFILE_LOCAL
    public_origin: str | None = None
    trusted_proxies: tuple[str, ...] = ()
    secret_account: str = LOCAL_SECRET_ACCOUNT
    oidc: OidcHostedSettings | None = None
    model_provider: ModelProviderSettings = field(default_factory=ModelProviderSettings)
    max_active_slots: int = DEFAULT_MAX_ACTIVE_SLOTS
    model_price_mode: str = "strict"

    @property
    def artifacts_dir(self) -> Path:
        """API-owned durable artifact root. Workers never receive a SQLite grant here."""

        return self.runtime_root / "artifacts"

    @property
    def backups_dir(self) -> Path:
        """API-owned backup generation root. Secret plaintext never lands here."""

        return self.runtime_root / "backups"

    def __post_init__(self) -> None:
        if self.model_price_mode not in {"strict","estimate"}:
            raise SettingsError("AIQA_MODEL_PRICE_MODE must be strict or estimate")
        if type(self.host) is not str or self.host != LOOPBACK_HOST:
            raise SettingsError(f"AIQA_HOST must be {LOOPBACK_HOST}; refused {self.host!r}")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise SettingsError(
                f"AIQA_PORT must be an integer from 1 to 65535; refused {self.port!r}"
            )
        if not isinstance(self.runtime_root, Path):
            raise SettingsError("runtime_root must be a pathlib.Path")
        if self.profile not in {PROFILE_LOCAL, PROFILE_HOSTED}:
            raise SettingsError(f"AIQA_PROFILE must be local or hosted; refused {self.profile!r}")
        if type(self.secret_account) is not str or self.secret_account.strip() == "":
            raise SettingsError("AIQA_SECRET_ACCOUNT is empty")
        if self.profile == PROFILE_LOCAL:
            if self.public_origin is not None:
                raise SettingsError("local profile refuses AIQA_PUBLIC_ORIGIN")
            if self.trusted_proxies:
                raise SettingsError("local profile refuses AIQA_TRUSTED_PROXIES")
            return
        if type(self.public_origin) is not str or self.public_origin.strip() == "":
            raise SettingsError("AIQA_PUBLIC_ORIGIN is required for hosted profile")
        parsed = urlparse(self.public_origin)
        if (
            parsed.scheme != "https"
            or parsed.netloc == ""
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise SettingsError("AIQA_PUBLIC_ORIGIN must be an https origin")
        if type(self.trusted_proxies) is not tuple or len(self.trusted_proxies) == 0:
            raise SettingsError("AIQA_TRUSTED_PROXIES is required for hosted profile")
        for entry in self.trusted_proxies:
            if type(entry) is not str or entry.strip() == "":
                raise SettingsError("AIQA_TRUSTED_PROXIES contains an empty entry")
        if self.oidc is not None and self.profile != PROFILE_HOSTED:
            raise SettingsError("OIDC settings require hosted profile")
        if type(self.max_active_slots) is not int or self.max_active_slots < 1:
            raise SettingsError("AIQA_MAX_ACTIVE_SLOTS must be an integer >= 1")


@dataclass(frozen=True, slots=True)
class WorkerClientSettings:
    """Outbound worker HTTPS settings. Raw tokens are not written to logs by callers."""

    base_url: str
    token: str
    timeout_seconds: float = DEFAULT_WORKER_TIMEOUT_SECONDS
    verify_tls: bool = True
    ca_bundle: Path | None = None

    def __post_init__(self) -> None:
        if type(self.base_url) is not str or self.base_url.strip() == "":
            raise SettingsError("AIQA_MANAGEMENT_BASE_URL is empty")
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or parsed.netloc == "" or parsed.username or parsed.password:
            raise SettingsError("AIQA_MANAGEMENT_BASE_URL must be an https origin")
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise SettingsError("AIQA_MANAGEMENT_BASE_URL must not include a path or query")
        if type(self.token) is not str or self.token.strip() == "":
            raise SettingsError("AIQA_WORKER_TOKEN is empty")
        if not isinstance(self.timeout_seconds, (int, float)) or not (0 < float(self.timeout_seconds) <= 300):
            raise SettingsError("AIQA_WORKER_TIMEOUT_SECONDS is invalid")
        if type(self.verify_tls) is not bool:
            raise SettingsError("AIQA_WORKER_VERIFY_TLS is invalid")
        if self.ca_bundle is not None and not isinstance(self.ca_bundle, Path):
            raise SettingsError("AIQA_WORKER_CA_BUNDLE must be a path")


def load_settings(env: Mapping[str, str] | None = None) -> AppSettings:
    """Read AIQA_* from env, or from the process environment when env is omitted."""

    source: Mapping[str, str] = os.environ if env is None else env
    host = source["AIQA_HOST"] if "AIQA_HOST" in source else LOOPBACK_HOST
    port = _parse_port(source["AIQA_PORT"]) if "AIQA_PORT" in source else DEFAULT_PORT
    if "AIQA_RUNTIME_ROOT" in source:
        raw_root = source["AIQA_RUNTIME_ROOT"]
        if type(raw_root) is not str or raw_root.strip() == "":
            raise SettingsError("AIQA_RUNTIME_ROOT is empty")
        runtime_root = Path(raw_root)
    else:
        local = source["LOCALAPPDATA"] if "LOCALAPPDATA" in source else ""
        if type(local) is not str or local.strip() == "":
            raise SettingsError("AIQA_RUNTIME_ROOT is unset and LOCALAPPDATA is missing")
        runtime_root = Path(local) / "AIQA"
    profile = PROFILE_LOCAL
    if "AIQA_PROFILE" in source:
        raw_profile = source["AIQA_PROFILE"]
        if type(raw_profile) is not str or raw_profile.strip() == "":
            raise SettingsError("AIQA_PROFILE is empty")
        profile = raw_profile.strip().lower()
    public_origin = None
    if "AIQA_PUBLIC_ORIGIN" in source:
        raw_origin = source["AIQA_PUBLIC_ORIGIN"]
        if type(raw_origin) is not str or raw_origin.strip() == "":
            raise SettingsError("AIQA_PUBLIC_ORIGIN is empty")
        public_origin = raw_origin.rstrip("/")
    trusted_proxies: tuple[str, ...] = ()
    if "AIQA_TRUSTED_PROXIES" in source:
        raw_proxies = source["AIQA_TRUSTED_PROXIES"]
        if type(raw_proxies) is not str:
            raise SettingsError("AIQA_TRUSTED_PROXIES is invalid")
        trusted_proxies = tuple(part.strip() for part in raw_proxies.split(",") if part.strip())
    if "AIQA_SECRET_ACCOUNT" in source:
        raw_account = source["AIQA_SECRET_ACCOUNT"]
        if type(raw_account) is not str or raw_account.strip() == "":
            raise SettingsError("AIQA_SECRET_ACCOUNT is empty")
        secret_account = raw_account.strip()
    else:
        secret_account = (
            HOSTED_SECRET_ACCOUNT if profile == PROFILE_HOSTED else LOCAL_SECRET_ACCOUNT
        )
    oidc: OidcHostedSettings | None = None
    if "AIQA_OIDC_ISSUER" in source:
        issuer = source["AIQA_OIDC_ISSUER"]
        audience = source.get("AIQA_OIDC_AUDIENCE", "aiqa-management")
        client_id = source.get("AIQA_OIDC_CLIENT_ID", "aiqa-management")
        issuer_url = str(issuer).rstrip("/")
        authorize = source.get("AIQA_OIDC_AUTHORIZE_ENDPOINT") or f"{issuer_url}/authorize"
        token = source.get("AIQA_OIDC_TOKEN_ENDPOINT") or f"{issuer_url}/token"
        oidc = OidcHostedSettings(
            issuer=issuer_url,
            audience=str(audience).strip(),
            client_id=str(client_id).strip(),
            authorize_endpoint=str(authorize).rstrip("/"),
            token_endpoint=str(token).rstrip("/"),
        )
    model_provider = _load_model_provider_settings(source)
    max_active_slots = DEFAULT_MAX_ACTIVE_SLOTS
    if "AIQA_MAX_ACTIVE_SLOTS" in source:
        raw_slots = source["AIQA_MAX_ACTIVE_SLOTS"]
        if type(raw_slots) is not str or not _PORT_TEXT.fullmatch(raw_slots.strip()):
            raise SettingsError("AIQA_MAX_ACTIVE_SLOTS is invalid")
        max_active_slots = int(raw_slots.strip())
    return AppSettings(
        host=host,
        port=port,
        runtime_root=runtime_root,
        profile=profile,
        public_origin=public_origin,
        trusted_proxies=trusted_proxies,
        secret_account=secret_account,
        oidc=oidc,
        model_provider=model_provider,
        max_active_slots=max_active_slots,
        model_price_mode=source.get("AIQA_MODEL_PRICE_MODE","strict"),
    )


def _load_model_provider_settings(source: Mapping[str, str]) -> ModelProviderSettings:
    mode = MODEL_PROVIDER_FIXTURE
    if "AIQA_MODEL_PROVIDER_MODE" in source:
        raw_mode = source["AIQA_MODEL_PROVIDER_MODE"]
        if type(raw_mode) is not str or raw_mode.strip() == "":
            raise SettingsError("AIQA_MODEL_PROVIDER_MODE is empty")
        mode = raw_mode.strip().lower()
    base_url = None
    if "AIQA_MODEL_PROVIDER_BASE_URL" in source:
        raw_url = source["AIQA_MODEL_PROVIDER_BASE_URL"]
        if type(raw_url) is not str or raw_url.strip() == "":
            raise SettingsError("AIQA_MODEL_PROVIDER_BASE_URL is empty")
        base_url = raw_url.rstrip("/")
    verify = True
    if "AIQA_MODEL_PROVIDER_VERIFY_TLS" in source:
        flag = source["AIQA_MODEL_PROVIDER_VERIFY_TLS"].strip().lower()
        if flag not in {"1", "0", "true", "false", "yes", "no"}:
            raise SettingsError("AIQA_MODEL_PROVIDER_VERIFY_TLS is invalid")
        verify = flag in {"1", "true", "yes"}
    ca_bundle = None
    if "AIQA_MODEL_PROVIDER_CA_BUNDLE" in source:
        raw_ca = source["AIQA_MODEL_PROVIDER_CA_BUNDLE"]
        if type(raw_ca) is not str or raw_ca.strip() == "":
            raise SettingsError("AIQA_MODEL_PROVIDER_CA_BUNDLE is empty")
        ca_bundle = Path(raw_ca)
    timeout = DEFAULT_MODEL_PROVIDER_TIMEOUT_SECONDS
    if "AIQA_MODEL_PROVIDER_TIMEOUT_SECONDS" in source:
        raw_timeout = source["AIQA_MODEL_PROVIDER_TIMEOUT_SECONDS"]
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise SettingsError("AIQA_MODEL_PROVIDER_TIMEOUT_SECONDS is invalid") from exc
    complete_path = "/v1/complete"
    if "AIQA_MODEL_PROVIDER_COMPLETE_PATH" in source:
        raw_path = source["AIQA_MODEL_PROVIDER_COMPLETE_PATH"]
        if type(raw_path) is not str or raw_path.strip() == "":
            raise SettingsError("AIQA_MODEL_PROVIDER_COMPLETE_PATH is empty")
        complete_path = raw_path.strip()
    return ModelProviderSettings(
        mode=mode,
        base_url=base_url,
        ca_bundle=ca_bundle,
        verify_tls=verify,
        timeout_seconds=timeout,
        complete_path=complete_path,
    )


def load_worker_client_settings(env: Mapping[str, str] | None = None) -> WorkerClientSettings:
    """Read outbound worker HTTPS settings. Missing required keys raise SettingsError."""

    source: Mapping[str, str] = os.environ if env is None else env
    if "AIQA_MANAGEMENT_BASE_URL" not in source:
        raise SettingsError("AIQA_MANAGEMENT_BASE_URL is unset")
    if "AIQA_WORKER_TOKEN" not in source:
        raise SettingsError("AIQA_WORKER_TOKEN is unset")
    timeout = DEFAULT_WORKER_TIMEOUT_SECONDS
    if "AIQA_WORKER_TIMEOUT_SECONDS" in source:
        raw = source["AIQA_WORKER_TIMEOUT_SECONDS"]
        try:
            timeout = float(raw)
        except (TypeError, ValueError) as exc:
            raise SettingsError("AIQA_WORKER_TIMEOUT_SECONDS is invalid") from exc
    verify = True
    if "AIQA_WORKER_VERIFY_TLS" in source:
        flag = source["AIQA_WORKER_VERIFY_TLS"].strip().lower()
        if flag not in {"1", "0", "true", "false", "yes", "no"}:
            raise SettingsError("AIQA_WORKER_VERIFY_TLS is invalid")
        verify = flag in {"1", "true", "yes"}
    ca_bundle = None
    if "AIQA_WORKER_CA_BUNDLE" in source:
        raw_ca = source["AIQA_WORKER_CA_BUNDLE"]
        if type(raw_ca) is not str or raw_ca.strip() == "":
            raise SettingsError("AIQA_WORKER_CA_BUNDLE is empty")
        ca_bundle = Path(raw_ca)
    return WorkerClientSettings(
        base_url=source["AIQA_MANAGEMENT_BASE_URL"].rstrip("/"),
        token=source["AIQA_WORKER_TOKEN"],
        timeout_seconds=timeout,
        verify_tls=verify,
        ca_bundle=ca_bundle,
    )


def _parse_port(raw: object) -> int:
    if type(raw) is not str or _PORT_TEXT.fullmatch(raw) is None:
        raise SettingsError(f"AIQA_PORT is not an integer: {raw!r}")
    return int(raw, 10)
