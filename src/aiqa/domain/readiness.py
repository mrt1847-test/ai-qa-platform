"""Separate saved, recordable, trial, review, and formal readiness. No device access."""

from __future__ import annotations

from uuid import uuid4

from aiqa.contracts.cases import (
    CaseDefinition,
    CaseReadiness,
    CaseVersion,
    ReadinessFacts,
    ReadinessReason,
)
from aiqa.domain.hashing import SCHEMA_VERSION, canonical_hash
from aiqa.domain.versions import verification_digest


def compute_case_readiness(version: CaseVersion, facts: ReadinessFacts) -> CaseReadiness:
    reasons: list[ReadinessReason] = []
    definition = version.definition
    ambiguous = definition.objective.strip() == "" or not definition.steps
    has_checks = any(step.expected for step in definition.steps) or bool(definition.final_expected)
    if ambiguous or not has_checks:
        reasons.append(ReadinessReason("DEFINITION_AMBIGUOUS", "definition is incomplete"))
    if not facts.variables_resolved:
        reasons.append(ReadinessReason("VARIABLE_MISSING", "a variable value is missing"))
    if not facts.resources_available:
        reasons.append(ReadinessReason("RESOURCE_UNAVAILABLE", "a required resource is unavailable"))
    if not facts.capability_supported:
        reasons.append(ReadinessReason("CAPABILITY_UNSUPPORTED", "the target capability is unsupported"))
    if not facts.source_complete:
        reasons.append(ReadinessReason("SOURCE_INCOMPLETE", "the recording source is incomplete"))
    if not facts.model_binding_available:
        reasons.append(ReadinessReason("MODEL_BINDING_UNAVAILABLE", "a model binding is unavailable"))
    if not facts.budget_available:
        reasons.append(ReadinessReason("BUDGET_UNAVAILABLE", "the execution budget is unavailable"))
    if not facts.package_ready:
        reasons.append(ReadinessReason("PACKAGE_MISSING", "a ready package is missing"))
    elif not facts.package_valid:
        reasons.append(ReadinessReason("PACKAGE_INVALID", "the package does not match this version"))
    if not facts.evidence_complete:
        reasons.append(ReadinessReason("EVIDENCE_INCOMPLETE", "evidence is incomplete"))
    if not facts.trial_present:
        reasons.append(ReadinessReason("TRIAL_MISSING", "a trial run is missing"))
    elif not facts.trial_clean:
        reasons.append(ReadinessReason("TRIAL_NOT_CLEAN", "the trial run was not clean"))
    elif not facts.trial_passed:
        reasons.append(ReadinessReason("TRIAL_NOT_PASS", "the trial run did not pass"))
    if not facts.review_complete:
        reasons.append(ReadinessReason("REVIEW_INCOMPLETE", "review is incomplete"))
    if facts.approval_revoked:
        reasons.append(ReadinessReason("APPROVAL_REVOKED", "approval was revoked"))
    elif not facts.approval_valid:
        reasons.append(ReadinessReason("APPROVAL_MISSING", "a valid approval is missing"))
    if not facts.scope_match:
        reasons.append(ReadinessReason("SCOPE_MISMATCH", "the version scope does not match"))
    recordable = not ambiguous and facts.variables_resolved and facts.resources_available and facts.capability_supported and facts.source_complete
    replayable = (
        recordable
        and has_checks
        and facts.package_ready
        and facts.package_valid
        and facts.model_binding_available
        and facts.budget_available
        and facts.scope_match
    )
    reviewable = replayable and facts.evidence_complete and facts.trial_present and facts.trial_clean and facts.trial_passed
    formal = reviewable and facts.review_complete and facts.approval_valid and not facts.approval_revoked and facts.scope_match
    return CaseReadiness(
        saved=True,
        recordable=recordable,
        replayable=replayable,
        reviewable=reviewable,
        formal_runnable=formal,
        reasons=tuple(reasons),
    )


def draft_after_meaning_edit(version: CaseVersion, definition: CaseDefinition) -> CaseVersion:
    """Meaning changes become a new draft. The old package and approval stay on the source."""

    digest = verification_digest(definition)
    return CaseVersion(
        id=uuid4(),
        project_id=version.project_id,
        case_id=version.case_id,
        definition=definition,
        replay_package_id=None,
        approval_id=None,
        creation_kind="edit",
        content_hash=canonical_hash({"verification_digest": digest}, SCHEMA_VERSION),
        verification_digest=digest,
        parent_version_id=version.id,
        rebuild=False,
    )


def same_source_rebuild(version: CaseVersion) -> CaseVersion:
    """Recompile the same definition. This does not stand in for a meaning edit."""

    return CaseVersion(
        id=uuid4(),
        project_id=version.project_id,
        case_id=version.case_id,
        definition=version.definition,
        replay_package_id=None,
        approval_id=None,
        creation_kind="recorded",
        content_hash=version.content_hash,
        verification_digest=version.verification_digest,
        parent_version_id=version.id,
        rebuild=True,
    )
