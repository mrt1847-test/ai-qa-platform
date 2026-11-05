"""Freeze one review snapshot and append action opinions. This does not approve a case."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from aiqa.domain.hashing import canonical_hash
from aiqa.domain.projects import next_commit_seq
from aiqa.store.artifacts import pin_review
from aiqa.store.models import Transaction


class ReviewRejected(Exception):
    """The version cannot take a review snapshot or action opinion."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ReviewConflict(Exception):
    """The submitted digest does not match the pinned entry."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ReviewEntry:
    owner_kind: str
    owner_id: str
    attempt_id: str
    action_id: str
    artifact_id: str
    role: str
    expected_hash: str


@dataclass(frozen=True, slots=True)
class ReviewSnapshot:
    review_id: UUID
    case_version_id: UUID
    version_hash: str
    source_manifest_id: UUID
    source_manifest_hash: str
    trial_case_run_id: UUID
    final_result_hash: str
    evidence_set_hash: str
    created_commit_seq: int
    retain_days: int


def request_review(connection: object, project_id: UUID, version_id: UUID, payload: dict[str, object]) -> ReviewSnapshot:
    """Pin source and trial evidence for 30 days. A healed trial is refused."""

    version = _version(connection, project_id, version_id)
    if version is None:
        raise ReviewRejected("version is missing")
    case_id, version_hash, package_id, manifest_id = version
    if not _package_ready(connection, project_id, case_id, version_id, package_id, manifest_id):
        raise ReviewRejected("package is not ready")
    recording_id = _stored_recording(connection, project_id, case_id, version_id)
    if recording_id is None:
        raise ReviewRejected("source is not stored")
    trial_id = payload.get("trial_case_run_id")
    if type(trial_id) is not str or not _trial(connection, project_id, case_id, version_id, trial_id):
        raise ReviewRejected("trial is missing")
    if _healed(connection, project_id, trial_id):
        raise ReviewRejected("healed trial is not accepted")
    entries = _entries(payload.get("entries"))
    if entries is None or entries == ():
        raise ReviewRejected("evidence is missing")
    for entry in entries:
        _require_entry(connection, project_id, case_id, recording_id, trial_id, entry)
    review_id = uuid4()
    evidence_hash = canonical_hash(
        {"entries": [_public_entry(entry) for entry in entries]},
        "canon-json-v1",
    )
    result_hash = canonical_hash({"actor": 0, "healing": False, "trial_case_run_id": trial_id}, "canon-json-v1")
    manifest_hash = _manifest_hash(connection, project_id, manifest_id)
    commit_seq = next_commit_seq(Transaction(connection), project_id)  # type: ignore[arg-type]
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO reviews (
            project_id, review_id, case_id, case_version_id, version_hash,
            source_manifest_id, trial_case_run_id, evidence_set_hash,
            expected_current_approval_id, created_commit_seq
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
        """,
        (str(project_id), str(review_id), case_id, str(version_id), version_hash, manifest_id, trial_id, evidence_hash, commit_seq),
    )
    for entry in entries:
        connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO review_evidence_entries (
                project_id, review_id, entry_id, owner_kind, owner_id, attempt_id, action_id,
                artifact_ref_id, role, expected_hash, evidence_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(project_id),
                str(review_id),
                str(uuid4()),
                entry.owner_kind,
                entry.owner_id,
                entry.attempt_id,
                entry.action_id,
                entry.artifact_id,
                entry.role,
                entry.expected_hash,
                evidence_hash,
            ),
        )
        pin_review(connection, project_id, UUID(entry.artifact_id), uuid4())
    return ReviewSnapshot(
        review_id,
        version_id,
        version_hash,
        UUID(manifest_id),
        manifest_hash,
        UUID(trial_id),
        result_hash,
        evidence_hash,
        commit_seq,
        30,
    )


@dataclass(frozen=True, slots=True)
class ActionReviewView:
    review_id: UUID
    entry_id: UUID
    owner_kind: str
    owner_id: str
    attempt_id: str
    action_id: str
    evidence_digest: str
    state: str
    actor_id: UUID
    created_at: str
    comment: str
    history_count: int
    latest_state: str
    source_reviewed: int
    source_total: int
    trial_reviewed: int
    trial_total: int
    next_unreviewed_entry_id: str | None


