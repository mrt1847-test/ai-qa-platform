"""Server-operator-only first-project provisioning; no HTTP authentication path."""
from __future__ import annotations

import argparse
import json
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

from aiqa.domain.projects import bind_store, create_project, grant_membership, active_membership_role
from aiqa.hosted.preflight import validate_hosted_environment
from aiqa.store.database import StorageConfig, migrate_store, open_store
from aiqa.store.models import Actor, ProjectCreate, Transaction


class BootstrapRefused(ValueError):
    pass


class _TransactionStore:
    """Let the domain project creator participate in this one atomic transaction."""
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def transaction(self):
        yield self.connection


def bootstrap_first_admin(store, *, issuer: str, subject: str, project: ProjectCreate):
    if not issuer.startswith('https://') or not subject.strip() or len(subject) > 1024:
        raise BootstrapRefused('Verified issuer and subject are required')
    with store.transaction() as connection:
        identity = connection.execute('SELECT actor_id FROM oidc_identities WHERE issuer=? AND subject=?',
                                      (issuer, subject)).fetchone()
        existing = connection.execute('SELECT project_id,name,description,target FROM projects WHERE key=?',
                                      (project.key,)).fetchone()
        if existing is not None:
            if (identity is None or tuple(existing[1:]) != (project.name, project.description, project.target)
                    or active_membership_role(Transaction(connection), UUID(str(existing[0])), UUID(str(identity[0]))) != 'admin'):
                raise BootstrapRefused('Existing project/identity cannot be adopted')
            return {'project_id': str(existing[0]), 'actor_id': str(identity[0])}
        if connection.execute('SELECT 1 FROM projects LIMIT 1').fetchone() is not None:
            raise BootstrapRefused('First-project bootstrap is already complete')
        actor_id = uuid4() if identity is None else UUID(str(identity[0]))
        with bind_store(_TransactionStore(connection)):
            created = create_project(Actor(actor_id, None, False), project)
        if identity is None:
            connection.execute('INSERT INTO oidc_identities(identity_id,issuer,subject,actor_id,created_at) VALUES(?,?,?,?,?)',
                               (str(uuid4()), issuer, subject, str(actor_id), datetime.now(timezone.utc).isoformat()))
        grant_membership(Transaction(connection), created.project_id, actor_id, 'admin')
        return {'project_id': str(created.project_id), 'actor_id': str(actor_id)}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Server operator: bootstrap the first hosted project/admin')
    parser.add_argument('--subject', required=True, help='Exact verified OIDC sub, never an email guess')
    parser.add_argument('--project-key', required=True)
    parser.add_argument('--project-name', required=True)
    parser.add_argument('--target', choices=('android', 'web'), default='android')
    args = parser.parse_args(argv)
    store = None
    try:
        settings = validate_hosted_environment()
        store = open_store(StorageConfig.from_settings(settings))
        migrate_store(store)
        result = bootstrap_first_admin(store, issuer=settings.oidc.issuer, subject=args.subject,
                                       project=ProjectCreate(args.project_name, args.project_key, '', args.target))
        print(json.dumps(result))
        return 0
    except Exception:
        print('Hosted bootstrap failed; check configuration, verified subject and existing project/admin', file=sys.stderr)
        return 1
    finally:
        if store is not None:
            store.close()


if __name__ == '__main__':
    raise SystemExit(main())
