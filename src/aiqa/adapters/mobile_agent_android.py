"""Mobile-Agent Android recording adapter. Replay never calls an authoring provider."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID, uuid4

from aiqa.contracts.actions import ActionProposal, CaptureGeometry, Observation
from aiqa.contracts.jobs import ControlDecision
from aiqa.contracts.models import ModelRequest, RoleBinding
from aiqa.environments.android_observation import AndroidGeometryError, require_usable_geometry
from aiqa.models.broker import ModelBroker
from aiqa.models.client import ModelClient
from aiqa.replay.android_plan import (
    PlanRejected,
    TypedAndroidAction,
    parse_mobile_agent_action,
    typed_from_upstream,
)
from aiqa.replay.android_runner import (
    AndroidDeterministicDriver,
    AndroidDispatchError,
    AndroidDispatchResult,
    AndroidPreflight,
    GeometryLock,
)
from aiqa.replay.targets import TargetBinding
from aiqa.security.redaction import RedactionError, filter_capture


class MobileAgentRejected(Exception):
    """Sanitization, geometry, parser, or authoring gate refused the step."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AuthoringControl(Protocol):
    def checkpoint(self) -> ControlDecision: ...


@dataclass(frozen=True, slots=True)
class AuthoringReceipt:
    call_id: UUID
    content: str
    allowed: bool
    authoring_calls: int


@dataclass(frozen=True, slots=True)
class RecordingStepResult:
    action: TypedAndroidAction
    dispatch: AndroidDispatchResult
    authoring_calls: int
    provider_calls: int
    before_ref: str | None
    after_ref: str | None


class MobileAgentAndroidAdapter:
    """Sanitize → optional authoring → allowlist parse → typed driver → evidence."""

    def __init__(self) -> None:
        self.provider_calls = 0
        self.authoring_calls = 0

    def before_capture(self, proposal: ActionProposal, observation: Observation) -> Observation:
        if observation.platform != "android" or not observation.capture_ok:
            return replace(observation, capture_ok=False, png=b"")
        return observation

    def sanitize(self, observation: Observation, *, secrets: tuple[str, ...] = ()) -> Observation:
        try:
            require_usable_geometry(observation)
            filter_capture(observation, secrets)
        except AndroidGeometryError as exc:
            raise MobileAgentRejected("geometry is invalid") from exc
        except RedactionError as exc:
            raise MobileAgentRejected("sanitize_failed") from exc
        return observation

    def author(
        self,
        *,
        broker: ModelBroker,
        control: AuthoringControl,
        fixture_response: str,
        item_id: str | None = None,
    ) -> AuthoringReceipt:
        """Recording-only authoring path. Metered through ModelBroker; response is fixture text."""

        client = ModelClient(broker)
        request = ModelRequest(
            uuid4(),
            "authoring",
            "authoring",
            item_id or broker.item_id,
            1,
            ("sanitized",),
            64,
            "2099-01-01T00:00:00+00:00",
        )
        response = client.invoke(request, control)  # type: ignore[arg-type]
        if not response.allowed:
            raise MobileAgentRejected("authoring refused")
        self.authoring_calls = broker.authoring_calls
        self.provider_calls += 1
        return AuthoringReceipt(response.call_id, fixture_response, True, broker.authoring_calls)

    def parse_to_typed(
        self,
        response: str,
        observation: Observation,
        *,
        secrets: tuple[str, ...] = (),
    ) -> TypedAndroidAction:
        try:
            geometry = require_usable_geometry(observation)
            parsed = parse_mobile_agent_action(response)
            return typed_from_upstream(parsed, geometry, secrets=secrets)
        except AndroidGeometryError as exc:
            raise MobileAgentRejected("geometry is invalid") from exc
        except PlanRejected as exc:
            raise MobileAgentRejected(exc.reason) from exc

    def record_step(
        self,
        *,
        observation: Observation,
        after: Observation,
        fixture_response: str,
        broker: ModelBroker,
        control: AuthoringControl,
        driver: AndroidDeterministicDriver,
        secrets: tuple[str, ...] = (),
    ) -> RecordingStepResult:
        """One recording tap path. Worker finish leaves review pending; never auto-approves."""

        before = self.sanitize(observation, secrets=secrets)
        authored = self.author(broker=broker, control=control, fixture_response=fixture_response)
        action = self.parse_to_typed(authored.content, before, secrets=secrets)
        dispatch = self._dispatch(driver, before, after, action)
        return RecordingStepResult(
            action,
            dispatch,
            authored.authoring_calls,
            self.provider_calls,
            dispatch.before_ref,
            dispatch.after_ref,
        )

    def replay_step(
        self,
        *,
        plan_response: str,
        observation: Observation,
        after: Observation,
        driver: AndroidDeterministicDriver,
        secrets: tuple[str, ...] = (),
        broker: ModelBroker | None = None,
    ) -> RecordingStepResult:
        """Replay uses the sealed plan text only. Authoring provider calls stay 0."""

        before_calls = 0 if broker is None else broker.authoring_calls
        before = self.sanitize(observation, secrets=secrets)
        action = self.parse_to_typed(plan_response, before, secrets=secrets)
        dispatch = self._dispatch(driver, before, after, action)
        after_calls = 0 if broker is None else broker.authoring_calls
        if after_calls != before_calls:
            raise MobileAgentRejected("replay authoring provider call is forbidden")
        return RecordingStepResult(
            action,
            dispatch,
            0,
            0,
            dispatch.before_ref,
            dispatch.after_ref,
        )

    def _dispatch(
        self,
        driver: AndroidDeterministicDriver,
        before: Observation,
        after: Observation,
        action: TypedAndroidAction,
    ) -> AndroidDispatchResult:
        # After rescale, driver locks identity geometry in physical pixels.
        dispatch_before = _physical_identity(before)
        dispatch_after = _physical_identity(after)
        lock = GeometryLock.from_observation(driver.serial, dispatch_before)
        binding = _binding_for(action, lock)
        try:
            return driver.run(
                preflight=AndroidPreflight(),
                binding=binding,
                before=dispatch_before,
                action=action,
                after=dispatch_after,
            )
        except AndroidDispatchError as exc:
            raise MobileAgentRejected(str(exc)) from exc


def recording_broker(item_id: str = "item-1") -> ModelBroker:
    return ModelBroker(
        item_id,
        (RoleBinding("authoring", 1, "fixture-author", "secret-ref"),),
        (),
        (),
    )


def _physical_identity(observation: Observation) -> Observation:
    geo = observation.geometry
    if geo is None:
        raise MobileAgentRejected("geometry is invalid")
    locked = CaptureGeometry(
        geo.physical_width,
        geo.physical_height,
        geo.physical_width,
        geo.physical_height,
        "identity",
        geo.rotation,
        geo.content_bounds,
    )
    return replace(observation, geometry=locked)


def _binding_for(action: TypedAndroidAction, lock: GeometryLock) -> TargetBinding:
    if action.kind == "tap":
        return TargetBinding(
            "coordinate",
            x=action.x,
            y=action.y,
            approved=True,
            approved_rotation=lock.rotation,
            approved_width=lock.width,
            approved_height=lock.height,
            approved_bounds=(0, 0, lock.width, lock.height),
        )
    # Non-coordinate actions still need an approved geometry lock surface.
    return TargetBinding(
        "coordinate",
        x=0,
        y=0,
        approved=True,
        approved_rotation=lock.rotation,
        approved_width=lock.width,
        approved_height=lock.height,
        approved_bounds=(0, 0, lock.width, lock.height),
    )