@dataclass(frozen=True, slots=True)
class OwnerCount:
    owner_kind: str
    owner_id: str
    reviewed: int
    total: int


@dataclass(frozen=True, slots=True)
class OpinionRecord:
    state: str
    actor_id: str
    created_at: str
    comment: str


@dataclass(frozen=True, slots=True)
class EntryBoard:
    entry_id: str
    owner_kind: str
    owner_id: str
    attempt_id: str
    action_id: str
    latest_state: str
    history: tuple[OpinionRecord, ...]
    role: str = ''


@dataclass(frozen=True, slots=True)
class ReviewBoard:
    source_reviewed: int
    source_total: int
    trial_reviewed: int
    trial_total: int
    owners: tuple[OwnerCount, ...]
    entries: tuple[EntryBoard, ...]
    next_unreviewed_entry_id: str | None


def review_action(
    connection: object,
    project_id: UUID,
    version_id: UUID,
    actor_id: UUID,
    payload: dict[str, object],
) -> ActionReviewView:
    """Append one opinion for an exact entry. A changed digest or open recording is refused."""

    review_id = payload.get("review_id")
    entry_key = payload.get("entry_key")
    digest = payload.get("evidence_digest")
    state = payload.get("state")
    comment = payload.get("comment")
    if any(type(value) is not str or value.strip() == "" for value in (review_id, entry_key, digest, state, comment)):
        raise ReviewRejected("action review is incomplete")
    if state not in {"reviewed", "needs_change", "evidence_missing"}:
        raise ReviewRejected("action review state is unknown")
    review = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT source_manifest_id FROM reviews
        WHERE project_id = ? AND review_id = ? AND case_version_id = ?
        """,
        (str(project_id), str(review_id), str(version_id)),
    ).fetchone()
    if review is None or review[0] is None:
        raise ReviewRejected("review is missing")
    if _recording_open(connection, project_id, str(review[0])):
        raise ReviewRejected("recording review is not allowed")
    entry = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT owner_kind, owner_id, attempt_id, action_id, evidence_digest
        FROM review_evidence_entries
        WHERE project_id = ? AND review_id = ? AND entry_id = ?
        """,
        (str(project_id), str(review_id), str(entry_key)),
    ).fetchone()
    if entry is None:
        raise ReviewRejected("entry is outside the review")
    if str(entry[4]) != digest:
        raise ReviewConflict("evidence digest changed")
    created_at = datetime.now(timezone.utc).isoformat()
    connection.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO action_reviews (
            project_id, opinion_id, review_id, entry_id, owner_kind, owner_id, attempt_id, action_id,
            evidence_digest, state, actor_id, created_at, comment
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(project_id),
            str(uuid4()),
            str(review_id),
            str(entry_key),
            str(entry[0]),
            str(entry[1]),
            str(entry[2]),
            str(entry[3]),
            str(entry[4]),
            state,
            str(actor_id),
            created_at,
            comment,
        ),
    )
    counts = _entry_counts(connection, project_id, str(review_id))
    history = _history(connection, project_id, str(entry_key))
    return ActionReviewView(
        UUID(str(review_id)),
        UUID(str(entry_key)),
        str(entry[0]),
        str(entry[1]),
        str(entry[2]),
        str(entry[3]),
        str(entry[4]),
        str(state),
        actor_id,
        created_at,
        str(comment),
        len(history),
        history[-1].state if history else "",
        counts[0],
        counts[1],
        counts[2],
        counts[3],
        _next_unreviewed(connection, project_id, str(review_id)),
    )


def review_board(connection: object, project_id: UUID, case_id: UUID, version_id: UUID | None = None) -> ReviewBoard | None:
    """Project the latest opinion per exact entry. Older opinions stay in the history."""

    review = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT review_id FROM reviews
        WHERE project_id = ? AND case_id = ?
          AND (? IS NULL OR case_version_id = ?)
        ORDER BY created_commit_seq DESC
        LIMIT 1
        """,
        (str(project_id), str(case_id), None if version_id is None else str(version_id), None if version_id is None else str(version_id)),
    ).fetchone()
    if review is None:
        return None
    review_id = str(review[0])
    rows = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT entry_id, owner_kind, owner_id, attempt_id, action_id, role
        FROM review_evidence_entries
        WHERE project_id = ? AND review_id = ?
        ORDER BY CASE owner_kind WHEN 'REC' THEN 0 ELSE 1 END, owner_id, action_id, role, entry_id
        """,
        (str(project_id), review_id),
    ).fetchall()
    entries = tuple(
        EntryBoard(str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]), _latest_state(_history(connection, project_id, str(row[0]))), _history(connection, project_id, str(row[0])), str(row[5]))
        for row in rows
    )
    source_reviewed, source_total, trial_reviewed, trial_total = _totals(entries)
    return ReviewBoard(
        source_reviewed,
        source_total,
        trial_reviewed,
        trial_total,
        _owners(entries),
        entries,
        _next_from(entries),
    )


