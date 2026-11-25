"""Hosted receipts retain identity across app restarts without DPAPI."""
import base64
import hmac
import sqlite3
from dataclasses import replace

import pytest

from aiqa.security import receipt_digest as receipts
from aiqa.store.database import StorageConfig
from tests.integration.test_hs1_hosted_secrets import hosted_settings


def provider(key=b'A' * 32):
    return receipts.EnvironmentReceiptKey(environ={
        'AIQA_RECEIPT_HMAC_KEY': base64.b64encode(key).decode('ascii'),
    })


def connection(path=':memory:'):
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE IF NOT EXISTS browser_receipt_key(singleton INTEGER PRIMARY KEY, protected_key BLOB NOT NULL)')
    return con


def test_same_key_restarts_and_other_keys_cannot_reinterpret_database(tmp_path, monkeypatch):
    def no_dpapi(*args, **kwargs):
        pytest.fail('hosted receipt used DPAPI')
    monkeypatch.setattr(receipts, '_dpapi', no_dpapi)
    path = tmp_path / 'receipt.sqlite'
    with connection(path) as con:
        first = receipts.protected_body_digest(con, b'secret payload', key_provider=provider())
        assert first == 'hmac-sha256:' + hmac.new(b'A' * 32, b'secret payload', 'sha256').hexdigest()
        marker = con.execute('SELECT protected_key FROM browser_receipt_key').fetchone()[0]
        assert b'A' * 32 not in marker
    with connection(path) as con:
        assert receipts.protected_body_digest(con, b'secret payload', key_provider=provider()) == first
        assert receipts.protected_body_digest(con, b'different', key_provider=provider()) != first
        with pytest.raises(receipts.ReceiptKeyUnavailable):
            receipts.protected_body_digest(con, b'secret payload', key_provider=provider(b'B' * 32))
        assert con.execute('SELECT protected_key FROM browser_receipt_key').fetchone()[0] == marker


@pytest.mark.parametrize('raw', [None, '', 'invalid secret marker', base64.b64encode(b'short').decode(),
                                  base64.b64encode(b'A' * 33).decode()])
def test_missing_or_invalid_key_never_creates_receipt(raw):
    env = {} if raw is None else {'AIQA_RECEIPT_HMAC_KEY': raw}
    key = receipts.EnvironmentReceiptKey(environ=env)
    with connection() as con:
        with pytest.raises(receipts.ReceiptKeyUnavailable) as exc:
            receipts.protected_body_digest(con, b'payload', key_provider=key)
        assert 'invalid secret marker' not in str(exc.value)
        assert con.execute('SELECT count(*) FROM browser_receipt_key').fetchone()[0] == 0


def test_hosted_and_local_envelopes_are_not_silently_rekeyed(monkeypatch):
    calls = []
    keys = []
    def local(data, *, decrypt):
        calls.append(decrypt)
        if decrypt:
            return keys[0]
        keys.append(data)
        return b'fixture-dpapi-envelope'
    monkeypatch.setattr(receipts, '_dpapi', local)
    with connection() as con:
        first = receipts.protected_body_digest(con, b'payload')
        assert receipts.protected_body_digest(con, b'payload') == first
        with pytest.raises(receipts.ReceiptKeyUnavailable):
            receipts.protected_body_digest(con, b'payload', key_provider=provider())
        assert calls == [False, True]
    with connection() as con:
        receipts.protected_body_digest(con, b'payload', key_provider=provider())
        with pytest.raises(receipts.ReceiptKeyUnavailable):
            receipts.protected_body_digest(con, b'payload')
        assert calls == [False, True]


def test_storage_config_captures_profile_key_per_app_without_repr_leak(tmp_path, monkeypatch):
    from aiqa.config import load_settings
    raw = base64.b64encode(b'A' * 32).decode()
    monkeypatch.setenv('AIQA_RECEIPT_HMAC_KEY', raw)
    a = StorageConfig.from_settings(hosted_settings(tmp_path / 'a'))
    assert raw not in repr(a)
    monkeypatch.setenv('AIQA_RECEIPT_HMAC_KEY', base64.b64encode(b'B' * 32).decode())
    b = StorageConfig.from_settings(hosted_settings(tmp_path / 'b'))
    local = StorageConfig.from_settings(load_settings({'AIQA_RUNTIME_ROOT': str(tmp_path / 'local')}))
    assert local.receipt_key_provider is None
    assert replace(a).receipt_key_provider is a.receipt_key_provider
    with connection() as con:
        first = receipts.protected_body_digest(con, b'payload', key_provider=a.receipt_key_provider)
        with pytest.raises(receipts.ReceiptKeyUnavailable):
            receipts.protected_body_digest(con, b'payload', key_provider=b.receipt_key_provider)
        assert receipts.protected_body_digest(con, b'payload', key_provider=a.receipt_key_provider) == first
