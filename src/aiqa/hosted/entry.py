"""Linux-safe API entry. It never starts an emulator, launcher, or worker."""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

import uvicorn

from aiqa.api.app import create_app
from aiqa.hosted.preflight import HostedConfigurationError, validate_hosted_environment
from aiqa.store.database import migrate_store
from aiqa.store.queue import reconcile_stored


def create_hosted_app():
    settings = validate_hosted_environment()
    app = create_app(settings)

    @asynccontextmanager
    async def lifespan(application):
        store = None
        try:
            store = application.state.open_store()
            revision = migrate_store(store)
            with store.transaction() as connection:
                # Remote incarnation/presence remains authoritative. This fresh
                # fence can never vouch for an old Windows/native runner host.
                report = reconcile_stored(connection, datetime.now(timezone.utc),
                                          'hosted-api:' + str(uuid4()))
            application.state.hosted_schema_revision = revision.id
            application.state.hosted_reconciliation = report
        except Exception:
            artifact_root = getattr(application.state, 'artifact_root', None)
            if callable(getattr(artifact_root, 'close', None)):
                artifact_root.close()
            raise RuntimeError('Hosted startup failed; check database, migrations and storage configuration') from None
        finally:
            if store is not None:
                store.close()
        try:
            yield
        finally:
            artifact_root = getattr(application.state, 'artifact_root', None)
            if callable(getattr(artifact_root, 'close', None)):
                artifact_root.close()

    app.router.lifespan_context = lifespan
    return app


def main() -> int:
    try:
        settings = validate_hosted_environment()
    except HostedConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 1
    uvicorn.run('aiqa.hosted.entry:create_hosted_app', factory=True,
                host='0.0.0.0', port=getattr(settings, 'port', 8000), workers=1,
                proxy_headers=False, access_log=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