def review_notice(connection: object, project_id: UUID, case_id: UUID) -> str | None:
    """Return the fixed snapshot sentence when this case already has a review."""

    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT 1 FROM reviews
        WHERE project_id = ? AND case_id = ?
        LIMIT 1
        """,
        (str(project_id), str(case_id)),
    ).fetchone()
    if row is None:
        return None
    return "검토 snapshot이 고정되어 30일 보호 중입니다."


@dataclass(frozen=True, slots=True)
class OfflineReviewGate:
    """Server-stored evidence can be reviewed without an online execution PC."""

    allowed: bool
    reason: str
    recording_id: str | None
    package_id: str | None
    trial_case_run_id: str | None
    worker_online: bool


def review_offline_gate(
    connection: object, project_id: UUID, case_id: UUID, version_id: UUID | None = None
) -> OfflineReviewGate:
    """Allow review/approve when required evidence is already ACK'd on the server."""

    from datetime import datetime, timedelta, timezone

    from aiqa.worker.presence import OFFLINE_AFTER

    now = datetime.now(timezone.utc)
    worker_online = False
    for row in connection.execute(  # type: ignore[attr-defined]
        "SELECT last_seen FROM worker_presence WHERE project_id = ?",
        (str(project_id),),
    ).fetchall():
        try:
            seen = datetime.fromisoformat(str(row[0]))
        except ValueError:
            continue
        if seen.tzinfo is None or seen.utcoffset() is None:
            continue
        if timedelta(0) <= now - seen.astimezone(timezone.utc) < OFFLINE_AFTER:
            worker_online = True
            break
    chosen = version_id
    if chosen is None:
        latest = connection.execute(  # type: ignore[attr-defined]
            """
            SELECT version_id FROM case_versions
            WHERE project_id = ? AND case_id = ?
            ORDER BY revision DESC
            LIMIT 1
            """,
            (str(project_id), str(case_id)),
        ).fetchone()
        if latest is None:
            return OfflineReviewGate(False, "version is missing", None, None, None, worker_online)
        chosen = UUID(str(latest[0]))
    version = _version(connection, project_id, chosen)
    if version is None:
        return OfflineReviewGate(False, "version is missing", None, None, None, worker_online)
    case_key, _hash, package_id, manifest_id = version
    recording_id = _stored_recording(connection, project_id, case_key, chosen)
    if recording_id is None:
        return OfflineReviewGate(False, "source is not stored", None, package_id, None, worker_online)
    if not _package_ready(connection, project_id, case_key, chosen, package_id, manifest_id):
        return OfflineReviewGate(False, "package is not ready", recording_id, package_id, None, worker_online)
    trial_id = _package_matched_trial(connection, project_id, case_key, chosen, package_id)
    if trial_id is None:
        return OfflineReviewGate(False, "trial is missing", recording_id, package_id, None, worker_online)
    if _healed(connection, project_id, trial_id):
        return OfflineReviewGate(False, "healed trial is not accepted", recording_id, package_id, trial_id, worker_online)
    if not _server_acked_evidence(connection, project_id, recording_id, trial_id):
        return OfflineReviewGate(False, "evidence is missing", recording_id, package_id, trial_id, worker_online)
    return OfflineReviewGate(True, "server evidence ready", recording_id, package_id, trial_id, worker_online)


