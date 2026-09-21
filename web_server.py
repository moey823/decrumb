#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Private browser controls for Decrumb's container edition.

The UI never sees account identifiers, message bodies, runtime paths or logs.
Only an authenticated pairing request exposes its short-lived QR image. Worker
and pairing subprocesses share the existing exclusive lock and privacy rules.
"""
import argparse
import contextlib
import fcntl
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

import decrumb
import diagnostics
import portable_cleaner

APP = Path(__file__).resolve().parent
MAX_BODY = 64 * 1024
ASSETS = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/app.css': ('app.css', 'text/css; charset=utf-8'),
          '/logo.svg': ('logo.svg', 'image/svg+xml')}


class Controller:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if self.root.is_relative_to(APP) or APP.is_relative_to(self.root):
            raise decrumb.SafeError('Private data must be outside the installed application.')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        diagnostics.configure(self.root, decrumb.LOG)
        self.lockfile = (self.root / 'web.lock').open('a')
        try:
            fcntl.flock(self.lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lockfile.close()
            raise
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.child = None
        self.role = None
        self.started = 0
        self.retry_at = 0
        self.ready = False
        self.error = None
        with decrumb.exclusive(self.root):
            if (self.root / 'config.json').exists():
                config = self.config()
            else:
                config = {'version': 1, 'account': None, 'paused': False,
                          'settings': {'mode': 'all', 'baseURLs': [], 'excludedURLs': [], 'rules': []},
                          'notes': decrumb.notes_settings(), 'phone_commands': {'enabled': False}}
            config.update(helper=str(APP / 'portable_cleaner.py'), signal_cli=str(self.root / 'dependency/signal-cli'))
            (self.root / 'signal-cli').mkdir(mode=0o700, exist_ok=True)
            (self.root / 'pairing.png').unlink(missing_ok=True)
            decrumb.write_json(self.root / 'config.json', config)
        self.thread = threading.Thread(target=self.monitor, daemon=True)

    def config(self):
        return decrumb.load_config(self.root, validate_helper=False)

    def launch(self, role):
        if self.child:
            raise decrumb.SafeError('Another operation is still finishing.')
        args = ([sys.executable, '-B', str(APP / 'web_server.py'), '--root', str(self.root), '--bootstrap']
                if role == 'bootstrap' else
                [sys.executable, '-B', str(APP / 'decrumb.py'), '--root', str(self.root), role])
        self.child = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, start_new_session=True,
                                      env={**os.environ, 'DECRUMB_INHERIT_PROCESS_GROUP': '1'})
        self.role, self.started = role, decrumb.now_ms()

    def stop_child(self):
        if self.child is not None:
            process = self.child
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=25)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            self.child = self.role = None
        (self.root / 'pairing.png').unlink(missing_ok=True)

    def start(self):
        self.launch('bootstrap')
        self.thread.start()

    def tick(self):
        if self.role == 'bootstrap' and decrumb.now_ms() - self.started > 10 * 60 * 1000:
            self.stop_child()
            self.error = 'Setup timed out. Check internet access, then retry setup.'
        if self.child is not None and self.child.poll() is not None:
            code, role = self.child.returncode, self.role
            self.child = self.role = None
            (self.root / 'pairing.png').unlink(missing_ok=True)
            if role == 'bootstrap':
                self.ready = code == 0
                self.error = None if self.ready else 'Setup could not finish. Check internet access and free storage, then retry setup.'
            elif role == 'pair':
                self.error = None if self.config().get('account') else 'Pairing expired or could not connect. Generate another QR code.'
            elif role == 'run':
                self.error = 'Connection stopped. Decrumb will retry in 30 seconds.'
                self.retry_at = time.monotonic() + 30
        config = self.config()
        if self.ready and self.child is None and config.get('account') and not config.get('paused') and time.monotonic() >= self.retry_at:
            self.launch('run')
        if self.role == 'run' and self.child and self.child.poll() is None:
            status = decrumb.read_status(self.root, config)
            if status.get('pid') == self.child.pid and status['state'] == 'running':
                self.error = None
            elif decrumb.now_ms() - max(status.get('updated_at', 0), self.started) > 120000:
                self.stop_child()
                self.error = 'Connection became unresponsive. Decrumb will retry in 30 seconds.'
                self.retry_at = time.monotonic() + 30

    def monitor(self):
        while not self.closed.wait(1):
            with self.lock:
                try:
                    self.tick()
                except Exception as error:
                    # Never expose exception messages: upstream failures can contain data.
                    diagnostics.failure(self.root, error)
                    self.error = 'Decrumb could not read its state. Restart the app from Umbrel.'

    def close(self):
        self.closed.set()
        with self.lock:
            self.stop_child()
        if self.thread.is_alive():
            self.thread.join(timeout=5)
        self.lockfile.close()

    def snapshot(self):
        with self.lock:
            config = self.config()
            status = decrumb.read_status(self.root, config)
            if not self.ready:
                state = 'preparing' if self.role == 'bootstrap' else 'setup_error'
            elif self.role == 'pair':
                state = 'pairing'
            elif not config.get('account'):
                state = 'unlinked'
            elif config.get('paused'):
                state = 'paused'
            elif self.child and self.role == 'run' and self.child.poll() is None:
                state = status['state'] if status.get('pid') == self.child.pid and status.get('updated_at', 0) >= self.started else 'starting'
            else:
                state = 'error'
            return {'state': state, 'linked': bool(config.get('account')), 'error': self.error,
                    'qr_ready': self.role == 'pair' and (self.root / 'pairing.png').is_file(),
                    'settings': config['settings'], 'notes': config['notes'],
                    'phone_commands': config['phone_commands'], 'counts': status['counts'],
                    'note_counts': decrumb.read_notes(self.root / 'outbox.sqlite3')['note_counts']}

    def qr(self):
        with self.lock:
            if self.role != 'pair' or not self.child or self.child.poll() is not None:
                raise decrumb.SafeError('Generate a new QR code.')
            try:
                return (self.root / 'pairing.png').read_bytes()
            except OSError:
                raise decrumb.SafeError('The QR code is not ready yet.') from None

    def action(self, action, data):
        with self.lock:
            if action in ('diagnostics', 'clear-diagnostics'):
                if data:
                    raise decrumb.SafeError('Diagnostics takes no additional data.')
                if action == 'clear-diagnostics':
                    diagnostics.maintain(self.root, clear=True)
                return diagnostics.report(self.root)
            if action == 'retry-setup':
                if self.ready or self.child:
                    raise decrumb.SafeError('Setup is already running or complete.')
                self.error = None
                self.launch('bootstrap')
                return
            if not self.ready:
                raise decrumb.SafeError('Wait for setup to finish.')
            config = self.config()
            if action == 'pair':
                if config.get('account') or self.child:
                    raise decrumb.SafeError('Signal is already linked or connecting.')
                self.error = None
                self.launch('pair')
                return
            if action == 'cancel-pair':
                if self.role == 'pair':
                    self.stop_child()
                self.error = None
                return
            if self.role == 'pair':
                raise decrumb.SafeError('Finish or cancel pairing first.')
            if action == 'preview':
                if set(data) != {'text', 'settings'} or not isinstance(data['text'], str) or len(data['text'].encode()) > 16384:
                    raise decrumb.SafeError('Enter a sample smaller than 16 KiB.')
                return portable_cleaner.request(data, portable_cleaner.load_rules(APP / 'rules/defaults.json'))
            if action == 'settings':
                if set(data) != {'settings', 'notes', 'phone_commands'} or data['phone_commands'] not in ({'enabled': True}, {'enabled': False}) or type(data['phone_commands']['enabled']) is not bool:
                    raise decrumb.SafeError('Invalid settings.')
                value = {'settings': portable_cleaner.settings(data['settings']),
                         'notes': decrumb.notes_settings(data['notes']), 'phone_commands': data['phone_commands']}
            elif action not in {'pause', 'resume', 'cleanup', 'clear-queue'}:
                raise decrumb.SafeError('Unknown control.')
            if action == 'resume' and not config.get('account'):
                raise decrumb.SafeError('Connect Signal first.')
            self.stop_child()
            try:
                with decrumb.exclusive(self.root):
                    # Pairing can finish just before cancellation, so read after stopping.
                    config = self.config()
                    if action == 'settings':
                        old_settings = config['settings']
                        config.update(value)
                    elif action in {'pause', 'resume'}:
                        config['paused'] = action == 'pause'
                    if (self.root / 'outbox.sqlite3').exists():
                        with contextlib.closing(decrumb.Store(self.root / 'outbox.sqlite3')) as store:
                            if action == 'settings':
                                if config['settings'] != old_settings:
                                    store.clear_pending()
                                store.update_schedule(config['notes'])
                            elif action == 'cleanup':
                                store.request_cleanup()
                            elif action == 'clear-queue' or (action == 'pause' and config['notes']['discard_on_pause']):
                                store.clear_pending()
                    decrumb.write_json(self.root / 'config.json', config)
                    self.error, self.retry_at = None, 0
            finally:
                if self.config().get('account') and not self.config().get('paused'):
                    self.launch('run')


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, controller, password):
        if len(password) < 16:
            raise decrumb.SafeError('Set a private app password of at least 16 characters.')
        self.controller, self.password = controller, password.encode()
        self.sessions = {}
        self.auth_lock = threading.Lock()
        self.attempts = []
        self.capacity = threading.BoundedSemaphore(16)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.capacity.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.capacity.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.capacity.release()

    def handle_error(self, request, client_address):
        pass  # No traceback or client address in logs.

    def login(self, password):
        with self.auth_lock:
            now = time.monotonic()
            self.attempts = [stamp for stamp in self.attempts if now - stamp < 60]
            if len(self.attempts) >= 5:
                return None
            if not isinstance(password, str) or not hmac.compare_digest(password.encode(), self.password):
                self.attempts.append(now)
                return None
            self.sessions = {token: expiry for token, expiry in self.sessions.items() if expiry > now}
            if len(self.sessions) >= 16:
                del self.sessions[next(iter(self.sessions))]
            token = secrets.token_urlsafe(32)
            self.sessions[token] = now + 12 * 3600
            return token

    def authenticated(self, value):
        with self.auth_lock:
            return isinstance(value, str) and value.startswith('Bearer ') and self.sessions.get(value[7:], 0) > time.monotonic()


class Handler(BaseHTTPRequestHandler):
    server_version = 'Decrumb'
    sys_version = ''

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_):
        pass  # Requests may contain private preview text or authentication material.

    def reply(self, code, data, kind='application/json'):
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def send_error(self, code, message=None, explain=None):
        self.reply(code, {'error': 'Request rejected.'})

    def same_origin(self):
        # Proxy preserves the browser Host. Never trust arbitrary forwarded headers.
        try:
            origin = urlsplit(self.headers.get('Origin', ''))
            return (origin.scheme in {'http', 'https'} and origin.netloc == self.headers.get('Host') and
                    not origin.path and not origin.query and not origin.fragment and
                    self.headers.get('Sec-Fetch-Site') not in {'cross-site', 'same-site'})
        except ValueError:
            return False

    def do_GET(self):
        try:
            if self.path in ASSETS:
                name, kind = ASSETS[self.path]
                self.reply(200, (APP / 'web' / name).read_bytes(), kind)
            elif self.path == '/healthz':
                self.reply(200, {'ok': True})
            elif not self.server.authenticated(self.headers.get('Authorization')):
                self.reply(401, {'error': 'Unlock Decrumb to continue.'})
            elif self.path == '/api/status':
                self.reply(200, self.server.controller.snapshot())
            elif self.path == '/api/qr':
                self.reply(200, self.server.controller.qr(), 'image/png')
            else:
                self.reply(404, {'error': 'Not found.'})
        except Exception:
            self.reply(409, {'error': 'Not ready. Refresh the dashboard and retry.'})

    def do_POST(self):
        try:
            if not self.same_origin() or self.headers.get('Content-Type') != 'application/json' or self.headers.get('Transfer-Encoding'):
                self.reply(403, {'error': 'Request must come from this dashboard.'})
                return
            lengths = self.headers.get_all('Content-Length', [])
            if len(lengths) != 1 or not lengths[0].isdigit() or not 0 < int(lengths[0]) <= MAX_BODY:
                self.reply(413, {'error': 'Request is too large or invalid.'})
                return
            data = json.loads(self.rfile.read(int(lengths[0])))
            if not isinstance(data, dict):
                raise ValueError()
            if self.path == '/api/login':
                token = self.server.login(data.get('password'))
                self.reply(200 if token else 401, {'token': token} if token else {'error': 'Password not accepted. After five attempts, wait one minute.'})
            elif not self.server.authenticated(self.headers.get('Authorization')):
                self.reply(401, {'error': 'Unlock Decrumb to continue.'})
            elif self.path == '/api/logout':
                with self.server.auth_lock:
                    self.server.sessions.pop(self.headers['Authorization'][7:], None)
                self.reply(200, {'ok': True})
            elif self.path.startswith('/api/'):
                result = self.server.controller.action(self.path[5:], data)
                self.reply(200, result if result is not None else {'ok': True})
            else:
                self.reply(404, {'error': 'Not found.'})
        except decrumb.SafeError as error:
            diagnostics.failure(self.server.controller.root, error)
            self.reply(409, {'error': str(error)})
        except (ValueError, KeyError, TypeError):
            self.reply(400, {'error': 'Check the supplied settings and try again.'})
        except Exception as error:
            diagnostics.failure(self.server.controller.root, error)
            self.reply(500, {'error': 'The operation could not finish. Refresh and retry.'})


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/data'))
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--bootstrap', action='store_true')
    args = parser.parse_args()
    if args.bootstrap:
        import container_dependency
        container_dependency.install(args.root)
        return
    password = os.environ.pop('DECRUMB_PASSWORD', '')
    if len(password) < 16:
        raise decrumb.SafeError('Set a private app password of at least 16 characters.')
    controller = Controller(args.root)
    try:
        with Server((args.host, args.port), controller, password) as server:
            controller.start()
            stop = threading.Event()
            def shutdown(*_):
                if not stop.is_set():
                    stop.set()
                    threading.Thread(target=server.shutdown, daemon=True).start()
            signal.signal(signal.SIGTERM, shutdown)
            signal.signal(signal.SIGINT, shutdown)
            server.serve_forever(poll_interval=0.25)
    finally:
        controller.close()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Decrumb could not start. Check its data permissions, app password and available storage.', file=sys.stderr)
        sys.exit(1)
