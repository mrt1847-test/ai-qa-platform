"""Provider HTTP port. Fixture counts calls and never opens a live LLM."""

from __future__ import annotations

import hashlib
import json
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from aiqa.config import (
    MODEL_PROVIDER_FIXTURE,
    MODEL_PROVIDER_OPERATIONAL,
    AppSettings,
    ModelProviderSettings,
)


@dataclass(frozen=True, slots=True)
class ProviderHttpResult:
    content: str
    provider_request_id: str
    http_status: int
    actual_model: str


@dataclass(frozen=True, slots=True)
class ProviderHttpCall:
    model: str
    role: str
    secret_present: bool
    token_output_limit: int
    sanitized_inputs: tuple[str, ...] = ()


class ProviderHttpPort(Protocol):
    def complete(
        self,
        *,
        model: str,
        role: str,
        secret: str,
        sanitized_inputs: tuple[str, ...],
        token_output_limit: int,
    ) -> ProviderHttpResult: ...


class ProviderHttpError(ValueError):
    """Outbound provider transport or response was refused."""

    def __init__(self, reason: str, *, status: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


def structured_fixture_content(role: str, *, sanitized_inputs: tuple[str, ...] = ()) -> str:
    """Typed action / verification / healing / structure payloads for fixture responses."""

    if role == "authoring":
        return json.dumps({"type": "click", "selector": "#go"}, separators=(",", ":"), sort_keys=True)
    if role == "verification":
        return json.dumps({"status": "satisfied", "reason": "ok"}, separators=(",", ":"), sort_keys=True)
    if role == "healing":
        return json.dumps(
            {"status": "candidate", "basis": "typed", "action": "click", "input": "#go", "path": "dom"},
            separators=(",", ":"),
            sort_keys=True,
        )
    if role == "structure":
        seed = "|".join(item.strip() for item in sanitized_inputs if type(item) is str and item.strip() != "")
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8] if seed else "default"
        label = seed[:24] if seed else "주문 확인"
        return json.dumps(
            {
                "objective": f"{label} ({digest})",
                "preconditions": [],
                "variables": {},
                "secret_refs": {},
                "steps": [
                    {
                        "id": f"step-{digest}",
                        "instruction": seed[:120] if seed else "로그인 후 첫 주문을 연다",
                        "expected": [{"id": f"exp-{digest}", "kind": "text", "expected": "주문번호"}],
                    }
                ],
                "final_expected": [{"id": f"final-{digest}", "kind": "text", "expected": "결제 금액"}],
                "path_policy": {"must_use": [], "forbidden": []},
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    return json.dumps({"status": "ok"}, separators=(",", ":"), sort_keys=True)


class FixtureProviderHttp:
    """In-process provider. Counts admissions; secret material is never stored."""

    kind = "fixture"

    def __init__(self) -> None:
        self.calls: list[ProviderHttpCall] = []

    def complete(
        self,
        *,
        model: str,
        role: str,
        secret: str,
        sanitized_inputs: tuple[str, ...],
        token_output_limit: int,
    ) -> ProviderHttpResult:
        if type(secret) is not str or secret.strip() == "":
            raise ValueError("provider secret is missing")
        if type(model) is not str or model.strip() == "":
            raise ValueError("provider model is missing")
        inputs = tuple(sanitized_inputs) if type(sanitized_inputs) is tuple else ()
        self.calls.append(
            ProviderHttpCall(
                model=model,
                role=role,
                secret_present=True,
                token_output_limit=token_output_limit,
                sanitized_inputs=inputs,
            )
        )
        seq = len(self.calls)
        return ProviderHttpResult(
            content=structured_fixture_content(role, sanitized_inputs=inputs),
            provider_request_id=f"fixture-{seq}",
            http_status=200,
            actual_model=model,
        )

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def calls_for(self, role: str) -> int:
        return sum(1 for item in self.calls if item.role == role)


class OperationalProviderHttp:
    """Live HTTPS provider. Disabled unless explicitly enabled with an approved origin."""

    kind = "operational"

    def __init__(
        self,
        *,
        allow_live: bool = False,
        base_url: str | None = None,
        ca_bundle: Path | None = None,
        verify_tls: bool = True,
        timeout_seconds: float = 10.0,
        complete_path: str = "/v1/complete",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.allow_live = allow_live
        self.base_url = None if base_url is None else str(base_url).rstrip("/")
        self.ca_bundle = ca_bundle
        self.verify_tls = verify_tls
        self.timeout_seconds = float(timeout_seconds)
        self.complete_path = complete_path if complete_path.startswith("/") else f"/{complete_path}"
        self._transport = transport
        self.calls: list[ProviderHttpCall] = []
        self._idempotent: dict[str, ProviderHttpResult] = {}

    def complete(
        self,
        *,
        model: str,
        role: str,
        secret: str,
        sanitized_inputs: tuple[str, ...],
        token_output_limit: int,
    ) -> ProviderHttpResult:
        if type(secret) is not str or secret.strip() == "":
            raise ValueError("provider secret is missing")
        if type(model) is not str or model.strip() == "":
            raise ValueError("provider model is missing")
        if not self.allow_live:
            raise ValueError("operational provider is not enabled")
        if self.base_url is None or self.base_url.strip() == "":
            raise ValueError("live provider endpoint is not configured")
        inputs = tuple(sanitized_inputs) if type(sanitized_inputs) is tuple else ()
        self.calls.append(
            ProviderHttpCall(
                model=model,
                role=role,
                secret_present=True,
                token_output_limit=token_output_limit,
                sanitized_inputs=inputs,
            )
        )
        body = {
            "model": model,
            "role": role,
            "sanitized_inputs": list(inputs),
            "token_output_limit": token_output_limit,
        }
        idempotency_key = _request_key(body)
        cached = self._idempotent.get(idempotency_key)
        if cached is not None:
            return cached
        verify: bool | ssl.SSLContext = False
        if self.verify_tls:
            if self.ca_bundle is not None:
                context = ssl.create_default_context(cafile=str(self.ca_bundle))
                verify = context
            else:
                verify = True
        headers = {
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
        }
        try:
            with httpx.Client(
                base_url=self.base_url,
                verify=verify,
                timeout=self.timeout_seconds,
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = client.post(self.complete_path, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderHttpError("provider_timeout") from exc
        except httpx.ConnectError as exc:
            raise ProviderHttpError("provider_unreachable") from exc
        except httpx.HTTPError as exc:
            raise ProviderHttpError("provider_transport") from exc
        if response.status_code == 429:
            raise ProviderHttpError("provider_quota", status=429)
        if response.status_code in {401, 403}:
            raise ProviderHttpError("provider_unauthorized", status=response.status_code)
        if response.status_code >= 400:
            raise ProviderHttpError("provider_http_error", status=response.status_code)
        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderHttpError("provider_response_invalid") from exc
        if type(payload) is not dict:
            raise ProviderHttpError("provider_response_invalid")
        content = payload.get("content")
        request_id = payload.get("provider_request_id")
        actual = payload.get("actual_model", model)
        if type(content) is not str or content.strip() == "":
            raise ProviderHttpError("provider_response_invalid")
        if type(request_id) is not str or request_id.strip() == "":
            raise ProviderHttpError("provider_response_invalid")
        if type(actual) is not str or actual.strip() == "":
            raise ProviderHttpError("provider_response_invalid")
        result = ProviderHttpResult(
            content=content,
            provider_request_id=request_id,
            http_status=int(response.status_code),
            actual_model=actual,
        )
        self._idempotent[idempotency_key] = result
        return result

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def calls_for(self, role: str) -> int:
        return sum(1 for item in self.calls if item.role == role)


def build_provider_from_settings(
    settings: AppSettings | ModelProviderSettings,
    *,
    transport: httpx.BaseTransport | None = None,
) -> FixtureProviderHttp | OperationalProviderHttp:
    """Select fixture or operational HTTP from approved settings. Keys are not read here."""

    conf = settings.model_provider if isinstance(settings, AppSettings) else settings
    if conf.mode == MODEL_PROVIDER_FIXTURE:
        return FixtureProviderHttp()
    if conf.mode != MODEL_PROVIDER_OPERATIONAL:
        raise ValueError("model provider mode is invalid")
    return OperationalProviderHttp(
        allow_live=True,
        base_url=conf.base_url,
        ca_bundle=conf.ca_bundle,
        verify_tls=conf.verify_tls,
        timeout_seconds=float(conf.timeout_seconds),
        complete_path=conf.complete_path,
        transport=transport,
    )


def _request_key(body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