def _package_matched_trial(
    connection: object,
    project_id: UUID,
    case_id: str,
    version_id: UUID,
    package_id: str | None,
) -> str | None:
    if package_id is None:
        return None
    package_hash = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT body_hash FROM replay_packages
        WHERE project_id = ? AND package_id = ? AND ready = 1
        """,
        (str(project_id), package_id),
    ).fetchone()
    if package_hash is None:
        return None
    rows = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT r.case_run_id, j.limits
        FROM case_runs r
        JOIN jobs j ON j.project_id = r.project_id AND j.case_run_id = r.case_run_id AND j.purpose = 'trial'
        WHERE r.project_id = ? AND r.case_id = ? AND r.case_version_id = ? AND r.purpose = 'trial'
        ORDER BY r.requested_at DESC, r.case_run_id DESC
        """,
        (str(project_id), case_id, str(version_id)),
    ).fetchall()
    expected_hash = str(package_hash[0])
    fallback = None
    for row in rows:
        try:
            limits = json.loads(str(row[1]))
        except json.JSONDecodeError:
            continue
        if type(limits) is not dict:
            continue
        if limits.get("self_healing_enabled") is not False or limits.get("actor", 0) != 0:
            continue
        pinned_id = limits.get("replay_package_id")
        pinned_hash = limits.get("replay_package_hash")
        if pinned_id not in {None, ""} or pinned_hash not in {None, ""}:
            if str(pinned_id or "") != package_id or str(pinned_hash or "") != expected_hash:
                continue
            return str(row[0])
        if fallback is None:
            fallback = str(row[0])
    return fallback


def _server_acked_evidence(connection: object, project_id: UUID, recording_id: str, trial_id: str) -> bool:
    source = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT COUNT(*) FROM artifact_objects
        WHERE project_id = ? AND owner_kind = 'REC' AND owner_id = ?
          AND role IN ('before', 'after', 'log') AND status = 'ready' AND acked = 1
        """,
        (str(project_id), recording_id),
    ).fetchone()
    trial = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT COUNT(*) FROM artifact_objects
        WHERE project_id = ? AND owner_kind = 'ITEM' AND owner_id = ?
          AND role IN ('before', 'after', 'log') AND status = 'ready' AND acked = 1
        """,
        (str(project_id), trial_id),
    ).fetchone()
    return int(source[0] if source else 0) > 0 and int(trial[0] if trial else 0) > 0


def _version(connection: object, project_id: UUID, version_id: UUID) -> tuple[str, str, str | None, str | None] | None:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT case_id, content_hash, replay_package_id, source_manifest_id
        FROM case_versions
        WHERE project_id = ? AND version_id = ?
        """,
        (str(project_id), str(version_id)),
    ).fetchone()
    if row is None:
        return None
    return (str(row[0]), str(row[1]), None if row[2] is None else str(row[2]), None if row[3] is None else str(row[3]))


def _package_ready(
    connection: object, project_id: UUID, case_id: str, version_id: UUID, package_id: str | None, manifest_id: str | None
) -> bool:
    if package_id is None or manifest_id is None:
        return False
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT 1 FROM replay_packages
        WHERE project_id = ? AND case_id = ? AND case_version_id = ? AND package_id = ?
          AND source_manifest_id = ? AND ready = 1
        """,
        (str(project_id), case_id, str(version_id), package_id, manifest_id),
    ).fetchone()
    return row is not None


def _stored_recording(connection: object, project_id: UUID, case_id: str, version_id: UUID) -> str | None:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT recording_id FROM recordings
        WHERE project_id = ? AND case_id = ? AND input_case_version_id = ?
          AND storage_status = 'stored' AND completion_status = 'completed' AND evidence_status = 'complete'
        """,
        (str(project_id), case_id, str(version_id)),
    ).fetchone()
    return None if row is None else str(row[0])


def _trial(connection: object, project_id: UUID, case_id: str, version_id: UUID, trial_id: str) -> bool:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT j.limits, v.replay_package_id, p.body_hash
        FROM case_runs r
        JOIN case_versions v
          ON v.project_id = r.project_id AND v.version_id = r.case_version_id
        JOIN jobs j
          ON j.project_id = r.project_id AND j.case_run_id = r.case_run_id AND j.purpose = 'trial'
        LEFT JOIN replay_packages p
          ON p.project_id = v.project_id AND p.package_id = v.replay_package_id AND p.ready = 1
        WHERE r.project_id = ? AND r.case_run_id = ? AND r.case_id = ? AND r.case_version_id = ?
          AND r.purpose = 'trial'
        """,
        (str(project_id), trial_id, case_id, str(version_id)),
    ).fetchone()
    if row is None:
        return False
    try:
        limits = json.loads(str(row[0]))
    except json.JSONDecodeError:
        return False
    if type(limits) is not dict:
        return False
    pinned_id = limits.get("replay_package_id")
    pinned_hash = limits.get("replay_package_hash")
    if pinned_id not in {None, ""} or pinned_hash not in {None, ""}:
        if row[1] in {None, ""} or row[2] in {None, ""}:
            return False
        if str(pinned_id or "") != str(row[1]):
            return False
        if str(pinned_hash or "") != str(row[2]):
            return False
    return True


