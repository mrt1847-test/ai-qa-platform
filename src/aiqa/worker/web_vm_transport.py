"""Allowlisted IPC transport between the isolation gate and trusted web driver.

Importing this module does not start a VM. Real VM product/image acceptance stays on RX-22.
Local fixture guest processes may speak on 127.0.0.1 only (RX-35).
"""

from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import sys
import time
from collections.abc import Mapping as MappingABC
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping
from uuid import uuid4

from aiqa.replay.ipc import TypedAction
from aiqa.worker.web_isolation_backend import (
    IsolationProof,
    IsolationRejected,
    WebIsolationGate,
)


_GUEST_FORBIDDEN = frozenset(
    {
        "cdp",
        "cdp_url",
        "devtools",
        "websocket",
        "ws_url",
        "endpoint",
        "model_key",
        "api_key",
        "provider_secret",
        "secret",
        "authorization",
        "bearer",
        "model_url",
        "provider",
    }
)

_DEFAULT_MAX_MESSAGE_BYTES = 65_536
_DEFAULT_CONNECT_DEADLINE = 2.0
_DEFAULT_REQUEST_DEADLINE = 2.0


@dataclass(frozen=True, slots=True)
class GuestIpcLimits:
    """Connect/request deadlines and message size for the guest channel."""

    connect_deadline_seconds: float = _DEFAULT_CONNECT_DEADLINE
    request_deadline_seconds: float = _DEFAULT_REQUEST_DEADLINE
    max_message_bytes: int = _DEFAULT_MAX_MESSAGE_BYTES

    def __post_init__(self) -> None:
        if not 0 < float(self.connect_deadline_seconds) <= 30:
            raise IsolationRejected("connect deadline is invalid")
        if not 0 < float(self.request_deadline_seconds) <= 30:
            raise IsolationRejected("request deadline is invalid")
        if not 256 <= int(self.max_message_bytes) <= 1_048_576:
            raise IsolationRejected("max message size is invalid")


@dataclass(frozen=True, slots=True)
class GuestEndpointBinding:
    """Maps an approved endpoint id to a loopback guest process address."""

    endpoint_id: str
    host: str
    port: int
    peer_token: str

    def __post_init__(self) -> None:
        if type(self.endpoint_id) is not str or self.endpoint_id.strip() == "":
            raise IsolationRejected("guest endpoint id is invalid")
        if self.host != "127.0.0.1":
            raise IsolationRejected("guest host must be 127.0.0.1")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise IsolationRejected("guest port is invalid")
        if type(self.peer_token) is not str or len(self.peer_token) < 8:
            raise IsolationRejected("peer auth token is required")


@dataclass(frozen=True, slots=True)
class VmTransportConfig:
    """Worker-approved guest endpoints only. Real VM stays off until RX-22 admits it."""

    approved_endpoints: frozenset[str]
    allow_real_vm: bool = False
    fail_connect: bool = False
    limits: GuestIpcLimits = field(default_factory=GuestIpcLimits)
    bindings: frozenset[GuestEndpointBinding] = frozenset()

    def __post_init__(self) -> None:
        if not self.approved_endpoints:
            raise IsolationRejected("approved guest endpoints are required")
        if any(type(item) is not str or item.strip() == "" for item in self.approved_endpoints):
            raise IsolationRejected("approved guest endpoint is invalid")
        for binding in self.bindings:
            if binding.endpoint_id not in self.approved_endpoints:
                raise IsolationRejected("binding endpoint is not approved")


@dataclass(slots=True)
class GuestSession:
    session_id: str
    endpoint_id: str
    proof: IsolationProof
    alive: bool = True
    cleaned: bool = False


