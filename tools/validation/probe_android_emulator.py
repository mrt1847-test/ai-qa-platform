"""Read-only Android emulator observation for development, separate from USB acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
from datetime import datetime, timezone


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', type=Path, required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--avd', default='AIQA_API36')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not args.serial.startswith('emulator-'):
        parser.error('This development probe accepts an explicitly selected emulator only.')

    def adb(*parts: str) -> bytes:
        return subprocess.run([str(args.adb), '-s', args.serial, *parts], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40).stdout

    def text(*parts: str) -> str:
        return adb(*parts).decode('utf-8', errors='replace').strip()

    avd = text('emu', 'avd', 'name').splitlines()[0].strip()
    if avd != args.avd:
        raise RuntimeError(f'AVD mismatch: expected {args.avd}, observed {avd}')
    if text('get-state') != 'device' or text('shell', 'getprop', 'sys.boot_completed') != '1':
        raise RuntimeError('The selected emulator has not completed booting.')
    png = adb('exec-out', 'screencap', '-p')
    if len(png) < 24 or png[:8] != b'\x89PNG\r\n\x1a\n':
        raise RuntimeError('The emulator did not return a PNG capture.')
    width, height = struct.unpack('>II', png[16:24])
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'observation.png').write_bytes(png)
    report = {
        'captured_at': datetime.now(timezone.utc).isoformat(),
        'serial': args.serial, 'avd': avd, 'device_kind': 'android_emulator',
        'android_release': text('shell', 'getprop', 'ro.build.version.release'),
        'api_level': text('shell', 'getprop', 'ro.build.version.sdk'),
        'model': text('shell', 'getprop', 'ro.product.model'),
        'emulator': text('shell', 'getprop', 'ro.kernel.qemu') == '1',
        'display_size': text('shell', 'wm', 'size'),
        'display_density': text('shell', 'wm', 'density'),
        'capture': {'path': 'observation.png', 'width': width, 'height': height,
                    'sha256': hashlib.sha256(png).hexdigest()},
        'scope': 'isolated emulator observation; not USB/native-model acceptance',
        'model_calls': 0,
    }
    (args.out / 'observation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