def _healed(connection: object, project_id: UUID, trial_id: str) -> bool:
    episode = connection.execute(  # type: ignore[attr-defined]
        "SELECT 1 FROM healing_episodes WHERE project_id = ? AND case_run_id = ?",
        (str(project_id), trial_id),
    ).fetchone()
    if episode is not None:
        return True
    row = connection.execute(  # type: ignore[attr-defined]
        "SELECT limits FROM jobs WHERE project_id = ? AND case_run_id = ? AND purpose = 'trial'",
        (str(project_id), trial_id),
    ).fetchone()
    if row is None:
        return True
    try:
        limits = json.loads(str(row[0]))
    except json.JSONDecodeError:
        return True
    if type(limits) is not dict:
        return True
    return limits.get("self_healing_enabled") is not False or limits.get("actor") != 0


def _entries(raw: object) -> tuple[ReviewEntry, ...] | None:
    if type(raw) is not list:
        return None
    entries: list[ReviewEntry] = []
    for item in raw:
        if type(item) is not dict:
            return None
        values = [item.get(name) for name in ("owner_kind", "owner_id", "attempt_id", "action_id", "artifact_id", "role", "expected_hash")]
        if any(type(value) is not str or value.strip() == "" for value in values):
            return None
        kind, owner, attempt, action, artifact, role, expected = (str(value) for value in values)
        if kind not in {"REC", "ITEM"} or role not in {"before", "after", "log", "check", "source"}:
            return None
        entries.append(ReviewEntry(kind, owner, attempt, action, artifact, role, expected))
    return tuple(entries)


def _require_entry(
    connection: object, project_id: UUID, case_id: str, recording_id: str, trial_id: str, entry: ReviewEntry
) -> None:
    if entry.owner_kind == "REC" and entry.owner_id != recording_id:
        raise ReviewRejected("evidence owner is outside the review")
    if entry.owner_kind == "ITEM" and entry.owner_id != trial_id:
        raise ReviewRejected("evidence owner is outside the review")
    owned = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT jobs.recording_id, jobs.case_run_id
        FROM actions
        JOIN attempts ON attempts.project_id = actions.project_id AND attempts.attempt_id = actions.attempt_id
        JOIN jobs ON jobs.project_id = attempts.project_id AND jobs.job_id = attempts.job_id
        WHERE actions.project_id = ? AND actions.attempt_id = ? AND actions.action_id = ?
          AND actions.case_id = ?
        """,
        (str(project_id), entry.attempt_id, entry.action_id, case_id),
    ).fetchone()
    if owned is None:
        mixed = connection.execute(  # type: ignore[attr-defined]
            "SELECT 1 FROM actions WHERE project_id = ? AND action_id = ? AND attempt_id <> ?",
            (str(project_id), entry.action_id, entry.attempt_id),
        ).fetchone()
        if mixed is not None:
            raise ReviewRejected("action owner is mixed")
        raise ReviewRejected("evidence is not ready")
    owner = owned[0] if entry.owner_kind == "REC" else owned[1]
    if owner != entry.owner_id:
        raise ReviewRejected("action owner is mixed")
    ready = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT 1 FROM artifact_objects
        JOIN artifact_refs ON artifact_refs.project_id = artifact_objects.project_id
         AND artifact_refs.artifact_id = artifact_objects.artifact_id
        WHERE artifact_objects.project_id = ? AND artifact_objects.artifact_id = ?
          AND artifact_objects.status = 'ready' AND artifact_objects.acked = 1
          AND artifact_objects.content_hash = ?
          AND artifact_refs.attempt_id = ? AND artifact_refs.action_id = ?
        """,
        (str(project_id), entry.artifact_id, entry.expected_hash, entry.attempt_id, entry.action_id),
    ).fetchone()
    if ready is None:
        raise ReviewRejected("evidence is not ready")


