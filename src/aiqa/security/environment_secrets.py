"""Read-only deployment secrets injected by the hosting platform, never SQL."""
from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from uuid import UUID

from aiqa.security.secrets import SecretUnavailable

SECRET_ENV = 'AIQA_HOSTED_SECRETS_JSON'


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate setting')
        result[key] = value
    return result


def _valid_target(target: str, account: str) -> bool:
    prefix = f'AIQA/{account}/'
    if target == prefix + 'oidc/client_secret':
        return True
    if not target.startswith(prefix + 'secret/'):
        return False
    parts = target[len(prefix + 'secret/'):].split('/')
    if len(parts) != 3 or not re.fullmatch(r'[1-9][0-9]{0,8}', parts[2]):
        return False
    try:
        return all(str(UUID(part)) == part for part in parts[:2])
    except ValueError:
        return False


def _load(raw, account):
    # Errors are handled here and discarded, so JSONDecodeError.doc cannot be
    # retained as the public exception's context (it contains the entire secret).
    try:
        if type(raw) is not str or len(raw.encode('utf-8')) > 262144:
            return None
        values = json.loads(raw, object_pairs_hook=_unique_object)
        if type(values) is not dict or len(values) > 256:
            return None
        for target, value in values.items():
            if (not _valid_target(target, account) or type(value) is not str
                    or not 1 <= len(value.encode('utf-8')) <= 4096):
                return None
        return values
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return None


class EnvironmentSecretBackend:
    """Snapshot of one deployment's values. Rotation requires a new deployment."""

    def __init__(self, account: str, *, environ: Mapping[str, str] | None = None):
        if type(account) is not str or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', account):
            raise SecretUnavailable('hosted secret account is invalid')
        source = os.environ if environ is None else environ
        values = _load(source.get(SECRET_ENV, '{}'), account)
        if values is None:
            raise SecretUnavailable('hosted secret configuration is invalid')
        self._values = values

    def read(self, target: str) -> str:
        if target not in self._values:
            raise OSError(1168, 'deployment secret is unavailable')
        return self._values[target]

    def write(self, target: str, value: str, *, account: str) -> None:
        raise SecretUnavailable('hosted secrets are managed by deployment configuration')

    def delete(self, target: str) -> None:
        raise SecretUnavailable('hosted secrets are managed by deployment configuration')
