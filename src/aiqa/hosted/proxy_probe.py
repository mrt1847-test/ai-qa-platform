"""Operator-only, secret-free TCP peer probe before the first hosted deployment.

No HTTP input is read. The API, auth, configuration and database are not imported.
"""
from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import socket
import sys

PEERS_PATH = Path('/tmp/aiqa-proxy-peers.json')
_REPLY = (b'HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n'
          b'Connection: close\r\nCache-Control: no-store\r\n\r\n')


def record_connection(connection, peer, path=PEERS_PATH):
    """Keep only the last 64 kernel-supplied socket peer IPs, never request bytes."""
    address = str(ipaddress.ip_address(peer[0]))
    try:
        peers = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        peers = []
    peers = [*peers[-63:], address]
    # New file is private from creation on Linux; the path is not HTTP-served.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
        json.dump(peers, output)
    connection.settimeout(1)
    try:
        connection.sendall(_REPLY)
    except OSError:
        pass


def main():
    # An accidental diagnostic release on a configured server must fail closed.
    if any(name.startswith(('AIQA_DATABASE_', 'AIQA_SUPABASE_', 'AIQA_HOSTED_SECRETS_',
                            'AIQA_OIDC_', 'AIQA_RECEIPT_')) or name in {'OPENAI_API_KEY', 'AIQA_API_KEY'}
           for name in os.environ):
        print('Proxy probe requires an app with no server secret or OIDC settings', file=sys.stderr)
        return 1
    PEERS_PATH.unlink(missing_ok=True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('0.0.0.0', 8000))
        listener.listen(16)
        while True:
            connection, peer = listener.accept()
            with connection:
                record_connection(connection, peer)


if __name__ == '__main__':
    raise SystemExit(main())
