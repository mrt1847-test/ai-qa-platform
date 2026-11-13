"""Outbound HTTPS client for a registered execution worker."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from aiqa.config import WorkerClientSettings


class RetryClass(str, Enum):
    retryable = "retryable"
    auth = "auth"
    tls = "tls"
    redirect = "redirect"
    timeout = "timeout"
    conflict = "conflict"
    fatal = "fatal"


class WorkerHttpError(Exception):
    """Outbound worker HTTP failed. Message must not include the bearer token."""

    def __init__(self, message: str, *, retry_class: RetryClass, status_code: int | None = None,
                 provider_dispatched: bool | None = None, reason: str | None = None, replayed: bool = False) -> None:
        super().__init__(_redact(message))
        self.retry_class = retry_class
        self.status_code = status_code
        self.provider_dispatched = provider_dispatched
        self.reason = reason
        self.replayed = replayed


class SanitizationRequired(WorkerHttpError):
    """Local sanitization failed; the client must not open an upload."""

    def __init__(self, message: str = "unsanitized evidence cannot be uploaded") -> None:
        super().__init__(message, retry_class=RetryClass.fatal)


@dataclass(frozen=True, slots=True)
class WorkerHttpResult:
    status_code: int
    body: dict[str, Any] | None
    retry_class: RetryClass


def classify_status(status_code: int) -> RetryClass:
    """Map an HTTP status to the single retry policy used by the worker client."""

    if status_code in {401, 403}:
        return RetryClass.auth
    if status_code in {408, 425}:
        return RetryClass.timeout
    if status_code == 409:
        return RetryClass.conflict
    if status_code in {502, 503, 504}:
        return RetryClass.retryable
    if 500 <= status_code <= 599:
        return RetryClass.retryable
    if 400 <= status_code <= 499:
        return RetryClass.fatal
    return RetryClass.fatal


def classify_exception(exc: BaseException) -> RetryClass:
    if isinstance(exc, WorkerHttpError):
        return exc.retry_class
    if isinstance(exc, httpx.TimeoutException):
        return RetryClass.timeout
    if isinstance(exc, (httpx.ConnectError, ssl_error_types())):
        text = _redact(str(exc)).lower()
        if "certificate" in text or "ssl" in text or "tls" in text:
            return RetryClass.tls
        return RetryClass.retryable
    return RetryClass.fatal


def ssl_error_types() -> tuple[type[BaseException], ...]:
    try:
        import ssl

        return (ssl.SSLError,)
    except Exception:
        return ()


class WorkerHttpClient:
    """Call management-server worker routes over HTTPS with injectable transport."""

    def __init__(
        self,
        settings: WorkerClientSettings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = settings.base_url.rstrip("/")
        self._token = settings.token
        verify: bool | str
        if not settings.verify_tls:
            verify = False
        elif settings.ca_bundle is not None:
            verify = str(settings.ca_bundle)
        else:
            verify = True
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=settings.timeout_seconds,
            verify=verify,
            transport=transport,
            follow_redirects=False,
        )
        self._origin = urlparse(self._base_url)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> WorkerHttpClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"WorkerHttpClient(base_url={self._base_url!r})"

    def heartbeat(self, boot_id: str) -> dict[str, Any]:
        return self._json(
            "POST",
            "/api/v1/worker/heartbeats",
            json_body={"boot_id": boot_id},
            idempotency_key=None,
        )

    def report_inventory(self, payload: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        if payload.get("raw_handle") is not None:
            raise WorkerHttpError("raw device handles cannot be uploaded", retry_class=RetryClass.fatal)
        blocked = {"pixels", "png", "screenshot", "observation", "body", "body_b64"}
        if any(key in payload for key in blocked):
            raise WorkerHttpError("raw screen upload is forbidden on inventory", retry_class=RetryClass.fatal)
        return self._json(
            "POST",
            "/api/v1/worker/inventory",
            json_body=payload,
            idempotency_key=idempotency_key,
        )

    def claim(
        self, *, boot_id: str, now: str, idempotency_key: str, project_id: str | None = None
    ) -> dict[str, Any] | None:
        """Claim one job. Lost responses must be retried with the same idempotency_key only."""

        if type(idempotency_key) is not str or idempotency_key.strip() == "":
            raise WorkerHttpError("claim idempotency key is required", retry_class=RetryClass.fatal)
        body: dict[str, Any] = {"boot_id": boot_id, "now": now}
        if project_id is not None:
            body["project_id"] = project_id
        result = self._request(
            "POST",
            "/api/v1/worker/claims",
            json_body=body,
            idempotency_key=idempotency_key,
        )
        if result.status_code == 204:
            return None
        if result.body is None:
            raise WorkerHttpError("claim response body is missing", retry_class=RetryClass.fatal, status_code=result.status_code)
        return result.body

    def acknowledge(
        self,
        *,
        project_id: str,
        job_id: str,
        generation: int,
        runner_nonce: str,
        now: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._json(
            "POST",
            "/api/v1/worker/attempt-acks",
            json_body={
                "project_id": project_id,
                "job_id": job_id,
                "generation": generation,
                "runner_nonce": runner_nonce,
                "now": now,
            },
            idempotency_key=idempotency_key,
        )

    def renew(
        self,
        *,
        project_id: str,
        job_id: str,
        generation: int,
        now: str,
        idempotency_key: str,
        model_wait: bool = False,
    ) -> dict[str, Any]:
        return self._json(
            "POST",
            "/api/v1/worker/lease-renewals",
            json_body={
                "project_id": project_id,
                "job_id": job_id,
                "generation": generation,
                "now": now,
                "model_wait": model_wait,
            },
            idempotency_key=idempotency_key,
        )

    def commit_evidence(
        self,
        *,
        sanitized: bool,
        project_id: str,
        job_id: str,
        generation: int,
        now: str,
        events: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Upload only sanitized evidence. A failed sanitize gate performs zero HTTP uploads."""

        if sanitized is not True:
            raise SanitizationRequired()
        if type(idempotency_key) is not str or idempotency_key.strip() == "":
            raise WorkerHttpError("commit idempotency key is required", retry_class=RetryClass.fatal)
        return self._json(
            "POST",
            "/api/v1/worker/evidence-commits",
            json_body={
                "sanitized": True,
                "project_id": project_id,
                "job_id": job_id,
                "generation": generation,
                "now": now,
                "events": events,
                "artifacts": artifacts,
            },
            idempotency_key=idempotency_key,
        )

    def finish_attempt(
        self,
        *,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Submit one terminal attempt result. The server never grants approval here."""

        if type(idempotency_key) is not str or idempotency_key.strip() == "":
            raise WorkerHttpError("finish idempotency key is required", retry_class=RetryClass.fatal)
        return self._json(
            "POST",
            "/api/v1/worker/attempt-finishes",
            json_body=payload,
            idempotency_key=idempotency_key,
        )

    def confirm_finish_attempt(
        self,
        *,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Re-post the same finish key and body after a lost response. Never invents completion."""

        return self.finish_attempt(payload=payload, idempotency_key=idempotency_key)

    def confirm_cleanup(
        self,
        *,
        project_id: str,
        job_id: str,
        attempt_id: str,
        generation: int,
        physical_key_id: str | None,
        proof_refs: list[str],
        now: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Confirm local cleanup so the server frees the lease (or quarantines without proof)."""

        if type(idempotency_key) is not str or idempotency_key.strip() == "":
            raise WorkerHttpError("cleanup idempotency key is required", retry_class=RetryClass.fatal)
        if type(proof_refs) is not list or any(type(item) is not str for item in proof_refs):
            raise WorkerHttpError("cleanup proof_refs must be a list of strings", retry_class=RetryClass.fatal)
        return self._json(
            "POST",
            "/api/v1/worker/cleanup-confirmations",
            json_body={
                "project_id": project_id,
                "job_id": job_id,
                "attempt_id": attempt_id,
                "generation": generation,
                "physical_key_id": physical_key_id,
                "proof_refs": list(proof_refs),
                "now": now,
            },
            idempotency_key=idempotency_key,
        )

    def confirm_pending_cleanup(
        self,
        *,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Re-post the same cleanup key and body after a lost response."""

        return self.confirm_cleanup(
            project_id=payload["project_id"],
            job_id=payload["job_id"],
            attempt_id=payload["attempt_id"],
            generation=payload["generation"],
            physical_key_id=payload.get("physical_key_id"),
            proof_refs=list(payload.get("proof_refs") or []),
            now=payload["now"],
            idempotency_key=idempotency_key,
        )

    def request_model(
        self,
        *,
        project_id: str,
        item_id: str,
        payload: dict[str, Any],
        idempotency_key: str,
        actor_id: str | None = None,
    ) -> dict[str, Any]:
        """Ask the management server to complete one model role. Secrets stay on the server."""

        if type(idempotency_key) is not str or idempotency_key.strip() == "":
            raise WorkerHttpError("model request idempotency key is required", retry_class=RetryClass.fatal)
        if type(project_id) is not str or project_id.strip() == "":
            raise WorkerHttpError("model request project_id is required", retry_class=RetryClass.fatal)
        if type(item_id) is not str or item_id.strip() == "":
            raise WorkerHttpError("model request item_id is required", retry_class=RetryClass.fatal)
        if type(payload) is not dict:
            raise WorkerHttpError("model request payload must be an object", retry_class=RetryClass.fatal)
        body = dict(payload)
        body["project_id"] = project_id
        body["item_id"] = item_id
        if actor_id is not None:
            body["actor_id"] = actor_id
        return self._json(
            "POST",
            "/api/v1/worker/model-requests",
            json_body=body,
            idempotency_key=idempotency_key,
        )

    def get_app_build(self, project_id: str, build_id: str) -> dict[str, Any]:
        """Read one build's server-side metadata. Authentication is the worker Bearer token."""

        return self._get_json(f"/api/v1/projects/{project_id}/app-builds/{build_id}")

    def fetch_app_build_content(
        self,
        project_id: str,
        build_id: str,
        *,
        expected_hash: str | None = None,
    ) -> tuple[bytes, str]:
        """Download APK bytes and verify the server-declared sha256. Returns (bytes, content_hash).

        A hash header that is missing, differs from the bytes, or differs from ``expected_hash``
        raises a fatal ``WorkerHttpError``; nothing is returned in that case.
        """

        import hashlib

        path = f"/api/v1/projects/{project_id}/app-builds/{build_id}/content"
        response = self._send_get(path, accept="application/vnd.android.package-archive")
        declared = response.headers.get("x-content-hash") or response.headers.get("content-hash") or ""
        body = response.content
        actual = "sha256:" + hashlib.sha256(body).hexdigest()
        if declared == "" or declared != actual:
            raise WorkerHttpError(
                "app build content hash does not match",
                retry_class=RetryClass.fatal,
                status_code=response.status_code,
            )
        if expected_hash is not None and expected_hash != actual:
            raise WorkerHttpError(
                "app build content hash is not the pinned hash",
                retry_class=RetryClass.fatal,
                status_code=response.status_code,
            )
        return body, actual

    def _get_json(self, path: str) -> dict[str, Any]:
        response = self._send_get(path, accept="application/json")
        try:
            payload = response.json()
        except ValueError as exc:
            raise WorkerHttpError("worker response is not JSON", retry_class=RetryClass.fatal, status_code=response.status_code) from exc
        if type(payload) is not dict:
            raise WorkerHttpError("worker response must be an object", retry_class=RetryClass.fatal, status_code=response.status_code)
        return _strip_secrets(payload)

    def _send_get(self, path: str, *, accept: str) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._token}", "Accept": accept}
        try:
            response = self._client.request("GET", path, headers=headers)
        except httpx.TimeoutException as exc:
            raise WorkerHttpError("worker request timed out", retry_class=RetryClass.timeout) from exc
        except httpx.ConnectError as exc:
            raise WorkerHttpError(f"worker connect failed: {exc}", retry_class=classify_exception(exc)) from exc
        except Exception as exc:
            if isinstance(exc, ssl_error_types()):
                raise WorkerHttpError("worker tls handshake failed", retry_class=RetryClass.tls) from exc
            raise WorkerHttpError(f"worker request failed: {exc}", retry_class=RetryClass.fatal) from exc
        self._reject_foreign_redirect(response)
        if response.status_code >= 400:
            raise WorkerHttpError(
                f"worker request rejected with status {response.status_code}",
                retry_class=classify_status(response.status_code),
                status_code=response.status_code,
            )
        return response

    def _json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any],
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        result = self._request(method, path, json_body=json_body, idempotency_key=idempotency_key)
        if result.body is None:
            raise WorkerHttpError(
                f"{path} response body is missing",
                retry_class=classify_status(result.status_code),
                status_code=result.status_code,
            )
        return result.body

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any],
        idempotency_key: str | None,
    ) -> WorkerHttpResult:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = self._client.request(method, path, json=json_body, headers=headers)
        except httpx.TimeoutException as exc:
            raise WorkerHttpError("worker request timed out", retry_class=RetryClass.timeout) from exc
        except httpx.ConnectError as exc:
            kind = classify_exception(exc)
            raise WorkerHttpError(f"worker connect failed: {exc}", retry_class=kind) from exc
        except Exception as exc:
            if isinstance(exc, ssl_error_types()):
                raise WorkerHttpError("worker tls handshake failed", retry_class=RetryClass.tls) from exc
            raise WorkerHttpError(f"worker request failed: {exc}", retry_class=RetryClass.fatal) from exc
        self._reject_foreign_redirect(response)
        if response.status_code == 204:
            return WorkerHttpResult(204, None, RetryClass.fatal)
        if response.status_code >= 400:
            retry = classify_status(response.status_code)
            dispatched=None;reason=None;replayed=False
            if path == "/api/v1/worker/model-requests":
                try:
                    error=response.json().get("error",{})
                    if type(error) is dict:
                        value=error.get("provider_dispatched")
                        dispatched=value if type(value) is bool else None
                        value=error.get("message")
                        if type(value) is str and value in {"provider_timeout","provider_quota","provider_unauthorized","provider_http_error",
                            "provider_response_invalid","provider_transport","provider_unreachable","dispatch_unknown","quota","secret",
                            "lease_unavailable","stale_generation","deadline","response_late","unknown_price","recording_authorization",
                            "recording_policy_invalid","binding_unavailable","binding_revision","intent_invalid","intent_hash_required",
                            "provider_endpoint","provider_unavailable","policy_conflict","idempotency_conflict","recording_policy_missing","cancelled"}:
                            reason=value
                        replayed=error.get("replayed") is True
                except (ValueError,AttributeError):pass
            raise WorkerHttpError(
                f"worker request rejected with status {response.status_code}",
                retry_class=retry,
                status_code=response.status_code,
                provider_dispatched=dispatched,reason=reason,replayed=replayed,
            )
        if not response.content:
            return WorkerHttpResult(response.status_code, None, RetryClass.fatal)
        try:
            payload = response.json()
        except ValueError as exc:
            raise WorkerHttpError("worker response is not JSON", retry_class=RetryClass.fatal, status_code=response.status_code) from exc
        if type(payload) is not dict:
            raise WorkerHttpError("worker response must be an object", retry_class=RetryClass.fatal, status_code=response.status_code)
        sanitized = _strip_secrets(payload)
        return WorkerHttpResult(response.status_code, sanitized, RetryClass.fatal)

    def _reject_foreign_redirect(self, response: httpx.Response) -> None:
        if response.status_code not in {301, 302, 303, 307, 308}:
            return
        location = response.headers.get("location", "")
        target = urlparse(urljoin(self._base_url + "/", location))
        if target.scheme != self._origin.scheme or target.netloc != self._origin.netloc:
            raise WorkerHttpError(
                "worker redirect left the management origin",
                retry_class=RetryClass.redirect,
                status_code=response.status_code,
            )
        raise WorkerHttpError(
            "worker redirects are not followed",
            retry_class=RetryClass.redirect,
            status_code=response.status_code,
        )


