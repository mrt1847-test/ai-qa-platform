"""One admission point for model roles, checks, and episodes. This does not call a provider."""

from __future__ import annotations

from dataclasses import dataclass

from aiqa.contracts.models import MODEL_ROLES, ModelRequest, OwnedCheck, OwnedEpisode, RoleBinding


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
        if basis in _VISUAL_BASIS or basis != "typed":
            return None
        if payload.get("kind") in _VISUAL_BASIS:
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
