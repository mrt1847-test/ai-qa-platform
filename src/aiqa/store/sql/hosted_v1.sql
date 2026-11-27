CREATE FUNCTION aiqa_json_valid(body text) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE AS $aiqa$
BEGIN
    IF body IS NULL THEN RETURN false; END IF;
    PERFORM body::jsonb;
    RETURN true;
EXCEPTION WHEN invalid_text_representation THEN RETURN false;
END
$aiqa$;

CREATE FUNCTION aiqa_json_type(body text, path text) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $aiqa$
DECLARE item jsonb; kind text;
BEGIN
    IF body IS NULL OR path IS NULL THEN RETURN NULL; END IF;
    IF path !~ '^\$\.[A-Za-z_][A-Za-z_0-9]*(\.[A-Za-z_][A-Za-z_0-9]*)*$' THEN
        RAISE EXCEPTION 'unsupported JSON path' USING ERRCODE = '22023';
    END IF;
    item := body::jsonb #> string_to_array(substring(path FROM 3), '.');
    kind := jsonb_typeof(item);
    RETURN CASE kind WHEN 'string' THEN 'text'
        WHEN 'boolean' THEN item #>> '{}'
        WHEN 'number' THEN CASE WHEN item::text ~ '^-?[0-9]+$' THEN 'integer' ELSE 'real' END
        ELSE kind END;
END
$aiqa$;

CREATE FUNCTION aiqa_json_extract(body text, path text) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $aiqa$
DECLARE item jsonb;
BEGIN
    IF body IS NULL OR path IS NULL THEN RETURN NULL; END IF;
    IF path !~ '^\$\.[A-Za-z_][A-Za-z_0-9]*(\.[A-Za-z_][A-Za-z_0-9]*)*$' THEN
        RAISE EXCEPTION 'unsupported JSON path' USING ERRCODE = '22023';
    END IF;
    item := body::jsonb #> string_to_array(substring(path FROM 3), '.');
    RETURN CASE WHEN item = 'true'::jsonb THEN '1' WHEN item = 'false'::jsonb THEN '0'
        ELSE item #>> '{}' END;
END
$aiqa$;

CREATE FUNCTION aiqa_json_array(item text) RETURNS text
LANGUAGE sql IMMUTABLE AS $aiqa$
    SELECT jsonb_build_array(item)::text
$aiqa$;

CREATE FUNCTION aiqa_json_each(body text) RETURNS TABLE(value text)
LANGUAGE plpgsql IMMUTABLE AS $aiqa$
DECLARE parsed jsonb;
BEGIN
    IF body IS NULL THEN RETURN; END IF;
    parsed := body::jsonb;
    RETURN QUERY
    SELECT CASE WHEN items.item = 'true'::jsonb THEN '1'
        WHEN items.item = 'false'::jsonb THEN '0' ELSE items.item #>> '{}' END
    FROM (
        SELECT elements.value AS item FROM jsonb_array_elements(
            CASE WHEN jsonb_typeof(parsed) = 'array' THEN parsed ELSE '[]'::jsonb END) AS elements
        UNION ALL
        SELECT members.value AS item FROM jsonb_each(
            CASE WHEN jsonb_typeof(parsed) = 'object' THEN parsed ELSE '{}'::jsonb END) AS members
        UNION ALL
        SELECT parsed WHERE jsonb_typeof(parsed) NOT IN ('array', 'object')
    ) AS items;
END
$aiqa$;

