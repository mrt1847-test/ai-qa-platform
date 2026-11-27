"""Fresh-process server imports must not load Windows worker-only facilities."""
import os
import subprocess
import sys


def test_hosted_entry_imports_without_windows_registry_or_dlls():
    source = '''
import fastapi, uvicorn, sys, ctypes
sys.modules['winreg'] = None
if hasattr(ctypes, 'WinDLL'): del ctypes.WinDLL
from aiqa.hosted.entry import create_hosted_app
from aiqa.api.app import create_app, health
from aiqa.config import load_settings
app=create_app(load_settings({'AIQA_PROFILE':'hosted', 'AIQA_RUNTIME_ROOT':'portability-fixture',
 'AIQA_PUBLIC_ORIGIN':'https://qa.example', 'AIQA_TRUSTED_PROXIES':'127.0.0.1'}))
assert health()['status']=='ok'
'''
    env = dict(os.environ)
    env.pop('AIQA_HOSTED_SECRETS_JSON', None)
    env.pop('AIQA_RECEIPT_HMAC_KEY', None)
    run = subprocess.run([sys.executable, '-B', '-c', source], env=env, capture_output=True, text=True, timeout=45)
    assert run.returncode == 0, run.stderr
