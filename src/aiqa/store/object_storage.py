"""Server-only private Storage port. Cache is disposable and never an ACK source.

No SDK public/signed URLs, environment lookup, redirects, upserts, or implicit
retry. An uncertain response must be retried by the existing staged request.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import quote, urlsplit

import httpx

from aiqa.store.artifacts import ArtifactRejected, content_hash
from aiqa.worker.files import file_lock


class DurableArtifactRoot:
    """An explicit remote root; deliberately not path-like."""

    def __init__(self, cache_dir: Path, url: str, key: str, bucket: str, *, client=None,
                 max_bytes: int = 500 * 1024 * 1024):
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise ValueError('Supabase URL must be an HTTPS origin')
        if not key or any(c in key for c in '\r\n') or not re.fullmatch(r'[A-Za-z0-9_-]+', bucket):
            raise ValueError('private Storage configuration is missing or invalid')
        if key.startswith('sb_publishable_'):
            raise ValueError('private Storage requires a server secret key')
        if type(max_bytes) is not int or max_bytes < 1 or max_bytes > 500 * 1024 * 1024:
            raise ValueError('Storage byte limit is invalid')
        self.cache_dir = cache_dir
        self._url = url.rstrip('/') + '/storage/v1'
        self._headers = {'apikey': key}
        # New secret keys are opaque API keys, not JWT bearer tokens. Legacy
        # service_role JWTs still use both headers (as do existing test ports).
        if not key.startswith('sb_secret_'):
            self._headers['Authorization'] = 'Bearer ' + key
        self._bucket = bucket
        self._client = client or httpx.Client(timeout=httpx.Timeout(60, connect=10), trust_env=False,
                                             follow_redirects=False)
        self.max_bytes = max_bytes

    def __repr__(self):
        return f'DurableArtifactRoot(cache_dir={self.cache_dir!r}, backend="supabase")'

    def close(self):
        self._client.close()

    def _request(self, method, route, *, limit=65536, **kwargs):
        try:
            with self._client.stream(method, self._url + route, headers=self._headers,
                                     follow_redirects=False, timeout=httpx.Timeout(60, connect=10), **kwargs) as response:
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise ArtifactRejected('Storage response exceeds byte limit')
                    chunks.append(chunk)
                return response.status_code, b''.join(chunks)
        except httpx.HTTPError:
            # Upstream errors/URLs may include privileged credentials. Never relay.
            raise ArtifactRejected('private Storage request failed') from None

    def _private(self):
        status, body = self._request('GET', '/bucket/' + self._bucket)
        try:
            metadata = json.loads(body)
        except (ValueError, TypeError):
            metadata = None
        if status != 200 or not isinstance(metadata, dict) or metadata.get('public') is not False:
            raise ArtifactRejected('private Storage bucket verification failed')

    def path(self, key: str) -> Path:
        from aiqa.store.artifacts import resolve_stored
        path = resolve_stored(self.cache_dir, key)
        if path is None or not re.fullmatch(r'[A-Za-z0-9_./-]+', key) or any(p in ('', '.') for p in key.split('/')):
            raise ArtifactRejected('object key leaves the artifact root')
        return path

    def _get(self, key):
        self.path(key)
        status, body = self._request('GET', '/object/authenticated/' + self._bucket + '/' + quote(key, safe='/'), limit=self.max_bytes)
        if status == 404:
            return None
        if status == 400:
            # Storage's compatibility handler wraps NoSuchKey in HTTP 400;
            # the structured status remains "404". Never infer absence from
            # error text, an auth failure, or another bucket/object error.
            try:
                error = json.loads(body)
            except (ValueError, TypeError):
                error = None
            if isinstance(error, dict) and error.get('code') == 'NoSuchKey' and error.get('statusCode') == '404':
                return None
        if status != 200:
            raise ArtifactRejected('private Storage read failed')
        return body

    def _cache(self, key, body):
        lock = self.cache_dir.parent / 'artifact-cache-locks' / (content_hash(key.encode()).split(':')[1] + '.lock')
        try:
            with file_lock(lock):
                return self._cache_locked(key, body)
        except OSError:
            # Keep the remote object for retry; cache failures cannot produce an
            # ACK or leak filesystem details through an unhandled exception.
            raise ArtifactRejected('artifact cache could not be written') from None

    def _cache_locked(self, key, body):
        destination = self.path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Windows readers cannot share an os.replace. Reuse equal, freshly
        # remote-verified bytes while serializing cache writers by object key.
        if destination.is_file() and destination.read_bytes() == body:
            return destination
        temporary = None
        try:
            with NamedTemporaryFile(dir=destination.parent, suffix='.partial', delete=False) as file:
                temporary = Path(file.name)
                file.write(body)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return destination

    def put(self, key: str, body: bytes):
        self.path(key)
        if not isinstance(body, bytes) or not 1 <= len(body) <= self.max_bytes:
            raise ArtifactRejected('Storage object exceeds byte limit')
        self._private()
        # Read first so a different immutable object never receives an upload.
        existing = self._get(key)
        if existing is not None:
            if existing != body:
                raise ArtifactRejected('immutable object already contains different bytes')
        else:
            status, _ = self._upload(key, body)
            if status not in (200, 201, 400, 409):
                raise ArtifactRejected('private Storage upload failed')
        # Even conflict/duplicate responses only succeed after authenticated readback.
        verified = self._get(key)
        if verified is None or content_hash(verified) != content_hash(body) or len(verified) != len(body):
            raise ArtifactRejected('Storage readback hash mismatch')
        self._cache(key, verified)

    def _upload(self, key, body):
        # Request-specific headers are merged here without exposing them to callers.
        headers = {**self._headers, 'Content-Type': 'application/octet-stream', 'x-upsert': 'false'}
        try:
            with self._client.stream('POST', self._url + '/object/' + self._bucket + '/' + quote(key, safe='/'),
                                     headers=headers, content=body, follow_redirects=False,
                                     timeout=httpx.Timeout(60, connect=10)) as response:
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 65536:
                        raise ArtifactRejected('Storage response exceeds byte limit')
                return response.status_code, b''
        except httpx.HTTPError:
            raise ArtifactRejected('private Storage upload failed') from None

    def read(self, key, expected_hash=None):
        self._private()
        body = self._get(key)
        if body is None:
            self.path(key).unlink(missing_ok=True)
            raise ArtifactRejected('artifact is missing')
        if expected_hash is not None and content_hash(body) != expected_hash:
            raise ArtifactRejected('hash mismatch')
        self._cache(key, body)
        return body

    def materialize(self, key):
        """Legacy Path readers still verify against their database digest."""
        try:
            self.read(key)
        except ArtifactRejected as exc:
            if str(exc) != 'artifact is missing':
                raise
        return self.path(key)

    def delete(self, key):
        self.path(key)
        self._private()
        status, _ = self._request('DELETE', '/object/' + self._bucket, json={'prefixes': [key]})
        if status not in (200, 204) or self._get(key) is not None:
            raise ArtifactRejected('private Storage deletion was not verified')
        self.path(key).unlink(missing_ok=True)


def artifact_root(cache_dir: Path, *, backend='local', supabase_url=None, service_key=None,
                  bucket=None, client=None, max_bytes=500 * 1024 * 1024) -> Path | DurableArtifactRoot:
    if backend == 'local':
        return cache_dir
    if backend != 'supabase':
        raise ValueError('artifact backend is unsupported')
    if not all(isinstance(value, str) and value for value in (supabase_url, service_key, bucket)):
        raise ValueError('private Storage configuration is missing')
    return DurableArtifactRoot(cache_dir, supabase_url, service_key, bucket, client=client, max_bytes=max_bytes)
