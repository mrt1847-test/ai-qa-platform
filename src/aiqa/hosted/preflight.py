"""Offline deployment validation. Public errors contain setting names only."""
from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from ipaddress import ip_network
from urllib.parse import parse_qs, urlsplit

from aiqa.config import AppSettings, SettingsError, load_settings
from aiqa.security.environment_secrets import EnvironmentSecretBackend
from aiqa.security.receipt_digest import EnvironmentReceiptKey, ReceiptKeyUnavailable
from aiqa.security.secrets import SecretUnavailable


class HostedConfigurationError(ValueError):
    def __init__(self, fields):
        self.fields = tuple(sorted(set(fields)))
        super().__init__('Hosted configuration invalid: ' + ', '.join(self.fields))


def _https(value, *, origin=False):
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username
                and not parsed.password and not parsed.fragment
                and (not origin or (parsed.path in ('', '/') and not parsed.query))
                and (parsed.port is None or 1 <= parsed.port <= 65535))
    except (ValueError, TypeError):
        return False


def _database(value):
    try:
        parsed = urlsplit(value)
        query = parse_qs(parsed.query)
        return (parsed.scheme in {'postgres', 'postgresql'} and bool(parsed.hostname)
                and bool(parsed.username) and bool(parsed.password) and parsed.path not in {'', '/'}
                and query.get('sslmode') in [['require'], ['verify-ca'], ['verify-full']]
                and not parsed.fragment)
    except (ValueError, TypeError):
        return False


def validate_hosted_environment(environ: Mapping[str, str] | None = None) -> AppSettings:
    """Fail closed before creating clients; never probe services or print values."""
    source = dict(os.environ if environ is None else environ)
    errors = []
    required = (
        'AIQA_PROFILE', 'AIQA_RUNTIME_ROOT', 'AIQA_PUBLIC_ORIGIN', 'AIQA_TRUSTED_PROXIES',
        'AIQA_DATABASE_URL', 'AIQA_ARTIFACT_BACKEND', 'AIQA_SUPABASE_URL',
        'AIQA_SUPABASE_SERVICE_KEY', 'AIQA_SUPABASE_BUCKET', 'AIQA_OIDC_ISSUER',
        'AIQA_OIDC_CLIENT_ID', 'AIQA_OIDC_AUDIENCE', 'AIQA_OIDC_AUTHORIZE_ENDPOINT',
        'AIQA_OIDC_TOKEN_ENDPOINT', 'AIQA_HOSTED_SECRETS_JSON', 'AIQA_RECEIPT_HMAC_KEY',
    )
    for name in required:
        if type(source.get(name)) is not str or not source[name].strip():
            errors.append(name)
    if source.get('AIQA_PROFILE') != 'hosted':
        errors.append('AIQA_PROFILE')
    if source.get('AIQA_ARTIFACT_BACKEND') != 'supabase':
        errors.append('AIQA_ARTIFACT_BACKEND')
    if source.get('AIQA_DATABASE_BACKEND', 'postgres') != 'postgres':
        errors.append('AIQA_DATABASE_BACKEND')
    if not _database(source.get('AIQA_DATABASE_URL', '')):
        errors.append('AIQA_DATABASE_URL')
    for name in ('AIQA_PUBLIC_ORIGIN', 'AIQA_SUPABASE_URL', 'AIQA_OIDC_ISSUER',
                 'AIQA_OIDC_AUTHORIZE_ENDPOINT', 'AIQA_OIDC_TOKEN_ENDPOINT'):
        if not _https(source.get(name, ''), origin=name in {'AIQA_PUBLIC_ORIGIN', 'AIQA_SUPABASE_URL'}):
            errors.append(name)
    if re.fullmatch(r'[A-Za-z0-9_-]{1,100}', source.get('AIQA_SUPABASE_BUCKET', '')) is None:
        errors.append('AIQA_SUPABASE_BUCKET')
    if any(char in source.get('AIQA_SUPABASE_SERVICE_KEY', '') for char in '\r\n'):
        errors.append('AIQA_SUPABASE_SERVICE_KEY')
    try:
        entries = source.get('AIQA_TRUSTED_PROXIES', '').split(',')
        for entry in entries:
            network = ip_network(entry.strip(), strict=False)
            # Explicit peers/subnets only; never trust all private or public hosts.
            if network.prefixlen < (24 if network.version == 4 else 96):
                raise ValueError
    except (ValueError, TypeError):
        errors.append('AIQA_TRUSTED_PROXIES')
    try:
        EnvironmentReceiptKey(environ=source).key()
    except ReceiptKeyUnavailable:
        errors.append('AIQA_RECEIPT_HMAC_KEY')
    try:
        account = source.get('AIQA_SECRET_ACCOUNT', 'aiqa-server')
        backend = EnvironmentSecretBackend(account, environ=source)
        if len(backend.read(f'AIQA/{account}/oidc/client_secret')) < 8:
            raise SecretUnavailable('OIDC client secret is unavailable')
    except (SecretUnavailable, OSError):
        errors.append('AIQA_HOSTED_SECRETS_JSON')
    settings = None
    try:
        settings = load_settings(source)
    except (SettingsError, ValueError, TypeError):
        # The base validator may include the refused value. Do not chain it.
        errors.extend(name for name in source if name.startswith('AIQA_') and name not in {
            'AIQA_DATABASE_URL', 'AIQA_HOSTED_SECRETS_JSON', 'AIQA_RECEIPT_HMAC_KEY',
            'AIQA_SUPABASE_SERVICE_KEY'})
    if settings is not None and settings.model_provider.verify_tls is not True:
        errors.append('AIQA_MODEL_PROVIDER_VERIFY_TLS')
    if errors:
        raise HostedConfigurationError(errors)
    assert settings is not None
    return settings


def main() -> int:
    try:
        validate_hosted_environment()
    except HostedConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 1
    print('Hosted configuration: valid (offline validation only)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
