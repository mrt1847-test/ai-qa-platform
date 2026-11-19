"""Web replay consumes the claim policy and does not reclick an unknown dispatch."""
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from aiqa.adapters.cuawright_web import CuawrightWebAdapter, local_web_fixture
from aiqa.healing.targets import HealingProposal, TargetCandidate
from aiqa.replay.driver import ApprovedWebPackage
from aiqa.worker.control import RemoteLeaseGuard
from aiqa.worker.dispatch_journal import DispatchJournal
from aiqa.worker.local_page import local_page_from_fixture_html
from aiqa.worker.spool import EvidenceSpool
from aiqa.worker.web_isolation_backend import IsolationConfig, WebIsolationGate, fixture_backend
from aiqa.worker.web_jobs import WebReplayContext, WebReplayHandler
from test_rx_34 import _observation

ORIGIN = "https://app.example.test"


def _handler(tmp_path: Path, *, client=None):
    now = datetime(2026, 11, 19, tzinfo=timezone.utc)
    fixture = local_web_fixture(origin=ORIGIN)
    gate = WebIsolationGate(IsolationConfig(backend=fixture_backend(allowed_origins=(ORIGIN,)), proof_secret=b"rx88-fixture-proof!!!!"))
    page = local_page_from_fixture_html(origin=ORIGIN, html=fixture.page_html)
    element = {"role":"button","name":"Save","container":"bar","resource_id":"com.example:id/save","text":"Save","context":"main","locator":"#save","visible":True,"enabled":True,"bounds":[0,0,4,4]}
    from dataclasses import replace
    before = _observation()
    before = replace(before, dom=json.dumps({"elements":[element]}))
    return WebReplayHandler(
        adapter=CuawrightWebAdapter(),
        gate=gate,
        guard=RemoteLeaseGuard(),
        journal=DispatchJournal(tmp_path / "journal.jsonl"),
        spool=EvidenceSpool(tmp_path / "spool"),
        context=WebReplayContext(
            approved=ApprovedWebPackage("sha256:"+"a"*64, "lock-1", ORIGIN),
            bundle_source=fixture.trajectory,
            before=before,
            after=_observation(),
            proof=gate.issue_proof(now=now),
            now=now,
            healing_client=client,
            runner=page.as_runner(),
        ),
    )


def _claim(**extra):
    snapshot = {"purpose":"regression","origin":ORIGIN,"revision":"lock-1","replay_package_hash":"sha256:"+"a"*64,"approved_digest":"sha256:"+"a"*64}
    snapshot.update(extra)
    return {"attempt_id":str(uuid4()),"snapshot":snapshot}


def _enable(monkeypatch, enabled=True):
    monkeypatch.setattr("aiqa.worker.healing_pin.resolve_claim_healing_pin", lambda snapshot: type("Pin", (), {"enabled":enabled,"policy":None,"binding":{"role":"healing"}})())


class Client:
    def __init__(self, reason, calls=1):
        self.reason = reason
        self.calls = calls
    def lookup(self, **kwargs):
        return self.reason
    def reserve(self, **kwargs):
        return type("Receipt", (), {"eligible":self.calls>0,"reserved_calls":self.calls})()
    def proposal(self, **kwargs):
        candidate = TargetCandidate("button","Save","bar","com.example:id/save","Save","main","#save","tap","","ok",(1,1),"typed")
        return HealingProposal("button","Save","bar","com.example:id/save","Save","main","#save","tap","","ok",candidate,True)


def test_on_without_a_client_does_not_start(tmp_path, monkeypatch):
    _enable(monkeypatch)
    handler = _handler(tmp_path)
    result = handler.handle(_claim())
    assert result.actions == 0 and handler.stopped_reason == "healing_runtime_unavailable"
    assert handler.actor_ai_calls == handler.healer_calls == 0


def test_locator_failure_runs_the_original_steps_once(tmp_path, monkeypatch):
    _enable(monkeypatch)
    handler = _handler(tmp_path, client=Client("target_not_found"))
    result = handler.handle(_claim())
    assert result.outcome == "completed" and result.actions == 2
    assert handler.healer_calls == 1 and handler.actor_ai_calls == 0
    assert handler.original_failure == "target_not_found"
    assert handler.package_digest_after == "sha256:"+"a"*64


def test_assertion_failure_and_tight_action_cap_do_not_dispatch(tmp_path, monkeypatch):
    _enable(monkeypatch)
    denied = _handler(tmp_path, client=Client("text_mismatch"))
    denied_result = denied.handle(_claim())
    assert denied_result.actions == 0 and denied.stopped_reason == "replay_rejected" and denied.healer_calls == 0
    capped = _handler(tmp_path, client=Client(None))
    capped_result = capped.handle(_claim(limits={"max_actions":1,"max_model_calls":0,"timeout_seconds":30}))
    assert capped_result.actions == 0 and capped.stopped_reason == "action_budget" and capped.healer_calls == 0


def test_trial_forces_healing_off_even_when_the_pin_is_on(tmp_path, monkeypatch):
    _enable(monkeypatch)
    handler = _handler(tmp_path)
    result = handler.handle(_claim(purpose="trial"))
    assert result.outcome == "completed" and result.actions == 2
    assert handler.healer_calls == handler.actor_ai_calls == 0
