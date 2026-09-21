# SPDX-License-Identifier: AGPL-3.0-only
"""Offline browser authentication, privacy, and controller transitions."""
import contextlib
import gzip
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import container_dependency
import decrumb
import web_server


class Process:
    pid = os.getpid()
    returncode = None

    def poll(self):
        return self.returncode


class OfflineController(web_server.Controller):
    def launch(self, role):
        assert self.child is None
        self.child, self.role, self.started = Process(), role, decrumb.now_ms()

    def stop_child(self):
        self.child = self.role = None
        (self.root / 'pairing.png').unlink(missing_ok=True)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='decrumb-web-test-')
        self.root = Path(self.temp.name)
        self.control = OfflineController(self.root)
        self.control.ready = True

    def tearDown(self):
        self.control.close()
        self.temp.cleanup()

    def linked(self):
        config = self.control.config()
        config['account'] = '+15550000001'
        decrumb.write_json(self.root / 'config.json', config)

    def test_defaults_and_private_snapshot(self):
        self.linked()
        snapshot = self.control.snapshot()
        self.assertFalse(snapshot['phone_commands']['enabled'])
        self.assertEqual(snapshot['notes']['cleanup_mode'], 'manual')
        serialized = json.dumps(snapshot)
        self.assertNotIn('+15550000001', serialized)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn('signal_cli', snapshot)
        self.assertEqual((self.root / 'config.json').stat().st_mode & 0o777, 0o600)

    def test_duplicate_controller_and_code_roots_rejected(self):
        with self.assertRaises(BlockingIOError):
            other = OfflineController(self.root)
        with self.assertRaises(decrumb.SafeError):
            OfflineController(web_server.APP / 'runtime')

    def test_boot_starts_linked_worker_and_pause_survives_restart(self):
        self.linked()
        self.control.tick()
        self.assertEqual(self.control.role, 'run')
        self.control.action('pause', {})
        self.control.tick()
        self.assertIsNone(self.control.child)
        self.control.close()
        self.control = OfflineController(self.root)
        self.control.ready = True
        self.control.tick()
        self.assertEqual(self.control.snapshot()['state'], 'paused')
        self.control.action('resume', {})
        self.assertEqual(self.control.role, 'run')

    def test_running_requires_fresh_heartbeat_from_owned_process(self):
        self.linked()
        decrumb.write_json(self.root / 'status.json', {'state': 'running', 'pid': os.getpid(), 'updated_at': 1})
        self.control.tick()
        self.assertEqual(self.control.snapshot()['state'], 'starting')
        decrumb.write_json(self.root / 'status.json', {'state': 'running', 'pid': os.getpid(), 'updated_at': decrumb.now_ms()})
        self.assertEqual(self.control.snapshot()['state'], 'running')

    def test_pairing_starts_worker_only_after_link_and_removes_qr(self):
        self.control.action('pair', {})
        (self.root / 'pairing.png').write_bytes(b'synthetic-private-qr')
        self.assertTrue(self.control.snapshot()['qr_ready'])
        self.assertEqual(self.control.qr(), b'synthetic-private-qr')
        with self.assertRaises(decrumb.SafeError):
            self.control.action('pause', {})
        self.linked()
        self.control.child.returncode = 0
        self.control.tick()
        self.assertEqual(self.control.role, 'run')
        self.assertFalse((self.root / 'pairing.png').exists())
        with self.assertRaises(decrumb.SafeError):
            self.control.action('pair', {})

    def test_pair_cancel_timeout_and_setup_retry(self):
        self.control.action('pair', {})
        (self.root / 'pairing.png').write_bytes(b'synthetic-qr')
        self.control.action('cancel-pair', {})
        self.assertFalse((self.root / 'pairing.png').exists())
        self.control.action('pair', {})
        self.control.child.returncode = 1
        self.control.tick()
        self.assertEqual(self.control.snapshot()['state'], 'unlinked')
        self.assertIsNotNone(self.control.error)
        self.control.ready = False
        self.control.action('retry-setup', {})
        self.control.child.returncode = 1
        self.control.tick()
        self.assertEqual(self.control.snapshot()['state'], 'setup_error')
        self.control.action('retry-setup', {})
        self.control.child.returncode = 0
        self.control.tick()
        self.assertTrue(self.control.ready)

    def test_crash_backoff(self):
        self.linked()
        self.control.tick()
        self.control.child.returncode = 1
        self.control.tick()
        self.assertIsNone(self.control.child)
        self.assertGreater(self.control.retry_at, time.monotonic())
        self.control.retry_at = 0
        self.control.tick()
        self.assertEqual(self.control.role, 'run')

    def test_settings_validation_and_no_message_snapshot(self):
        with contextlib.closing(decrumb.Store(self.root / 'outbox.sqlite3')) as store:
            store.db.execute("INSERT INTO outbox(id,timestamp,state,body) VALUES('fixture',?,'pending','synthetic-private-body')", (decrumb.now_ms(),))
            store.db.commit()
        snapshot = self.control.snapshot()
        self.assertNotIn('synthetic-private-body', json.dumps(snapshot))
        data = {key: snapshot[key] for key in ('settings', 'notes', 'phone_commands')}
        data['phone_commands'] = {'enabled': 1}
        with self.assertRaises(decrumb.SafeError):
            self.control.action('settings', data)
        self.assertFalse(self.control.config()['phone_commands']['enabled'])
        data['phone_commands'] = {'enabled': True}
        self.control.action('settings', data)
        with contextlib.closing(decrumb.Store(self.root / 'outbox.sqlite3')) as store:
            self.assertEqual(store.counts().get('pending'), 1)
        data['settings']['mode'] = 'off'
        self.control.action('settings', data)
        with contextlib.closing(decrumb.Store(self.root / 'outbox.sqlite3')) as store:
            self.assertEqual(store.counts().get('pending', 0), 0)

    def test_preview_is_offline_and_does_not_save(self):
        before = (self.root / 'config.json').read_bytes()
        data = {'text': 'https://example.com/a?utm_source=test&id=42', 'settings': self.control.config()['settings']}
        with patch('subprocess.Popen', side_effect=AssertionError('No subprocess allowed')):
            result = self.control.action('preview', data)
        self.assertEqual(result['urls'], ['https://example.com/a?id=42'])
        self.assertEqual((self.root / 'config.json').read_bytes(), before)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='decrumb-web-http-test-')
        self.control = OfflineController(Path(self.temp.name))
        self.control.ready = True
        self.server = web_server.Server(('127.0.0.1', 0), self.control, 'synthetic-password-not-a-secret')
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.control.close()
        self.temp.cleanup()

    def request(self, path, data=None, token='', **headers):
        merged = {'Authorization': 'Bearer ' + token}
        if data is not None:
            merged.update({'Origin': self.base, 'Content-Type': 'application/json'})
        merged.update(headers)
        request = Request(self.base + path, data=None if data is None else json.dumps(data).encode(), headers=merged)
        try:
            result = urlopen(request, timeout=5)
        except HTTPError as error:
            result = error
        with result:
            return result.status, result.read(), result.headers

    def login(self):
        code, body, _ = self.request('/api/login', {'password': 'synthetic-password-not-a-secret'})
        self.assertEqual(code, 200)
        return json.loads(body)['token']

    def test_all_private_routes_require_auth(self):
        for path in ('/api/status', '/api/qr', '/config.json', '/../config.json'):
            self.assertEqual(self.request(path)[0], 401)
        for action in ('pair', 'pause', 'resume', 'settings', 'preview', 'cleanup', 'retry-setup', 'clear-queue'):
            self.assertEqual(self.request('/api/' + action, {})[0], 401)
        self.assertEqual(self.request('/')[0], 200)
        self.assertEqual(self.request('/healthz')[0], 200)

    def test_authenticated_state_headers_and_logout(self):
        token = self.login()
        code, body, headers = self.request('/api/status', token=token)
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)['state'], 'unlinked')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertNotIn('Access-Control-Allow-Origin', headers)
        self.assertEqual(self.request('/api/logout', {}, token)[0], 200)
        self.assertEqual(self.request('/api/status', token=token)[0], 401)

    def test_cross_origin_and_non_json_mutations_rejected(self):
        token = self.login()
        for headers in ({'Origin': 'https://attacker.example'}, {'Origin': 'null'},
                        {'Origin': self.base + '/'}, {'Sec-Fetch-Site': 'same-site'},
                        {'Content-Type': 'text/plain'}, {'Transfer-Encoding': 'chunked'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request('/api/pair', {}, token, **headers)[0], 403)
        self.assertIsNone(self.control.child)

    def test_session_expiry_and_bounded_login_attempts(self):
        token = self.login()
        self.server.sessions[token] = 0
        self.assertEqual(self.request('/api/status', token=token)[0], 401)
        for _ in range(5):
            self.assertEqual(self.request('/api/login', {'password': 'wrong'})[0], 401)
        self.assertEqual(self.request('/api/login', {'password': 'synthetic-password-not-a-secret'})[0], 401)

    def test_input_bounds_and_redacted_errors(self):
        token = self.login()
        self.assertEqual(self.request('/api/preview', {'text': 'x' * (64 * 1024)}, token)[0], 413)
        with patch.object(self.control, 'action', side_effect=RuntimeError('synthetic-private-identifier')):
            code, body, _ = self.request('/api/pause', {}, token)
        self.assertEqual(code, 500)
        self.assertNotIn(b'synthetic-private-identifier', body)


class DependencyTests(unittest.TestCase):
    def test_bounded_copy_and_machine_validation(self):
        with self.assertRaises(decrumb.SafeError):
            container_dependency.copy_bounded(io.BytesIO(b'12345'), io.BytesIO(), 4)
        with patch('platform.machine', return_value='i686'):
            with self.assertRaises(decrumb.SafeError):
                container_dependency.architecture()

    def test_archive_never_extracts_member_paths_or_links(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            packed = root / 'archive.tgz'
            with tarfile.open(packed, 'w:gz') as archive:
                member = tarfile.TarInfo('../../signal-cli')
                member.size = 7
                archive.addfile(member, io.BytesIO(b'fixture'))
                link = tarfile.TarInfo('evil-link')
                link.type, link.linkname = tarfile.SYMTYPE, '/etc/passwd'
                archive.addfile(link)
            container_dependency.unpack(packed, root / 'binary', 'tar.gz')
            self.assertEqual((root / 'binary').read_bytes(), b'fixture')
            self.assertEqual({p.name for p in root.iterdir()}, {'archive.tgz', 'binary'})

    def test_checksum_failure_never_installs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            packed = root / 'wrong.gz'
            packed.write_bytes(gzip.compress(b'not the dependency'))
            with self.assertRaises(decrumb.SafeError), patch('container_dependency.verify') as verify:
                container_dependency.install(root, archive=packed)
            verify.assert_not_called()
            self.assertFalse((root / 'dependency/signal-cli').exists())
            self.assertFalse((root / 'dependency/download.part').exists())


if __name__ == '__main__':
    unittest.main()
