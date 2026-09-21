# SPDX-License-Identifier: AGPL-3.0-only
import gzip
import contextlib
import io
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import decrumb
import pi
from tools import install_pi, package_pi

ROOT = Path(__file__).resolve().parent.parent


class FakeService:
    def __init__(self, root, app, unit, *, fail_install=False):
        self.root, self.app, self.path = root, app, unit
        self.running = False
        self.fail_install = fail_install
        self.calls = []
    def check_owned(self):
        pass
    def loaded(self):
        return self.running
    def call(self, *args, **kwargs):
        self.calls.append(args)
        return True
    def stop(self, disable=False):
        self.running = False
        with decrumb.exclusive(self.root):
            pass
    def install(self):
        if self.fail_install:
            raise decrumb.SafeError('Synthetic activation failure.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(pi.unit_text(self.root, self.app))
    def start(self):
        self.running = True


class PiPlatformTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'source'
        self.source.mkdir()
        for name in package_pi.ROOT_FILES + package_pi.TOOLS + ['rules/defaults.json', 'linux/dependencies.json']:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / name).read_bytes())
        files = {str(p.relative_to(self.source)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in self.source.rglob('*') if p.is_file()}
        (self.source / 'pi-manifest.json').write_text(json.dumps({'schema': 1, 'version': '1.0.0', 'files': files}))
        self.target = self.base / 'lib/decrumb'
        self.launcher = self.base / 'bin/decrumb'
        self.root = self.base / 'private'
        self.root.mkdir()
        self.service = FakeService(self.root, self.target, self.base / 'units/decrumb.service')

    @staticmethod
    def fake_dependency(source, destination, archive=None):
        destination.write_text('#!/bin/sh\nexit 0\n')
        destination.chmod(0o700)

    def install(self):
        with patch.object(install_pi, 'obtain_signal', self.fake_dependency):
            install_pi.install(self.source, self.target, self.launcher, self.root, service=self.service)

    def test_install_uses_private_runtime_and_does_not_start_unlinked(self):
        self.install()
        config = decrumb.load_config(self.root)
        self.assertIsNone(config['account'])
        self.assertEqual(config['helper'], str(self.target / 'portable_cleaner.py'))
        self.assertEqual(config['phone_commands'], {'enabled': False})
        self.assertFalse(self.service.running)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.root / 'config.json').stat().st_mode & 0o777, 0o600)
        self.assertTrue(self.launcher.read_text().startswith('#!/usr/bin/python3\n' + install_pi.LAUNCHER_MARKER))
        self.assertFalse((self.target / 'config.json').exists())

    def test_upgrade_preserves_pairing_rules_pause_and_private_files(self):
        self.install()
        config = decrumb.load_config(self.root)
        config.update(account='synthetic-account', paused=True)
        config['settings']['excludedURLs'] = ['https://example.org']
        decrumb.write_json(self.root / 'config.json', config)
        (self.root / 'signal-cli/synthetic.key').write_text('synthetic-key')
        self.install()
        self.assertEqual(decrumb.load_config(self.root), config)
        self.assertEqual((self.root / 'signal-cli/synthetic.key').read_text(), 'synthetic-key')
        self.assertFalse(self.service.running)
        self.assertFalse(self.target.with_name('.decrumb-previous').exists())

    def test_failed_activation_restores_code_config_launcher_unit_and_service(self):
        self.install()
        config = decrumb.load_config(self.root)
        config['account'] = 'synthetic-account'
        decrumb.write_json(self.root / 'config.json', config)
        (self.target / 'old-release-marker').write_text('preserve')
        before = {p: p.read_bytes() for p in [self.root / 'config.json', self.launcher, self.service.path]}
        self.service.running = True
        self.service.fail_install = True
        with self.assertRaises(decrumb.SafeError):
            self.install()
        self.assertTrue((self.target / 'old-release-marker').exists())
        self.assertTrue(self.service.running)
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)

    def test_download_failure_happens_before_existing_service_is_stopped(self):
        self.install()
        self.service.running = True
        with patch.object(install_pi, 'obtain_signal', side_effect=decrumb.SafeError('Synthetic download failure.')):
            with self.assertRaises(decrumb.SafeError):
                install_pi.install(self.source, self.target, self.launcher, self.root, service=self.service)
        self.assertTrue(self.service.running)
        self.assertTrue(self.target.exists())

    def test_foreign_directory_and_command_are_not_replaced(self):
        self.target.mkdir(parents=True)
        (self.target / 'keep').write_text('foreign')
        with self.assertRaises(decrumb.SafeError):
            self.install()
        self.assertEqual((self.target / 'keep').read_text(), 'foreign')
        self.target.rename(self.base / 'foreign')
        self.launcher.parent.mkdir(parents=True)
        self.launcher.write_text('foreign-command')
        with self.assertRaises(decrumb.SafeError):
            self.install()
        self.assertEqual(self.launcher.read_text(), 'foreign-command')

    def test_symbolic_link_targets_and_source_files_rejected(self):
        self.target.parent.mkdir(parents=True)
        self.target.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(decrumb.SafeError):
            self.install()
        self.target.unlink()
        original = self.source / 'notes.py'
        data = original.read_bytes()
        original.unlink()
        substitute = self.base / 'notes.py'
        substitute.write_bytes(data)
        original.symlink_to(substitute)
        with self.assertRaises(decrumb.SafeError):
            self.install()

    def test_modified_release_rejected_before_execution(self):
        (self.source / 'pi.py').write_text('changed')
        with patch.object(install_pi, 'obtain_signal') as fetch:
            with self.assertRaises(decrumb.SafeError):
                self.install()
            fetch.assert_not_called()

    def test_configure_imports_mac_export_and_inner_settings(self):
        self.install()
        file = self.base / 'rules-export.json'
        settings = {'mode': 'off', 'baseURLs': [], 'excludedURLs': [], 'rules': []}
        for value in ({'version': 1, 'settings': settings}, settings):
            file.write_text(json.dumps(value))
            with patch.object(pi, 'PiService', return_value=self.service), contextlib.redirect_stdout(io.StringIO()):
                pi.dispatch(SimpleNamespace(command='configure', file=file), self.root)
            self.assertEqual(decrumb.load_config(self.root)['settings'], settings)

    def test_invalid_rules_exports_do_not_change_existing_config(self):
        self.install()
        file = self.base / 'invalid-rules.json'
        original = (self.root / 'config.json').read_bytes()
        for value in ({'version': 2, 'settings': {}}, {'version': True, 'settings': {}},
                      {'version': '1', 'settings': {}}, {'version': 1}, {'settings': {}},
                      {'version': 1, 'settings': []}, {'version': 1, 'settings': {}, 'account': 'synthetic'}, []):
            file.write_text(json.dumps(value))
            with patch.object(pi, 'PiService', return_value=self.service):
                with self.assertRaises(decrumb.SafeError):
                    pi.dispatch(SimpleNamespace(command='configure', file=file), self.root)
            self.assertEqual((self.root / 'config.json').read_bytes(), original)

    def test_service_ownership_and_systemd_escaping(self):
        unit = self.base / 'decrumb.service'
        control = pi.PiService(self.root, self.source, unit)
        unit.write_text('[Service]\nWorkingDirectory=/other\n')
        with self.assertRaises(decrumb.SafeError):
            control.check_owned()
        root = Path('/tmp/user with $ and %/state')
        rendered = pi.unit_text(root, self.source)
        self.assertIn('WorkingDirectory="/tmp/user with $ and %%/state"', rendered)
        self.assertIn('--root "/tmp/user with $$ and %%/state"', rendered)
        with self.assertRaises(decrumb.SafeError):
            pi.unit_quote('/tmp/\nExecStart=/bad')

    def test_service_start_requires_fresh_running_heartbeat(self):
        self.install()
        control = pi.PiService(self.root, self.target, self.service.path)
        with patch.object(control, 'loaded', return_value=True), patch.object(decrumb, 'read_status', return_value={'state': 'running', 'updated_at': 200}):
            control.wait_ready(200, timeout=0.01)
        with patch.object(control, 'loaded', return_value=False), patch.object(decrumb, 'read_status', return_value={'state': 'running', 'updated_at': 200}):
            with self.assertRaisesRegex(decrumb.SafeError, 'failed to start'):
                control.wait_ready(200, timeout=0.01)
        with patch.object(control, 'loaded', return_value=True), patch.object(decrumb, 'read_status', return_value={'state': 'running', 'updated_at': 199}):
            with self.assertRaisesRegex(decrumb.SafeError, 'not connected'):
                control.wait_ready(200, timeout=0.01)

    def test_swap_failure_restores_previous_installation(self):
        self.install()
        old_code = (self.target / 'pi.py').read_bytes()
        self.service.running = True
        original = Path.rename
        def rename(path, target):
            if path.name.startswith('.decrumb-stage-'):
                raise OSError('Synthetic swap failure')
            return original(path, target)
        with patch.object(Path, 'rename', rename):
            with self.assertRaises(OSError):
                self.install()
        self.assertEqual((self.target / 'pi.py').read_bytes(), old_code)
        self.assertTrue(self.service.running)

    def test_runtime_nested_in_installation_cannot_be_replaced(self):
        self.install()
        nested = self.target / 'private'
        nested.mkdir()
        config = decrumb.load_config(self.root)
        config['account'] = 'synthetic-account'
        decrumb.write_json(nested / 'config.json', config)
        (nested / 'synthetic.key').write_text('must-survive')
        original = (nested / 'config.json').read_bytes()
        with self.assertRaisesRegex(decrumb.SafeError, 'separate'):
            install_pi.install(self.source, self.target, self.launcher, nested, service=self.service)
        self.assertEqual((nested / 'config.json').read_bytes(), original)
        self.assertEqual((nested / 'synthetic.key').read_text(), 'must-survive')
        self.assertFalse((nested / 'control.lock').exists())
        with self.assertRaisesRegex(decrumb.SafeError, 'separate'):
            install_pi.install(self.source, self.target, self.launcher, self.source / 'private', service=self.service)
        self.assertFalse((self.source / 'private').exists())

    def test_control_operations_are_serialized(self):
        with pi.operation(self.root):
            with self.assertRaises(decrumb.SafeError):
                with pi.operation(self.root):
                    pass

    def test_checksum_mismatch_never_decompresses_or_executes(self):
        packed = self.base / 'wrong.gz'
        packed.write_bytes(gzip.compress(b'fake'))
        with patch.object(install_pi, 'verify_binary') as verify:
            with self.assertRaises(decrumb.SafeError):
                install_pi.obtain_signal(self.source, self.base / 'binary', packed)
            verify.assert_not_called()

    def test_package_excludes_private_and_git_ignored_files(self):
        for name in ('docs/config.json', 'docs/local.pem', 'docs/private/runtime.json', 'docs/local-notes.txt'):
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic private placeholder')
        (self.source / '.git').mkdir()
        listed = '\0'.join(str(p.relative_to(self.source)) for p in self.source.rglob('*')
                           if p.is_file() and p.name != 'local-notes.txt') + '\0'
        with patch.object(package_pi.materials.subprocess, 'check_output', return_value=listed.encode()):
            files = package_pi.source_files(self.source)
        self.assertFalse(any(name.endswith(('.pem', '/config.json', '/runtime.json', '/local-notes.txt')) for name in files))
        self.assertIn('desktop.py', files)
        self.assertIn('tools/prepare_release_materials.py', files)

    def test_archive_contains_only_selected_source_and_valid_manifest(self):
        archive = package_pi.package(ROOT, self.base / 'out', '1.0.0', '4')
        original = archive.read_bytes()
        self.assertEqual(package_pi.package(ROOT, self.base / 'out', '1.0.0', '4').read_bytes(), original)
        unpack = self.base / 'unpacked'
        with tarfile.open(archive) as bundle:
            names = bundle.getnames()
            self.assertFalse(any(name.endswith('/config.json') or '/build/' in name or name.endswith('/signal-cli') for name in names))
            bundle.extractall(unpack)
        extracted = next(unpack.iterdir())
        manifest = install_pi.read_manifest(extracted)
        self.assertIn('phone_commands.py', manifest['files'])
        self.assertNotIn('signal-cli', manifest['files'])


if __name__ == '__main__':
    unittest.main()
