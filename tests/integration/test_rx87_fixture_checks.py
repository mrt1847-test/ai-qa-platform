"""Fixture checks are not a product verdict and do not spend the server model gate."""
import sqlite3

from aiqa.contracts.checks import CheckSpec
from test_rx86_healing_execution import healing_execution, healing_metadata
from test_rx87_claim_off import _off_claim
from test_rx_34 import _replay
from ux_support import ux_app


def test_fixture_checks_match_a_zero_server_model_gate(healing_execution, tmp_path):
    claim = _off_claim(healing_execution)
    handler, calls = _replay(tmp_path)
    handler.context.checks = (CheckSpec("check-1", "text", "로그인됨", subject="com.app:id/ok"),)
    claim["snapshot"]["serial"] = handler.context.expected_serial
    result = handler.handle(claim)
    worker_calls = handler.authoring_calls_seen + handler.verifier_calls + handler.healer_calls
    with sqlite3.connect(healing_execution["database"]) as db:
        server_calls = db.execute("SELECT COUNT(*) FROM model_call_facts").fetchone()[0]
    assert result.outcome == "completed" and result.actions == len(calls) == 1
    assert handler.stopped_reason != "check_failed" and handler.original_failure == ""
    assert result.check_results == ()
    assert worker_calls == server_calls == 0
