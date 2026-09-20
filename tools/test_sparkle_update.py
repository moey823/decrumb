#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Real, isolated Sparkle replacement/relaunch acceptance test on macOS.

Requires a Developer ID identity and the release EdDSA Keychain account. No keys
are exported. A test-only host uses production AppUpdater.swift and updater.py;
only the Signal service is replaced by a synthetic process holding worker.lock.
Never changes Decrumb's installed app, defaults, LaunchAgents, or real runtime.
"""
import argparse
import functools
import hashlib
import http.server
import json
import os
from pathlib import Path
import plistlib
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import sparkle


BACKEND = r'''
import fcntl, json, os, pathlib, plistlib, signal, subprocess, sys, time
from unittest.mock import patch
sys.path.insert(0, SOURCE_ROOT)
import decrumb, updater, service
command, folder, app, owner = sys.argv[1:]
root = pathlib.Path(folder)
resources = pathlib.Path(app) / 'Contents/Helpers'
if command == 'worker':
    with (root / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        (root / 'worker-ready').write_text(str(os.getpid()))
        while True: time.sleep(1)
class Control:
    def stop(self):
        pidfile = root / 'worker-ready'
        if pidfile.exists():
            pid = int(pidfile.read_text())
            try: os.kill(pid, signal.SIGTERM)
            except ProcessLookupError: pass
            for _ in range(100):
                try:
                    with decrumb.exclusive(root): break
                except decrumb.SafeError: time.sleep(.05)
            pidfile.unlink(missing_ok=True)
        with (root / 'service-events').open('a') as output: output.write('stop\n')
    def start(self, login=False):
        subprocess.Popen([sys.executable, __file__, 'worker', folder, app, owner],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(100):
            if (root / 'worker-ready').exists(): break
            time.sleep(.05)
        else: raise RuntimeError('Fixture worker did not start')
        with (root / 'service-events').open('a') as output: output.write('start\n')
control = Control()
if command == 'start': control.start(); print('{}'); sys.exit()
if command == 'stop': control.stop(); print('{}'); sys.exit()
value = json.load(sys.stdin)
with patch.object(service, 'UpdateRecovery'), patch.object(service, 'configure_app_login'):
    with updater.operation(root):
        if command == 'update-prepare':
            info = plistlib.loads((pathlib.Path(app) / 'Contents/Info.plist').read_bytes())
            if info['FixtureMode'] in ('drafts', 'pairing'):
                assert 'settings-finished' in (root / 'events.txt').read_text(), 'Unsaved changes were interrupted'
            result = updater.prepare(root, control, resources, owner=int(owner), target_build=value['target_build'])
            if info['FixtureMode'] == 'crash':
                os.kill(int(owner), signal.SIGKILL)
        elif command == 'update-abort':
            updater.recover(root, resources, control, token=value['token'])
            result = {}
        elif command == 'bootstrap':
            updater.recover(root, resources, control, bootstrap=True)
            result = {}
        else: raise RuntimeError('Unexpected fixture command')
print(json.dumps(result))
'''


def run(*args, **kwargs):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError(f'{Path(str(args[0])).name} failed: {result.stderr[-1800:]}')
    return result.stdout.strip()


def wait_for(predicate, timeout=100):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.2)
    raise AssertionError('Timed out waiting for the signed update test')


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


def make_app(path, binary, framework, info, identity):
    contents = path / 'Contents'
    (contents / 'MacOS').mkdir(parents=True)
    (contents / 'Helpers').mkdir()
    (contents / 'Frameworks').mkdir()
    shutil.copy2(binary, contents / 'MacOS/Decrumb')
    # Paths must exist for the production recovery validator. They are never run.
    for name in ('url-cleaner', 'signal-cli'):
        target = contents / 'Helpers' / name
        shutil.copy2(binary, target)
        run('/usr/bin/codesign', '--force', '--sign', identity, '--options', 'runtime', '--timestamp=none', target)
    shutil.copytree(framework, contents / 'Frameworks/Sparkle.framework', symlinks=True)
    (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
    run('/usr/bin/codesign', '--force', '--sign', identity, '--options', 'runtime', '--timestamp=none', path)
    run('/usr/bin/codesign', '--verify', '--deep', '--strict', path)


def scenario(parent, binary, framework, args, mode):
    folder = parent / mode
    folder.mkdir()
    runtime = folder / 'runtime'
    runtime.mkdir(mode=0o700)
    serving = folder / 'server'
    serving.mkdir()
    backend = folder / 'backend.py'
    backend.write_text('SOURCE_ROOT = ' + repr(str(ROOT)) + '\n' + BACKEND)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(serving)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = f'http://127.0.0.1:{server.server_port}/'
    identifier = 'com.matthew.decrumb.update-fixture.' + uuid.uuid4().hex
    info = {**sparkle.configuration(), 'CFBundleIdentifier': identifier,
            'CFBundleName': 'Decrumb Update Fixture', 'CFBundleExecutable': 'Decrumb',
            'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': '1.0.0',
            'LSMinimumSystemVersion': '14.0', 'LSUIElement': True,
            'NSAppTransportSecurity': {'NSAllowsLocalNetworking': True},
            'SUFeedURL': address + 'appcast.xml', 'FixturePython': sys.executable,
            'FixtureRoot': str(runtime), 'FixtureBackend': str(backend), 'FixtureMode': mode}
    old = folder / 'installed/Decrumb.app'
    new = folder / 'new/Decrumb.app'
    make_app(old, binary, framework, {**info, 'CFBundleVersion': '1'}, args.identity)
    make_app(new, binary, framework, {**info, 'CFBundleVersion': '2'}, args.identity)
    archive = serving / 'update.zip'
    run('/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', new, archive)
    tools = ROOT / 'build/sparkle/bin'
    signature = run(tools / 'sign_update', '--account', args.account, '-p', archive)
    if mode == 'bad-archive':
        data = bytearray(archive.read_bytes())
        data[len(data) // 2] ^= 1
        archive.write_bytes(data)
    feed = serving / 'appcast.xml'
    feed.write_text('<?xml version="1.0" encoding="utf-8"?>\n'
                    '<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">'
                    '<channel><title>Isolated updater test</title><item><title>Fixture 2</title>'
                    '<sparkle:version>2</sparkle:version><sparkle:shortVersionString>1.0.0</sparkle:shortVersionString>'
                    '<sparkle:minimumSystemVersion>14.0</sparkle:minimumSystemVersion>'
                    f'<enclosure url="{escape(address)}update.zip" length="{archive.stat().st_size}" '
                    f'type="application/octet-stream" sparkle:edSignature="{signature}" />'
                    '</item></channel></rss>\n')
    run(tools / 'sign_update', '--account', args.account, feed)
    if mode == 'bad-feed':
        feed.write_bytes(feed.read_bytes().replace(b'Fixture 2', b'Fixture 3'))
    config = {'version': 1, 'account': '+15550000001',
              'helper': str(old / 'Contents/Helpers/url-cleaner'),
              'signal_cli': str(old / 'Contents/Helpers/signal-cli'),
              'settings': {'mode': 'all', 'baseURLs': [], 'excludedURLs': [], 'rules': []},
              'paused': mode == 'paused', 'start_at_login': False}
    (runtime / 'config.json').write_text(json.dumps(config))
    # The coordinator must leave all account bytes and pending work untouched.
    for name in ('synthetic-account-keys', 'outbox.sqlite3', 'receipts.json'):
        (runtime / name).write_bytes(b'FIXTURE DATA ONLY: preserve this exactly\x00\x01')
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in runtime.iterdir() if p.name != 'config.json'}
    process = None
    recovery_process = None
    events = runtime / 'events.txt'
    read_events = lambda: events.read_text() if events.exists() else ''
    try:
        if mode != 'paused':
            run(sys.executable, backend, 'start', runtime, old, os.getpid())
        log = (folder / 'host.log').open('w')
        process = subprocess.Popen([str(old / 'Contents/MacOS/Decrumb')], stdout=log, stderr=log)
        success = mode in ('install', 'paused', 'quit', 'automatic', 'drafts', 'pairing', 'crash')
        if success:
            if mode == 'crash':
                # Replace only the watchdog's open action. Sparkle must perform
                # the actual replacement after the old GUI is forcibly killed.
                def replaced():
                    try: return plistlib.loads((old / 'Contents/Info.plist').read_bytes())['CFBundleVersion'] == '2'
                    except (OSError, ValueError): return False
                wait_for(replaced)
                recovery_process = subprocess.Popen([str(old / 'Contents/MacOS/Decrumb')], stdout=log, stderr=log)
            wait_for(lambda: 'recovered:2' in read_events())
            assert plistlib.loads((old / 'Contents/Info.plist').read_bytes())['CFBundleVersion'] == '2'
            assert not (runtime / 'update-transition.json').exists()
            assert (runtime / 'worker-ready').exists() == (mode != 'paused')
            updated = json.loads((runtime / 'config.json').read_text())
            assert updated['paused'] == config['paused']
            assert updated['account'] == config['account']
            assert updated['settings'] == config['settings']
            assert updated['start_at_login'] == config['start_at_login']
        else:
            wait_for(lambda: ('error:' in read_events()) if mode.startswith('bad-') else ('ready' in read_events() and 'dismissed' in read_events()))
            assert plistlib.loads((old / 'Contents/Info.plist').read_bytes())['CFBundleVersion'] == '1'
            assert not (runtime / 'update-transition.json').exists()
            assert (runtime / 'worker-ready').exists()
            if mode.startswith('bad-'):
                assert 'ready' not in read_events(), 'Unverified update became installable'
                assert 'stop' not in (runtime / 'service-events').read_text(), 'Rejected update stopped cleaning'
        for name, digest in before.items():
            assert hashlib.sha256((runtime / name).read_bytes()).hexdigest() == digest
        print(f'PASS {mode}: signed Sparkle host; worker and persistent data verified', flush=True)
    except Exception:
        print(f'FAIL {mode}; fixture events: {read_events()}', file=sys.stderr)
        raise
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        # Sparkle relaunches a new process which is not our original Popen child.
        # Limit cleanup to executables inside this one generated fixture folder.
        for line in run('/bin/ps', '-axo', 'pid=,comm=').splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[1] == str(old / 'Contents/MacOS/Decrumb'):
                try: os.kill(int(parts[0]), signal.SIGTERM)
                except ProcessLookupError: pass
        run(sys.executable, backend, 'stop', runtime, old, os.getpid())
        if recovery_process is not None:
            recovery_process.wait(timeout=10)
        server.shutdown()
        server.server_close()
        # Only the random test bundle's defaults/cache are eligible for cleanup.
        subprocess.run(['/usr/bin/defaults', 'delete', identifier], capture_output=True)
        cache = Path.home() / 'Library/Caches' / identifier
        if cache.exists(): shutil.rmtree(cache)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identity', required=True, help='Developer ID Application identity or SHA1')
    parser.add_argument('--account', default='decrumb-updates', help='EdDSA Keychain account, never a private key')
    parser.add_argument('--mode', choices=('install', 'paused', 'quit', 'automatic', 'drafts', 'pairing', 'crash', 'cancel', 'bad-feed', 'bad-archive'), action='append')
    parser.add_argument('--keep', action='store_true', help='Keep synthetic artifacts in build/ for diagnosis')
    args = parser.parse_args()
    framework = ROOT / 'build/sparkle/Sparkle.framework'
    if not framework.is_dir():
        raise SystemExit('Run python3 build.py first to verify/download the pinned Sparkle framework.')
    folder = Path(tempfile.mkdtemp(prefix='sparkle-acceptance-', dir=ROOT / 'build'))
    try:
        private_framework = folder / 'Sparkle.framework'
        shutil.copytree(framework, private_framework, symlinks=True)
        for code in sparkle.nested_code(private_framework):
            run('/usr/bin/codesign', '--force', '--sign', args.identity, '--options', 'runtime', '--timestamp=none', code)
        binary = folder / 'Decrumb'
        run('xcrun', 'swiftc', '-O', '-swift-version', '5', '-parse-as-library',
            ROOT / 'app/AppUpdater.swift', ROOT / 'tests/SparkleUpdateHarness.swift',
            '-F', folder, '-framework', 'Sparkle', '-Xlinker', '-rpath', '-Xlinker', '@executable_path/../Frameworks',
            '-module-cache-path', ROOT / 'build/ModuleCache', '-o', binary)
        for mode in args.mode or ('install', 'paused', 'quit', 'automatic', 'drafts', 'pairing', 'crash', 'cancel', 'bad-feed', 'bad-archive'):
            scenario(folder, binary, private_framework, args, mode)
    finally:
        if args.keep: print('Synthetic fixture artifacts: ' + str(folder))
        else: shutil.rmtree(folder)


if __name__ == '__main__':
    main()
