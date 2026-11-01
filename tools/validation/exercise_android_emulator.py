"""Development spike: capture each fixed Settings action on the isolated AIQA AVD."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
import re
import xml.etree.ElementTree as ET


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', type=Path, required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not args.serial.startswith('emulator-'):
        parser.error('Physical Android devices are outside this development spike.')

    def call(*parts: str) -> bytes:
        return subprocess.run([str(args.adb), '-s', args.serial, *parts], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40).stdout

    avd = call('emu', 'avd', 'name').decode().splitlines()[0].strip()
    if avd != 'AIQA_API36' or call('shell', 'getprop', 'sys.boot_completed').strip() != b'1':
        raise RuntimeError('Only the booted, isolated AIQA_API36 development AVD is allowed.')
    size = re.search(rb'(\d+)x(\d+)', call('shell', 'wm', 'size'))
    if size is None:
        raise RuntimeError('The selected display geometry is unavailable.')
    width, height = map(int, size.groups())
    args.out.mkdir(parents=True, exist_ok=True)
    call('shell', 'am', 'force-stop', 'com.android.settings')
    call('shell', 'am', 'start', '-W', '-a', 'android.settings.SETTINGS')

    def idle():
        call('shell', 'uiautomator', 'dump', '/data/local/tmp/aiqa-action.xml')
        return call('shell', 'cat', '/data/local/tmp/aiqa-action.xml')

    def texts(tree):
        return [node.get('text', '') for node in ET.fromstring(tree).iter('node')]

    def wait_scene(predicate):
        deadline = time.monotonic() + 35
        tree = b''
        while time.monotonic() < deadline:
            tree = idle()
            if any("isn't responding" in text for text in texts(tree)):
                return tree, False
            if predicate(tree):
                return tree, True
        return tree, False

    def capture(name: str):
        png = call('exec-out', 'screencap', '-p')
        if not png.startswith(b'\x89PNG\r\n\x1a\n'):
            raise RuntimeError('Capture is not a PNG.')
        (args.out / name).write_bytes(png)
        return {'path': name, 'sha256': hashlib.sha256(png).hexdigest(), 'bytes': len(png)}

    home = lambda tree: 'Search Settings' in texts(tree) and 'Network & internet' in texts(tree)
    scene, ready = wait_scene(home)
    if not ready:
        raise RuntimeError('The observed Settings home scene is not ready. No tap dispatched.')
    row = next(node for node in ET.fromstring(scene).iter('node') if node.get('text') == 'Network & internet')
    x1, y1, x2, y2 = map(int, re.findall(r'\d+', row.get('bounds', '')))
    network = lambda tree: 'Internet' in texts(tree) and 'VPN' in texts(tree)
    scrolled = lambda tree: any(text in texts(tree) for text in ('System', 'About phone', 'Security & privacy'))
    launcher = lambda tree: any('nexuslauncher' in node.get('package', '') for node in ET.fromstring(tree).iter('node'))
    steps = [
        ('tap', ['tap', str((x1+x2)//2), str((y1+y2)//2)], 'Open the observed Network & internet row', network),
        ('back', ['keyevent', 'KEYCODE_BACK'], 'Return to Settings home', home),
        ('swipe', ['swipe', str(width//2), str(height*3//4), str(width//2), str(height//4), '350'], 'Scroll the Settings list', scrolled),
        ('back', ['keyevent', 'KEYCODE_BACK'], 'Leave Settings', launcher),
    ]
    records = []
    with (args.out / 'actions.jsonl').open('w', encoding='utf-8') as log:
        for index, (kind, arguments, intent, expected_scene) in enumerate(steps, 1):
            step = f'step-{index:02d}'
            before = capture(f'{step}-before.png')
            started = datetime.now(timezone.utc).isoformat()
            record = {'step_id': step, 'kind': kind, 'intent': intent, 'serial': args.serial,
                      'arguments': arguments, 'started_at': started, 'before': before,
                      'state': 'dispatch_started', 'model_calls': 0}
            log.write(json.dumps(record) + '\n'); log.flush()
            begin = time.monotonic()
            output = call('shell', 'input', *arguments)
            tree, verified = wait_scene(expected_scene)
            (args.out / f'{step}-after.xml').write_bytes(tree)
            record.update(state='observed', finished_at=datetime.now(timezone.utc).isoformat(),
                          elapsed_seconds=round(time.monotonic() - begin, 3),
                          after=capture(f'{step}-after.png'), output=output.decode(errors='replace'),
                          scene_verified=verified, qa_result='not_evaluated')
            records.append(record)
            log.write(json.dumps(record) + '\n'); log.flush()
            print(json.dumps({'step_id': step, 'kind': kind, 'state': 'observed'}), flush=True)
            if not verified:
                raise RuntimeError(f'{step} did not reach the expected development scene; remaining actions not dispatched.')
    manifest = {'scope': 'isolated Android emulator Settings development spike',
                'avd': avd, 'serial': args.serial, 'steps': records, 'model_calls': 0,
                'geometry': {'width': width, 'height': height},
                'usb_acceptance': False, 'product_recording_integrated': False}
    (args.out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
