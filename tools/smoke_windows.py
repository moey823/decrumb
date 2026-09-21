#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Check the real Windows bundle using empty accounts and synthetic inputs only."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import decrumb
import windows_native


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise SystemExit('Run this smoke test on Windows x64.')
    bundle = args.bundle.resolve()
    def call(name, arguments=(), data=None):
        result = subprocess.run([str(bundle / name), *map(str, arguments)], input=data, capture_output=True, timeout=60)
        if result.returncode:
            raise RuntimeError('Packaged command failed: ' + name)
        return result.stdout
    if not call('decrumb.exe', ['--version']).startswith(b'Decrumb '):
        raise RuntimeError('Packaged version response missing')
    request = {'text': 'https://example.invalid/café?utm_source=synthetic&id=1',
               'settings': {'mode': 'all', 'baseURLs': []}}
    result = json.loads(call('url-cleaner.exe', data=json.dumps(request).encode()))
    if result['urls'] != ['https://example.invalid/café?id=1']:
        raise RuntimeError('Packaged cleaner conformance failed')
    with tempfile.TemporaryDirectory(prefix='decrumb-windows-smoke-') as folder:
        root = Path(folder) / 'private state'
        windows_native.secure_directory(root)
        (root / 'tmp').mkdir()
        qr = root / 'pairing.png'
        call('url-cleaner.exe', ['--qr', qr], b'sgnl://linkdevice?uuid=synthetic&pub_key=synthetic')
        if not qr.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
            raise RuntimeError('Packaged QR generation failed')
        qr.unlink()
        command = [str(bundle / 'decrumb-signal.exe'), '--java', str(bundle / 'jre/bin/java.exe'),
                   '--libraries', str(bundle / 'signal-cli/lib/*'), '--temporary', str(root / 'tmp'), '--',
                   '--config', str(root / 'signal-cli'), '--scrub-log', '--disable-send-log',
                   'jsonRpc', '--receive-mode', 'manual', '--ignore-attachments', '--ignore-stories',
                   '--ignore-avatars', '--ignore-stickers']
        with decrumb.Rpc(root, {}, command=command) as rpc:
            if rpc.call('listAccounts', timeout=45) != []:
                raise RuntimeError('Expected isolated empty account directory')
        decrumb.write_json(root / 'config.json', {'version': 1, 'account': None, 'paused': True,
            'helper': str(bundle / 'url-cleaner.exe'), 'signal_cli': str(bundle / 'signal-cli/bin/signal-cli.bat'),
            'java': str(bundle / 'jre/bin/java.exe'), 'settings': {'mode': 'all', 'baseURLs': []}})
        status = json.loads(call('decrumb.exe', ['--root', root, 'status']))
        if status['linked'] or status['service_active']:
            raise RuntimeError('Empty packaged status was incorrect')
        call('decrumb-background.exe', ['--root', root, '_background'])
        report = json.loads(call('decrumb.exe', ['--root', root, 'diagnostics']))
        if 'account' in json.dumps(report):
            raise RuntimeError('Diagnostic report contained an account field')
    print('Windows bundle verified: version, Unicode cleanup, QR, native Signal/JRE, empty account, status and hidden entry point.')


if __name__ == '__main__':
    main()