@dataclass
class GuestIpcLink:
    """Length-prefixed JSON over TCP to a local guest process."""

    sock: socket.socket
    limits: GuestIpcLimits
    peer_token: str
    closed: bool = False

    def handshake(self) -> None:
        """Authenticate the peer before any IPC body is exchanged."""

        reply = self._exchange({"op": "auth", "token": self.peer_token}, self.limits.connect_deadline_seconds)
        if reply.get("ok") is not True:
            raise IsolationRejected("guest peer auth failed")

    def request(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        return self._exchange(
            {"op": "ipc", "payload": dict(payload)},
            self.limits.request_deadline_seconds,
        )

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()

    def _exchange(self, message: Mapping[str, object], deadline: float) -> Mapping[str, object]:
        if self.closed:
            raise IsolationRejected("guest channel is closed")
        raw = json.dumps(message, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if len(raw) > self.limits.max_message_bytes:
            raise IsolationRejected("guest message exceeds size limit")
        frame = struct.pack(">I", len(raw)) + raw
        self.sock.settimeout(deadline)
        try:
            self.sock.sendall(frame)
            header = _recvexact(self.sock, 4)
            (length,) = struct.unpack(">I", header)
            if length > self.limits.max_message_bytes:
                raise IsolationRejected("guest response exceeds size limit")
            body = _recvexact(self.sock, length)
        except TimeoutError as exc:
            raise IsolationRejected("guest request timed out") from exc
        except OSError as exc:
            raise IsolationRejected("guest channel closed unexpectedly") from exc
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IsolationRejected("guest response schema is invalid") from exc
        if type(decoded) is not dict:
            raise IsolationRejected("guest response schema is invalid")
        return decoded


@dataclass
class LocalGuestProcess:
    """Separate local fixture guest that accepts one authenticated IPC session."""

    process: subprocess.Popen[bytes]
    binding: GuestEndpointBinding

    def poll_alive(self) -> bool:
        return self.process.poll() is None

    def terminate(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()


def spawn_local_guest_process(
    *,
    endpoint_id: str,
    peer_token: str,
    max_message_bytes: int = _DEFAULT_MAX_MESSAGE_BYTES,
    ready_deadline_seconds: float = 5.0,
) -> LocalGuestProcess:
    """Start a loopback guest worker process and wait until it accepts connections."""

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    host, port = listener.getsockname()
    listener.close()
    binding = GuestEndpointBinding(endpoint_id, host, int(port), peer_token)
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _GUEST_SERVER_SOURCE,
            host,
            str(port),
            peer_token,
            str(int(max_message_bytes)),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + ready_deadline_seconds
    assert process.stdout is not None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            err = process.stderr.read() if process.stderr is not None else b""
            raise IsolationRejected(f"guest process exited before ready: {err!r}")
        # Do not TCP-probe: the fixture guest accepts a single session only.
        line = process.stdout.readline()
        if line.strip() == b"READY":
            return LocalGuestProcess(process, binding)
        if line == b"":
            time.sleep(0.05)
    process.terminate()
    raise IsolationRejected("guest process failed to listen")


@dataclass(frozen=True, slots=True)
class WebGuestEntryBinding:
    """Worker entry wiring for a local fixture guest (not a real VM)."""

    endpoint_id: str
    peer_token: str
    approved_origin: str


def load_web_guest_entry_binding(env: MappingABC[str, str] | None = None) -> WebGuestEntryBinding | None:
    """Read Web guest entry env. Missing values mean no guest auto-wiring."""

    source: MappingABC[str, str] = os.environ if env is None else env
    endpoint = str(source.get("AIQA_WEB_GUEST_ENDPOINT", "")).strip()
    token = str(source.get("AIQA_WEB_GUEST_PEER_TOKEN", "")).strip()
    origin = str(source.get("AIQA_WEB_APPROVED_ORIGIN", "")).strip()
    if endpoint == "" or token == "" or origin == "":
        return None
    if not origin.startswith("https://"):
        return None
    return WebGuestEntryBinding(endpoint_id=endpoint, peer_token=token, approved_origin=origin)


def open_guest_link(binding: GuestEndpointBinding, limits: GuestIpcLimits) -> GuestIpcLink:
    """Connect to a loopback guest with connect deadline and peer handshake."""

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(limits.connect_deadline_seconds)
    try:
        sock.connect((binding.host, binding.port))
    except OSError as exc:
        sock.close()
        raise IsolationRejected("guest connection failed") from exc
    link = GuestIpcLink(sock, limits, binding.peer_token)
    try:
        link.handshake()
    except IsolationRejected:
        link.close()
        raise
    return link


@dataclass
class WebVmTransport:
    """Connect isolation runner IPC to the trusted driver without exposing CDP or model keys."""

    gate: WebIsolationGate
    config: VmTransportConfig
    session: GuestSession | None = None
    link: GuestIpcLink | None = None
    guest_process: LocalGuestProcess | None = None
    connect_attempts: int = 0
    cleanup_proofs: list[str] = field(default_factory=list)
    dispatch_count: int = 0
    channel_exchanges: int = 0

    def web_ready(self, *, now: datetime | None = None) -> bool:
        """Without a live approved session and verified proof, Web is not ready."""

        if self.session is None or not self.session.alive:
            return False
        if self.guest_process is not None and not self.guest_process.poll_alive():
            return False
        if not self.config.allow_real_vm and self.gate.config.backend.name != "fixture":
            return False
        return self.gate.web_ready(self.session.proof, now=now) is not None

    def connect(
        self,
        endpoint_id: str,
        proof: IsolationProof,
        *,
        now: datetime | None = None,
        guest_process: LocalGuestProcess | None = None,
        open_channel: bool = False,
    ) -> GuestSession:
        """Open one guest session on a worker-approved endpoint."""

        self.connect_attempts += 1
        if self.config.fail_connect:
            self._cleanup("connect_failed")
            raise IsolationRejected("guest connection failed")
        if not self.config.allow_real_vm and self.gate.config.backend.name != "fixture":
            self._cleanup("real_vm_unavailable")
            raise IsolationRejected("real VM is not ready")
        if endpoint_id not in self.config.approved_endpoints:
            self._cleanup("endpoint_refused")
            raise IsolationRejected("guest endpoint is not approved")
        verified = self.gate.verify_proof(proof, now=now)
        if self.session is not None and self.session.alive:
            self._cleanup("replaced_session")
        binding = self._binding_for(endpoint_id)
        link: GuestIpcLink | None = None
        if open_channel or guest_process is not None:
            if binding is None and guest_process is None:
                self._cleanup("endpoint_unbound")
                raise IsolationRejected("guest endpoint has no local binding")
            use_binding = guest_process.binding if guest_process is not None else binding
            assert use_binding is not None
            if use_binding.endpoint_id != endpoint_id:
                self._cleanup("endpoint_mismatch")
                raise IsolationRejected("guest endpoint binding mismatch")
            try:
                link = open_guest_link(use_binding, self.config.limits)
            except IsolationRejected:
                self._cleanup("connect_failed")
                raise
            self.guest_process = guest_process
        self.link = link
        self.session = GuestSession(str(uuid4()), endpoint_id, verified, True, False)
        return self.session

    def dispatch_ipc(
        self,
        payload: Mapping[str, object],
        *,
        now: datetime | None = None,
        presented_proof: IsolationProof | None = None,
    ) -> TypedAction:
        """Run allowlisted IPC only. Forged/swapped proof or dead guest triggers cleanup."""

        if self.session is None or not self.session.alive:
            self._cleanup("guest_not_alive")
            raise IsolationRejected("guest session is not alive")
        if self.guest_process is not None and not self.guest_process.poll_alive():
            self._cleanup("guest_exited")
            raise IsolationRejected("guest process exited")
        if presented_proof is not None and presented_proof.token != self.session.proof.token:
            self._cleanup("guest_proof_replaced")
            raise IsolationRejected("guest proof was replaced")
        try:
            _refuse_guest_secrets(payload)
            action = self.gate.run_guest_ipc(self.session.proof, payload, now=now)
            if self.link is not None:
                reply = self.link.request(payload)
                if reply.get("ok") is not True:
                    raise IsolationRejected(str(reply.get("error") or "guest rejected ipc"))
                self.channel_exchanges += 1
        except IsolationRejected:
            self._cleanup("ipc_rejected")
            raise
        self.dispatch_count += 1
        return action

    def note_guest_exit(self) -> None:
        """Guest process ended. Block further IPC and record cleanup."""

        if self.session is not None:
            self.session.alive = False
        self._cleanup("guest_exited")

    def inject_forged_ipc(self, payload: Mapping[str, object], *, now: datetime | None = None) -> None:
        """Attempt a forged/bypass IPC and ensure cleanup blocks the session."""

        try:
            self.dispatch_ipc(payload, now=now)
        except IsolationRejected:
            return
        raise IsolationRejected("forged ipc was not blocked")

    def close(self) -> tuple[str, ...]:
        """Explicit cleanup used by attempt teardown."""

        self._cleanup("closed")
        return tuple(self.cleanup_proofs)

    def _binding_for(self, endpoint_id: str) -> GuestEndpointBinding | None:
        for binding in self.config.bindings:
            if binding.endpoint_id == endpoint_id:
                return binding
        return None

    def _cleanup(self, reason: str) -> None:
        marker = f"guest-cleanup:{reason}"
        self.cleanup_proofs.append(marker)
        if self.link is not None:
            self.link.close()
            self.link = None
        if self.guest_process is not None:
            self.guest_process.terminate()
            self.guest_process = None
        if self.session is not None:
            self.session.alive = False
            self.session.cleaned = True


def open_web_vm_transport(
    gate: WebIsolationGate,
    *,
    approved_endpoints: frozenset[str] | tuple[str, ...],
    allow_real_vm: bool = False,
    fail_connect: bool = False,
    limits: GuestIpcLimits | None = None,
    bindings: frozenset[GuestEndpointBinding] | tuple[GuestEndpointBinding, ...] = (),
) -> WebVmTransport:
    """Build a transport bound to the current isolation gate."""

    return WebVmTransport(
        gate,
        VmTransportConfig(
            approved_endpoints=frozenset(approved_endpoints),
            allow_real_vm=allow_real_vm,
            fail_connect=fail_connect,
            limits=limits or GuestIpcLimits(),
            bindings=frozenset(bindings),
        ),
    )


def _refuse_guest_secrets(payload: Mapping[str, object]) -> None:
    if not isinstance(payload, Mapping):
        raise IsolationRejected("guest payload must be an object")
    leaked = _GUEST_FORBIDDEN.intersection(payload)
    if leaked:
        raise IsolationRejected(f"guest secret refused: {sorted(leaked)[0]}")
    body = payload.get("payload")
    if isinstance(body, Mapping):
        leaked_body = _GUEST_FORBIDDEN.intersection(body)
        if leaked_body:
            raise IsolationRejected(f"guest secret refused: {sorted(leaked_body)[0]}")


def _recvexact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise IsolationRejected("guest channel closed unexpectedly")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


# Minimal guest worker executed in a separate local process for fixture tests.
_GUEST_SERVER_SOURCE = r"""
import json, socket, struct, sys

host, port, token, max_bytes = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])

def recvexact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf

def read_msg(sock):
    (length,) = struct.unpack(">I", recvexact(sock, 4))
    if length > max_bytes:
        return None, "oversized"
    raw = recvexact(sock, length)
    return json.loads(raw.decode("utf-8")), None

def write_msg(sock, obj):
    raw = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(raw) > max_bytes:
        raise ValueError("response too large")
    sock.sendall(struct.pack(">I", len(raw)) + raw)

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind((host, port))
srv.listen(1)
sys.stdout.write("READY\n")
sys.stdout.flush()
conn, _ = srv.accept()
try:
    msg, err = read_msg(conn)
    if err or not isinstance(msg, dict) or msg.get("op") != "auth" or msg.get("token") != token:
        write_msg(conn, {"ok": False, "error": "auth"})
        raise SystemExit(2)
    write_msg(conn, {"ok": True})
    while True:
        msg, err = read_msg(conn)
        if err == "oversized":
            write_msg(conn, {"ok": False, "error": "oversized"})
            continue
        if not isinstance(msg, dict) or msg.get("op") != "ipc":
            write_msg(conn, {"ok": False, "error": "schema"})
            continue
        write_msg(conn, {"ok": True, "echo": msg.get("payload")})
except Exception:
    raise SystemExit(1)
finally:
    conn.close()
    srv.close()
"""