CREATE TABLE action_reviews (
    project_id TEXT NOT NULL,
    opinion_id TEXT NOT NULL,
    review_id TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    owner_kind TEXT NOT NULL CHECK (owner_kind IN ('REC', 'ITEM')),
    owner_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    evidence_digest TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('reviewed', 'needs_change', 'evidence_missing')),
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    comment TEXT NOT NULL,
    PRIMARY KEY (project_id, opinion_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE actions (
    project_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    action_seq BIGINT NOT NULL,
    step_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    package_step_id TEXT,
    proposal_hash TEXT NOT NULL,
    dispatch_state TEXT NOT NULL CHECK (dispatch_state IN (
                'planned', 'lookup_failed', 'dispatch_started', 'acknowledged', 'observed', 'unknown'
            )),
    case_id TEXT NOT NULL,
    case_version_id TEXT NOT NULL,
    outcome_known BIGINT NOT NULL CHECK (outcome_known IN (0, 1)),
    PRIMARY KEY (project_id, attempt_id, action_seq),
    UNIQUE (project_id, attempt_id, action_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE analysis_records (
    project_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    case_run_id TEXT NOT NULL,
    commit_seq BIGINT NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (project_id, record_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE app_builds (
    project_id TEXT NOT NULL,
    build_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    filename TEXT NOT NULL DEFAULT '',
    package_name TEXT NOT NULL DEFAULT '',
    version_name TEXT NOT NULL DEFAULT '',
    min_sdk TEXT NOT NULL DEFAULT '',
    abi TEXT NOT NULL DEFAULT '',
    signature_status TEXT NOT NULL DEFAULT 'unknown',
    ready BIGINT NOT NULL DEFAULT 0,
    object_key TEXT,
    byte_length BIGINT NOT NULL DEFAULT 0,
    artifact_id TEXT,
    inspect_job_id TEXT,
    created_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (project_id, build_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE approval_events (
    project_id TEXT NOT NULL,
    approval_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    case_version_id TEXT NOT NULL,
    review_id TEXT NOT NULL,
    event_kind TEXT NOT NULL CHECK (event_kind IN ('approved', 'rejected', 'revoked')),
    prior_approval_id TEXT,
    version_hash TEXT NOT NULL,
    evidence_set_hash TEXT NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY (project_id, approval_id),
    CHECK (
                (event_kind IN ('approved', 'rejected') AND prior_approval_id IS NULL)
                OR (event_kind = 'revoked' AND prior_approval_id IS NOT NULL)
            ),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE approval_pin_releases (
    project_id TEXT NOT NULL,
    release_id TEXT NOT NULL,
    protection_id TEXT NOT NULL,
    approval_id TEXT NOT NULL,
    released_at TEXT NOT NULL,
    grace_until TEXT NOT NULL,
    PRIMARY KEY (project_id, release_id),
    UNIQUE (project_id, protection_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE approval_queue_blocks (
    project_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    approval_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, job_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE artifact_objects (
    project_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    object_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    byte_length BIGINT NOT NULL,
    media_type TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ready', 'quarantine')),
    acked BIGINT NOT NULL CHECK (acked IN (0, 1)),
    custody TEXT NOT NULL DEFAULT 'stored',
    stored_at TEXT NOT NULL DEFAULT '',
    owner_kind TEXT,
    attempt_id TEXT,
    action_id TEXT,
    check_id TEXT,
    role TEXT,
    job_id TEXT,
    generation BIGINT,
    PRIMARY KEY (project_id, artifact_id),
    CHECK (
                (status = 'ready' AND acked = 1)
                OR (status = 'quarantine' AND acked = 0)
            ),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE artifact_protections (
    project_id TEXT NOT NULL,
    protection_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('review', 'approval', 'backup', 'build', 'manual')),
    backup_receipt_id TEXT,
    build_id TEXT,
    manual_request_id TEXT,
    PRIMARY KEY (project_id, protection_id),
    CHECK (
                (kind = 'backup' AND backup_receipt_id IS NOT NULL
                    AND build_id IS NULL AND manual_request_id IS NULL)
                OR (kind = 'build' AND build_id IS NOT NULL
                    AND backup_receipt_id IS NULL AND manual_request_id IS NULL)
                OR (kind = 'manual' AND manual_request_id IS NOT NULL
                    AND backup_receipt_id IS NULL AND build_id IS NULL)
                OR (kind IN ('review', 'approval')
                    AND backup_receipt_id IS NULL AND build_id IS NULL AND manual_request_id IS NULL)
            ),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE artifact_provenance (
    project_id TEXT NOT NULL,
    provenance_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    source_note TEXT NOT NULL,
    PRIMARY KEY (project_id, provenance_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE artifact_refs (
    project_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    attempt_id TEXT,
    action_id TEXT,
    check_id TEXT,
    recording_id TEXT,
    review_id TEXT,
    build_id TEXT,
    export_id TEXT,
    package_id TEXT,
    healing_id TEXT,
    proposal_id TEXT,
    resource_observation_id TEXT,
    PRIMARY KEY (project_id, artifact_id),
    CHECK (
                (
                    (action_id IS NOT NULL)::integer
                    + (check_id IS NOT NULL)::integer
                    + (recording_id IS NOT NULL)::integer
                    + (review_id IS NOT NULL)::integer
                    + (build_id IS NOT NULL)::integer
                    + (export_id IS NOT NULL)::integer
                    + (package_id IS NOT NULL)::integer
                    + (healing_id IS NOT NULL)::integer
                    + (proposal_id IS NOT NULL)::integer
                    + (resource_observation_id IS NOT NULL)::integer
                ) = 1
                AND ((action_id IS NULL AND check_id IS NULL) OR attempt_id IS NOT NULL)
            ),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE artifact_staging (
    project_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    object_key TEXT NOT NULL,
    identity TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    byte_length BIGINT NOT NULL,
    PRIMARY KEY(project_id,artifact_id),
    UNIQUE(project_id,identity,content_hash),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE artifact_upload_requests (
    project_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    generation BIGINT NOT NULL,
    worker_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    response_body TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY(project_id,job_id,generation,worker_id,request_key),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE attempt_events (
    project_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    local_seq BIGINT NOT NULL,
    captured_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    minimum_facts TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    detail_payload TEXT,
    sealed BIGINT NOT NULL DEFAULT 0 CHECK (sealed IN (0, 1)),
    PRIMARY KEY (project_id, event_id),
    UNIQUE (project_id, attempt_id, local_seq),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE attempt_finish_requests (
    project_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    response_body TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, attempt_id, request_key),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE attempt_incarnations (
    project_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    boot_id TEXT NOT NULL,
    PRIMARY KEY (project_id, attempt_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE attempt_runners (
    project_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    runner_nonce TEXT NOT NULL,
    acked_at TEXT NOT NULL,
    PRIMARY KEY (project_id, attempt_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE attempts (
    project_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    generation BIGINT NOT NULL,
    physical_key_id TEXT,
    PRIMARY KEY (project_id, attempt_id),
    UNIQUE (project_id, job_id, generation),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE automation_cases (
    project_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    name TEXT NOT NULL,
    folder_id TEXT,
    tc_reference TEXT,
    next_revision BIGINT NOT NULL,
    latest_draft_version_id TEXT,
    current_approval_id TEXT,
    lock_version BIGINT NOT NULL,
    archived_at TEXT,
    priority TEXT,
    assignee_id TEXT,
    PRIMARY KEY (project_id, case_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE backup_receipts (
    project_id TEXT NOT NULL,
    receipt_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, receipt_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE backup_snapshots (
    project_id TEXT NOT NULL,
    receipt_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    byte_length BIGINT NOT NULL,
    content_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('complete', 'incomplete')),
    missing_count BIGINT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, receipt_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE binding_revisions (
    project_id TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    revision BIGINT NOT NULL,
    role TEXT NOT NULL,
    provider TEXT NOT NULL,
    endpoint_kind TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    model TEXT NOT NULL,
    key_ref_id TEXT NOT NULL,
    key_revision BIGINT NOT NULL,
    prompt_hash TEXT NOT NULL,
    tariff_id TEXT NOT NULL,
    compatibility_status TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, binding_id, revision_id),
    UNIQUE (binding_id, revision),
    UNIQUE (project_id, revision_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE browser_mutation_receipts (
    actor_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    request_key TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    status_code BIGINT NOT NULL,
    response_body BYTEA NOT NULL,
    media_type TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    PRIMARY KEY(actor_id,project_id,operation,request_key),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE browser_nonces (
    nonce_hash TEXT PRIMARY KEY,
    origin TEXT NOT NULL,
    project_id TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE browser_receipt_key (
    singleton BIGINT PRIMARY KEY CHECK(singleton=1),
    protected_key BYTEA NOT NULL,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE browser_sessions (
    session_id TEXT PRIMARY KEY,
    origin TEXT NOT NULL,
    csrf_hash TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    project_scope TEXT NOT NULL,
    is_local_owner BIGINT NOT NULL,
    expires_at TEXT NOT NULL,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE case_clone_provenance (
    project_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    source_case_id TEXT NOT NULL,
    source_version_id TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, case_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE case_edit_proposals (
    project_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    base_version_id TEXT NOT NULL,
    base_hash TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('structure', 'tc_import')),
    body TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    source_job_id TEXT,
    tc_version_id TEXT,
    PRIMARY KEY (project_id, proposal_id),
    CHECK (
                (kind = 'structure' AND source_job_id IS NOT NULL AND tc_version_id IS NULL)
                OR (kind = 'tc_import' AND tc_version_id IS NOT NULL AND source_job_id IS NULL)
            ),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE case_open_recordings (
    project_id TEXT NOT NULL,
    recording_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (project_id, recording_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE case_proposal_decisions (
    project_id TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'rejected')),
    produced_version_id TEXT,
    actor_id TEXT NOT NULL,
    commit_seq BIGINT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, decision_id),
    CHECK (
                (decision = 'accepted' AND produced_version_id IS NOT NULL)
                OR (decision = 'rejected' AND produced_version_id IS NULL)
            ),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE case_revision_audits (
    project_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    commit_seq BIGINT NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    created_at TEXT NOT NULL,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE case_runs (
    project_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    case_run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    case_version_id TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose IN ('trial', 'regression', 'reverification')),
    requested_at TEXT NOT NULL,
    PRIMARY KEY (project_id, case_run_id),
    UNIQUE (project_id, execution_id, case_run_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE case_tag_links (
    project_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    tag_id TEXT NOT NULL,
    PRIMARY KEY (project_id, case_id, tag_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE case_tc_reference_audits (
    project_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    tc_version_id TEXT,
    action TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    commit_seq BIGINT NOT NULL,
    created_at TEXT NOT NULL,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE case_tc_references (
    project_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    tc_version_id TEXT,
    PRIMARY KEY (project_id, case_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE case_versions (
    project_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    revision BIGINT NOT NULL,
    creation_kind TEXT NOT NULL,
    parent_version_id TEXT,
    base_version_id TEXT,
    is_branch BIGINT NOT NULL,
    definition_json TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    recorded_steps_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    verification_digest TEXT NOT NULL,
    source_manifest_id TEXT,
    replay_package_id TEXT,
    readiness_json TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, case_id, version_id),
    UNIQUE (case_id, revision),
    UNIQUE (project_id, version_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE check_results (
    project_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    check_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('satisfied', 'violated', 'unknown', 'not_run')),
    method TEXT NOT NULL CHECK (method IN (
                'deterministic', 'ai_visual', 'deterministic_then_ai_unknown'
            )),
    expected_snapshot TEXT NOT NULL,
    sanitized_observed TEXT NOT NULL,
    reason TEXT NOT NULL,
    artifact_refs TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    PRIMARY KEY (project_id, attempt_id, check_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE claim_receipts (
    project_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    job_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    generation BIGINT NOT NULL,
    physical_key_id TEXT,
    expires_at TEXT NOT NULL,
    session_id TEXT,
    boot_id TEXT,
    purpose TEXT NOT NULL,
    target_ref TEXT,
    revision_ref TEXT,
    policy_ref TEXT,
    digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, worker_id, request_key),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE cleanup_confirmations (
    project_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    generation BIGINT NOT NULL,
    worker_id TEXT NOT NULL,
    physical_key_id TEXT,
    released BIGINT NOT NULL,
    quarantined BIGINT NOT NULL,
    proof_refs TEXT NOT NULL,
    confirmed_at TEXT NOT NULL,
    PRIMARY KEY (project_id, attempt_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE dataset_versions (
    project_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    revision BIGINT NOT NULL,
    body_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, dataset_id, version_id),
    UNIQUE (dataset_id, revision),
    UNIQUE (project_id, version_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE datasets (
    project_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    name TEXT NOT NULL,
    next_revision BIGINT NOT NULL,
    latest_version_id TEXT,
    PRIMARY KEY (project_id, dataset_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE dispatch_journal (
    project_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    action_seq BIGINT NOT NULL,
    entry_seq BIGINT NOT NULL,
    dispatch_state TEXT NOT NULL CHECK (dispatch_state IN (
                'planned', 'lookup_failed', 'dispatch_started', 'acknowledged', 'observed', 'unknown'
            )),
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (project_id, attempt_id, action_seq, entry_seq),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE environment_revisions (
    project_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    revision BIGINT NOT NULL,
    body_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, environment_id, revision_id),
    UNIQUE (environment_id, revision),
    UNIQUE (project_id, revision_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE environments (
    project_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    name TEXT NOT NULL,
    next_revision BIGINT NOT NULL,
    latest_revision_id TEXT,
    PRIMARY KEY (project_id, environment_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE evidence_commit_requests (
    project_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    generation BIGINT NOT NULL,
    worker_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    response_body TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, job_id, generation, worker_id, request_key),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE execution_exclusions (
    project_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    PRIMARY KEY (project_id, execution_id, entry_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE executions (
    project_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    name TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose IN ('trial', 'regression', 'reverification')),
    source TEXT NOT NULL CHECK (source IN ('single', 'selection', 'suite', 'rerun')),
    suite_version_id TEXT,
    scope_requested_at TEXT NOT NULL,
    PRIMARY KEY (project_id, execution_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE fingerprint_observations (
    project_id TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    case_run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    commit_seq BIGINT NOT NULL,
    verification_digest TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    env_profile_revision TEXT NOT NULL,
    data_fingerprint TEXT NOT NULL,
    oracle_policy TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    PRIMARY KEY (project_id, observation_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE folders (
    project_id TEXT NOT NULL,
    folder_id TEXT NOT NULL,
    parent_folder_id TEXT,
    name TEXT NOT NULL,
    PRIMARY KEY (project_id, folder_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE gc_claims (
    project_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('delete_pending')),
    claimed_at TEXT NOT NULL,
    PRIMARY KEY (project_id, claim_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE gc_pause (
    pause_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (pause_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE healing_episodes (
    project_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    case_run_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    package_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    PRIMARY KEY (project_id, episode_id),
    UNIQUE (project_id, case_run_id),
    UNIQUE (project_id, case_run_id, request_key),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE healing_reservations (
    project_id TEXT NOT NULL,
    reservation_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    case_run_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (reason IN ('target_not_found', 'ambiguous', 'layout_shift')),
    reserved_calls BIGINT NOT NULL CHECK (reserved_calls BETWEEN 1 AND 2),
    reserved_seconds BIGINT NOT NULL CHECK (reserved_seconds BETWEEN 1 AND 30),
    created_at TEXT NOT NULL,
    action_id TEXT,
    PRIMARY KEY (project_id, reservation_id),
    UNIQUE (project_id, episode_id),
    UNIQUE (project_id, case_run_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE item_finalizations (
    project_id TEXT NOT NULL,
    case_run_id TEXT NOT NULL,
    created_seq BIGINT NOT NULL,
    finalized_seq BIGINT NOT NULL,
    release_label TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    core_result TEXT NOT NULL CHECK (core_result IN (
                'PASS', 'FAIL', 'BLOCKED', 'INCONCLUSIVE', 'SKIPPED', 'CANCELLED', 'NOT_RUN'
            )),
    denominator BIGINT NOT NULL CHECK (denominator IN (0, 1)),
    PRIMARY KEY (project_id, case_run_id),
    CHECK (created_seq <= finalized_seq),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE item_lifecycle_events (
    project_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    case_run_id TEXT NOT NULL,
    commit_seq BIGINT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('created', 'finalized')),
    PRIMARY KEY (project_id, event_id),
    UNIQUE (project_id, case_run_id, kind),
    UNIQUE (project_id, case_run_id, commit_seq),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE item_usage_facts (
    project_id TEXT NOT NULL,
    usage_id TEXT NOT NULL,
    case_run_id TEXT NOT NULL,
    commit_seq BIGINT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('authoring', 'verification', 'healing', 'maintenance')),
    measurement_status TEXT NOT NULL CHECK (measurement_status IN (
                'measured', 'estimated', 'unreported', 'not_used', 'unknown'
            )),
    amount TEXT,
    currency TEXT,
    PRIMARY KEY (project_id, usage_id),
    CHECK (
                (
                    measurement_status IN ('not_used', 'unknown', 'unreported')
                    AND amount IS NULL
                    AND currency IS NULL
                )
                OR (
                    measurement_status IN ('measured', 'estimated')
                    AND amount IS NOT NULL
                    AND currency IS NOT NULL
                )
            ),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE job_cancellations (
    project_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    job_id TEXT NOT NULL,
    expected_state TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    status_after TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    runner_stopped BIGINT NOT NULL CHECK (runner_stopped IN (0, 1)),
    cleanup_completed BIGINT NOT NULL CHECK (cleanup_completed IN (0, 1)),
    PRIMARY KEY (project_id, actor_id, request_key),
    UNIQUE (project_id, job_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE job_finish_facts (
    project_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    verdict TEXT CHECK (verdict IS NULL OR verdict IN ('FAIL', 'INCONCLUSIVE')),
    finish_reason TEXT NOT NULL CHECK (finish_reason IN ('lost', 'cancelled', 'crash')),
    cleanup_failed BIGINT NOT NULL CHECK (cleanup_failed IN (0, 1)),
    resource_state TEXT NOT NULL CHECK (resource_state IN ('unchanged', 'quarantine')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, job_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE job_receipts (
    project_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    request_key TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    job_id TEXT NOT NULL,
    purpose TEXT NOT NULL,
    recording_id TEXT,
    execution_id TEXT,
    case_run_id TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, actor_id, operation, request_key),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE job_reconciliations (
    project_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    generation BIGINT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('continued', 'lost')),
    reason TEXT NOT NULL CHECK (
                reason IN ('live', 'dead_runner', 'restarted', 'expired', 'watchdog')
            ),
    reconciled_at TEXT NOT NULL,
    PRIMARY KEY (project_id, job_id, generation),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE job_worker_sessions (
    project_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    PRIMARY KEY (project_id, job_id, worker_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE jobs (
    project_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose IN (
                'recording', 'trial', 'regression', 'structure', 'app_inspect', 'app_install',
                'resource_probe', 'model_check', 'export', 'evidence_sync', 'package_rebuild', 'backup'
            )),
    recording_id TEXT,
    case_run_id TEXT,
    payload_hash TEXT NOT NULL,
    source_refs TEXT NOT NULL,
    limits TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
                'queued', 'preparing', 'running', 'finalizing', 'completed',
                'cancel_requested', 'cancelled', 'error', 'lost'
            )),
    PRIMARY KEY (project_id, job_id),
    CHECK (
                (
                    purpose = 'recording'
                    AND recording_id IS NOT NULL
                    AND case_run_id IS NULL
                )
                OR (
                    purpose IN ('trial', 'regression')
                    AND recording_id IS NULL
                    AND case_run_id IS NOT NULL
                )
                OR (
                    purpose IN (
                        'structure', 'app_inspect', 'app_install', 'resource_probe', 'model_check',
                        'export', 'evidence_sync', 'package_rebuild', 'backup'
                    )
                    AND recording_id IS NULL
                    AND case_run_id IS NULL
                    AND source_refs <> '[]'
                )
            ),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE late_evidence_inbox (
    project_id TEXT NOT NULL,
    inbox_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    generation BIGINT NOT NULL,
    content_hash TEXT NOT NULL,
    media_type TEXT NOT NULL,
    role TEXT NOT NULL,
    filename TEXT NOT NULL,
    reason TEXT NOT NULL,
    received_at TEXT NOT NULL,
    PRIMARY KEY (project_id, inbox_id),
    UNIQUE (project_id, attempt_id, content_hash, role, filename),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE leases (
    project_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    generation BIGINT NOT NULL,
    worker_id TEXT NOT NULL,
    physical_key_id TEXT,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (project_id, job_id, generation),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE live_video_publishers (
    session_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    native_id TEXT NOT NULL,
    producer_id TEXT NOT NULL,
    closed BIGINT NOT NULL DEFAULT 0,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE local_owner_identity (
    singleton BIGINT PRIMARY KEY CHECK(singleton=1),
    actor_id TEXT NOT NULL UNIQUE,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE manual_retention_requests (
    project_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, request_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE materialization_receipts (
    project_id TEXT NOT NULL,
    receipt_id TEXT NOT NULL,
    manifest_id TEXT NOT NULL,
    produced_version_id TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    PRIMARY KEY (project_id, receipt_id),
    UNIQUE (project_id, manifest_id),
    UNIQUE (project_id, produced_version_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE model_bindings (
    project_id TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    name TEXT NOT NULL,
    next_revision BIGINT NOT NULL,
    latest_revision_id TEXT,
    PRIMARY KEY (project_id, binding_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE model_call_facts (
    project_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('authoring', 'verification', 'healing', 'maintenance')),
    action_id TEXT,
    check_id TEXT,
    measurement_status TEXT NOT NULL CHECK (measurement_status IN (
                'measured', 'estimated', 'unreported', 'not_used', 'unknown'
            )),
    input_tokens BIGINT,
    output_tokens BIGINT,
    cache_tokens BIGINT,
    image_tokens BIGINT,
    PRIMARY KEY (project_id, call_id),
    CHECK (
                (action_id IS NOT NULL AND check_id IS NULL)
                OR (action_id IS NULL AND check_id IS NOT NULL)
            ),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE model_observations (
    project_id TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    model_fingerprint TEXT NOT NULL,
    policy_ref TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    image_hash TEXT NOT NULL,
    geometry_hash TEXT NOT NULL,
    geometry_json TEXT NOT NULL,
    source_observation_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(project_id,observation_id),
    UNIQUE(project_id,attempt_id,request_key),
    UNIQUE(project_id,call_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE model_request_receipts (
    project_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    call_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    policy_ref TEXT NOT NULL,
    price_mode TEXT NOT NULL CHECK(price_mode='estimate'),
    state TEXT NOT NULL CHECK(state IN ('pending','completed')),
    charged BIGINT NOT NULL CHECK(charged IN (0,1)),
    status_code BIGINT,
    response_json TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    PRIMARY KEY(project_id,attempt_id,request_key),
    UNIQUE(project_id,call_id),
    CHECK((state='pending' AND response_json IS NULL AND status_code IS NULL AND completed_at IS NULL AND charged=1)
           OR (state='completed' AND response_json IS NOT NULL AND status_code IS NOT NULL AND completed_at IS NOT NULL)),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE oidc_auth_codes (
    code_hash TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    nonce TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    issuer TEXT NOT NULL,
    subject TEXT NOT NULL,
    audience TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE oidc_identities (
    identity_id TEXT PRIMARY KEY,
    issuer TEXT NOT NULL,
    subject TEXT NOT NULL,
    actor_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE (issuer, subject),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE oidc_login_states (
    state TEXT PRIMARY KEY,
    nonce TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    code_verifier TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    project_id TEXT,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE package_steps (
    project_id TEXT NOT NULL,
    package_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    position BIGINT NOT NULL,
    step_hash TEXT NOT NULL,
    PRIMARY KEY (project_id, package_id, step_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE package_version_links (
    project_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    package_id TEXT NOT NULL,
    PRIMARY KEY (project_id, case_id, version_id),
    UNIQUE (project_id, case_id, package_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE payload_retention_events (
    project_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    subject_kind TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, event_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE physical_resource_keys (
    physical_key_id TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL,
    native_id TEXT NOT NULL,
    UNIQUE (worker_id, native_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE project_audit_links (
    project_id TEXT NOT NULL,
    audit_id TEXT NOT NULL,
    note TEXT NOT NULL,
    commit_seq BIGINT NOT NULL,
    PRIMARY KEY (project_id, audit_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE project_audits (
    project_id TEXT NOT NULL,
    audit_id TEXT NOT NULL,
    commit_seq BIGINT NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, audit_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE project_commit_clock (
    project_id TEXT PRIMARY KEY,
    commit_seq BIGINT NOT NULL,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE project_memberships (
    project_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('viewer', 'operator', 'admin')),
    created_at TEXT NOT NULL,
    revoked_at TEXT,
    PRIMARY KEY (project_id, actor_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE project_row_notes (
    project_id TEXT NOT NULL,
    note TEXT NOT NULL,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE project_rows (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE project_settings (
    project_id TEXT PRIMARY KEY,
    lock_version BIGINT NOT NULL,
    failure_policy TEXT NOT NULL,
    retention TEXT NOT NULL,
    timeout_seconds BIGINT NOT NULL,
    healing_scope TEXT NOT NULL,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    target TEXT NOT NULL,
    created_at TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_project_scope TEXT,
    actor_is_local_owner BIGINT NOT NULL,
    archived_at TEXT,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE protection_releases (
    project_id TEXT NOT NULL,
    release_id TEXT NOT NULL,
    protection_id TEXT NOT NULL,
    released_at TEXT NOT NULL,
    PRIMARY KEY (project_id, release_id),
    UNIQUE (project_id, protection_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE recording_check_bindings (
    project_id TEXT NOT NULL,
    recording_id TEXT NOT NULL,
    manifest_id TEXT NOT NULL,
    source_manifest_id TEXT NOT NULL,
    source_manifest_hash TEXT NOT NULL,
    input_case_version_id TEXT NOT NULL,
    bindings_json TEXT NOT NULL,
    binding_hash TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    request_key TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(project_id,manifest_id),
    UNIQUE(project_id,recording_id,request_key),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE recording_intents (
    project_id TEXT NOT NULL,
    recording_id TEXT NOT NULL,
    case_version_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    intent_hash TEXT NOT NULL,
    body_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, recording_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE recording_manifests (
    project_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    recording_id TEXT NOT NULL,
    manifest_id TEXT NOT NULL,
    revision BIGINT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('original', 'recovery', 'package_rebuild')),
    prior_manifest_id TEXT,
    input_version_hash TEXT NOT NULL,
    source_artifact_hashes TEXT NOT NULL,
    action_mapping TEXT NOT NULL,
    evidence_completeness TEXT NOT NULL,
    request_key TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    PRIMARY KEY (project_id, manifest_id),
    UNIQUE (project_id, recording_id, revision),
    UNIQUE (project_id, recording_id, request_key),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE recording_notes (
    project_id TEXT NOT NULL,
    recording_id TEXT NOT NULL,
    note_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    commit_seq BIGINT NOT NULL,
    body TEXT NOT NULL,
    request_key TEXT NOT NULL,
    PRIMARY KEY (project_id, recording_id, note_id),
    UNIQUE (project_id, recording_id, commit_seq),
    UNIQUE (project_id, recording_id, request_key),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE recordings (
    project_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    recording_id TEXT NOT NULL,
    creation_kind TEXT NOT NULL CHECK (creation_kind = 'recorded'),
    input_case_version_id TEXT NOT NULL,
    base_case_version_id TEXT,
    parent_recording_id TEXT,
    source_recording_id TEXT,
    storage_status TEXT NOT NULL CHECK (storage_status IN ('local', 'spooling', 'stored')),
    stop_status TEXT NOT NULL CHECK (stop_status IN ('running', 'stopped')),
    completion_status TEXT NOT NULL CHECK (completion_status IN ('open', 'completed', 'interrupted', 'error')),
    evidence_status TEXT NOT NULL CHECK (evidence_status IN ('incomplete', 'complete')),
    PRIMARY KEY (project_id, recording_id),
    UNIQUE (project_id, case_id, recording_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE repair_adoptions (
    project_id TEXT NOT NULL,
    adoption_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    recording_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, adoption_id),
    UNIQUE (project_id, proposal_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE repair_proposals (
    project_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    case_run_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    package_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    diff_hash TEXT NOT NULL,
    accepted_target_json TEXT NOT NULL DEFAULT '',
    diff_json TEXT NOT NULL DEFAULT '',
    evidence_hash TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (project_id, proposal_id),
    UNIQUE (project_id, episode_id),
    UNIQUE (project_id, episode_id, request_key),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE replay_packages (
    project_id TEXT NOT NULL,
    package_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    case_version_id TEXT NOT NULL,
    ready BIGINT NOT NULL CHECK (ready IN (0, 1)),
    schema_version TEXT NOT NULL,
    source_manifest_id TEXT NOT NULL,
    source_manifest_hash TEXT NOT NULL,
    raw_source_hash TEXT NOT NULL,
    approved_code_hash TEXT NOT NULL,
    runtime_ref TEXT NOT NULL,
    compiler_ref TEXT NOT NULL,
    lock_hash TEXT NOT NULL,
    step_mapping_hash TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    PRIMARY KEY (project_id, package_id),
    UNIQUE (project_id, case_id, package_id),
    UNIQUE (project_id, case_id, case_version_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE resource_aliases (
    project_id TEXT NOT NULL,
    physical_key_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('web', 'android')),
    alias_id TEXT,
    PRIMARY KEY (project_id, physical_key_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE resource_inventory (
    physical_key_id TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK (state IN ('offline', 'unauthorized', 'busy', 'ready')),
    os_build TEXT NOT NULL,
    geometry TEXT NOT NULL,
    permissions TEXT NOT NULL,
    ime TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE resource_observations (
    project_id TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    probe_job_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    geometry TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    scope_hash TEXT NOT NULL,
    PRIMARY KEY (project_id, artifact_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE resource_quarantine (
    physical_key_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL CHECK (reason IN ('expired', 'restarted', 'dead_runner')),
    quarantined_at TEXT NOT NULL,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE restore_activations (
    project_id TEXT NOT NULL,
    activation_id TEXT NOT NULL,
    validation_id TEXT NOT NULL,
    auto_replayed_jobs BIGINT NOT NULL CHECK (auto_replayed_jobs = 0),
    old_leases_reused BIGINT NOT NULL CHECK (old_leases_reused = 0),
    secret_reset_required BIGINT NOT NULL CHECK (secret_reset_required = 1),
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, activation_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE restore_validations (
    project_id TEXT NOT NULL,
    validation_id TEXT NOT NULL,
    receipt_id TEXT NOT NULL,
    separate_path TEXT NOT NULL,
    schema_ok BIGINT NOT NULL CHECK (schema_ok IN (0, 1)),
    foreign_keys_ok BIGINT NOT NULL CHECK (foreign_keys_ok IN (0, 1)),
    integrity_ok BIGINT NOT NULL CHECK (integrity_ok IN (0, 1)),
    manifest_ok BIGINT NOT NULL CHECK (manifest_ok IN (0, 1)),
    hash_ok BIGINT NOT NULL CHECK (hash_ok IN (0, 1)),
    missing_count BIGINT NOT NULL,
    secret_reset_required BIGINT NOT NULL CHECK (secret_reset_required = 1),
    accepted BIGINT NOT NULL CHECK (accepted IN (0, 1)),
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, validation_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE retention_command_receipts (
    project_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    protection_id TEXT NOT NULL,
    PRIMARY KEY (project_id, actor_id, operation, idempotency_key),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE retention_tombstones (
    project_id TEXT NOT NULL,
    tombstone_id TEXT NOT NULL,
    subject_kind TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    expired_at TEXT NOT NULL,
    PRIMARY KEY (project_id, tombstone_id),
    UNIQUE (project_id, subject_kind, subject_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE review_decisions (
    project_id TEXT NOT NULL,
    review_id TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('approved', 'rejected')),
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    version_hash TEXT NOT NULL,
    PRIMARY KEY (project_id, decision_id),
    UNIQUE (project_id, review_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE review_evidence_entries (
    project_id TEXT NOT NULL,
    review_id TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    owner_kind TEXT NOT NULL CHECK (owner_kind IN ('REC', 'ITEM')),
    owner_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    artifact_ref_id TEXT NOT NULL,
    role TEXT NOT NULL,
    expected_hash TEXT NOT NULL,
    evidence_digest TEXT NOT NULL,
    PRIMARY KEY (project_id, entry_id),
    UNIQUE (
                project_id, review_id, owner_kind, owner_id, attempt_id, action_id, artifact_ref_id
            ),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE review_materialization_claims (
    project_id TEXT NOT NULL,
    receipt_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    manifest_id TEXT NOT NULL,
    produced_version_id TEXT NOT NULL,
    PRIMARY KEY(project_id,receipt_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE review_package_pair_claims (
    project_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    package_id TEXT NOT NULL,
    ready BIGINT NOT NULL DEFAULT 1 CHECK (ready = 1),
    PRIMARY KEY (project_id,case_id,version_id,package_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE review_package_source_claims (
    project_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    package_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    manifest_id TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    PRIMARY KEY(project_id,package_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE review_retention_events (
    project_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    review_id TEXT NOT NULL,
    protection_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, event_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE review_version_source_claims (
    project_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    manifest_id TEXT NOT NULL,
    PRIMARY KEY(project_id,version_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE reviews (
    project_id TEXT NOT NULL,
    review_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    case_version_id TEXT NOT NULL,
    version_hash TEXT NOT NULL,
    source_manifest_id TEXT,
    trial_case_run_id TEXT,
    evidence_set_hash TEXT NOT NULL,
    expected_current_approval_id TEXT,
    created_commit_seq BIGINT NOT NULL,
    PRIMARY KEY (project_id, review_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE runner_hosts (
    project_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    boot_id TEXT NOT NULL,
    PRIMARY KEY (project_id, attempt_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE runtime_overrides (
    project_id TEXT NOT NULL,
    override_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    case_run_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    package_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    PRIMARY KEY (project_id, override_id),
    UNIQUE (project_id, episode_id),
    UNIQUE (project_id, episode_id, request_key),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE schema_migrations (
    id TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE secret_ref_audits (
    project_id TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    revision BIGINT NOT NULL,
    commit_seq BIGINT NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    created_at TEXT NOT NULL,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE secret_ref_snapshots (
    project_id TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    revision BIGINT NOT NULL,
    commit_seq BIGINT NOT NULL,
    created_at TEXT NOT NULL,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE secret_refs (
    project_id TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    revision BIGINT NOT NULL,
    name TEXT NOT NULL,
    availability TEXT NOT NULL,
    created_at TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    PRIMARY KEY (project_id, ref_id, revision),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE stale_event_inbox (
    project_id TEXT NOT NULL,
    inbox_id TEXT NOT NULL,
    attempt_id TEXT,
    job_id TEXT NOT NULL,
    generation BIGINT NOT NULL,
    local_seq BIGINT NOT NULL,
    payload_hash TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (reason IN ('expired', 'terminal')),
    received_at TEXT NOT NULL,
    PRIMARY KEY (project_id, inbox_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE suite_entries (
    project_id TEXT NOT NULL,
    suite_version_id TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    position BIGINT NOT NULL,
    case_id TEXT NOT NULL DEFAULT '',
    case_version_id TEXT NOT NULL DEFAULT '',
    approval_id TEXT NOT NULL DEFAULT '',
    data_name TEXT NOT NULL DEFAULT '',
    environment_revision_id TEXT NOT NULL DEFAULT '',
    reset_policy TEXT NOT NULL DEFAULT '',
    failure_policy TEXT NOT NULL DEFAULT 'stop',
    resource_id TEXT NOT NULL DEFAULT '',
    target_kind TEXT NOT NULL DEFAULT 'web',
    PRIMARY KEY (project_id, suite_version_id, entry_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE suite_receipts (
    project_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    request_key TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    suite_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    suite_version_id TEXT,
    PRIMARY KEY (project_id, actor_id, operation, request_key),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE suite_versions (
    project_id TEXT NOT NULL,
    suite_id TEXT NOT NULL,
    suite_version_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    PRIMARY KEY (project_id, suite_version_id),
    UNIQUE (project_id, suite_id, suite_version_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE suites (
    project_id TEXT NOT NULL,
    suite_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    target_kind TEXT NOT NULL DEFAULT 'web',
    owner_name TEXT NOT NULL DEFAULT '',
    classification TEXT NOT NULL DEFAULT '',
    head_version_id TEXT,
    archived_at TEXT,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (project_id, suite_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE tags (
    project_id TEXT NOT NULL,
    tag_id TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (project_id, tag_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE tc_versions (
    project_id TEXT NOT NULL,
    tc_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    revision BIGINT NOT NULL,
    body_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, tc_id, version_id),
    UNIQUE (tc_id, revision),
    UNIQUE (project_id, version_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE test_cases (
    project_id TEXT NOT NULL,
    tc_id TEXT NOT NULL,
    name TEXT NOT NULL,
    next_revision BIGINT NOT NULL,
    latest_version_id TEXT,
    archived_at TEXT,
    PRIMARY KEY (project_id, tc_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE usage_adjustments (
    project_id TEXT NOT NULL,
    adjustment_id TEXT NOT NULL,
    case_run_id TEXT NOT NULL,
    commit_seq BIGINT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('authoring', 'verification', 'healing', 'maintenance')),
    measurement_status TEXT NOT NULL CHECK (measurement_status IN (
                'measured', 'estimated', 'unreported', 'not_used', 'unknown'
            )),
    amount TEXT,
    currency TEXT,
    PRIMARY KEY (project_id, adjustment_id),
    UNIQUE (project_id, case_run_id, commit_seq, role),
    CHECK (
                (
                    measurement_status IN ('not_used', 'unknown', 'unreported')
                    AND amount IS NULL
                    AND currency IS NULL
                )
                OR (
                    measurement_status IN ('measured', 'estimated')
                    AND amount IS NOT NULL
                    AND currency IS NOT NULL
                )
            ),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE worker_enrollment_codes (
    code_id TEXT PRIMARY KEY,
    code_hash TEXT NOT NULL UNIQUE,
    enrollment_id TEXT NOT NULL,
    purpose TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    created_at TEXT NOT NULL,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE worker_enrollments (
    enrollment_id TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE worker_presence (
    project_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    boot_id TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    session_id TEXT NOT NULL,
    PRIMARY KEY (project_id, worker_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE worker_retired_boots (
    project_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    boot_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    PRIMARY KEY (project_id, worker_id, boot_id),
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE TABLE worker_tokens (
    token_id TEXT PRIMARY KEY,
    enrollment_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    purpose TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    rowid BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE
);

CREATE UNIQUE INDEX app_builds_project_content_hash
        ON app_builds (project_id, content_hash)
        WHERE content_hash != '' AND object_key IS NOT NULL;

CREATE INDEX approval_events_case
        ON approval_events(project_id, case_id, case_version_id);

CREATE UNIQUE INDEX approval_events_one_revoke
        ON approval_events(project_id, prior_approval_id)
        WHERE event_kind = 'revoked';

CREATE UNIQUE INDEX artifact_objects_ready_identity ON artifact_objects(
        project_id, owner_kind, owner_id, attempt_id, COALESCE(action_id,''),
        COALESCE(check_id,''), role, media_type, content_hash) WHERE status='ready';

CREATE INDEX artifact_protections_artifact
        ON artifact_protections(project_id, artifact_id);

CREATE INDEX automation_cases_archive
        ON automation_cases(project_id, archived_at, case_id);

CREATE INDEX automation_cases_folder ON automation_cases(project_id, folder_id, case_id);

CREATE INDEX automation_cases_name ON automation_cases(project_id, name, case_id);

CREATE INDEX browser_receipts_expiry ON browser_mutation_receipts(created_at);

CREATE INDEX case_open_recordings_case
        ON case_open_recordings(project_id, case_id, status);

CREATE UNIQUE INDEX case_proposal_one_accept
        ON case_proposal_decisions(project_id, proposal_id)
        WHERE decision = 'accepted';

CREATE INDEX case_runs_case_requested
        ON case_runs(project_id, case_id, requested_at, case_run_id);

CREATE INDEX case_runs_requested
        ON case_runs(project_id, requested_at, case_run_id);

CREATE INDEX case_tag_links_tag ON case_tag_links(project_id, tag_id, case_id);

CREATE INDEX check_results_status
        ON check_results(project_id, check_id, status, attempt_id);

CREATE UNIQUE INDEX claim_receipts_attempt
        ON claim_receipts (project_id, attempt_id);

CREATE UNIQUE INDEX gc_claims_one_pending
        ON gc_claims(project_id, artifact_id);

CREATE INDEX item_finalizations_seq
        ON item_finalizations(project_id, finalized_seq);

CREATE INDEX item_lifecycle_seq
        ON item_lifecycle_events(project_id, commit_seq);

CREATE UNIQUE INDEX jobs_case_run_owner
        ON jobs(project_id, case_run_id)
        WHERE case_run_id IS NOT NULL;

CREATE INDEX jobs_queue
        ON jobs(project_id, status, job_id);

CREATE UNIQUE INDEX jobs_recording_owner
        ON jobs(project_id, recording_id)
        WHERE recording_id IS NOT NULL;

CREATE INDEX leases_resource
        ON leases(physical_key_id, generation)
        WHERE physical_key_id IS NOT NULL;

CREATE UNIQUE INDEX model_request_one_pending
        ON model_request_receipts(project_id,attempt_id) WHERE state='pending';

CREATE UNIQUE INDEX recording_intents_hash
        ON recording_intents (project_id, recording_id, intent_hash);

CREATE UNIQUE INDEX recording_manifests_case_key
        ON recording_manifests(project_id, case_id, manifest_id);

CREATE UNIQUE INDEX resource_aliases_alias_id
        ON resource_aliases (alias_id);

CREATE UNIQUE INDEX review_link_pair_exact ON package_version_links(project_id,case_id,version_id,package_id);

CREATE UNIQUE INDEX review_manifest_hash_exact ON recording_manifests(project_id,case_id,manifest_id,body_hash);

CREATE UNIQUE INDEX review_package_source_exact ON replay_packages(project_id,case_id,package_id,case_version_id,source_manifest_id,source_manifest_hash);

CREATE UNIQUE INDEX review_package_version_exact ON replay_packages(project_id,case_id,case_version_id,package_id,ready);

CREATE UNIQUE INDEX review_version_package_exact ON case_versions(project_id,case_id,version_id,replay_package_id);

CREATE UNIQUE INDEX review_version_source_exact ON case_versions(project_id,case_id,version_id,source_manifest_id);

CREATE UNIQUE INDEX tags_project_name ON tags(project_id, name);

CREATE INDEX usage_adjustments_seq
        ON usage_adjustments(project_id, commit_seq);

ALTER TABLE action_reviews ADD FOREIGN KEY (project_id, review_id) REFERENCES reviews(project_id, review_id);

ALTER TABLE action_reviews ADD FOREIGN KEY (project_id, entry_id) REFERENCES review_evidence_entries(project_id, entry_id);

ALTER TABLE actions ADD FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id);

ALTER TABLE actions ADD FOREIGN KEY (project_id, case_id, case_version_id)
                REFERENCES case_versions(project_id, case_id, version_id);

ALTER TABLE analysis_records ADD FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id);

ALTER TABLE app_builds ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE approval_events ADD FOREIGN KEY (project_id, case_id, case_version_id)
                REFERENCES case_versions(project_id, case_id, version_id);

ALTER TABLE approval_events ADD FOREIGN KEY (project_id, review_id) REFERENCES reviews(project_id, review_id);

ALTER TABLE approval_events ADD FOREIGN KEY (project_id, prior_approval_id)
                REFERENCES approval_events(project_id, approval_id);

ALTER TABLE approval_pin_releases ADD FOREIGN KEY (project_id, protection_id) REFERENCES artifact_protections(project_id, protection_id);

ALTER TABLE approval_pin_releases ADD FOREIGN KEY (project_id, approval_id) REFERENCES approval_events(project_id, approval_id);

ALTER TABLE approval_queue_blocks ADD FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id);

ALTER TABLE approval_queue_blocks ADD FOREIGN KEY (project_id, approval_id) REFERENCES approval_events(project_id, approval_id);

ALTER TABLE artifact_objects ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE artifact_protections ADD FOREIGN KEY (project_id, artifact_id) REFERENCES artifact_refs(project_id, artifact_id);

ALTER TABLE artifact_protections ADD FOREIGN KEY (project_id, backup_receipt_id)
                REFERENCES backup_receipts(project_id, receipt_id);

ALTER TABLE artifact_protections ADD FOREIGN KEY (project_id, build_id) REFERENCES app_builds(project_id, build_id);

ALTER TABLE artifact_protections ADD FOREIGN KEY (project_id, manual_request_id)
                REFERENCES manual_retention_requests(project_id, request_id);

ALTER TABLE artifact_provenance ADD FOREIGN KEY (project_id, artifact_id) REFERENCES artifact_refs(project_id, artifact_id);

ALTER TABLE artifact_refs ADD FOREIGN KEY (project_id, attempt_id, action_id)
                REFERENCES actions(project_id, attempt_id, action_id);

ALTER TABLE artifact_refs ADD FOREIGN KEY (project_id, attempt_id, check_id)
                REFERENCES check_results(project_id, attempt_id, check_id);

ALTER TABLE artifact_refs ADD FOREIGN KEY (project_id, recording_id) REFERENCES recordings(project_id, recording_id);

ALTER TABLE artifact_refs ADD FOREIGN KEY (project_id, review_id) REFERENCES reviews(project_id, review_id);

ALTER TABLE artifact_refs ADD FOREIGN KEY (project_id, build_id) REFERENCES app_builds(project_id, build_id);

ALTER TABLE artifact_staging ADD FOREIGN KEY(project_id) REFERENCES projects(project_id);

ALTER TABLE artifact_upload_requests ADD FOREIGN KEY(project_id,job_id) REFERENCES jobs(project_id,job_id);

ALTER TABLE attempt_events ADD FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id);

ALTER TABLE attempt_finish_requests ADD FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id);

ALTER TABLE attempt_incarnations ADD FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id);

ALTER TABLE attempt_runners ADD FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id);

ALTER TABLE attempts ADD FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id);

ALTER TABLE attempts ADD FOREIGN KEY (physical_key_id) REFERENCES physical_resource_keys(physical_key_id);

ALTER TABLE automation_cases ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE automation_cases ADD FOREIGN KEY (project_id, folder_id) REFERENCES folders(project_id, folder_id);

ALTER TABLE backup_receipts ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE backup_snapshots ADD FOREIGN KEY (project_id, receipt_id) REFERENCES backup_receipts(project_id, receipt_id);

ALTER TABLE backup_snapshots ADD FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id);

ALTER TABLE binding_revisions ADD FOREIGN KEY (project_id, binding_id) REFERENCES model_bindings(project_id, binding_id);

ALTER TABLE browser_nonces ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE browser_sessions ADD FOREIGN KEY (project_scope) REFERENCES projects(project_id);

ALTER TABLE case_clone_provenance ADD FOREIGN KEY (project_id, case_id) REFERENCES automation_cases(project_id, case_id);

ALTER TABLE case_clone_provenance ADD FOREIGN KEY (project_id, source_case_id) REFERENCES automation_cases(project_id, case_id);

ALTER TABLE case_edit_proposals ADD FOREIGN KEY (project_id, case_id, base_version_id)
                REFERENCES case_versions(project_id, case_id, version_id);

ALTER TABLE case_edit_proposals ADD FOREIGN KEY (project_id, source_job_id) REFERENCES jobs(project_id, job_id);

ALTER TABLE case_edit_proposals ADD FOREIGN KEY (project_id, tc_version_id) REFERENCES tc_versions(project_id, version_id);

ALTER TABLE case_open_recordings ADD FOREIGN KEY (project_id, case_id) REFERENCES automation_cases(project_id, case_id);

ALTER TABLE case_proposal_decisions ADD FOREIGN KEY (project_id, proposal_id)
                REFERENCES case_edit_proposals(project_id, proposal_id);

ALTER TABLE case_proposal_decisions ADD FOREIGN KEY (project_id, produced_version_id)
                REFERENCES case_versions(project_id, version_id);

ALTER TABLE case_runs ADD FOREIGN KEY (project_id, execution_id) REFERENCES executions(project_id, execution_id);

ALTER TABLE case_runs ADD FOREIGN KEY (project_id, case_id, case_version_id)
                REFERENCES case_versions(project_id, case_id, version_id);

ALTER TABLE case_tag_links ADD FOREIGN KEY (project_id, case_id) REFERENCES automation_cases(project_id, case_id);

ALTER TABLE case_tag_links ADD FOREIGN KEY (project_id, tag_id) REFERENCES tags(project_id, tag_id);

ALTER TABLE case_tc_references ADD FOREIGN KEY (project_id, case_id) REFERENCES automation_cases(project_id, case_id);

ALTER TABLE case_tc_references ADD FOREIGN KEY (project_id, tc_version_id) REFERENCES tc_versions(project_id, version_id);

ALTER TABLE case_versions ADD FOREIGN KEY (project_id, case_id) REFERENCES automation_cases(project_id, case_id);

ALTER TABLE case_versions ADD FOREIGN KEY (project_id, case_id, parent_version_id)
                REFERENCES case_versions(project_id, case_id, version_id);

ALTER TABLE case_versions ADD FOREIGN KEY (project_id, case_id, base_version_id)
                REFERENCES case_versions(project_id, case_id, version_id);

ALTER TABLE check_results ADD FOREIGN KEY (project_id, attempt_id, action_id)
                REFERENCES actions(project_id, attempt_id, action_id);

ALTER TABLE claim_receipts ADD FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id);

ALTER TABLE claim_receipts ADD FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id);

ALTER TABLE cleanup_confirmations ADD FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id);

ALTER TABLE dataset_versions ADD FOREIGN KEY (project_id, dataset_id) REFERENCES datasets(project_id, dataset_id);

ALTER TABLE datasets ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE dispatch_journal ADD FOREIGN KEY (project_id, attempt_id, action_seq)
                REFERENCES actions(project_id, attempt_id, action_seq);

ALTER TABLE environment_revisions ADD FOREIGN KEY (project_id, environment_id) REFERENCES environments(project_id, environment_id);

ALTER TABLE environments ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE evidence_commit_requests ADD FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id);

ALTER TABLE execution_exclusions ADD FOREIGN KEY (project_id, execution_id)
                REFERENCES executions(project_id, execution_id);

ALTER TABLE executions ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE executions ADD FOREIGN KEY (project_id, suite_version_id)
                REFERENCES suite_versions(project_id, suite_version_id);

ALTER TABLE fingerprint_observations ADD FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id);

ALTER TABLE fingerprint_observations ADD FOREIGN KEY (project_id, case_id) REFERENCES automation_cases(project_id, case_id);

ALTER TABLE folders ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE folders ADD FOREIGN KEY (project_id, parent_folder_id) REFERENCES folders(project_id, folder_id);

ALTER TABLE gc_claims ADD FOREIGN KEY (project_id, artifact_id) REFERENCES artifact_refs(project_id, artifact_id);

ALTER TABLE healing_episodes ADD FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id);

ALTER TABLE healing_episodes ADD FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id);

ALTER TABLE healing_episodes ADD FOREIGN KEY (project_id, package_id) REFERENCES replay_packages(project_id, package_id);

ALTER TABLE healing_reservations ADD FOREIGN KEY (project_id, episode_id) REFERENCES healing_episodes(project_id, episode_id);

ALTER TABLE item_finalizations ADD FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id);

ALTER TABLE item_lifecycle_events ADD FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id);

ALTER TABLE item_usage_facts ADD FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id);

ALTER TABLE job_cancellations ADD FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id);

ALTER TABLE job_finish_facts ADD FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id);

ALTER TABLE job_receipts ADD FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id);

ALTER TABLE job_receipts ADD FOREIGN KEY (project_id, recording_id) REFERENCES recordings(project_id, recording_id);

ALTER TABLE job_receipts ADD FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id);

ALTER TABLE job_reconciliations ADD FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id);

ALTER TABLE job_worker_sessions ADD FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id) ON DELETE CASCADE;

ALTER TABLE jobs ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE jobs ADD FOREIGN KEY (project_id, recording_id) REFERENCES recordings(project_id, recording_id);

ALTER TABLE jobs ADD FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id);

ALTER TABLE late_evidence_inbox ADD FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id);

ALTER TABLE leases ADD FOREIGN KEY (project_id, job_id) REFERENCES jobs(project_id, job_id);

ALTER TABLE leases ADD FOREIGN KEY (physical_key_id) REFERENCES physical_resource_keys(physical_key_id);

ALTER TABLE live_video_publishers ADD FOREIGN KEY(project_id) REFERENCES projects(project_id);

ALTER TABLE manual_retention_requests ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE materialization_receipts ADD FOREIGN KEY (project_id, manifest_id)
                REFERENCES recording_manifests(project_id, manifest_id);

ALTER TABLE model_bindings ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE model_call_facts ADD FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id);

ALTER TABLE model_call_facts ADD FOREIGN KEY (project_id, attempt_id, action_id)
                REFERENCES actions(project_id, attempt_id, action_id);

ALTER TABLE model_call_facts ADD FOREIGN KEY (project_id, attempt_id, check_id)
                REFERENCES check_results(project_id, attempt_id, check_id);

ALTER TABLE model_observations ADD FOREIGN KEY(project_id,attempt_id) REFERENCES attempts(project_id,attempt_id);

ALTER TABLE model_observations ADD FOREIGN KEY(project_id,artifact_id) REFERENCES artifact_objects(project_id,artifact_id);

ALTER TABLE model_request_receipts ADD FOREIGN KEY(project_id,attempt_id) REFERENCES attempts(project_id,attempt_id);

ALTER TABLE package_steps ADD FOREIGN KEY (project_id, package_id) REFERENCES replay_packages(project_id, package_id);

ALTER TABLE package_version_links ADD FOREIGN KEY (project_id, case_id, version_id)
                REFERENCES case_versions(project_id, case_id, version_id)
                DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE package_version_links ADD FOREIGN KEY (project_id, case_id, package_id)
                REFERENCES replay_packages(project_id, case_id, package_id)
                DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE payload_retention_events ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE project_audit_links ADD FOREIGN KEY (project_id, audit_id)
                REFERENCES project_audits(project_id, audit_id);

ALTER TABLE project_audits ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE project_commit_clock ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE project_memberships ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE project_row_notes ADD FOREIGN KEY (project_id) REFERENCES project_rows(project_id);

ALTER TABLE project_settings ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE protection_releases ADD FOREIGN KEY (project_id, protection_id)
                REFERENCES artifact_protections(project_id, protection_id);

ALTER TABLE recording_check_bindings ADD FOREIGN KEY(project_id,recording_id) REFERENCES recordings(project_id,recording_id);

ALTER TABLE recording_check_bindings ADD FOREIGN KEY(project_id,manifest_id) REFERENCES recording_manifests(project_id,manifest_id);

ALTER TABLE recording_check_bindings ADD FOREIGN KEY(project_id,source_manifest_id) REFERENCES recording_manifests(project_id,manifest_id);

ALTER TABLE recording_check_bindings ADD FOREIGN KEY(project_id,input_case_version_id) REFERENCES case_versions(project_id,version_id);

ALTER TABLE recording_intents ADD FOREIGN KEY (project_id, recording_id)
                REFERENCES recordings(project_id, recording_id);

ALTER TABLE recording_manifests ADD FOREIGN KEY (project_id, case_id, recording_id)
                REFERENCES recordings(project_id, case_id, recording_id);

ALTER TABLE recording_manifests ADD FOREIGN KEY (project_id, prior_manifest_id)
                REFERENCES recording_manifests(project_id, manifest_id);

ALTER TABLE recording_notes ADD FOREIGN KEY (project_id, recording_id) REFERENCES recordings(project_id, recording_id);

ALTER TABLE recordings ADD FOREIGN KEY (project_id, case_id) REFERENCES automation_cases(project_id, case_id);

ALTER TABLE recordings ADD FOREIGN KEY (project_id, case_id, input_case_version_id)
                REFERENCES case_versions(project_id, case_id, version_id);

ALTER TABLE recordings ADD FOREIGN KEY (project_id, case_id, base_case_version_id)
                REFERENCES case_versions(project_id, case_id, version_id);

ALTER TABLE recordings ADD FOREIGN KEY (project_id, case_id, parent_recording_id)
                REFERENCES recordings(project_id, case_id, recording_id);

ALTER TABLE recordings ADD FOREIGN KEY (project_id, case_id, source_recording_id)
                REFERENCES recordings(project_id, case_id, recording_id);

ALTER TABLE repair_adoptions ADD FOREIGN KEY (project_id, proposal_id) REFERENCES repair_proposals(project_id, proposal_id);

ALTER TABLE repair_adoptions ADD FOREIGN KEY (project_id, case_id) REFERENCES automation_cases(project_id, case_id);

ALTER TABLE repair_adoptions ADD FOREIGN KEY (project_id, recording_id) REFERENCES recordings(project_id, recording_id);

ALTER TABLE repair_proposals ADD FOREIGN KEY (project_id, episode_id) REFERENCES healing_episodes(project_id, episode_id);

ALTER TABLE repair_proposals ADD FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id);

ALTER TABLE repair_proposals ADD FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id);

ALTER TABLE repair_proposals ADD FOREIGN KEY (project_id, package_id) REFERENCES replay_packages(project_id, package_id);

ALTER TABLE replay_packages ADD FOREIGN KEY (project_id, case_id, case_version_id)
                REFERENCES case_versions(project_id, case_id, version_id);

ALTER TABLE replay_packages ADD FOREIGN KEY (project_id, case_id, source_manifest_id)
                REFERENCES recording_manifests(project_id, case_id, manifest_id);

ALTER TABLE resource_aliases ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE resource_aliases ADD FOREIGN KEY (physical_key_id) REFERENCES physical_resource_keys(physical_key_id);

ALTER TABLE resource_inventory ADD FOREIGN KEY (physical_key_id) REFERENCES physical_resource_keys(physical_key_id);

ALTER TABLE resource_observations ADD FOREIGN KEY (project_id, resource_id)
                REFERENCES resource_aliases(project_id, physical_key_id);

ALTER TABLE resource_observations ADD FOREIGN KEY (project_id, probe_job_id) REFERENCES jobs(project_id, job_id);

ALTER TABLE resource_observations ADD FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id);

ALTER TABLE resource_quarantine ADD FOREIGN KEY (physical_key_id) REFERENCES physical_resource_keys(physical_key_id);

ALTER TABLE restore_activations ADD FOREIGN KEY (project_id, validation_id)
                REFERENCES restore_validations(project_id, validation_id);

ALTER TABLE restore_validations ADD FOREIGN KEY (project_id, receipt_id) REFERENCES backup_receipts(project_id, receipt_id);

ALTER TABLE retention_command_receipts ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE retention_tombstones ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE review_decisions ADD FOREIGN KEY (project_id, review_id) REFERENCES reviews(project_id, review_id);

ALTER TABLE review_evidence_entries ADD FOREIGN KEY (project_id, review_id) REFERENCES reviews(project_id, review_id);

ALTER TABLE review_evidence_entries ADD FOREIGN KEY (project_id, attempt_id, action_id)
                REFERENCES actions(project_id, attempt_id, action_id);

ALTER TABLE review_evidence_entries ADD FOREIGN KEY (project_id, artifact_ref_id) REFERENCES artifact_refs(project_id, artifact_id);

ALTER TABLE review_materialization_claims ADD FOREIGN KEY(project_id,receipt_id) REFERENCES materialization_receipts(project_id,receipt_id)
                DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE review_materialization_claims ADD FOREIGN KEY(project_id,case_id,manifest_id)
                REFERENCES recording_manifests(project_id,case_id,manifest_id)
                DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE review_materialization_claims ADD FOREIGN KEY(project_id,case_id,produced_version_id,manifest_id)
                REFERENCES case_versions(project_id,case_id,version_id,source_manifest_id)
                DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE review_package_pair_claims ADD FOREIGN KEY (project_id,case_id,version_id,package_id)
                REFERENCES case_versions(project_id,case_id,version_id,replay_package_id)
                DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE review_package_pair_claims ADD FOREIGN KEY (project_id,case_id,version_id,package_id,ready)
                REFERENCES replay_packages(project_id,case_id,case_version_id,package_id,ready)
                DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE review_package_pair_claims ADD FOREIGN KEY (project_id,case_id,version_id,package_id)
                REFERENCES package_version_links(project_id,case_id,version_id,package_id)
                DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE review_package_source_claims ADD FOREIGN KEY(project_id,case_id,package_id,version_id,manifest_id,manifest_hash)
                REFERENCES replay_packages(project_id,case_id,package_id,case_version_id,source_manifest_id,source_manifest_hash)
                DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE review_package_source_claims ADD FOREIGN KEY(project_id,case_id,version_id,manifest_id)
                REFERENCES case_versions(project_id,case_id,version_id,source_manifest_id)
                DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE review_package_source_claims ADD FOREIGN KEY(project_id,case_id,manifest_id,manifest_hash)
                REFERENCES recording_manifests(project_id,case_id,manifest_id,body_hash)
                DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE review_retention_events ADD FOREIGN KEY (project_id, review_id) REFERENCES reviews(project_id, review_id);

ALTER TABLE review_retention_events ADD FOREIGN KEY (project_id, protection_id) REFERENCES artifact_protections(project_id, protection_id);

ALTER TABLE review_retention_events ADD FOREIGN KEY (project_id, artifact_id) REFERENCES artifact_refs(project_id, artifact_id);

ALTER TABLE review_version_source_claims ADD FOREIGN KEY(project_id,case_id,version_id,manifest_id)
                REFERENCES case_versions(project_id,case_id,version_id,source_manifest_id)
                DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE review_version_source_claims ADD FOREIGN KEY(project_id,case_id,manifest_id)
                REFERENCES recording_manifests(project_id,case_id,manifest_id)
                DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE reviews ADD FOREIGN KEY (project_id, case_id, case_version_id)
                REFERENCES case_versions(project_id, case_id, version_id);

ALTER TABLE reviews ADD FOREIGN KEY (project_id, source_manifest_id)
                REFERENCES recording_manifests(project_id, manifest_id);

ALTER TABLE reviews ADD FOREIGN KEY (project_id, trial_case_run_id)
                REFERENCES case_runs(project_id, case_run_id);

ALTER TABLE runner_hosts ADD FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id);

ALTER TABLE runtime_overrides ADD FOREIGN KEY (project_id, episode_id) REFERENCES healing_episodes(project_id, episode_id);

ALTER TABLE runtime_overrides ADD FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id);

ALTER TABLE runtime_overrides ADD FOREIGN KEY (project_id, attempt_id) REFERENCES attempts(project_id, attempt_id);

ALTER TABLE runtime_overrides ADD FOREIGN KEY (project_id, package_id) REFERENCES replay_packages(project_id, package_id);

ALTER TABLE secret_ref_audits ADD FOREIGN KEY (project_id, ref_id, revision)
                REFERENCES secret_refs(project_id, ref_id, revision);

ALTER TABLE secret_ref_snapshots ADD FOREIGN KEY (project_id, ref_id, revision)
                REFERENCES secret_refs(project_id, ref_id, revision);

ALTER TABLE secret_refs ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE suite_entries ADD FOREIGN KEY (project_id, suite_version_id)
                REFERENCES suite_versions(project_id, suite_version_id);

ALTER TABLE suite_receipts ADD FOREIGN KEY (project_id, suite_id) REFERENCES suites(project_id, suite_id);

ALTER TABLE suite_versions ADD FOREIGN KEY (project_id, suite_id) REFERENCES suites(project_id, suite_id);

ALTER TABLE suites ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE tags ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE tc_versions ADD FOREIGN KEY (project_id, tc_id) REFERENCES test_cases(project_id, tc_id);

ALTER TABLE test_cases ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE usage_adjustments ADD FOREIGN KEY (project_id, case_run_id) REFERENCES case_runs(project_id, case_run_id);

ALTER TABLE worker_enrollment_codes ADD FOREIGN KEY (enrollment_id) REFERENCES worker_enrollments(enrollment_id);

ALTER TABLE worker_enrollments ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE worker_presence ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE worker_presence ADD FOREIGN KEY (token_id) REFERENCES worker_tokens(token_id) ON DELETE CASCADE;

ALTER TABLE worker_retired_boots ADD FOREIGN KEY (project_id) REFERENCES projects(project_id);

ALTER TABLE worker_retired_boots ADD FOREIGN KEY (token_id) REFERENCES worker_tokens(token_id) ON DELETE CASCADE;

ALTER TABLE worker_tokens ADD FOREIGN KEY (enrollment_id) REFERENCES worker_enrollments(enrollment_id);

CREATE FUNCTION aiqa_guard_action_reviews_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'action review is append-only';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER action_reviews_no_delete BEFORE DELETE ON action_reviews FOR EACH ROW EXECUTE FUNCTION aiqa_guard_action_reviews_no_delete();

CREATE FUNCTION aiqa_guard_action_reviews_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'action review is append-only';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER action_reviews_no_update BEFORE UPDATE ON action_reviews FOR EACH ROW EXECUTE FUNCTION aiqa_guard_action_reviews_no_update();

CREATE FUNCTION aiqa_guard_analysis_records_immutable() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'analysis record is append-only';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER analysis_records_immutable BEFORE UPDATE ON analysis_records FOR EACH ROW EXECUTE FUNCTION aiqa_guard_analysis_records_immutable();

CREATE FUNCTION aiqa_guard_approval_events_match_review() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NOT EXISTS (
            SELECT 1 FROM reviews
            WHERE project_id = NEW.project_id
              AND review_id = NEW.review_id
              AND case_id = NEW.case_id
        ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'approval review is outside the case';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER approval_events_match_review BEFORE INSERT ON approval_events FOR EACH ROW EXECUTE FUNCTION aiqa_guard_approval_events_match_review();

CREATE FUNCTION aiqa_guard_approval_events_revoke_target() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.event_kind = 'revoked'
          AND NOT EXISTS (
            SELECT 1 FROM approval_events
            WHERE project_id = NEW.project_id
              AND approval_id = NEW.prior_approval_id
              AND event_kind = 'approved'
              AND case_id = NEW.case_id
          ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'revoke requires the approved event';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER approval_events_revoke_target BEFORE INSERT ON approval_events FOR EACH ROW EXECUTE FUNCTION aiqa_guard_approval_events_revoke_target();

CREATE FUNCTION aiqa_guard_approval_pin_releases_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'approval pin grace is permanent';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER approval_pin_releases_no_delete BEFORE DELETE ON approval_pin_releases FOR EACH ROW EXECUTE FUNCTION aiqa_guard_approval_pin_releases_no_delete();

CREATE FUNCTION aiqa_guard_approval_pin_releases_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'approval pin grace is permanent';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER approval_pin_releases_no_update BEFORE UPDATE ON approval_pin_releases FOR EACH ROW EXECUTE FUNCTION aiqa_guard_approval_pin_releases_no_update();

CREATE FUNCTION aiqa_guard_approval_queue_blocks_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'approval queue block is permanent';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER approval_queue_blocks_no_delete BEFORE DELETE ON approval_queue_blocks FOR EACH ROW EXECUTE FUNCTION aiqa_guard_approval_queue_blocks_no_delete();

CREATE FUNCTION aiqa_guard_approval_queue_blocks_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'approval queue block is permanent';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER approval_queue_blocks_no_update BEFORE UPDATE ON approval_queue_blocks FOR EACH ROW EXECUTE FUNCTION aiqa_guard_approval_queue_blocks_no_update();

CREATE FUNCTION aiqa_guard_artifact_objects_content_immutable() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF OLD.status='ready' THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'ready evidence metadata is immutable';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER artifact_objects_content_immutable BEFORE UPDATE OF project_id,artifact_id,object_key,content_hash,byte_length,media_type,owner_id,owner_kind, attempt_id,action_id,check_id,role,job_id,generation,status,acked ON artifact_objects FOR EACH ROW EXECUTE FUNCTION aiqa_guard_artifact_objects_content_immutable();

CREATE FUNCTION aiqa_guard_artifact_objects_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF OLD.status='ready' THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'ready evidence metadata is immutable';
    END IF;
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER artifact_objects_no_delete BEFORE DELETE ON artifact_objects FOR EACH ROW EXECUTE FUNCTION aiqa_guard_artifact_objects_no_delete();

CREATE FUNCTION aiqa_guard_artifact_objects_no_promotion() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF OLD.status<>'ready' AND (NEW.status='ready' OR NEW.acked=1) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'ready evidence must be created atomically with provenance';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER artifact_objects_no_promotion BEFORE UPDATE ON artifact_objects FOR EACH ROW EXECUTE FUNCTION aiqa_guard_artifact_objects_no_promotion();

CREATE FUNCTION aiqa_guard_artifact_ready_requires_typed_owner() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.status='ready' AND (NEW.owner_kind IS NULL OR NEW.owner_kind NOT IN ('REC','ITEM') OR NEW.role IS NULL
        OR NOT EXISTS (
          SELECT 1 FROM jobs j JOIN attempts a USING(project_id,job_id)
          WHERE j.project_id=NEW.project_id AND j.job_id=NEW.job_id
            AND a.attempt_id=NEW.attempt_id AND a.generation=NEW.generation
            AND ((NEW.owner_kind='REC' AND j.recording_id=NEW.owner_id)
              OR (NEW.owner_kind='ITEM' AND j.case_run_id=NEW.owner_id)))
        OR NOT EXISTS (
          SELECT 1 FROM artifact_refs r WHERE r.project_id=NEW.project_id AND r.artifact_id=NEW.artifact_id
          AND ((NEW.action_id IS NOT NULL AND NEW.check_id IS NULL AND r.action_id=NEW.action_id AND r.attempt_id=NEW.attempt_id)
            OR (NEW.check_id IS NOT NULL AND NEW.action_id IS NULL AND r.check_id=NEW.check_id AND r.attempt_id=NEW.attempt_id)
            OR (NEW.action_id IS NULL AND NEW.check_id IS NULL AND NEW.owner_kind='REC' AND r.recording_id=NEW.owner_id)))
        OR NEW.role NOT IN ('before','after','log','check','source')
        OR (NEW.role IN ('before','after') AND NEW.action_id IS NULL)
        OR (NEW.role='check' AND NEW.check_id IS NULL)
        OR ((NEW.action_id IS NOT NULL OR NEW.check_id IS NOT NULL) AND NOT EXISTS (
          SELECT 1 FROM actions a
          LEFT JOIN check_results c ON c.project_id=a.project_id AND c.attempt_id=a.attempt_id AND c.action_id=a.action_id
          JOIN jobs j ON j.project_id=a.project_id AND j.job_id=NEW.job_id
          LEFT JOIN recordings r ON r.project_id=j.project_id AND r.recording_id=j.recording_id
          LEFT JOIN case_runs i ON i.project_id=j.project_id AND i.case_run_id=j.case_run_id
          WHERE a.project_id=NEW.project_id AND a.attempt_id=NEW.attempt_id
          AND ((NEW.action_id IS NOT NULL AND a.action_id=NEW.action_id)
            OR (NEW.check_id IS NOT NULL AND c.check_id=NEW.check_id))
          AND ((NEW.owner_kind='REC' AND a.case_id=r.case_id AND a.case_version_id=r.input_case_version_id)
            OR (NEW.owner_kind='ITEM' AND a.case_id=i.case_id AND a.case_version_id=i.case_version_id))))
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'ready evidence requires exact typed ownership';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER artifact_ready_requires_typed_owner BEFORE INSERT ON artifact_objects FOR EACH ROW EXECUTE FUNCTION aiqa_guard_artifact_ready_requires_typed_owner();

CREATE FUNCTION aiqa_guard_artifact_refs_healing_owner() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.healing_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM healing_episodes
            WHERE project_id = NEW.project_id AND episode_id = NEW.healing_id
          ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'healing owner is missing';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER artifact_refs_healing_owner BEFORE INSERT ON artifact_refs FOR EACH ROW EXECUTE FUNCTION aiqa_guard_artifact_refs_healing_owner();

CREATE FUNCTION aiqa_guard_artifact_refs_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'evidence provenance is immutable';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER artifact_refs_no_delete BEFORE DELETE ON artifact_refs FOR EACH ROW EXECUTE FUNCTION aiqa_guard_artifact_refs_no_delete();

CREATE FUNCTION aiqa_guard_artifact_refs_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'evidence provenance is immutable';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER artifact_refs_no_update BEFORE UPDATE ON artifact_refs FOR EACH ROW EXECUTE FUNCTION aiqa_guard_artifact_refs_no_update();

CREATE FUNCTION aiqa_guard_artifact_refs_observation_owner() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.resource_observation_id IS NOT NULL
          AND (
            NEW.artifact_id <> NEW.resource_observation_id
            OR NEW.attempt_id IS NULL
            OR NOT EXISTS (
                SELECT 1 FROM resource_observations
                WHERE project_id = NEW.project_id
                  AND artifact_id = NEW.resource_observation_id
                  AND attempt_id = NEW.attempt_id
            )
          ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'observation owner does not match the capture';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER artifact_refs_observation_owner BEFORE INSERT ON artifact_refs FOR EACH ROW EXECUTE FUNCTION aiqa_guard_artifact_refs_observation_owner();

CREATE FUNCTION aiqa_guard_artifact_refs_package_owner() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.package_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM replay_packages
            WHERE project_id = NEW.project_id AND package_id = NEW.package_id
          ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'package owner is missing';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER artifact_refs_package_owner BEFORE INSERT ON artifact_refs FOR EACH ROW EXECUTE FUNCTION aiqa_guard_artifact_refs_package_owner();

CREATE FUNCTION aiqa_guard_artifact_refs_probe_not_recording_after() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.recording_id IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM resource_observations
            WHERE project_id = NEW.project_id AND artifact_id = NEW.artifact_id
          ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'probe capture is not a recording after image';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER artifact_refs_probe_not_recording_after BEFORE INSERT ON artifact_refs FOR EACH ROW EXECUTE FUNCTION aiqa_guard_artifact_refs_probe_not_recording_after();

CREATE FUNCTION aiqa_guard_artifact_refs_proposal_owner() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.proposal_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM repair_proposals
            WHERE project_id = NEW.project_id AND proposal_id = NEW.proposal_id
          ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'proposal owner is missing';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER artifact_refs_proposal_owner BEFORE INSERT ON artifact_refs FOR EACH ROW EXECUTE FUNCTION aiqa_guard_artifact_refs_proposal_owner();

CREATE FUNCTION aiqa_guard_attempt_events_hash_conflict() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF EXISTS (
            SELECT 1 FROM attempt_events
            WHERE project_id = NEW.project_id
              AND attempt_id = NEW.attempt_id
              AND local_seq = NEW.local_seq
              AND (payload_hash <> NEW.payload_hash OR body_hash <> NEW.body_hash)
        ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'event hash conflict';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER attempt_events_hash_conflict BEFORE INSERT ON attempt_events FOR EACH ROW EXECUTE FUNCTION aiqa_guard_attempt_events_hash_conflict();

CREATE FUNCTION aiqa_guard_attempt_events_protect_facts() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF OLD.sealed = 1
          OR NEW.attempt_id <> OLD.attempt_id
          OR NEW.local_seq <> OLD.local_seq
          OR NEW.payload_hash <> OLD.payload_hash
          OR NEW.body_hash <> OLD.body_hash
          OR NEW.minimum_facts <> OLD.minimum_facts
          OR NEW.event_id <> OLD.event_id THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'event fact is sealed';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER attempt_events_protect_facts BEFORE UPDATE ON attempt_events FOR EACH ROW EXECUTE FUNCTION aiqa_guard_attempt_events_protect_facts();

CREATE FUNCTION aiqa_guard_automation_cases_approval_pointer() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.current_approval_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM approval_events
            WHERE project_id = NEW.project_id
              AND approval_id = NEW.current_approval_id
              AND case_id = NEW.case_id
              AND event_kind = 'approved'
          ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'approval pointer is outside the case';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER automation_cases_approval_pointer BEFORE UPDATE OF current_approval_id ON automation_cases FOR EACH ROW EXECUTE FUNCTION aiqa_guard_automation_cases_approval_pointer();

CREATE FUNCTION aiqa_guard_binding_revisions_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'binding_revisions content is immutable';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER binding_revisions_no_delete BEFORE DELETE ON binding_revisions FOR EACH ROW EXECUTE FUNCTION aiqa_guard_binding_revisions_no_delete();

CREATE FUNCTION aiqa_guard_binding_revisions_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'binding_revisions content is immutable';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER binding_revisions_no_update BEFORE UPDATE ON binding_revisions FOR EACH ROW EXECUTE FUNCTION aiqa_guard_binding_revisions_no_update();

CREATE FUNCTION aiqa_guard_case_edit_proposals_immutable() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'case proposal is immutable';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER case_edit_proposals_immutable BEFORE UPDATE ON case_edit_proposals FOR EACH ROW EXECUTE FUNCTION aiqa_guard_case_edit_proposals_immutable();

CREATE FUNCTION aiqa_guard_case_edit_proposals_structure_case() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.kind = 'structure'
          AND NOT EXISTS (
            SELECT 1 FROM jobs
            JOIN aiqa_json_each(jobs.source_refs) AS source_ref
              ON source_ref.value = NEW.case_id
            WHERE jobs.project_id = NEW.project_id
              AND jobs.job_id = NEW.source_job_id
              AND jobs.purpose = 'structure'
          ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'structure job belongs to another case';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER case_edit_proposals_structure_case BEFORE INSERT ON case_edit_proposals FOR EACH ROW EXECUTE FUNCTION aiqa_guard_case_edit_proposals_structure_case();

CREATE FUNCTION aiqa_guard_case_proposal_decisions_immutable() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'proposal decision is append-only';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER case_proposal_decisions_immutable BEFORE UPDATE ON case_proposal_decisions FOR EACH ROW EXECUTE FUNCTION aiqa_guard_case_proposal_decisions_immutable();

CREATE FUNCTION aiqa_guard_case_runs_match_execution() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NOT EXISTS (
            SELECT 1 FROM executions
            WHERE project_id = NEW.project_id
              AND execution_id = NEW.execution_id
              AND purpose = NEW.purpose
              AND scope_requested_at = NEW.requested_at
        ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'item scope does not match the execution';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER case_runs_match_execution BEFORE INSERT ON case_runs FOR EACH ROW EXECUTE FUNCTION aiqa_guard_case_runs_match_execution();

CREATE FUNCTION aiqa_guard_case_versions_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'case version content is immutable';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER case_versions_no_delete BEFORE DELETE ON case_versions FOR EACH ROW EXECUTE FUNCTION aiqa_guard_case_versions_no_delete();

CREATE FUNCTION aiqa_guard_case_versions_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'case version content is immutable';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER case_versions_no_update BEFORE UPDATE ON case_versions FOR EACH ROW EXECUTE FUNCTION aiqa_guard_case_versions_no_update();

CREATE FUNCTION aiqa_guard_dataset_versions_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'dataset_versions content is immutable';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER dataset_versions_no_delete BEFORE DELETE ON dataset_versions FOR EACH ROW EXECUTE FUNCTION aiqa_guard_dataset_versions_no_delete();

CREATE FUNCTION aiqa_guard_dataset_versions_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'dataset_versions content is immutable';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER dataset_versions_no_update BEFORE UPDATE ON dataset_versions FOR EACH ROW EXECUTE FUNCTION aiqa_guard_dataset_versions_no_update();

CREATE FUNCTION aiqa_guard_dispatch_journal_no_lookup_after_start() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.dispatch_state = 'lookup_failed'
          AND EXISTS (
            SELECT 1 FROM dispatch_journal
            WHERE project_id = NEW.project_id
              AND attempt_id = NEW.attempt_id
              AND action_seq = NEW.action_seq
              AND dispatch_state = 'dispatch_started'
          ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'lookup_failed cannot follow dispatch_started';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER dispatch_journal_no_lookup_after_start BEFORE INSERT ON dispatch_journal FOR EACH ROW EXECUTE FUNCTION aiqa_guard_dispatch_journal_no_lookup_after_start();

CREATE FUNCTION aiqa_guard_environment_revisions_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'environment_revisions content is immutable';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER environment_revisions_no_delete BEFORE DELETE ON environment_revisions FOR EACH ROW EXECUTE FUNCTION aiqa_guard_environment_revisions_no_delete();

CREATE FUNCTION aiqa_guard_environment_revisions_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'environment_revisions content is immutable';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER environment_revisions_no_update BEFORE UPDATE ON environment_revisions FOR EACH ROW EXECUTE FUNCTION aiqa_guard_environment_revisions_no_update();

CREATE FUNCTION aiqa_guard_executions_suite_ref() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF (NEW.source = 'suite' AND NEW.suite_version_id IS NULL)
          OR (NEW.source <> 'suite' AND NEW.suite_version_id IS NOT NULL) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'suite version belongs only to a suite execution';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER executions_suite_ref BEFORE INSERT ON executions FOR EACH ROW EXECUTE FUNCTION aiqa_guard_executions_suite_ref();

CREATE FUNCTION aiqa_guard_fingerprint_observations_same_case() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NOT EXISTS (
            SELECT 1 FROM case_runs
            WHERE project_id = NEW.project_id
              AND case_run_id = NEW.case_run_id
              AND case_id = NEW.case_id
        ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'fingerprint case does not match the item';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER fingerprint_observations_same_case BEFORE INSERT ON fingerprint_observations FOR EACH ROW EXECUTE FUNCTION aiqa_guard_fingerprint_observations_same_case();

CREATE FUNCTION aiqa_guard_healing_episodes_same_case() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NOT EXISTS (
            SELECT 1
            FROM case_runs
            JOIN attempts
              ON attempts.project_id = case_runs.project_id
             AND attempts.attempt_id = NEW.attempt_id
            JOIN jobs
              ON jobs.project_id = attempts.project_id
             AND jobs.job_id = attempts.job_id
             AND jobs.case_run_id = case_runs.case_run_id
            JOIN replay_packages
              ON replay_packages.project_id = NEW.project_id
             AND replay_packages.package_id = NEW.package_id
             AND replay_packages.case_id = case_runs.case_id
            WHERE case_runs.project_id = NEW.project_id
              AND case_runs.case_run_id = NEW.case_run_id
        ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'episode is outside the item package';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER healing_episodes_same_case BEFORE INSERT ON healing_episodes FOR EACH ROW EXECUTE FUNCTION aiqa_guard_healing_episodes_same_case();

CREATE FUNCTION aiqa_guard_healing_reservations_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'healing reservation is permanent';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER healing_reservations_no_delete BEFORE DELETE ON healing_reservations FOR EACH ROW EXECUTE FUNCTION aiqa_guard_healing_reservations_no_delete();

CREATE FUNCTION aiqa_guard_healing_reservations_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'healing reservation is permanent';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER healing_reservations_no_update BEFORE UPDATE ON healing_reservations FOR EACH ROW EXECUTE FUNCTION aiqa_guard_healing_reservations_no_update();

CREATE FUNCTION aiqa_guard_healing_reservations_unsent_action() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.action_id IS NOT NULL AND NOT EXISTS (
            SELECT 1
            FROM healing_episodes AS episode
            JOIN actions AS action
              ON action.project_id = episode.project_id
             AND action.attempt_id = episode.attempt_id
             AND action.action_id = NEW.action_id
            WHERE episode.project_id = NEW.project_id
              AND episode.episode_id = NEW.episode_id
              AND action.dispatch_state IN ('planned', 'lookup_failed')
              AND NOT EXISTS (
                  SELECT 1 FROM dispatch_journal AS journal
                  WHERE journal.project_id = action.project_id
                    AND journal.attempt_id = action.attempt_id
                    AND journal.action_seq = action.action_seq
                    AND journal.dispatch_state IN ('dispatch_started', 'acknowledged', 'observed', 'unknown')
              )
        ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'healing action was sent';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER healing_reservations_unsent_action BEFORE INSERT ON healing_reservations FOR EACH ROW EXECUTE FUNCTION aiqa_guard_healing_reservations_unsent_action();

CREATE FUNCTION aiqa_guard_item_finalizations_immutable() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'item finalization is immutable';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER item_finalizations_immutable BEFORE UPDATE ON item_finalizations FOR EACH ROW EXECUTE FUNCTION aiqa_guard_item_finalizations_immutable();

CREATE FUNCTION aiqa_guard_item_lifecycle_events_immutable() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'lifecycle event is append-only';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER item_lifecycle_events_immutable BEFORE UPDATE ON item_lifecycle_events FOR EACH ROW EXECUTE FUNCTION aiqa_guard_item_lifecycle_events_immutable();

CREATE FUNCTION aiqa_guard_item_usage_facts_immutable() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'usage fact is immutable';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER item_usage_facts_immutable BEFORE UPDATE ON item_usage_facts FOR EACH ROW EXECUTE FUNCTION aiqa_guard_item_usage_facts_immutable();

CREATE FUNCTION aiqa_guard_job_finish_facts_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'job finish fact is permanent';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER job_finish_facts_no_delete BEFORE DELETE ON job_finish_facts FOR EACH ROW EXECUTE FUNCTION aiqa_guard_job_finish_facts_no_delete();

CREATE FUNCTION aiqa_guard_job_finish_facts_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'job finish fact is permanent';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER job_finish_facts_no_update BEFORE UPDATE ON job_finish_facts FOR EACH ROW EXECUTE FUNCTION aiqa_guard_job_finish_facts_no_update();

CREATE FUNCTION aiqa_guard_jobs_match_execution_purpose() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.purpose IN ('trial', 'regression')
          AND NOT EXISTS (
            SELECT 1
            FROM case_runs AS runs
            JOIN executions AS runs_exec
              ON runs_exec.project_id = runs.project_id
             AND runs_exec.execution_id = runs.execution_id
            WHERE runs.project_id = NEW.project_id
              AND runs.case_run_id = NEW.case_run_id
              AND runs.requested_at = runs_exec.scope_requested_at
              AND runs.purpose = runs_exec.purpose
              AND (
                (NEW.purpose = 'trial' AND runs_exec.purpose = 'trial')
                OR (
                    NEW.purpose = 'regression'
                    AND runs_exec.purpose IN ('regression', 'reverification')
                )
              )
          ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'job purpose does not match the item execution';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER jobs_match_execution_purpose BEFORE INSERT ON jobs FOR EACH ROW EXECUTE FUNCTION aiqa_guard_jobs_match_execution_purpose();

CREATE FUNCTION aiqa_guard_jobs_pin_worker_session() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.status = 'queued'
          AND NEW.purpose IN ('recording','trial','regression','resource_probe','app_install') THEN
        INSERT INTO job_worker_sessions (project_id, job_id, worker_id, session_id)
            SELECT DISTINCT NEW.project_id, NEW.job_id, presence.worker_id, presence.session_id
            FROM aiqa_json_each(
                CASE
                    WHEN NEW.purpose IN ('trial', 'regression')
                        AND aiqa_json_type(
                            CASE WHEN aiqa_json_valid(NEW.limits) THEN NEW.limits ELSE '{}' END, '$.resource_id'
                        ) = 'text'
                    THEN aiqa_json_array(aiqa_json_extract(NEW.limits, '$.resource_id'))
                    WHEN aiqa_json_valid(NEW.source_refs) THEN NEW.source_refs
                    ELSE '[]'
                END
            ) AS ref
            JOIN resource_aliases AS alias
              ON alias.project_id = NEW.project_id AND alias.physical_key_id = ref.value
            JOIN physical_resource_keys AS resource ON resource.physical_key_id = alias.physical_key_id
            JOIN worker_presence AS presence
              ON presence.project_id = NEW.project_id AND presence.worker_id = resource.worker_id;
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER jobs_pin_worker_session AFTER INSERT ON jobs FOR EACH ROW EXECUTE FUNCTION aiqa_guard_jobs_pin_worker_session();

CREATE FUNCTION aiqa_guard_model_call_facts_unknown_usage() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.measurement_status IN ('unknown', 'unreported', 'not_used')
          AND (
            NEW.input_tokens IS NOT NULL
            OR NEW.output_tokens IS NOT NULL
            OR NEW.cache_tokens IS NOT NULL
            OR NEW.image_tokens IS NOT NULL
          ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'unknown usage has no token count';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER model_call_facts_unknown_usage BEFORE INSERT ON model_call_facts FOR EACH ROW EXECUTE FUNCTION aiqa_guard_model_call_facts_unknown_usage();

CREATE FUNCTION aiqa_guard_model_observation_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'model observation is immutable';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER model_observation_no_delete BEFORE DELETE ON model_observations FOR EACH ROW EXECUTE FUNCTION aiqa_guard_model_observation_no_delete();

CREATE FUNCTION aiqa_guard_model_observation_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'model observation is immutable';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER model_observation_no_update BEFORE UPDATE ON model_observations FOR EACH ROW EXECUTE FUNCTION aiqa_guard_model_observation_no_update();

CREATE FUNCTION aiqa_guard_model_request_receipt_immutable() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF OLD.state='completed'
          OR NEW.project_id<>OLD.project_id OR NEW.attempt_id<>OLD.attempt_id
          OR NEW.request_key<>OLD.request_key OR NEW.call_id<>OLD.call_id
          OR NEW.worker_id<>OLD.worker_id OR NEW.fingerprint<>OLD.fingerprint
          OR NEW.policy_ref<>OLD.policy_ref OR NEW.created_at<>OLD.created_at OR NEW.price_mode<>OLD.price_mode THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'model request receipt is immutable';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER model_request_receipt_immutable BEFORE UPDATE ON model_request_receipts FOR EACH ROW EXECUTE FUNCTION aiqa_guard_model_request_receipt_immutable();

CREATE FUNCTION aiqa_guard_model_request_receipt_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'model request receipt is immutable';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER model_request_receipt_no_delete BEFORE DELETE ON model_request_receipts FOR EACH ROW EXECUTE FUNCTION aiqa_guard_model_request_receipt_no_delete();

CREATE FUNCTION aiqa_guard_physical_resource_keys_identity() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'physical key is immutable';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER physical_resource_keys_identity BEFORE UPDATE OF worker_id, native_id ON physical_resource_keys FOR EACH ROW EXECUTE FUNCTION aiqa_guard_physical_resource_keys_identity();

CREATE FUNCTION aiqa_guard_physical_resource_keys_require_worker() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NOT EXISTS (
            SELECT 1 FROM worker_enrollments WHERE worker_id = NEW.worker_id
        ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'unknown worker';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER physical_resource_keys_require_worker BEFORE INSERT ON physical_resource_keys FOR EACH ROW EXECUTE FUNCTION aiqa_guard_physical_resource_keys_require_worker();

CREATE FUNCTION aiqa_guard_protection_releases_manual_only() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NOT EXISTS (
            SELECT 1 FROM artifact_protections
            WHERE project_id = NEW.project_id
              AND protection_id = NEW.protection_id
              AND kind = 'manual'
        ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'only a manual protection is released here';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER protection_releases_manual_only BEFORE INSERT ON protection_releases FOR EACH ROW EXECUTE FUNCTION aiqa_guard_protection_releases_manual_only();

CREATE FUNCTION aiqa_guard_recording_check_binding_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'recording check binding is immutable';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER recording_check_binding_no_delete BEFORE DELETE ON recording_check_bindings FOR EACH ROW EXECUTE FUNCTION aiqa_guard_recording_check_binding_no_delete();

CREATE FUNCTION aiqa_guard_recording_check_binding_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'recording check binding is immutable';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER recording_check_binding_no_update BEFORE UPDATE ON recording_check_bindings FOR EACH ROW EXECUTE FUNCTION aiqa_guard_recording_check_binding_no_update();

CREATE FUNCTION aiqa_guard_recording_check_binding_owner_insert() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NOT EXISTS (
            SELECT 1 FROM recordings r
            JOIN recording_manifests m ON m.project_id=r.project_id AND m.recording_id=r.recording_id AND m.case_id=r.case_id
            JOIN recording_manifests s ON s.project_id=r.project_id AND s.recording_id=r.recording_id AND s.case_id=r.case_id
            JOIN case_versions v ON v.project_id=r.project_id AND v.version_id=r.input_case_version_id AND v.case_id=r.case_id
            WHERE r.project_id=NEW.project_id AND r.recording_id=NEW.recording_id
              AND m.manifest_id=NEW.manifest_id AND m.kind='package_rebuild'
              AND s.manifest_id=NEW.source_manifest_id AND m.prior_manifest_id=s.manifest_id
              AND s.body_hash=NEW.source_manifest_hash AND r.input_case_version_id=NEW.input_case_version_id
              AND m.action_mapping=s.action_mapping AND m.source_artifact_hashes=s.source_artifact_hashes
              AND m.input_version_hash=v.content_hash AND r.completion_status='completed'
              AND m.evidence_completeness='complete' AND s.evidence_completeness='complete'
        ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'recording check binding source or owner differs';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER recording_check_binding_owner_insert BEFORE INSERT ON recording_check_bindings FOR EACH ROW EXECUTE FUNCTION aiqa_guard_recording_check_binding_owner_insert();

CREATE FUNCTION aiqa_guard_recording_manifests_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'manifest is immutable';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER recording_manifests_no_update BEFORE UPDATE ON recording_manifests FOR EACH ROW EXECUTE FUNCTION aiqa_guard_recording_manifests_no_update();

CREATE FUNCTION aiqa_guard_recording_notes_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'recording note is append-only';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER recording_notes_no_delete BEFORE DELETE ON recording_notes FOR EACH ROW EXECUTE FUNCTION aiqa_guard_recording_notes_no_delete();

CREATE FUNCTION aiqa_guard_recording_notes_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'recording note is append-only';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER recording_notes_no_update BEFORE UPDATE ON recording_notes FOR EACH ROW EXECUTE FUNCTION aiqa_guard_recording_notes_no_update();

CREATE FUNCTION aiqa_guard_recordings_protect_identity() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'recording identity is immutable';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER recordings_protect_identity BEFORE UPDATE OF input_case_version_id, base_case_version_id, parent_recording_id, source_recording_id, creation_kind, case_id ON recordings FOR EACH ROW EXECUTE FUNCTION aiqa_guard_recordings_protect_identity();

CREATE FUNCTION aiqa_guard_repair_adoptions_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'adoption is append-only';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER repair_adoptions_no_delete BEFORE DELETE ON repair_adoptions FOR EACH ROW EXECUTE FUNCTION aiqa_guard_repair_adoptions_no_delete();

CREATE FUNCTION aiqa_guard_repair_adoptions_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'adoption is append-only';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER repair_adoptions_no_update BEFORE UPDATE ON repair_adoptions FOR EACH ROW EXECUTE FUNCTION aiqa_guard_repair_adoptions_no_update();

CREATE FUNCTION aiqa_guard_repair_proposals_immutable() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'repair proposal is immutable';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER repair_proposals_immutable BEFORE UPDATE ON repair_proposals FOR EACH ROW EXECUTE FUNCTION aiqa_guard_repair_proposals_immutable();

CREATE FUNCTION aiqa_guard_repair_proposals_match_episode() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NOT EXISTS (
            SELECT 1 FROM healing_episodes
            WHERE project_id = NEW.project_id
              AND episode_id = NEW.episode_id
              AND case_run_id = NEW.case_run_id
              AND attempt_id = NEW.attempt_id
              AND package_id = NEW.package_id
        ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'proposal is outside the episode';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER repair_proposals_match_episode BEFORE INSERT ON repair_proposals FOR EACH ROW EXECUTE FUNCTION aiqa_guard_repair_proposals_match_episode();

CREATE FUNCTION aiqa_guard_resource_aliases_binding_immutable() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'alias project binding is immutable';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER resource_aliases_binding_immutable BEFORE UPDATE OF project_id, physical_key_id ON resource_aliases FOR EACH ROW EXECUTE FUNCTION aiqa_guard_resource_aliases_binding_immutable();

CREATE FUNCTION aiqa_guard_resource_aliases_require_enrollment() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NOT EXISTS (
            SELECT 1
            FROM physical_resource_keys AS keys
            JOIN worker_enrollments AS enrollments
              ON enrollments.worker_id = keys.worker_id
             AND enrollments.project_id = NEW.project_id
            WHERE keys.physical_key_id = NEW.physical_key_id
        ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'alias project does not enroll this worker';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER resource_aliases_require_enrollment BEFORE INSERT ON resource_aliases FOR EACH ROW EXECUTE FUNCTION aiqa_guard_resource_aliases_require_enrollment();

CREATE FUNCTION aiqa_guard_resource_observations_immutable() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'resource observation is append-only';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER resource_observations_immutable BEFORE UPDATE ON resource_observations FOR EACH ROW EXECUTE FUNCTION aiqa_guard_resource_observations_immutable();

CREATE FUNCTION aiqa_guard_resource_observations_match_lease() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NOT EXISTS (
            SELECT 1
            FROM attempts
            JOIN jobs
              ON jobs.project_id = attempts.project_id
             AND jobs.job_id = attempts.job_id
            JOIN leases
              ON leases.project_id = attempts.project_id
             AND leases.job_id = attempts.job_id
             AND leases.generation = attempts.generation
            WHERE attempts.project_id = NEW.project_id
              AND attempts.attempt_id = NEW.attempt_id
              AND jobs.job_id = NEW.probe_job_id
              AND jobs.purpose = 'resource_probe'
              AND leases.physical_key_id = NEW.resource_id
              AND attempts.physical_key_id = NEW.resource_id
        ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'observation does not match the probe lease';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER resource_observations_match_lease BEFORE INSERT ON resource_observations FOR EACH ROW EXECUTE FUNCTION aiqa_guard_resource_observations_match_lease();

CREATE FUNCTION aiqa_guard_review_analysis_records_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER review_analysis_records_no_delete BEFORE DELETE ON analysis_records FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_analysis_records_no_delete();

CREATE FUNCTION aiqa_guard_review_analysis_records_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_analysis_records_no_update BEFORE UPDATE ON analysis_records FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_analysis_records_no_update();

CREATE FUNCTION aiqa_guard_review_case_versions_pair_insert() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.replay_package_id IS NOT NULL THEN
        INSERT INTO review_package_pair_claims
                        (project_id,case_id,version_id,package_id)
                    VALUES (NEW.project_id,NEW.case_id,NEW.version_id,NEW.replay_package_id) ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_case_versions_pair_insert AFTER INSERT ON case_versions FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_case_versions_pair_insert();

CREATE FUNCTION aiqa_guard_review_case_versions_pair_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.replay_package_id IS NOT NULL THEN
        INSERT INTO review_package_pair_claims
                        (project_id,case_id,version_id,package_id)
                    VALUES (NEW.project_id,NEW.case_id,NEW.version_id,NEW.replay_package_id) ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_case_versions_pair_update AFTER UPDATE ON case_versions FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_case_versions_pair_update();

CREATE FUNCTION aiqa_guard_review_evidence_same_owner() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NOT EXISTS (
            SELECT 1
            FROM reviews
            JOIN actions
              ON actions.project_id = NEW.project_id
             AND actions.attempt_id = NEW.attempt_id
             AND actions.action_id = NEW.action_id
            JOIN attempts
              ON attempts.project_id = actions.project_id
             AND attempts.attempt_id = actions.attempt_id
            JOIN jobs
              ON jobs.project_id = attempts.project_id
             AND jobs.job_id = attempts.job_id
            WHERE reviews.project_id = NEW.project_id
              AND reviews.review_id = NEW.review_id
              AND (
                (
                    NEW.owner_kind = 'ITEM'
                    AND jobs.case_run_id = NEW.owner_id
                    AND reviews.case_id = (
                        SELECT case_id FROM case_runs
                        WHERE project_id = NEW.project_id AND case_run_id = NEW.owner_id
                    )
                )
                OR (
                    NEW.owner_kind = 'REC'
                    AND jobs.recording_id = NEW.owner_id
                    AND EXISTS (
                        SELECT 1 FROM recordings
                        WHERE project_id = NEW.project_id
                          AND recording_id = NEW.owner_id
                          AND case_id = reviews.case_id
                    )
                )
              )
        ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'evidence owner is outside the review';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_evidence_same_owner BEFORE INSERT ON review_evidence_entries FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_evidence_same_owner();

CREATE FUNCTION aiqa_guard_review_fingerprint_observations_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER review_fingerprint_observations_no_delete BEFORE DELETE ON fingerprint_observations FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_fingerprint_observations_no_delete();

CREATE FUNCTION aiqa_guard_review_fingerprint_observations_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_fingerprint_observations_no_update BEFORE UPDATE ON fingerprint_observations FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_fingerprint_observations_no_update();

CREATE FUNCTION aiqa_guard_review_item_finalizations_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER review_item_finalizations_no_delete BEFORE DELETE ON item_finalizations FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_item_finalizations_no_delete();

CREATE FUNCTION aiqa_guard_review_item_finalizations_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_item_finalizations_no_update BEFORE UPDATE ON item_finalizations FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_item_finalizations_no_update();

CREATE FUNCTION aiqa_guard_review_item_lifecycle_events_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER review_item_lifecycle_events_no_delete BEFORE DELETE ON item_lifecycle_events FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_item_lifecycle_events_no_delete();

CREATE FUNCTION aiqa_guard_review_item_lifecycle_events_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_item_lifecycle_events_no_update BEFORE UPDATE ON item_lifecycle_events FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_item_lifecycle_events_no_update();

CREATE FUNCTION aiqa_guard_review_item_usage_facts_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER review_item_usage_facts_no_delete BEFORE DELETE ON item_usage_facts FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_item_usage_facts_no_delete();

CREATE FUNCTION aiqa_guard_review_item_usage_facts_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_item_usage_facts_no_update BEFORE UPDATE ON item_usage_facts FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_item_usage_facts_no_update();

CREATE FUNCTION aiqa_guard_review_manifest_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'sealed source manifest is immutable';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER review_manifest_no_delete BEFORE DELETE ON recording_manifests FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_manifest_no_delete();

CREATE FUNCTION aiqa_guard_review_manifest_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'sealed source manifest is immutable';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_manifest_no_update BEFORE UPDATE ON recording_manifests FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_manifest_no_update();

CREATE FUNCTION aiqa_guard_review_materialization_insert() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    INSERT INTO review_materialization_claims
            SELECT NEW.project_id,NEW.receipt_id,case_id,NEW.manifest_id,NEW.produced_version_id
            FROM recording_manifests WHERE project_id=NEW.project_id AND manifest_id=NEW.manifest_id;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_materialization_insert AFTER INSERT ON materialization_receipts FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_materialization_insert();

CREATE FUNCTION aiqa_guard_review_materialization_receipts_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER review_materialization_receipts_no_delete BEFORE DELETE ON materialization_receipts FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_materialization_receipts_no_delete();

CREATE FUNCTION aiqa_guard_review_materialization_receipts_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_materialization_receipts_no_update BEFORE UPDATE ON materialization_receipts FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_materialization_receipts_no_update();

CREATE FUNCTION aiqa_guard_review_package_source_insert() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.ready=1 THEN
        INSERT INTO review_package_source_claims VALUES
                (NEW.project_id,NEW.case_id,NEW.package_id,NEW.case_version_id,NEW.source_manifest_id,NEW.source_manifest_hash) ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_package_source_insert AFTER INSERT ON replay_packages FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_package_source_insert();

CREATE FUNCTION aiqa_guard_review_package_source_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.ready=1 THEN
        INSERT INTO review_package_source_claims VALUES
                (NEW.project_id,NEW.case_id,NEW.package_id,NEW.case_version_id,NEW.source_manifest_id,NEW.source_manifest_hash) ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_package_source_update AFTER UPDATE ON replay_packages FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_package_source_update();

CREATE FUNCTION aiqa_guard_review_package_version_links_pair_insert() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    INSERT INTO review_package_pair_claims
                        (project_id,case_id,version_id,package_id)
                    VALUES (NEW.project_id,NEW.case_id,NEW.version_id,NEW.package_id) ON CONFLICT DO NOTHING;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_package_version_links_pair_insert AFTER INSERT ON package_version_links FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_package_version_links_pair_insert();

CREATE FUNCTION aiqa_guard_review_package_version_links_pair_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    INSERT INTO review_package_pair_claims
                        (project_id,case_id,version_id,package_id)
                    VALUES (NEW.project_id,NEW.case_id,NEW.version_id,NEW.package_id) ON CONFLICT DO NOTHING;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_package_version_links_pair_update AFTER UPDATE ON package_version_links FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_package_version_links_pair_update();

CREATE FUNCTION aiqa_guard_review_replay_packages_pair_insert() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.ready = 1 THEN
        INSERT INTO review_package_pair_claims
                        (project_id,case_id,version_id,package_id)
                    VALUES (NEW.project_id,NEW.case_id,NEW.case_version_id,NEW.package_id) ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_replay_packages_pair_insert AFTER INSERT ON replay_packages FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_replay_packages_pair_insert();

CREATE FUNCTION aiqa_guard_review_replay_packages_pair_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.ready = 1 THEN
        INSERT INTO review_package_pair_claims
                        (project_id,case_id,version_id,package_id)
                    VALUES (NEW.project_id,NEW.case_id,NEW.case_version_id,NEW.package_id) ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_replay_packages_pair_update AFTER UPDATE ON replay_packages FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_replay_packages_pair_update();

CREATE FUNCTION aiqa_guard_review_retention_events_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'review retention is append-only';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER review_retention_events_no_delete BEFORE DELETE ON review_retention_events FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_retention_events_no_delete();

CREATE FUNCTION aiqa_guard_review_retention_events_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'review retention is append-only';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_retention_events_no_update BEFORE UPDATE ON review_retention_events FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_retention_events_no_update();

CREATE FUNCTION aiqa_guard_review_review_materialization_claims_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER review_review_materialization_claims_no_delete BEFORE DELETE ON review_materialization_claims FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_review_materialization_claims_no_delete();

CREATE FUNCTION aiqa_guard_review_review_materialization_claims_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_review_materialization_claims_no_update BEFORE UPDATE ON review_materialization_claims FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_review_materialization_claims_no_update();

CREATE FUNCTION aiqa_guard_review_review_package_pair_claims_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER review_review_package_pair_claims_no_delete BEFORE DELETE ON review_package_pair_claims FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_review_package_pair_claims_no_delete();

CREATE FUNCTION aiqa_guard_review_review_package_pair_claims_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_review_package_pair_claims_no_update BEFORE UPDATE ON review_package_pair_claims FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_review_package_pair_claims_no_update();

CREATE FUNCTION aiqa_guard_review_review_package_source_claims_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER review_review_package_source_claims_no_delete BEFORE DELETE ON review_package_source_claims FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_review_package_source_claims_no_delete();

CREATE FUNCTION aiqa_guard_review_review_package_source_claims_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_review_package_source_claims_no_update BEFORE UPDATE ON review_package_source_claims FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_review_package_source_claims_no_update();

CREATE FUNCTION aiqa_guard_review_review_version_source_claims_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER review_review_version_source_claims_no_delete BEFORE DELETE ON review_version_source_claims FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_review_version_source_claims_no_delete();

CREATE FUNCTION aiqa_guard_review_review_version_source_claims_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_review_version_source_claims_no_update BEFORE UPDATE ON review_version_source_claims FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_review_version_source_claims_no_update();

CREATE FUNCTION aiqa_guard_review_usage_adjustments_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER review_usage_adjustments_no_delete BEFORE DELETE ON usage_adjustments FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_usage_adjustments_no_delete();

CREATE FUNCTION aiqa_guard_review_usage_adjustments_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'permanent fact is append-only';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_usage_adjustments_no_update BEFORE UPDATE ON usage_adjustments FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_usage_adjustments_no_update();

CREATE FUNCTION aiqa_guard_review_version_source_insert() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.source_manifest_id IS NOT NULL THEN
        INSERT INTO review_version_source_claims VALUES
                (NEW.project_id,NEW.case_id,NEW.version_id,NEW.source_manifest_id);
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER review_version_source_insert AFTER INSERT ON case_versions FOR EACH ROW EXECUTE FUNCTION aiqa_guard_review_version_source_insert();

CREATE FUNCTION aiqa_guard_reviews_trial_same_case() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NEW.trial_case_run_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM case_runs
            WHERE project_id = NEW.project_id
              AND case_run_id = NEW.trial_case_run_id
              AND case_id = NEW.case_id
          ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'trial item is outside the review case';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER reviews_trial_same_case BEFORE INSERT ON reviews FOR EACH ROW EXECUTE FUNCTION aiqa_guard_reviews_trial_same_case();

CREATE FUNCTION aiqa_guard_runtime_overrides_match_episode() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    IF NOT EXISTS (
            SELECT 1 FROM healing_episodes
            WHERE project_id = NEW.project_id
              AND episode_id = NEW.episode_id
              AND case_run_id = NEW.case_run_id
              AND attempt_id = NEW.attempt_id
              AND package_id = NEW.package_id
        ) THEN
        RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'override is outside the episode';
    END IF;
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER runtime_overrides_match_episode BEFORE INSERT ON runtime_overrides FOR EACH ROW EXECUTE FUNCTION aiqa_guard_runtime_overrides_match_episode();

CREATE FUNCTION aiqa_guard_tc_versions_no_delete() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'tc version content is immutable';
    RETURN OLD;
END
$aiqa$;

CREATE TRIGGER tc_versions_no_delete BEFORE DELETE ON tc_versions FOR EACH ROW EXECUTE FUNCTION aiqa_guard_tc_versions_no_delete();

CREATE FUNCTION aiqa_guard_tc_versions_no_update() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'tc version content is immutable';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER tc_versions_no_update BEFORE UPDATE ON tc_versions FOR EACH ROW EXECUTE FUNCTION aiqa_guard_tc_versions_no_update();

CREATE FUNCTION aiqa_guard_usage_adjustments_immutable() RETURNS trigger LANGUAGE plpgsql AS $aiqa$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'usage adjustment is append-only';
    RETURN NEW;
END
$aiqa$;

CREATE TRIGGER usage_adjustments_immutable BEFORE UPDATE ON usage_adjustments FOR EACH ROW EXECUTE FUNCTION aiqa_guard_usage_adjustments_immutable();
