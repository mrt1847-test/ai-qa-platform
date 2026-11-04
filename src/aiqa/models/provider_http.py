"""Provider HTTP port. Fixture counts calls and never opens a live LLM."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol


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


def structured_fixture_content(role: str) -> str:
    """Typed action / verification / healing payloads for fixture responses."""

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
        self.calls.append(
            ProviderHttpCall(
                model=model,
                role=role,
                secret_present=True,
                token_output_limit=token_output_limit,
            )
        )
        seq = len(self.calls)
        return ProviderHttpResult(
            content=structured_fixture_content(role),
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
    """Live provider boundary. Refused unless explicitly enabled; never used by fixture tests."""

    kind = "operational"

    def __init__(self, *, allow_live: bool = False) -> None:
        self.allow_live = allow_live
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
        if not self.allow_live:
            raise ValueError("operational provider is not enabled")
        self.calls.append(
            ProviderHttpCall(
                model=model,
                role=role,
                secret_present=True,
                token_output_limit=token_output_limit,
            )
        )
        raise ValueError("live provider endpoint is not configured")

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def calls_for(self, role: str) -> int:
        return sum(1 for item in self.calls if item.role == role)
