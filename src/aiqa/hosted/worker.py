"""Re-exec the existing outbound worker under an explicit environment allowlist."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from aiqa.config import load_worker_client_settings

_OS_KEYS = frozenset({'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'HOME', 'USERPROFILE',
                      'LOCALAPPDATA', 'APPDATA', 'LANG', 'LC_ALL', 'ANDROID_HOME',
                      'ANDROID_SDK_ROOT', 'ADB_VENDOR_KEYS'})
_WORKER_KEYS = frozenset({
    'AIQA_MANAGEMENT_BASE_URL', 'AIQA_WORKER_TOKEN', 'AIQA_WORKER_TIMEOUT_SECONDS',
    'AIQA_WORKER_VERIFY_TLS', 'AIQA_WORKER_CA_BUNDLE', 'AIQA_WORKER_PROJECT_ID',
    'AIQA_WORKER_RUNTIME_ROOT', 'AIQA_WORKER_MODEL_MODE', 'AIQA_ADB_PATH',
    'AIQA_ANDROID_SERIAL', 'AIQA_ANDROID_AVD', 'AIQA_ANDROID_VIDEO',
    'AIQA_WORKER_APPROVED_DIGEST', 'AIQA_WORKER_APPROVED_PLAN', 'AIQA_WORKER_APPROVED_REVISION',
    # These authenticate this worker to its own optional Web guest, never the API's stores.
    'AIQA_WEB_GUEST_ENDPOINT', 'AIQA_WEB_GUEST_PEER_TOKEN', 'AIQA_WEB_APPROVED_ORIGIN',
    'AIQA_WEB_GUEST_PROOF_SECRET',
})


def build_worker_environment(source):
    settings = load_worker_client_settings(source)
    if not settings.verify_tls:
        raise ValueError('AIQA_WORKER_VERIFY_TLS must be enabled')
    child = {key: value for key, value in source.items()
             if key.upper() in _OS_KEYS or key in _WORKER_KEYS}
    child.update(PYTHONPATH=str(Path(__file__).resolve().parents[2]),
                 PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    return child


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        env = build_worker_environment(os.environ)
    except (ValueError, TypeError):
        print('Worker configuration invalid; check AIQA_MANAGEMENT_BASE_URL, AIQA_WORKER_TOKEN and TLS settings', file=sys.stderr)
        return 1
    if args == ['--runtime-child']:
        from aiqa.worker.runtime import run_worker_process
        return run_worker_process(env)
    if args:
        print('Worker entry takes no arguments', file=sys.stderr)
        return 1
    return subprocess.run([sys.executable, '-B', '-m', 'aiqa.hosted.worker', '--runtime-child'],
                          env=env, shell=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())
