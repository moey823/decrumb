#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Disposable-container smoke: real dependency, then synthetic Signal only.

Never point this script at a real linked account. It creates all state beneath
/data/smoke-* and refuses to reuse those directories.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback
from urllib.request import Request, urlopen

sys.path.insert(0, '/app')
import container_dependency
import decrumb
import web_server

FAKE_SIGNAL = '''#!/usr/local/bin/python3
import json, pathlib, sys, time
root = pathlib.Path(sys.argv[sys.argv.index('--config') + 1])
for line in sys.stdin:
 request = json.loads(line)
 method = request['method']
 if method == 'listAccounts': result = [{'number': '+15550000001'}] if (root/'linked').exists() else []
 elif method == 'startLink': result = {'deviceLinkUri': 'sgnl://linkdevice?uuid=synthetic&pub_key=synthetic'}
 elif method == 'finishLink':
  while not (root/'allow-link').exists(): time.sleep(.1)
  (root/'linked').write_text('synthetic-linked-state')
  result = {}
 elif method == 'listContacts': result = [{'number': '+15550000001', 'uuid': '00000000-0000-4000-8000-000000000001'}]
 elif method in ('subscribeReceive', 'unsubscribeReceive'): result = 0
 else: result = {}
 print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
'''


def require(value, message):
    if not value:
        raise RuntimeError(message)


def wait(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.2)
    raise RuntimeError('Timed out waiting for a synthetic transition.')


def main():
    os.umask(0o077)
    require(os.getuid() == 1000, 'The app must run as UID 1000.')
    native = Path('/data/smoke-native')
    native.mkdir(mode=0o700)
    print('Container smoke: installing the pinned native dependency.', flush=True)
    container_dependency.install(native)
    print('Container smoke: native executable installed; checking cached startup.', flush=True)
    # A second startup must use the verified cache without downloading again.
    container_dependency.install(native)
    print('Container smoke: reading the isolated empty account.', flush=True)
    (native / 'empty-account').mkdir(mode=0o700)
    result = subprocess.run([str(native / 'dependency/signal-cli'), '--config', str(native / 'empty-account'),
                             '--scrub-log', '--disable-send-log', '--output', 'json', 'listAccounts'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    if result.returncode:
        # This directory was created exclusively above and has never been linked.
        # Only this empty-account probe may expose upstream dependency diagnostics.
        print(result.stderr.decode(errors='replace')[:4096], file=sys.stderr)
        raise RuntimeError('Isolated native account listing failed.')
    require(json.loads(result.stdout) == [], 'Isolated native account listing did not return an empty account.')
    print('Verified native dependency and empty account on ' + container_dependency.architecture() + '.', flush=True)

    root = Path('/data/smoke-synthetic')
    root.mkdir(mode=0o700)
    controller = web_server.Controller(root)
    (root / 'dependency').mkdir(mode=0o700)
    binary = root / 'dependency/signal-cli'
    binary.write_text(FAKE_SIGNAL)
    binary.chmod(0o700)
    controller.ready = True
    controller.thread.start()
    print('Container smoke: testing authenticated browser pairing and worker transitions.', flush=True)
    with web_server.Server(('127.0.0.1', 0), controller, 'synthetic-password-not-a-secret') as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = 'http://127.0.0.1:' + str(server.server_port)
        token = ''
        def request(path, data=None, binary=False):
            headers = {'Authorization': 'Bearer ' + token}
            if data is not None:
                headers.update({'Origin': origin, 'Content-Type': 'application/json'})
            with urlopen(Request(origin + '/api/' + path, headers=headers, data=None if data is None else json.dumps(data).encode()), timeout=35) as response:
                content = response.read()
                return content if binary else json.loads(content)
        try:
            token = request('login', {'password': 'synthetic-password-not-a-secret'})['token']
            require(request('status')['state'] == 'unlinked', 'Fresh install did not show pairing.')
            request('pair', {})
            print('Container smoke: waiting for the synthetic QR.', flush=True)
            wait(lambda: request('status')['qr_ready'])
            require(request('qr', binary=True).startswith(b'\x89PNG'), 'Pairing QR was not rendered.')
            request('cancel-pair', {})
            require(not (root / 'pairing.png').exists(), 'Cancelled QR was retained.')
            request('pair', {})
            wait(lambda: request('status')['qr_ready'])
            (root / 'signal-cli/allow-link').touch()
            print('Container smoke: verifying automatic startup after linking.', flush=True)
            wait(lambda: request('status')['state'] == 'running')
            require(not (root / 'pairing.png').exists(), 'Linked QR was retained.')
            state = request('status')
            settings = {key: state[key] for key in ('settings', 'notes', 'phone_commands')}
            require(not settings['phone_commands']['enabled'], 'Phone commands must default off.')
            settings['phone_commands']['enabled'] = True
            request('settings', settings)
            wait(lambda: request('status')['state'] == 'running')
            preview = request('preview', {'text': 'https://example.com/a?utm_source=test&id=42', 'settings': settings['settings']})
            require(preview['urls'] == ['https://example.com/a?id=42'], 'Offline preview failed.')
            request('pause', {})
            require(request('status')['state'] == 'paused', 'Pause did not stop the worker.')
            request('resume', {})
            wait(lambda: request('status')['state'] == 'running')
            # Graceful supervisor shutdown must preserve linking and settings.
            request('pause', {})
        finally:
            server.shutdown()
            thread.join()
            controller.close()
    preserved = (root / 'signal-cli/linked').read_bytes()
    restarted = web_server.Controller(root)
    print('Container smoke: verifying persisted configuration after recreation.', flush=True)
    try:
        restarted.ready = True
        restarted.tick()
        require(restarted.snapshot()['state'] == 'paused', 'Pause did not survive recreation.')
        require(restarted.config()['phone_commands']['enabled'], 'Settings did not survive recreation.')
        require((root / 'signal-cli/linked').read_bytes() == preserved, 'Linked state changed on recreation.')
        restarted.action('resume', {})
        restarted.thread.start()
        wait(lambda: restarted.snapshot()['state'] == 'running')
    finally:
        restarted.close()
    print('Synthetic browser login, pairing, cancellation, auto-start, settings, preview, pause/resume and persistence passed.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        frame = traceback.extract_tb(error.__traceback__)[-1]
        print('Container smoke failed: ' + type(error).__name__ + ' in ' + frame.name + ':' + str(frame.lineno), file=sys.stderr)
        if isinstance(error, decrumb.SafeError):
            print(str(error), file=sys.stderr)  # These are fixed, content-free errors.
        sys.exit(1)
