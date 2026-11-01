"""Side-by-side run comparison. This does not rewrite an original result."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from aiqa.contracts.reports import CaseRunFacts
from aiqa.domain.cohorts import compute_series_key, compute_strict_cohort_key
from aiqa.store.models import Actor, Transaction

_LABELS = {
    "FAIL": "실패",
    "BLOCKED": "차단",
    "INCONCLUSIVE": "불명",
    "SKIPPED": "건너뜀",
    "CANCELLED": "취소",
    "NOT_RUN": "미실행",
}


class ComparisonMissing(Exception):
    """One of the runs is not in this project."""


class ComparisonRejected(Exception):
    """The comparison cannot be read."""


@dataclass(frozen=True, slots=True)
class ComparisonSide:
    case_run_id: str
    result_label: str
    environment: str
    build: str
    data: str
    expected: str
    verification: str
    healing: str
    step: str
    observed: str
    duration: str
    cost: str
    capture: str


@dataclass(frozen=True, slots=True)
class ComparisonPair:
    case_id: str
    data: str
    target: str
    kind: str
    separate_series: bool
    condition_fields: tuple[str, ...]
    baseline: ComparisonSide | None
    candidate: ComparisonSide | None


@dataclass(frozen=True, slots=True)
class ExecutionComparison:
    baseline_id: str
    candidate_id: str
    pairs: tuple[ComparisonPair, ...]
    mixed: bool
    constituent_count: int
    confirmed_improvements: int
    confirmed_regressions: int
    original_fail_preserved: bool


def compare_executions(
    tx: Transaction, actor: Actor, project_id: UUID, baseline_id: UUID, candidate_id: UUID, as_of: int
) -> ExecutionComparison:
    """Align two runs by case, data, and target. A different strict cohort stays marked."""

    if actor.project_scope != project_id or type(as_of) is not int:
        raise ComparisonRejected("comparison is invalid")
    if baseline_id == candidate_id:
        raise ComparisonRejected("comparison is invalid")
    baseline = _load(tx, project_id, baseline_id)
    candidate = _load(tx, project_id, candidate_id)
    if baseline is None or candidate is None:
        raise ComparisonMissing("execution was not found")
    keys = sorted(set(baseline) | set(candidate))
    pairs: list[ComparisonPair] = []
    strict_keys: set[str] = set()
    for key in keys:
        left = baseline.get(key)
        right = candidate.get(key)
        for side in (left, right):
            if side is None:
                continue
            facts = side["facts"]
            assert isinstance(facts, CaseRunFacts)
            strict_keys.add(compute_strict_cohort_key(facts, as_of).value)
        pairs.append(_pair(key, left, right))
    preserved = any(item["result"] == "FAIL" for item in baseline.values())
    return ExecutionComparison(
        str(baseline_id),
        str(candidate_id),
        tuple(pairs),
        len(strict_keys) > 1,
        len(strict_keys),
        0,
        0,
        preserved,
    )


def _pair(
    key: tuple[str, str, str],
    left: dict[str, object] | None,
    right: dict[str, object] | None,
) -> ComparisonPair:
    fields: list[str] = []
    separate = False
    if left is not None and right is not None:
        if str(left["environment"]) != str(right["environment"]):
            fields.append("environment")
        if str(left["build"]) != str(right["build"]):
            fields.append("build")
        if str(left["expected"]) != str(right["expected"]):
            fields.append("expected")
        if str(left["healing"]) != str(right["healing"]):
            fields.append("healing")
        left_facts = left["facts"]
        right_facts = right["facts"]
        assert isinstance(left_facts, CaseRunFacts) and isinstance(right_facts, CaseRunFacts)
        separate = compute_series_key(left_facts).value != compute_series_key(right_facts).value
    kind = _kind(left, right, fields)
    return ComparisonPair(
        key[0],
        key[1],
        key[2],
        kind,
        separate,
        tuple(fields),
        None if left is None else _side(left),
        None if right is None else _side(right),
    )


def _kind(left: dict[str, object] | None, right: dict[str, object] | None, fields: list[str]) -> str:
    if left is None:
        return "added"
    if right is None:
        return "removed"
    if str(left["result"]) == "FAIL" and str(right["result"]) == "FAIL":
        return "continued_failure"
    if fields or str(left["result"]) != str(right["result"]) or str(left["verification"]) != str(right["verification"]):
        return "changed"
    return "same"


def _side(row: dict[str, object]) -> ComparisonSide:
    return ComparisonSide(
        str(row["case_run_id"]),
        _label(str(row["result"])),
        str(row["environment"]),
        str(row["build"]),
        str(row["data"]),
        str(row["expected"]),
        str(row["verification"]),
        str(row["healing"]),
        str(row["step"]),
        str(row["observed"]),
        str(row["duration"]),
        str(row["cost"]),
        str(row["capture"]),
    )


def _label(code: str) -> str:
    if code in _LABELS:
        return _LABELS[code]
    if code == "":
        return "진행"
    return "만족"


def _load(tx: Transaction, project_id: UUID, execution_id: UUID) -> dict[tuple[str, str, str], dict[str, object]] | None:
    found = tx.connection.execute(
        "SELECT 1 FROM executions WHERE project_id = ? AND execution_id = ?",
        (str(project_id), str(execution_id)),
    ).fetchone()
    if found is None:
        return None
    rows = tx.connection.execute(
        """
        SELECT case_runs.case_run_id, case_runs.case_id, case_versions.verification_digest,
               jobs.limits, item_finalizations.core_result
        FROM case_runs
        JOIN case_versions
          ON case_versions.project_id = case_runs.project_id
         AND case_versions.version_id = case_runs.case_version_id
        LEFT JOIN jobs
          ON jobs.project_id = case_runs.project_id
         AND jobs.case_run_id = case_runs.case_run_id
        LEFT JOIN item_finalizations
          ON item_finalizations.project_id = case_runs.project_id
         AND item_finalizations.case_run_id = case_runs.case_run_id
        WHERE case_runs.project_id = ? AND case_runs.execution_id = ?
        ORDER BY case_runs.rowid
        """,
        (str(project_id), str(execution_id)),
    ).fetchall()
    aligned: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in rows:
        limits = _object(row[3])
        data = str(limits.get("data_fingerprint", ""))
        target = str(limits.get("target_kind", "web"))
        case_id = str(row[1])
        result = "" if row[4] is None else str(row[4])
        environment = str(limits.get("environment_revision_id", ""))
        build = str(limits.get("build_id", ""))
        expected = str(limits.get("oracle_policy", ""))
        healing = "on" if limits.get("healing_requested") == "on" else "off"
        facts = CaseRunFacts(
            result if result != "" else "running",
            project_id=str(project_id),
            case_id=case_id,
            verification_digest=str(row[2]),
            target_kind=target,
            env_profile_revision=environment,
            data_fingerprint=data,
            oracle_policy=expected,
            actual_build=build,
            model_status=str(limits.get("model_status", "unknown")),
            healing_requested=healing,
            item_id=str(row[0]),
        )
        aligned[(case_id, data, target)] = {
            "case_run_id": str(row[0]),
            "result": result,
            "environment": environment,
            "build": build,
            "data": data,
            "expected": expected,
            "verification": str(row[2]),
            "healing": healing,
            "step": str(limits.get("step_id", "")),
            "observed": str(limits.get("observed", "")),
            "duration": "" if limits.get("duration_ms") is None else str(limits.get("duration_ms")),
            "cost": _cost(tx, project_id, str(row[0])),
            "capture": _capture(tx, project_id, str(row[0])),
            "facts": facts,
        }
    return aligned


def _cost(tx: Transaction, project_id: UUID, case_run_id: str) -> str:
    rows = tx.connection.execute(
        """
        SELECT amount FROM usage_adjustments
        WHERE project_id = ? AND case_run_id = ? AND measurement_status = 'measured'
        """,
        (str(project_id), case_run_id),
    ).fetchall()
    if rows == []:
        return "없음"
    total = sum((Decimal(str(row[0])) for row in rows), Decimal("0"))
    return f"{total.quantize(Decimal('0.01'))}"


def _capture(tx: Transaction, project_id: UUID, case_run_id: str) -> str:
    row = tx.connection.execute(
        """
        SELECT COUNT(*)
        FROM jobs
        JOIN attempts
          ON attempts.project_id = jobs.project_id
         AND attempts.job_id = jobs.job_id
        JOIN artifact_refs
          ON artifact_refs.project_id = attempts.project_id
         AND artifact_refs.attempt_id = attempts.attempt_id
        WHERE jobs.project_id = ? AND jobs.case_run_id = ?
        """,
        (str(project_id), case_run_id),
    ).fetchone()
    count = 0 if row is None else int(row[0])
    return "있음" if count else "화면이 없습니다"


def _object(raw: object) -> dict[str, object]:
    if raw is None:
        return {}
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return parsed if type(parsed) is dict else {}
