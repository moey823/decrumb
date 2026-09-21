# SPDX-License-Identifier: AGPL-3.0-only
"""Offline Windows controls, archive boundaries and native lifecycle checks."""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch
import zipfile

import cli_common
import decrumb
import diagnostics
import runtime_platform as runtime
import windows
import windows_native
from tools import build_windows

ROOT = Path(__file__).resolve().parents[1]


class WindowsControlsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = {'version': 1, 'account': 'synthetic-account', 'helper': str(self.root / 'helper'),
                       'signal_cli': str(self.root / 'signal'), 'settings': {'mode': 'all', 'baseURLs': []},
                       'phone_commands': {'enabled': False}, 'paused': False}
        decrumb.write_json(self.root / 'config.json', self.config)

    def tearDown(self):
        self.temporary.cleanup()

    def test_exclusive_and_background_locks_release(self):
        with windows.operation(self.root):
            with self.assertRaises(decrumb.SafeError):
                with windows.operation(self.root):
                    pass
        with windows.operation(self.root):
            pass
        with windows.operation(self.root, 'background.lock'):
            self.assertTrue(windows.WindowsService(self.root).loaded())
        self.assertFalse(windows.WindowsService(self.root).loaded())

    def test_stop_does_not_kill_any_pid(self):
        service = windows.WindowsService(self.root)
        with patch.object(windows.os, 'kill', side_effect=AssertionError('Never kill by PID')):
            service.stop()
        self.assertTrue((self.root / 'stop.request').exists())

    def test_pause_preserves_account_and_is_durable(self):
        with patch.object(windows, 'WindowsService') as service, contextlib.redirect_stdout(io.StringIO()):
            windows.dispatch(argparse.Namespace(command='pause'), self.root)
        saved = decrumb.load_config(self.root, validate_helper=False)
        self.assertTrue(saved['paused'])
        self.assertEqual(saved['account'], self.config['account'])
        service.return_value.stop.assert_called_once()

    def test_rule_change_discards_only_pending_and_preserves_account(self):
        with contextlib.closing(decrumb.Store(self.root / 'outbox.sqlite3')) as store:
            store.enqueue('synthetic-event', decrumb.now_ms(), ['https://example.invalid/'])
        service = Mock()
        service.loaded.return_value = True
        cli_common.change_settings(self.root, self.config, service, 'settings', {'mode': 'off', 'baseURLs': []})
        saved = decrumb.load_config(self.root, validate_helper=False)
        self.assertEqual(saved['account'], 'synthetic-account')
        with contextlib.closing(decrumb.Store(self.root / 'outbox.sqlite3')) as store:
            self.assertEqual(store.counts(), {'cancelled': 1})
        service.start.assert_called_once()

    def test_setup_preserves_account_rules_and_keys(self):
        bundle = self.root / 'bundle'
        for name in ('signal-cli/bin/signal-cli.bat', 'jre/bin/java.exe'):
            path = bundle / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        self.config['paused'] = True
        self.config['settings']['excludedURLs'] = ['https://example.invalid']
        decrumb.write_json(self.root / 'config.json', self.config)
        (self.root / 'signal-cli').mkdir()
        (self.root / 'signal-cli/synthetic.key').write_text('synthetic-secret')
        with patch.object(decrumb, 'clean', return_value=[]):
            saved = windows.initialize(self.root, bundle)
        self.assertEqual(saved['account'], self.config['account'])
        self.assertEqual(saved['settings'], self.config['settings'])
        self.assertTrue(saved['paused'])
        self.assertEqual((self.root / 'signal-cli/synthetic.key').read_text(), 'synthetic-secret')

    def test_pairing_failure_removes_qr_and_never_saves_account(self):
        rpc = Mock()
        rpc.__enter__ = Mock(return_value=rpc)
        rpc.__exit__ = Mock(return_value=False)
        rpc.call.side_effect = [[], {'deviceLinkUri': 'sgnl://linkdevice?synthetic'}, decrumb.SafeError('Pairing code expired.')]
        def qr(*args, **kwargs):
            (self.root / 'pairing.png').write_bytes(b'synthetic')
        with patch.object(decrumb, 'Rpc', return_value=rpc), patch.object(decrumb.subprocess, 'run', side_effect=qr), \
                patch.object(decrumb.signal, 'signal'), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(decrumb.SafeError):
                decrumb.pair(self.root, self.config)
        self.assertFalse((self.root / 'pairing.png').exists())

    def test_startup_owns_only_its_registry_value_and_is_opt_in(self):
        registry = Mock(HKEY_CURRENT_USER=1, REG_SZ=1, KEY_SET_VALUE=2)
        key = Mock()
        registry.CreateKeyEx.return_value.__enter__ = Mock(return_value=key)
        registry.CreateKeyEx.return_value.__exit__ = Mock(return_value=False)
        command = [r'C:\Decrumb\decrumb-background.exe', '--root', r'C:\Users\Test\AppData\Local\Decrumb', '_background']
        with patch.dict(sys.modules, {'winreg': registry}), \
                patch.object(windows, 'background_command', return_value=command), \
                patch.object(windows, 'startup_value', return_value='unrelated-command'):
            with self.assertRaises(decrumb.SafeError):
                windows.set_startup(self.root, self.config, True)
            registry.SetValueEx.assert_not_called()
        with patch.dict(sys.modules, {'winreg': registry}), \
                patch.object(windows, 'background_command', return_value=command), \
                patch.object(windows, 'startup_value', return_value=None):
            windows.set_startup(self.root, self.config, True)
        self.assertEqual(self.config['startup_command'], subprocess.list2cmdline(command))
        self.assertNotIn('synthetic-account', self.config['startup_command'])

    def test_windows_status_probe_never_uses_os_kill(self):
        handle = Mock()
        api = Mock()
        api.OpenProcess.return_value = handle
        events = Mock(WAIT_TIMEOUT=258)
        events.WaitForSingleObject.return_value = 258
        with patch.object(runtime.sys, 'platform', 'win32'), \
                patch.dict(sys.modules, {'win32api': api, 'win32event': events, 'pywintypes': types.SimpleNamespace(error=OSError)}), \
                patch.object(runtime.os, 'kill', side_effect=AssertionError('Windows os.kill terminates processes')):
            self.assertTrue(runtime.process_alive(1234))
        handle.Close.assert_called_once()

    def test_runtime_cannot_overlap_source_or_bundle(self):
        for code, state in ((self.root, self.root / 'state'), (self.root / 'app', self.root)):
            with self.assertRaises(decrumb.SafeError):
                cli_common.guard_runtime(state, code)

    def test_windows_diagnostics_report_platform_without_identifiers(self):
        with patch.object(diagnostics.platform, 'system', return_value='Windows'), \
                patch.object(diagnostics.platform, 'version', return_value='10.0.26100'), \
                patch.object(diagnostics.platform, 'machine', return_value='AMD64'):
            report = diagnostics.report(self.root)
        self.assertEqual(report['platform'], {'os': 'Windows', 'os_version': '10.0.26100', 'architecture': 'AMD64'})
        self.assertNotIn('synthetic-account', json.dumps(report))


