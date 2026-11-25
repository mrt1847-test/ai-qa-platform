"""Metadata registration for immutable deployment secret references."""
from uuid import UUID

from aiqa.domain.projects import active_membership_role
from aiqa.security.secrets import (
    SecretScopeDenied, SecretUnavailable, SecretValidationError, _record_secret_ref,
)
from aiqa.store.models import SecretRefView, Transaction


def register_deployment_ref(store, actor, ref, name, backend, account):
    if actor.project_scope != ref.project_id:
        raise SecretScopeDenied('secret ref is outside this project')
    if (type(ref.project_id) is not UUID or type(ref.ref_id) is not UUID
            or type(ref.revision) is not int or not 1 <= ref.revision <= 999999999
            or type(name) is not str or not name.strip() or len(name) > 200):
        raise SecretValidationError({'reference': ['invalid deployment reference']})
    with store.transaction() as con:
        project = con.execute('SELECT archived_at FROM projects WHERE project_id=?', (str(ref.project_id),)).fetchone()
        if (project is None or project[0] is not None
                or active_membership_role(Transaction(con), ref.project_id, actor.actor_id) != 'admin'):
            raise SecretScopeDenied('active project admin membership is required')
        try:
            backend.read(f'AIQA/{account}/secret/{ref.project_id}/{ref.ref_id}/{ref.revision}')
        except OSError:
            raise SecretUnavailable('deployment secret is unavailable') from None
        rows = con.execute('SELECT revision,name,availability FROM secret_refs WHERE project_id=? AND ref_id=? ORDER BY revision DESC',
                           (str(ref.project_id), str(ref.ref_id))).fetchall()
        for row in rows:
            if int(row[0]) == ref.revision:
                if row[1] != name or row[2] != 'available':
                    raise SecretValidationError({'reference': ['existing reference cannot be replaced']})
                return SecretRefView(ref.project_id, ref.ref_id, ref.revision, name, 'available')
        expected = int(rows[0][0]) + 1 if rows else 1
        if ref.revision != expected or (rows and rows[0][1] != name):
            raise SecretValidationError({'reference': ['next revision and existing name are required']})
        _record_secret_ref(con, actor, ref, name, 'rotate' if rows else 'create')
    return SecretRefView(ref.project_id, ref.ref_id, ref.revision, name, 'available')
