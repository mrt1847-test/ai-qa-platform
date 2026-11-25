"""Keyed request identity; sensitive payloads never leave an offline raw hash."""
import base64
import binascii
import ctypes
from collections.abc import Mapping
from ctypes import wintypes
import hmac
import os
import secrets


class ReceiptKeyUnavailable(RuntimeError):
    pass


_HOSTED_MARKER = b'aiqa-hosted-receipt-v1:'
_VERIFIER_MESSAGE = b'aiqa hosted receipt key verification v1'


class EnvironmentReceiptKey:
    """One app's deployment key snapshot; no global profile or DPAPI fallback."""

    def __init__(self, *, environ: Mapping[str, str] | None = None):
        source = os.environ if environ is None else environ
        self._raw = source.get('AIQA_RECEIPT_HMAC_KEY')

    def key(self) -> bytes:
        key = None
        try:
            if type(self._raw) is str and len(self._raw) == 44:
                key = base64.b64decode(self._raw, validate=True)
        except (ValueError, binascii.Error):
            pass
        if key is None or len(key) != 32:
            raise ReceiptKeyUnavailable('hosted request integrity key is unavailable')
        return key


class _Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data: bytes, *, decrypt: bool) -> bytes:
    if os.name != 'nt':
        raise ReceiptKeyUnavailable('Windows user protection is unavailable')
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, output = _Blob(len(data), buffer), _Blob()
    library = ctypes.WinDLL('crypt32', use_last_error=True)
    function = library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ReceiptKeyUnavailable('local receipt key is unavailable')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


def protected_body_digest(connection, canonical: bytes, *, key_provider: EnvironmentReceiptKey | None = None) -> str:
    row = connection.execute('SELECT protected_key FROM browser_receipt_key WHERE singleton=1').fetchone()
    if key_provider is not None:
        key = key_provider.key()
        marker = _HOSTED_MARKER + hmac.digest(key, _VERIFIER_MESSAGE, 'sha256')
        if row is None:
            connection.execute('INSERT INTO browser_receipt_key(singleton,protected_key) VALUES(1,?)', (marker,))
        elif not hmac.compare_digest(bytes(row[0]), marker):
            raise ReceiptKeyUnavailable('hosted request integrity key does not match this database')
    elif row is None:
        key = secrets.token_bytes(32)
        envelope = _dpapi(key, decrypt=False)
        connection.execute('INSERT INTO browser_receipt_key(singleton,protected_key) VALUES(1,?)', (envelope,))
    else:
        if bytes(row[0]).startswith(_HOSTED_MARKER):
            raise ReceiptKeyUnavailable('hosted request integrity key is required')
        key = _dpapi(bytes(row[0]), decrypt=True)
    if len(key) != 32:
        raise ReceiptKeyUnavailable('local receipt key is invalid')
    return 'hmac-sha256:' + hmac.new(key, canonical, 'sha256').hexdigest()