def _manifest_hash(connection: object, project_id: UUID, manifest_id: str) -> str:
    row = connection.execute(  # type: ignore[attr-defined]
        "SELECT body_hash FROM recording_manifests WHERE project_id = ? AND manifest_id = ?",
        (str(project_id), manifest_id),
    ).fetchone()
    return "" if row is None else str(row[0])


def _recording_open(connection: object, project_id: UUID, manifest_id: str) -> bool:
    row = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT recordings.storage_status, recordings.stop_status, recordings.completion_status, recordings.evidence_status
        FROM recording_manifests
        JOIN recordings
          ON recordings.project_id = recording_manifests.project_id
         AND recordings.recording_id = recording_manifests.recording_id
        WHERE recording_manifests.project_id = ? AND recording_manifests.manifest_id = ?
        """,
        (str(project_id), manifest_id),
    ).fetchone()
    if row is None:
        return True
    return str(row[0]) != "stored" or str(row[1]) != "stopped" or str(row[2]) != "completed" or str(row[3]) != "complete"


def _history(connection: object, project_id: UUID, entry_id: str) -> tuple[OpinionRecord, ...]:
    rows = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT state, actor_id, created_at, comment
        FROM action_reviews
        WHERE project_id = ? AND entry_id = ?
        ORDER BY created_at, rowid
        """,
        (str(project_id), entry_id),
    ).fetchall()
    return tuple(OpinionRecord(str(row[0]), str(row[1]), str(row[2]), str(row[3])) for row in rows)


def _latest_state(history: tuple[OpinionRecord, ...]) -> str:
    if not history:
        return ""
    return history[-1].state


def _entry_counts(connection: object, project_id: UUID, review_id: str) -> tuple[int, int, int, int]:
    rows = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT owner_kind, entry_id
        FROM review_evidence_entries
        WHERE project_id = ? AND review_id = ?
        """,
        (str(project_id), review_id),
    ).fetchall()
    source_reviewed = source_total = trial_reviewed = trial_total = 0
    for row in rows:
        reviewed = _latest_state(_history(connection, project_id, str(row[1]))) == "reviewed"
        if str(row[0]) == "REC":
            source_total += 1
            source_reviewed += int(reviewed)
        else:
            trial_total += 1
            trial_reviewed += int(reviewed)
    return source_reviewed, source_total, trial_reviewed, trial_total


def _next_unreviewed(connection: object, project_id: UUID, review_id: str) -> str | None:
    rows = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT entry_id
        FROM review_evidence_entries
        WHERE project_id = ? AND review_id = ?
        ORDER BY owner_kind, owner_id, action_id, entry_id
        """,
        (str(project_id), review_id),
    ).fetchall()
    for row in rows:
        if _latest_state(_history(connection, project_id, str(row[0]))) != "reviewed":
            return str(row[0])
    return None


def _totals(entries: tuple[EntryBoard, ...]) -> tuple[int, int, int, int]:
    source_reviewed = source_total = trial_reviewed = trial_total = 0
    for entry in entries:
        reviewed = entry.latest_state == "reviewed"
        if entry.owner_kind == "REC":
            source_total += 1
            source_reviewed += int(reviewed)
        else:
            trial_total += 1
            trial_reviewed += int(reviewed)
    return source_reviewed, source_total, trial_reviewed, trial_total


def _owners(entries: tuple[EntryBoard, ...]) -> tuple[OwnerCount, ...]:
    buckets: dict[tuple[str, str], list[int]] = {}
    for entry in entries:
        key = (entry.owner_kind, entry.owner_id)
        reviewed, total = buckets.get(key, [0, 0])
        total += 1
        if entry.latest_state == "reviewed":
            reviewed += 1
        buckets[key] = [reviewed, total]
    return tuple(OwnerCount(kind, owner, values[0], values[1]) for (kind, owner), values in buckets.items())


def _next_from(entries: tuple[EntryBoard, ...]) -> str | None:
    for entry in entries:
        if entry.latest_state != "reviewed":
            return entry.entry_id
    return None


def _public_entry(entry: ReviewEntry) -> dict[str, str]:
    return {
        "action_id": entry.action_id,
        "artifact_id": entry.artifact_id,
        "attempt_id": entry.attempt_id,
        "expected_hash": entry.expected_hash,
        "owner_id": entry.owner_id,
        "owner_kind": entry.owner_kind,
        "role": entry.role,
    }
