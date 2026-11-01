"""Series and strict cohort keys. A later observation is not written into the past."""

from __future__ import annotations

from dataclasses import dataclass

from aiqa.contracts.reports import CaseRunFacts
from aiqa.domain.hashing import SCHEMA_VERSION, canonical_hash


@dataclass(frozen=True, slots=True)
class Fingerprint:
    schema_version: str
    value: str


def compute_series_key(facts: CaseRunFacts) -> Fingerprint:
    """Hash the planned comparison axes. Expected changes leave the old series."""

    return _fingerprint(_series_body(facts))


def compute_strict_cohort_key(facts: CaseRunFacts, as_of: int) -> Fingerprint:
    """Hash the series plus the actual axes visible at as_of."""

    if type(as_of) is not int:
        raise ValueError("as_of is invalid")
    body = _series_body(facts)
    body.update(
        {
            "browser": facts.browser,
            "device_os": facts.device_os,
            "engine_patch": facts.engine_patch,
            "healing_policy_hash": facts.healing_policy_hash,
            "healing_requested": facts.healing_requested,
            "lock_hash": facts.lock_hash,
            "model_prompt": facts.model_prompt,
            "model_status": facts.model_status,
            "package_hash": facts.package_hash,
            "runtime_ref": facts.runtime_ref,
            "verifier_binding": facts.verifier_binding,
            "verifier_method": facts.verifier_method,
            "viewport_dpr": facts.viewport_dpr,
        }
    )
    if facts.actual_build_seq is not None and facts.actual_build_seq <= as_of:
        body["actual_build"] = facts.actual_build
    return _fingerprint(body)


def _series_body(facts: CaseRunFacts) -> dict[str, str]:
    return {
        "case_id": facts.case_id,
        "data_fingerprint": facts.data_fingerprint,
        "env_profile_revision": facts.env_profile_revision,
        "oracle_policy": facts.oracle_policy,
        "project_id": facts.project_id,
        "target_kind": facts.target_kind,
        "verification_digest": facts.verification_digest,
    }


def _fingerprint(body: dict[str, str]) -> Fingerprint:
    return Fingerprint(SCHEMA_VERSION, canonical_hash(body, SCHEMA_VERSION))
