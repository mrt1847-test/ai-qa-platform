"""Explicit connection reports for fixture workers in execution tests."""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from aiqa.store.models import WorkerScope
from aiqa.worker.presence import report_presence


def seed_presence(connection, project, worker, now=None):
    project = str(project)
    now = now or datetime.now(timezone.utc)
    enrollment = connection.execute(
        "SELECT enrollment_id FROM worker_enrollments WHERE project_id=? AND worker_id=? LIMIT 1",
        (project, worker),
    ).fetchone()[0]
    token = connection.execute(
        "SELECT token_id, purpose FROM worker_tokens WHERE enrollment_id=? LIMIT 1", (enrollment,),
    ).fetchone()
    if token is None:
        token = (str(uuid4()), "resource_probe")
        connection.execute(
            """
            INSERT INTO worker_tokens (token_id, enrollment_id, token_hash, purpose, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (token[0], enrollment, str(uuid4()), token[1], now.isoformat()),
        )
    report_presence(connection, WorkerScope(worker, (UUID(project),), (token[1],), token[0]), "fixture-boot", now)


def seed_inventory(connection, resource):
    connection.execute(
        """INSERT INTO resource_inventory VALUES (?, 'ready', '', '', '[]', '', '')""", (str(resource),),
    )
