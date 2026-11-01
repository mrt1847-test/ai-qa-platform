"""Deterministic checks. An engine completion message does not satisfy a check."""

from __future__ import annotations

from aiqa.contracts.actions import Observation
from aiqa.contracts.checks import CheckSpec
from aiqa.validation.web import Validator


def test_w17_02() -> None:
    validator = Validator()
    equal = validator.evaluate(_check("text", "로그인됨"), _observation("web", _web("로그인됨")))
    mismatch = validator.evaluate(_check("text", "로그인됨"), _observation("web", _web("실패")))
    missing = validator.evaluate(_check("text", "로그인됨"), None)
    done = validator.evaluate(
        _check("text", "로그인됨"),
        _observation("web", '{"nodes":[]}', messages=("engine-done",)),
    )
    android = validator.evaluate(
        _check("text", "로그인됨", "name"),
        _observation("android", "", '{"nodes":[{"resource_id":"name","text":"로그인됨","state":"enabled"}]}'),
    )
    bypassed = validator.evaluate(
        CheckSpec("path-1", "path", "login,submit", subject="로그인됨"),
        _observation("web", _web("로그인됨"), messages=("engine-done",)),
    )
    followed = validator.evaluate(
        CheckSpec("path-2", "path", "login,submit", subject="로그인됨"),
        _observation("web", _web("로그인됨"), messages=("login", "submit")),
    )
    observed = {
        "equal": equal.status,
        "mismatch": mismatch.status,
        "missing_observation": missing.status,
        "engine_done_is_pass": done.status == "satisfied",
    }
    assert android.status == "satisfied"
    assert bypassed.status == "violated" and bypassed.reason == "path was bypassed"
    assert followed.status == "satisfied"
    assert observed == {
        "equal": "satisfied",
        "mismatch": "violated",
        "missing_observation": "unknown",
        "engine_done_is_pass": False,
    }


def _check(kind: str, expected: str, subject: str = "#login") -> CheckSpec:
    return CheckSpec("check-1", kind, expected, subject=subject)


def _web(text: str) -> str:
    return '{"nodes":[{"locator":"#login","text":"' + text + '","value":"ada","state":"visible"}]}'


def _observation(platform: str, dom: str, stdout: str = "", messages: tuple[str, ...] = ()) -> Observation:
    return Observation("obs-1", "2026-11-01T00:00:00+00:00", None, b"", dom, stdout, messages, "", True, platform)


def test_w17_03() -> None:
    from aiqa.contracts.jobs import ControlDecision
    from aiqa.contracts.models import OwnedCheck, RoleBinding
    from aiqa.domain.verdicts import FailureLatch
    from aiqa.models.broker import ModelBroker, ModelTransport
    from aiqa.validation.visual import evaluate_check_policy

    class _Script(ModelTransport):
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, check_id: str) -> str:
            self.calls += 1
            return "not-json"

    class _Allow:
        def checkpoint(self) -> ControlDecision:
            return ControlDecision(True, "before_model")

        def allow_model_action(self, *, late: bool) -> ControlDecision:
            return ControlDecision(not late, "before_model")

    transport = _Script()
    broker = ModelBroker("item-1", (RoleBinding("verification", 1, "fixture-check", "ref-1"),), (OwnedCheck("check-1", "item-1"),), ())
    control = _Allow()
    violated = evaluate_check_policy(
        CheckSpec("check-1", "text", "로그인됨", subject="#login", method="deterministic_then_ai_unknown", allow_unknown_supplement=True),
        _observation("web", _web("실패")),
        control,
        broker=broker,
        transport=transport,
    )
    violated_calls = transport.calls
    undeclared = evaluate_check_policy(
        CheckSpec("check-1", "text", "로그인됨", subject="#login", method="guess"),
        _observation("web", _web("로그인됨")),
        control,
        broker=broker,
        transport=transport,
    )
    undeclared_calls = transport.calls - violated_calls
    parsed = evaluate_check_policy(
        CheckSpec("check-1", "text", "로그인됨", subject="#login", method="ai_visual"),
        _observation("web", _web("로그인됨")),
        control,
        broker=broker,
        transport=transport,
    )
    latch = FailureLatch()
    required = evaluate_check_policy(
        CheckSpec("check-1", "text", "로그인됨", subject="#login", required=True),
        _observation("web", _web("실패")),
        control,
        broker=broker,
        transport=transport,
        latch=latch,
    )
    later = evaluate_check_policy(
        CheckSpec("check-1", "text", "로그인됨", subject="#login", required=True),
        _observation("web", _web("로그인됨")),
        control,
        broker=broker,
        transport=transport,
        latch=latch,
    )
    observed = {
        "violated_supplement_calls": violated_calls,
        "undeclared_ai_calls": undeclared_calls,
        "parse_failure": parsed.status,
        "required_violation_final": required.latch,
    }
    assert violated.status == "violated" and undeclared.reason == "method is not declared"
    assert transport.calls == 1 and parsed.reason == "parse failed"
    assert later.latch == "FAIL" and later.status == "satisfied"
    class _Timeout(ModelTransport):
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, check_id: str) -> str:
            self.calls += 1
            raise TimeoutError("timed out")

    class _Hold:
        def checkpoint(self) -> ControlDecision:
            return ControlDecision(False, "budget")

        def allow_model_action(self, *, late: bool) -> ControlDecision:
            return ControlDecision(False, "budget")

    timed = _Timeout()
    timeout = evaluate_check_policy(
        CheckSpec("check-1", "text", "로그인됨", subject="#login", method="ai_visual"),
        _observation("web", _web("로그인됨")),
        control,
        broker=broker,
        transport=timed,
    )
    budget = evaluate_check_policy(
        CheckSpec("check-1", "text", "로그인됨", subject="#login", method="ai_visual"),
        _observation("web", _web("로그인됨")),
        _Hold(),
        broker=broker,
        transport=timed,
    )
    occluded = evaluate_check_policy(
        CheckSpec("check-1", "text", "로그인됨", subject="#login", method="ai_visual"),
        _observation("web", _web("로그인됨"), messages=("occluded",)),
        control,
        broker=broker,
        transport=timed,
    )
    class _Reply(ModelTransport):
        def complete(self, check_id: str) -> str:
            return '{"status":"unknown","reason":"screen was unread"}'

    supplemented = evaluate_check_policy(
        CheckSpec("check-1", "text", "로그인됨", subject="#login", method="deterministic_then_ai_unknown", allow_unknown_supplement=True),
        _observation("web", '{"nodes":[]}'),
        control,
        broker=broker,
        transport=_Reply(),
    )
    assert timeout.status == "unknown" and timeout.reason == "timed out" and timed.calls == 1
    assert budget.status == "unknown" and budget.reason == "budget is missing" and timed.calls == 1
    assert occluded.status == "unknown" and occluded.reason == "observation is occluded" and timed.calls == 1
    assert supplemented.status == "unknown" and supplemented.reason == "screen was unread"
    assert observed == {
        "violated_supplement_calls": 0,
        "undeclared_ai_calls": 0,
        "parse_failure": "unknown",
        "required_violation_final": "FAIL",
    }
