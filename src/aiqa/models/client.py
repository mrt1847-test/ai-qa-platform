"""Model client. Replay text keeps actor 0 and does not carry a key or a provider address."""

from __future__ import annotations

from aiqa.contracts.jobs import ControlDecision
from aiqa.contracts.models import ModelRequest, ModelResponse
from aiqa.models.broker import ModelBroker
from aiqa.models.usage import record_model_usage
from aiqa.store.usage import ModelCallSettlement
from aiqa.worker.control import RunControl


class ModelClient:
    """Send every call through the broker. The replay script has no secret and no network path."""

    def __init__(self, broker: ModelBroker) -> None:
        self.broker = broker

    def invoke(self, request: ModelRequest, control: RunControl) -> ModelResponse:
        decision = control.checkpoint()
        if not isinstance(decision, ControlDecision) or not decision.allowed:
            return _unused(request)
        admission = self.broker.admit(request)
        if not admission.allowed:
            return _unused(request)
        self.broker.meter(request)
        response = ModelResponse(request.call_id, admission.model, "", "metered", True, None)
        _record(request, response, sent=True)
        return response

    def replay_script(self) -> str:
        return "actor=0"


def _unused(request: ModelRequest) -> ModelResponse:
    response = ModelResponse(request.call_id, None, "", "not_used", False, None)
    _record(request, response, sent=False)
    return response


def _record(request: ModelRequest, response: ModelResponse, sent: bool) -> None:
    try:
        record_model_usage(
            ModelCallSettlement(
                request.call_id,
                request.role,
                sent,
                response.provider_request_id,
                None,
                response.actual_model,
                None,
                None,
                None,
                None,
                None,
                None,
                "unreported" if sent else "not_used",
            )
        )
    except LookupError:
        return
