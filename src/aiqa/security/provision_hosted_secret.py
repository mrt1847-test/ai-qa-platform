"""Operator CLI. Secret values are read from deployment configuration, never argv."""
import argparse
import json
import sys
from uuid import UUID

from aiqa.config import PROFILE_HOSTED, SettingsError, load_settings
from aiqa.security.secrets import (
    SecretScopeDenied, SecretUnavailable, SecretValidationError, bind_secret_store,
    build_server_secret_resolver,
)
from aiqa.store.database import StorageConfig, migrate_store, open_store
from aiqa.store.models import Actor, SecretRef


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Register metadata for an already deployed hosted model key')
    parser.add_argument('--project-id', type=UUID, required=True)
    parser.add_argument('--actor-id', type=UUID, required=True)
    parser.add_argument('--ref-id', type=UUID, required=True)
    parser.add_argument('--revision', type=int, required=True)
    parser.add_argument('--name', required=True)
    args = parser.parse_args(argv)
    store = None
    try:
        settings = load_settings()
        if settings.profile != PROFILE_HOSTED:
            raise SecretUnavailable('hosted profile is required')
        resolver = build_server_secret_resolver(settings)
        store = open_store(StorageConfig.from_settings(settings))
        migrate_store(store)
        ref = SecretRef(args.project_id, args.ref_id, args.revision)
        with bind_secret_store(store):
            view = resolver.register_deployment_ref(Actor(args.actor_id, args.project_id, False), ref, args.name)
        print(json.dumps({'project_id': str(view.project_id), 'ref_id': str(view.ref_id),
                          'revision': view.revision, 'availability': view.availability}))
        return 0
    except (SettingsError, SecretUnavailable, SecretScopeDenied, SecretValidationError):
        print('Deployment reference registration failed; check configuration, admin membership and next revision.', file=sys.stderr)
        return 1
    finally:
        if store is not None:
            store.close()


if __name__ == '__main__':
    raise SystemExit(main())