class WindowsArchiveTests(unittest.TestCase):
    def test_distinct_notices_with_the_same_filename_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / 'bundle'
            target.mkdir()
            (root / 'LICENSE.txt').write_text('Synthetic Python license')
            files = [Path('first/LICENSE'), Path('second/LICENSE')]
            for index, entry in enumerate(files):
                (root / entry).parent.mkdir()
                (root / entry).write_text('Synthetic license ' + str(index))
            distribution = Mock(files=files)
            distribution.locate_file.side_effect = lambda path: root / path
            with patch.object(build_windows.importlib.metadata, 'distribution', return_value=distribution), \
                    patch.object(build_windows.sys, 'base_prefix', str(root)):
                build_windows.copy_notices(target)
            self.assertEqual((target / 'licenses/pywin32/first/LICENSE').read_text(), 'Synthetic license 0')
            self.assertEqual((target / 'licenses/pywin32/second/LICENSE').read_text(), 'Synthetic license 1')

    def test_archive_paths_reject_windows_aliases_and_traversal(self):
        for name in ('../outside', 'bundle/../outside', 'bundle/C:drive', 'bundle/file:stream',
                     'bundle/CON.txt', 'bundle/file.', 'bundle/a\\outside', '/bundle/x'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                build_windows.relative_member(name, 'bundle')
        self.assertEqual(build_windows.relative_member('bundle/lib/ok.jar', 'bundle'), Path('lib/ok.jar'))

    def test_extract_rejects_links_case_collisions_and_zip_escape(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / 'test.zip'
            for index, names in enumerate((['bundle/../outside'], ['bundle/A', 'bundle/a'])):
                with zipfile.ZipFile(archive, 'w') as out:
                    for name in names:
                        out.writestr(name, b'synthetic')
                with self.assertRaises(ValueError):
                    build_windows.extract(archive, {'archive': 'zip', 'prefix': 'bundle'}, root / str(index))
            archive = root / 'test.tar.gz'
            with tarfile.open(archive, 'w:gz') as out:
                entry = tarfile.TarInfo('bundle/link')
                entry.type = tarfile.SYMTYPE
                entry.linkname = '../../outside'
                out.addfile(entry)
            with self.assertRaises(ValueError):
                build_windows.extract(archive, {'archive': 'tar.gz', 'prefix': 'bundle'}, root / 'tar')
            self.assertFalse((root / 'outside').exists())

    def test_bad_download_hash_is_not_cached_or_extracted(self):
        with tempfile.TemporaryDirectory() as folder:
            dependency = {'sha256': hashlib.sha256(b'expected').hexdigest(), 'archive': 'zip', 'url': 'https://example.invalid/'}
            with patch.object(build_windows.urllib.request, 'urlopen', return_value=io.BytesIO(b'changed')):
                with self.assertRaises(ValueError):
                    build_windows.download(dependency, Path(folder))
            self.assertEqual(list(Path(folder).iterdir()), [])


@unittest.skipUnless(sys.platform == 'win32', 'requires native Windows APIs')
class WindowsNativeTests(unittest.TestCase):
    def test_private_acl_inheritance_and_widened_root_rejection(self):
        import win32security
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'private'
            windows_native.secure_directory(root)
            windows_native.check_private_directory(root)
            secret = root / 'synthetic.key'
            secret.write_text('synthetic')
            descriptor = win32security.GetNamedSecurityInfo(str(secret), win32security.SE_FILE_OBJECT,
                                                            win32security.DACL_SECURITY_INFORMATION)
            self.assertEqual(descriptor.GetSecurityDescriptorDacl().GetAceCount(), 2)
            acl = win32security.ACL()
            acl.AddAccessAllowedAceEx(2, 3, 0x1F01FF, win32security.CreateWellKnownSid(win32security.WinWorldSid, None))
            win32security.SetNamedSecurityInfo(str(root), win32security.SE_FILE_OBJECT,
                win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
                None, None, acl, None)
            with self.assertRaises(OSError):
                windows_native.check_private_directory(root)

    def test_crashed_bridge_kills_its_child(self):
        script = ('import windows_native,subprocess,sys,time; windows_native.contain_children(); '
                  'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(90)"]); '
                  'print(child.pid,flush=True); time.sleep(90)')
        parent = subprocess.Popen([sys.executable, '-c', script], stdout=subprocess.PIPE, cwd=ROOT)
        child = None
        try:
            child = int(parent.stdout.readline())
            self.assertTrue(runtime.process_alive(child))
            parent.terminate()
            parent.wait(timeout=10)
            deadline = time.monotonic() + 10
            while runtime.process_alive(child) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(runtime.process_alive(child))
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait(timeout=10)
            parent.stdout.close()

    def test_offline_worker_duplicate_filters_pause_and_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'runtime with spaces'
            windows_native.secure_directory(root)
            (root / 'signal-cli').mkdir()
            (root / 'signal-cli/linked.test').touch()
            (root / 'tmp').mkdir()
            config = {'version': 1, 'account': '+15550000001', 'paused': False,
                      'signal_cli': str(ROOT / 'tests/fixtures/windows_fake_signal.py'),
                      'helper': str(ROOT / 'windows_helper.py'), 'settings': {'mode': 'all', 'baseURLs': []}}
            decrumb.write_json(root / 'config.json', config)
            service = windows.WindowsService(root)
            process = subprocess.Popen([sys.executable, str(ROOT / 'windows.py'), '--root', str(root), 'run'],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 20
                calls = root / 'signal-cli/calls.test'
                while not calls.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(calls.exists(), 'The synthetic worker did not deliver')
                service.stop()
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0)
                values = json.loads(calls.read_text())
                self.assertEqual(len(values), 1)
                self.assertTrue(values[0]['noteToSelf'])
                self.assertIn('https://example.invalid/?id=1', values[0]['message'])
                self.assertNotIn('example.invalid', (stdout + stderr).decode())
                self.assertEqual(json.loads((root / 'status.json').read_text())['counts'], {'sent': 1})
                self.assertFalse(service.loaded())
                # Background startup uses pythonw and runs after the control process returns.
                service.start()
                self.assertTrue(service.loaded())
                service.stop()
            finally:
                (root / 'stop.request').touch()
                if process.poll() is None:
                    process.wait(timeout=15)
                if process.stdout:
                    process.stdout.close()
                    process.stderr.close()


if __name__ == '__main__':
    unittest.main()
