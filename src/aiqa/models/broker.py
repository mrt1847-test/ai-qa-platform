"""One admission point for model roles, checks, and episodes. This does not call a provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from threading import Lock
from uuid import UUID, uuid4

from aiqa.contracts.models import MODEL_ROLES, ModelRequest, OwnedCheck, OwnedEpisode, RoleBinding
from aiqa.models.budget import CallBudget
from aiqa.models.provider_http import FixtureProviderHttp, ProviderHttpError, ProviderHttpPort
from aiqa.models.usage import bind_usage, record_model_usage, reset_usage
from aiqa.security.secrets import (
    SecretScopeDenied,
    SecretUnavailable,
    ServerSecretResolver,
    bind_secret_store,
    scrub_worker_dto,
)
from aiqa.store.models import RuntimeScope, SecretRef, WorkerScope
from aiqa.store.usage import ModelCallSettlement, UsageLedger


@dataclass(frozen=True, slots=True)
class Admission:
    allowed: bool
    model: str | None
    reason: str


class ModelBroker:
    """Admit a call only when the role binding and the owner belong to this item."""

    def __init__(
        self,
        item_id: str,
        bindings: tuple[RoleBinding, ...],
        checks: tuple[OwnedCheck, ...],
        episodes: tuple[OwnedEpisode, ...],
    ) -> None:
        self.item_id = item_id
        self.authoring_calls = 0
        self._bindings = {(binding.role, binding.revision): binding for binding in bindings}
        self._checks = {check.check_id: check for check in checks}
        self._episodes = {episode.episode_id: episode for episode in episodes}
        self._budget = None

    def attach_budget(self, budget: object) -> None:
        self._budget = budget

    def admit(self, request: ModelRequest) -> Admission:
        if request.role not in MODEL_ROLES:
            return Admission(False, None, "role")
        binding = self._bindings.get((request.role, request.binding_revision))
        if binding is None:
            return Admission(False, None, "role")
        if request.owner_kind == "check":
            if request.check_id is None:
                return Admission(False, None, "unowned")
            check = self._checks.get(request.check_id)
            if check is None:
                return Admission(False, None, "unowned")
            if check.item_id != self.item_id:
                return Admission(False, None, "cross_item")
        elif request.owner_kind == "episode":
            if request.episode_id is None:
                return Admission(False, None, "unowned")
            episode = self._episodes.get(request.episode_id)
            if episode is None or episode.item_id != self.item_id:
                return Admission(False, None, "cross_item")
        elif request.owner_kind != "authoring" or request.role != "authoring":
            return Admission(False, None, "unowned")
        if self._budget is not None and not self._budget.room_for(request.role):
            return Admission(False, None, "budget")
        return Admission(True, binding.model, "admitted")

    def meter(self, request: ModelRequest) -> None:
        if request.role == "authoring":
            self.authoring_calls += 1

    def admit_verifier(self, check_id: str, method: str) -> Admission:
        """Admit a declared visual check. An undeclared method is not a call."""

        if method not in {"ai_visual", "deterministic_then_ai_unknown"}:
            return Admission(False, None, "undeclared")
        check = self._checks.get(check_id)
        if check is None or check.item_id != self.item_id:
            return Admission(False, None, "unowned")
        binding = next((item for item in self._bindings.values() if item.role == "verification"), None)
        if binding is None:
            return Admission(False, None, "role")
        if self._budget is not None and not self._budget.room_for("verification"):
            return Admission(False, None, "budget")
        return Admission(True, binding.model, "admitted")

    def parse_healer_target(self, payload: dict[str, object]) -> dict[str, object] | None:
        """Keep a typed target candidate. A visual, canvas, or guessed target is refused."""

        basis = payload.get("basis")
        if type(basis) is not str or basis != "typed":
            return None
        kind = payload.get("kind")
        if kind is not None and type(kind) is not str:
            return None
        if kind in _VISUAL_BASIS:
            return None
        if type(payload.get("action")) is not str or payload.get("action") == "":
            return None
        if type(payload.get("input")) is not str or type(payload.get("path")) is not str:
            return None
        if type(payload.get("locator")) is not str:
            return None
        named = _text(payload, "role") and _text(payload, "name") and _text(payload, "container")
        located = _text(payload, "resource_id") and _text(payload, "text") and _text(payload, "context")
        if not named and not located:
            return None
        point = payload.get("coordinates")
        if point is not None and (
            type(point) is not list or len(point) != 2 or any(type(item) is not int for item in point)
        ):
            return None
        return payload


def _text(payload: dict[str, object], key: str) -> bool:
    return type(payload.get(key)) is str and payload.get(key) != ""


_VISUAL_BASIS = frozenset({"visual", "canvas", "guess"})


class ModelTransport:
    """The caller supplies a response. This default does not open a network."""

    def complete(self, check_id: str) -> str:
        raise TimeoutError("provider is not connected")


_REPLAY_PURPOSES = frozenset({"trial", "regression"})
_PURPOSE_ROLES: dict[str, frozenset[str]] = {
    "recording": frozenset({"authoring", "maintenance"}),
    "trial": frozenset({"verification"}),
    "regression": frozenset({"verification"}),
}


@dataclass(frozen=True, slots=True)
class AttemptModelPolicy:
    """Immutable attempt policy held on the management server."""

    project_id: UUID
    item_id: str
    purpose: str
    healing_enabled: bool
    max_calls: int
    budget: str
    bindings: tuple[RoleBinding, ...]
    checks: tuple[OwnedCheck, ...]
    episodes: tuple[OwnedEpisode, ...]
    secret_refs: dict[str, SecretRef] = field(default_factory=dict)
    generation: int = 1


@dataclass(frozen=True, slots=True)
class WorkerModelRequest:
    call_id: UUID
    purpose: str
    role: str
    owner_kind: str
    owner_id: str
    binding_revision: int
    sanitized_inputs: tuple[str, ...]
    token_output_limit: int
    deadline: str
    check_id: str | None = None
    episode_id: str | None = None
    generation: int | None = None


@dataclass(frozen=True, slots=True)
class ModelRequestReceipt:
    call_id: UUID
    allowed: bool
    reason: str
    actual_model: str | None
    measurement_status: str
    provider_request_id: str | None
    role: str
    purpose: str
    replayed: bool
    usage: dict[str, object]
    content: str = ""
    item_id: str = ""
    generation: int = 1


class ModelRequestDenied(Exception):
    """Worker model request refused by server policy."""

    def __init__(self, reason: str, *, status: int = 403, provider_dispatched: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.provider_dispatched = provider_dispatched


class ModelRequestConflict(Exception):
    """Idempotency key reused with a different body."""


def build_model_gateway(
    resolver: ServerSecretResolver | None,
    *,
    provider: ProviderHttpPort | None = None,
    operational: bool = False,
) -> "ServerModelGateway":
    """Prefer fixture provider; operational HTTPS stays off unless settings or injection request it."""

    from aiqa.models.provider_http import OperationalProviderHttp

    if provider is not None:
        chosen = provider
    elif operational:
        # Legacy flag: keep disabled until an approved base URL is supplied by settings.
        chosen = OperationalProviderHttp(allow_live=False)
    else:
        chosen = FixtureProviderHttp()
    return ServerModelGateway(provider=chosen, resolver=resolver)


class ServerModelGateway:
    """Admit worker model calls through ModelBroker and a server-only provider port."""

    def __init__(
        self,
        provider: ProviderHttpPort | None = None,
        resolver: ServerSecretResolver | None = None,
    ) -> None:
        self.provider = provider if provider is not None else FixtureProviderHttp()
        self.resolver = resolver
        self._policies: dict[tuple[UUID, str], AttemptModelPolicy] = {}
        self._receipts: dict[str, tuple[str, ModelRequestReceipt]] = {}
        self._attempt_receipts: dict[tuple[UUID, str], list[ModelRequestReceipt]] = {}
        self._ledgers: dict[tuple[UUID, str], dict[str, int]] = {}
        self._usage = UsageLedger()
        self._lock = Lock()

    def register_policy(self, policy: AttemptModelPolicy) -> None:
        self._policies[(policy.project_id, policy.item_id)] = policy
        key = (policy.project_id, policy.item_id)
        if key not in self._ledgers:
            self._ledgers[key] = {
                "authoring": 0,
                "verification": 0,
                "healing": 0,
                "maintenance": 0,
            }

    def ensure_policy(self, policy: AttemptModelPolicy) -> None:
        """Register once. Later recording/replay attempts keep the first sealed policy."""

        key = (policy.project_id, policy.item_id)
        if key in self._policies:
            return
        self.register_policy(policy)

    def handle(
        self,
        worker: WorkerScope,
        request: WorkerModelRequest,
        *,
        project_id: UUID,
        item_id: str,
        idempotency_key: str,
        actor_id: UUID,
        store: object | None = None,
    ) -> ModelRequestReceipt:
        fingerprint = _fingerprint(request, project_id, item_id)
        with self._lock:
            prior = self._receipts.get(idempotency_key)
            if prior is not None:
                if prior[0] != fingerprint:
                    raise ModelRequestConflict("idempotency conflict")
                return ModelRequestReceipt(
                    prior[1].call_id,
                    prior[1].allowed,
                    prior[1].reason,
                    prior[1].actual_model,
                    prior[1].measurement_status,
                    prior[1].provider_request_id,
                    prior[1].role,
                    prior[1].purpose,
                    True,
                    dict(prior[1].usage),
                    prior[1].content,
                    prior[1].item_id,
                    prior[1].generation,
                )
            if store is None:
                receipt = self._admit(worker, request, project_id, item_id, actor_id)
            else:
                with bind_secret_store(store):  # type: ignore[arg-type]
                    receipt = self._admit(worker, request, project_id, item_id, actor_id)
            self._receipts[idempotency_key] = (fingerprint, receipt)
            self._attempt_receipts.setdefault((project_id, item_id), []).append(receipt)
            return receipt

    def receipts_for(self, project_id: UUID, item_id: str) -> tuple[ModelRequestReceipt, ...]:
        """Server-side call receipts owned by one attempt item."""

        with self._lock:
            return tuple(self._attempt_receipts.get((project_id, item_id), ()))

    def usage_for(self, project_id: UUID, item_id: str) -> dict[str, object]:
        with self._lock:
            return self._usage_for_unlocked(project_id, item_id)

    def usage_snapshot(self) -> dict[str, object]:
        with self._lock:
            totals = {"authoring": 0, "verification": 0, "healing": 0, "maintenance": 0}
            for ledger in self._ledgers.values():
                for role, count in ledger.items():
                    totals[role] = totals.get(role, 0) + count
            return {
                "authoring_calls": totals["authoring"],
                "verification_calls": totals["verification"],
                "healing_calls": totals["healing"],
                "maintenance_calls": totals["maintenance"],
                "reserved_cost": "0",
                "provider_calls": getattr(self.provider, "call_count", 0),
                "provider_kind": getattr(self.provider, "kind", "unknown"),
            }

    def _usage_for_unlocked(self, project_id: UUID, item_id: str) -> dict[str, object]:
        ledger = self._ledgers.get(
            (project_id, item_id),
            {"authoring": 0, "verification": 0, "healing": 0, "maintenance": 0},
        )
        return {
            "authoring_calls": ledger["authoring"],
            "verification_calls": ledger["verification"],
            "healing_calls": ledger["healing"],
            "maintenance_calls": ledger["maintenance"],
            "reserved_cost": "0",
            "provider_calls": sum(ledger.values()),
            "item_id": item_id,
        }

    def _admit(
        self,
        worker: WorkerScope,
        request: WorkerModelRequest,
        project_id: UUID,
        item_id: str,
        actor_id: UUID,
    ) -> ModelRequestReceipt:
        if project_id not in worker.permitted_projects:
            raise ModelRequestDenied("project")
        if request.purpose not in worker.permitted_purposes:
            raise ModelRequestDenied("forged_purpose")
        policy = self._policies.get((project_id, item_id))
        if policy is None:
            raise ModelRequestDenied("policy", status=404)
        if request.purpose != policy.purpose:
            raise ModelRequestDenied("forged_purpose")
        if request.generation is not None and int(request.generation) != int(policy.generation):
            raise ModelRequestDenied("stale_generation")
        allowed_roles = set(_PURPOSE_ROLES.get(policy.purpose, frozenset()))
        if policy.healing_enabled:
            allowed_roles.add("healing")
        if request.role == "healing" and not policy.healing_enabled:
            raise ModelRequestDenied("healing_off")
        if request.role == "authoring" and policy.purpose in _REPLAY_PURPOSES:
            raise ModelRequestDenied("replay_actor")
        if request.role not in allowed_roles:
            raise ModelRequestDenied("purpose_role")
        ledger = self._ledgers.setdefault(
            (project_id, item_id),
            {"authoring": 0, "verification": 0, "healing": 0, "maintenance": 0},
        )
        used = sum(ledger.values())
        if used >= policy.max_calls:
            raise ModelRequestDenied("quota")
        if request.role == "healing" and ledger.get("healing", 0) >= 2:
            raise ModelRequestDenied("quota")

        broker = ModelBroker(policy.item_id, policy.bindings, policy.checks, policy.episodes)
        remaining = max(0, policy.max_calls - used)
        budget = CallBudget(budget=policy.budget, max_calls=remaining)
        broker.attach_budget(budget)
        model_request = ModelRequest(
            request.call_id,
            request.role,
            request.owner_kind,
            request.owner_id,
            request.binding_revision,
            request.sanitized_inputs,
            request.token_output_limit,
            request.deadline,
            request.check_id,
            request.episode_id,
        )
        admission = broker.admit(model_request)
        if not admission.allowed:
            reason = "quota" if admission.reason == "budget" else admission.reason
            raise ModelRequestDenied(reason)

        binding = next(
            item
            for item in policy.bindings
            if item.role == request.role and item.revision == request.binding_revision
        )
        secret_ref = policy.secret_refs.get(request.role)
        if secret_ref is None:
            raise ModelRequestDenied("secret")
        if self.resolver is None:
            raise ModelRequestDenied("secret", status=503)
        try:
            secret = self.resolver.resolve_for_server(
                secret_ref, RuntimeScope(project_id, actor_id)
            )
        except SecretScopeDenied as exc:
            raise ModelRequestDenied("secret") from exc
        except SecretUnavailable as exc:
            raise ModelRequestDenied("secret", status=503) from exc

        try:
            result = self.provider.complete(
                model=binding.model,
                role=request.role,
                secret=secret.value,
                sanitized_inputs=request.sanitized_inputs,
                token_output_limit=request.token_output_limit,
            )
        except ProviderHttpError as exc:
            # A completed HTTP failure or uncertain send still consumes a call.
            broker.meter(model_request)
            ledger[request.role] = ledger.get(request.role, 0) + 1
            raise ModelRequestDenied(exc.reason, status=exc.status or 502, provider_dispatched=True) from exc
        except TimeoutError as exc:
            broker.meter(model_request)
            ledger[request.role] = ledger.get(request.role, 0) + 1
            raise ModelRequestDenied("provider_timeout", status=504, provider_dispatched=True) from exc
        broker.meter(model_request)
        ledger[request.role] = ledger.get(request.role, 0) + 1
        token = bind_usage(self._usage)
        try:
            record_model_usage(
                ModelCallSettlement(
                    request.call_id,
                    request.role,
                    True,
                    result.provider_request_id,
                    result.http_status,
                    result.actual_model,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    "metered",
                )
            )
        finally:
            reset_usage(token)

        usage = self._usage_for_unlocked(project_id, item_id)
        receipt = ModelRequestReceipt(
            request.call_id,
            True,
            "admitted",
            result.actual_model,
            "metered",
            result.provider_request_id,
            request.role,
            request.purpose,
            False,
            usage,
            result.content,
            item_id,
            policy.generation,
        )
        cleaned = scrub_worker_dto(
            {
                "call_id": str(receipt.call_id),
                "allowed": receipt.allowed,
                "reason": receipt.reason,
                "actual_model": receipt.actual_model,
                "measurement_status": receipt.measurement_status,
                "provider_request_id": receipt.provider_request_id,
                "role": receipt.role,
                "purpose": receipt.purpose,
                "replayed": receipt.replayed,
                "usage": receipt.usage,
                "content": receipt.content,
                "secret": secret.value,
                "api_key": secret.value,
            }
        )
        assert isinstance(cleaned, dict)
        assert cleaned.get("secret") is None
        assert cleaned.get("api_key") is None
        return receipt


def recording_authoring_policy(
    project_id: UUID,
    item_id: str,
    secret_ref: SecretRef,
    *,
    model: str = "ops-author",
    max_calls: int = 2,
    generation: int = 1,
) -> AttemptModelPolicy:
    """Default recording policy: authoring only, secret ref resolved on the server."""

    return AttemptModelPolicy(
        project_id=project_id,
        item_id=item_id,
        purpose="recording",
        healing_enabled=False,
        max_calls=max_calls,
        budget="2.00",
        bindings=(RoleBinding("authoring", 1, model, str(secret_ref.ref_id)),),
        checks=(),
        episodes=(),
        secret_refs={"authoring": secret_ref},
        generation=generation,
    )


class WorkerModelCallBridge:
    """Connect verifier/healer completes to ServerModelGateway (worker model-requests)."""

    def __init__(
        self,
        gateway: ServerModelGateway,
        worker: WorkerScope,
        *,
        project_id: UUID,
        item_id: str,
        actor_id: UUID,
        purpose: str,
        store: object | None = None,
        binding_revision: int = 1,
        force_timeout: bool = False,
    ) -> None:
        self.gateway = gateway
        self.worker = worker
        self.project_id = project_id
        self.item_id = item_id
        self.actor_id = actor_id
        self.purpose = purpose
        self.store = store
        self.binding_revision = binding_revision
        self.force_timeout = force_timeout
        self.calls = 0
        self.roles: list[str] = []
        self._seq = 0

    def complete_role(
        self,
        role: str,
        *,
        check_id: str | None = None,
        episode_id: str | None = None,
        owner_kind: str | None = None,
        owner_id: str | None = None,
    ) -> str:
        self.calls += 1
        self.roles.append(role)
        if self.force_timeout:
            raise TimeoutError("timed out")
        self._seq += 1
        kind = owner_kind if owner_kind is not None else ("check" if check_id else "episode")
        owner = owner_id if owner_id is not None else (check_id or episode_id or self.item_id)
        request = WorkerModelRequest(
            call_id=uuid4(),
            purpose=self.purpose,
            role=role,
            owner_kind=kind,
            owner_id=owner,
            binding_revision=self.binding_revision,
            sanitized_inputs=("ok",),
            token_output_limit=16,
            deadline="2099-01-01T00:00:00+00:00",
            check_id=check_id,
            episode_id=episode_id,
        )
        receipt = self.gateway.handle(
            self.worker,
            request,
            project_id=self.project_id,
            item_id=self.item_id,
            idempotency_key=f"verify-heal-{self.item_id}-{self._seq}-{role}",
            actor_id=self.actor_id,
            store=self.store,
        )
        return receipt.content

    def as_verifier_transport(self) -> ModelTransport:
        bridge = self

        class _Transport(ModelTransport):
            def __init__(self) -> None:
                self.calls = 0

            def complete(self, check_id: str) -> str:
                self.calls += 1
                return bridge.complete_role(
                    "verification",
                    check_id=check_id,
                    owner_kind="check",
                    owner_id=check_id,
                )

        return _Transport()


def _fingerprint(request: WorkerModelRequest, project_id: UUID, item_id: str) -> str:
    return "|".join(
        (
            str(project_id),
            item_id,
            str(request.call_id),
            request.purpose,
            request.role,
            request.owner_kind,
            request.owner_id,
            str(request.binding_revision),
            ",".join(request.sanitized_inputs),
            str(request.token_output_limit),
            request.deadline,
            request.check_id or "",
            request.episode_id or "",
            "" if request.generation is None else str(request.generation),
        )
    )