def _strip_secrets(payload: dict[str, Any]) -> dict[str, Any]:
    blocked = {"token", "access_token", "refresh_token", "authorization", "bearer"}
    return {key: value for key, value in payload.items() if key.lower() not in blocked}


def _redact(message: str) -> str:
    text = message
    for marker in ("Bearer ", "bearer "):
        while True:
            start = text.find(marker)
            if start < 0:
                break
            end = start + len(marker)
            while end < len(text) and not text[end].isspace() and text[end] not in {",", ";", "'", '"'}:
                end += 1
            text = text[: start + len(marker)] + "[redacted]" + text[end:]
    return text


class SyncASGITransport(httpx.BaseTransport):
    """Run an ASGI app from the sync WorkerHttpClient (tests and local fixtures)."""

    def __init__(self, app: object, *, base_url: str = "https://127.0.0.1") -> None:
        self._app = app
        self._base_url = base_url.rstrip("/")

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        import asyncio

        path = request.url.raw_path.decode("ascii")
        if request.url.query:
            path = f"{path}?{request.url.query.decode('ascii')}"

        async def _send() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self._app),
                base_url=self._base_url,
            ) as client:
                response = await client.request(
                    request.method,
                    path,
                    headers=request.headers,
                    content=request.content,
                )
                body = await response.aread()
                return httpx.Response(
                    status_code=response.status_code,
                    headers=response.headers,
                    content=body,
                    request=request,
                )

        return asyncio.run(_send())

    def close(self) -> None:
        return None
