"""Web isolation backend port and proof gate. Importing this module opens no VM."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping

from aiqa.replay.ipc import WEB_ACTION_TYPES, TypedAction, parse_ipc_message

DEFAULT_PROOF_TTL_SECONDS = 300
BYPASS_KINDS = frozenset(
    {
        "host_filesystem",
        "host_process",
        "adb",
        "cdp",
        "direct_provider",
        "arbitrary_network",
    }
)
_BYPASS_FIELDS = frozenset(
    {
        "path",
        "filesystem",
        "open",
        "subprocess",
        "shell",
        "adb",
        "serial",
        "provider",
        "model_url",
        "http_url",
        "fetch",
        "socket",
        "network",
        "cdp",
        "cdp_url",
        "websocket",
        "ws_url",
        "endpoint",
        "page",
        "browser",
        "context",
        "handle",
        "devtools",
    }
)


class IsolationRejected(Exception):
    """Isolation config, proof, or guest channel was refused."""


@dataclass(frozen=True, slots=True)
class IsolationBackendPort:
    """Contract surface for a fixture or real VM backend."""

    name: str
    proof_ttl_seconds: int
    allowed_origins: tuple[str, ...]
    allowed_actions: frozenset[str]

    def __post_init__(self) -> None:
        if type(self.name) is not str or self.name.strip() == "":
            raise IsolationRejected("backend name is required")
        if type(self.proof_ttl_seconds) is not int or not 1 <= self.proof_ttl_seconds <= 3600:
            raise IsolationRejected("proof TTL must be 1..3600 seconds")
        if not self.allowed_origins:
            raise IsolationRejected("allowed_origins is required")
        if not self.allowed_actions or not self.allowed_actions.issubset(WEB_ACTION_TYPES):
            raise IsolationRejected("allowed_actions must be a non-empty IPC subset")


@dataclass(frozen=True, slots=True)
class IsolationConfig:
    """Required isolation settings. Missing config cannot produce Web ready."""

    backend: IsolationBackendPort
    proof_secret: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.backend, IsolationBackendPort):
            raise IsolationRejected("backend port is required")
        if type(self.proof_secret) is not bytes or len(self.proof_secret) < 16:
            raise IsolationRejected("proof secret is required")

    @property
    def scope_hash(self) -> str:
        material = "|".join(
            [
                self.backend.name,
                str(self.backend.proof_ttl_seconds),
                ",".join(self.backend.allowed_origins),
                ",".join(sorted(self.backend.allowed_actions)),
            ]
        )
        return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class IsolationProof:
    backend: str
    issued_at: str
    expires_at: str
    scope_hash: str
    nonce: str
    token: str


@dataclass(frozen=True, slots=True)
class WebReady:
    backend: str
    scope_hash: str
    expires_at: str


def fixture_backend(
    *,
    name: str = "fixture",
    ttl_seconds: int = DEFAULT_PROOF_TTL_SECONDS,
    allowed_origins: tuple[str, ...] = ("https://app.example.test",),
) -> IsolationBackendPort:
    return IsolationBackendPort(
        name=name,
        proof_ttl_seconds=ttl_seconds,
        allowed_origins=allowed_origins,
        allowed_actions=frozenset(WEB_ACTION_TYPES),
    )


def unsupported_vm_backend(
    *,
    name: str = "hyper-v-guest",
    ttl_seconds: int = DEFAULT_PROOF_TTL_SECONDS,
    allowed_origins: tuple[str, ...] = ("https://app.example.test",),
) -> IsolationBackendPort:
    """Named real-VM backend surface. Ready stays false until RX-22 admits a product."""

    return IsolationBackendPort(
        name=name,
        proof_ttl_seconds=ttl_seconds,
        allowed_origins=allowed_origins,
        allowed_actions=frozenset(WEB_ACTION_TYPES),
    )


class WebIsolationGate:
    """Admit Web ready and guest IPC only after a verified isolation proof."""

    def __init__(self, config: IsolationConfig) -> None:
        self._config = config
        self.execution_count = 0

    @property
    def config(self) -> IsolationConfig:
        return self._config

    def issue_proof(self, *, now: datetime | None = None) -> IsolationProof:
        instant = _utc(now)
        expires = instant + timedelta(seconds=self._config.backend.proof_ttl_seconds)
        nonce = secrets.token_urlsafe(16)
        proof = IsolationProof(
            backend=self._config.backend.name,
            issued_at=instant.isoformat(),
            expires_at=expires.isoformat(),
            scope_hash=self._config.scope_hash,
            nonce=nonce,
            token="",
        )
        return IsolationProof(
            backend=proof.backend,
            issued_at=proof.issued_at,
            expires_at=proof.expires_at,
            scope_hash=proof.scope_hash,
            nonce=proof.nonce,
            token=_sign(self._config.proof_secret, proof),
        )

    def verify_proof(self, proof: IsolationProof | None, *, now: datetime | None = None) -> IsolationProof:
        if proof is None:
            raise IsolationRejected("isolation proof is missing")
        if proof.backend != self._config.backend.name:
            raise IsolationRejected("isolation proof backend mismatch")
        if proof.scope_hash != self._config.scope_hash:
            raise IsolationRejected("isolation proof scope mismatch")
        expected = _sign(self._config.proof_secret, proof)
        if not hmac.compare_digest(expected, proof.token):
            raise IsolationRejected("isolation proof was forged")
        if datetime.fromisoformat(proof.expires_at) <= _utc(now):
            raise IsolationRejected("isolation proof expired")
        return proof

    def web_ready(self, proof: IsolationProof | None, *, now: datetime | None = None) -> WebReady | None:
        try:
            verified = self.verify_proof(proof, now=now)
        except IsolationRejected:
            return None
        return WebReady(
            backend=verified.backend,
            scope_hash=verified.scope_hash,
            expires_at=verified.expires_at,
        )

    def run_guest_ipc(
        self,
        proof: IsolationProof | None,
        payload: Mapping[str, object],
        *,
        now: datetime | None = None,
    ) -> TypedAction:
        if self.web_ready(proof, now=now) is None:
            raise IsolationRejected("web is not ready without isolation confirmation")
        action = admit_guest_channel(payload, allowed_actions=self._config.backend.allowed_actions)
        self.execution_count += 1
        return action


def admit_guest_channel(
    payload: Mapping[str, object],
    *,
    allowed_actions: frozenset[str],
) -> TypedAction:
    """Accept typed IPC only. Host/process/ADB/CDP/provider/network bypass is refused."""

    if not isinstance(payload, Mapping):
        raise IsolationRejected("guest payload must be an object")
    kind = payload.get("kind", "ipc")
    if kind in BYPASS_KINDS:
        raise IsolationRejected(f"isolation bypass refused: {kind}")
    if kind != "ipc":
        raise IsolationRejected("guest channel only admits ipc")
    body = payload.get("payload", payload)
    if not isinstance(body, Mapping):
        raise IsolationRejected("ipc payload must be an object")
    leaked = _BYPASS_FIELDS.intersection(body)
    if leaked:
        raise IsolationRejected(f"isolation bypass refused: {sorted(leaked)[0]}")
    try:
        action = parse_ipc_message(dict(body))
    except ValueError as exc:
        raise IsolationRejected(str(exc)) from exc
    if action.type not in allowed_actions:
        raise IsolationRejected("ipc action is outside the isolation allowlist")
    return action


def _sign(secret: bytes, proof: IsolationProof) -> str:
    material = "|".join(
        [proof.backend, proof.issued_at, proof.expires_at, proof.scope_hash, proof.nonce]
    )
    digest = hmac.new(secret, material.encode("utf-8"), hashlib.sha256).hexdigest()
    return "sha256:" + digest


def _utc(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise IsolationRejected("now must be timezone-aware")
    return now.astimezone(timezone.utc)
