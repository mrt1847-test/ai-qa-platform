"""Read-only review choices. Admission still validates every selected owner/hash."""
import json


def review_candidates(connection, project_id, case_id, version_id):
    source = connection.execute(
        """
        SELECT m.recording_id, v.replay_package_id, p.body_hash
        FROM case_versions v
        JOIN recording_manifests m
          ON m.project_id = v.project_id AND m.manifest_id = v.source_manifest_id
        LEFT JOIN replay_packages p
          ON p.project_id = v.project_id AND p.package_id = v.replay_package_id AND p.ready = 1
        WHERE v.project_id = ? AND v.case_id = ? AND v.version_id = ?
        """,
        (str(project_id), str(case_id), str(version_id)),
    ).fetchone()
    if source is None:
        return []
    package_id = None if source[1] in {None, ""} else str(source[1])
    package_hash = None if source[2] in {None, ""} else str(source[2])
    trials = connection.execute(
        """
        SELECT r.case_run_id, r.requested_at, j.limits, f.core_result
        FROM case_runs r
        JOIN jobs j ON j.project_id = r.project_id AND j.case_run_id = r.case_run_id
        JOIN item_finalizations f ON f.project_id = r.project_id AND f.case_run_id = r.case_run_id
        WHERE r.project_id = ? AND r.case_id = ? AND r.case_version_id = ? AND r.purpose = 'trial'
        ORDER BY r.requested_at DESC, r.case_run_id DESC
        LIMIT 20
        """,
        (str(project_id), str(case_id), str(version_id)),
    ).fetchall()
    candidates = []
    for trial in trials:
        try:
            limits = json.loads(trial[2])
        except (ValueError, TypeError):
            continue
        if type(limits) is not dict:
            continue
        if limits.get("self_healing_enabled") is not False or limits.get("actor", 0) != 0:
            continue
        pinned_id = limits.get("replay_package_id")
        pinned_hash = limits.get("replay_package_hash")
        package_matched = False
        if pinned_id not in {None, ""} or pinned_hash not in {None, ""}:
            if package_id is None or package_hash is None:
                continue
            if str(pinned_id or "") != package_id or str(pinned_hash or "") != package_hash:
                continue
            package_matched = True
        elif package_id is not None and package_hash is not None:
            package_matched = True
        entries = []
        for kind, owner in [("REC", str(source[0])), ("ITEM", str(trial[0]))]:
            column = "recording_id" if kind == "REC" else "case_run_id"
            rows = connection.execute(
                f"""
                SELECT a.artifact_id, a.attempt_id, a.action_id, a.role, a.content_hash
                FROM artifact_objects a
                JOIN attempts t ON t.project_id = a.project_id AND t.attempt_id = a.attempt_id
                JOIN jobs j ON j.project_id = t.project_id AND j.job_id = t.job_id
                WHERE a.project_id = ? AND a.owner_kind = ? AND a.owner_id = ? AND j.{column} = ?
                  AND a.role IN ('before', 'after', 'log') AND a.action_id IS NOT NULL
                  AND a.status = 'ready' AND a.acked = 1
                  AND t.generation = (
                    SELECT MAX(t2.generation) FROM attempts t2
                    WHERE t2.project_id = t.project_id AND t2.job_id = t.job_id
                  )
                ORDER BY a.action_id, a.role, a.artifact_id
                """,
                (str(project_id), kind, owner, owner),
            ).fetchall()
            if not rows:
                rows = connection.execute(
                    f"""
                    SELECT a.artifact_id, a.attempt_id, a.action_id, a.role, a.content_hash
                    FROM artifact_objects a
                    JOIN attempts t ON t.project_id = a.project_id AND t.attempt_id = a.attempt_id
                    JOIN jobs j ON j.project_id = t.project_id AND j.job_id = t.job_id
                    WHERE a.project_id = ? AND a.owner_kind = ? AND a.owner_id = ? AND j.{column} = ?
                      AND a.role IN ('before', 'after', 'log') AND a.action_id IS NOT NULL
                      AND t.generation = (
                        SELECT MAX(t2.generation) FROM attempts t2
                        WHERE t2.project_id = t.project_id AND t2.job_id = t.job_id
                      )
                    ORDER BY a.action_id, a.role, a.artifact_id
                    """,
                    (str(project_id), kind, owner, owner),
                ).fetchall()
            entries.extend(
                {
                    "owner_kind": kind,
                    "owner_id": owner,
                    "attempt_id": str(row[1]),
                    "action_id": str(row[2]),
                    "artifact_id": str(row[0]),
                    "role": str(row[3]),
                    "expected_hash": str(row[4]),
                }
                for row in rows
            )
        if not any(item["owner_kind"] == "REC" for item in entries) or not any(
            item["owner_kind"] == "ITEM" for item in entries
        ):
            continue
        candidates.append(
            {
                "trial_case_run_id": str(trial[0]),
                "result": str(trial[3]),
                "requested_at": str(trial[1]),
                "replay_package_id": package_id,
                "replay_package_hash": package_hash,
                "package_matched": package_matched,
                "entries": entries,
            }
        )
    return candidates
