# SPDX-License-Identifier: AGPL-3.0-only
"""Synthetic app-quit tests; never control real services or Signal accounts."""
import contextlib
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, call, patch

import decrumb
import desktop
import service
import updater


class DesktopQuitTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='decrumb-quit-test-')
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name).resolve() / 'runtime'
        self.root.mkdir()
        self.resources = Path(self.folder.name).resolve() / 'Decrumb.app/Contents/Helpers'
        self.config = {
            'version': 1, 'account': 'synthetic-self-account',
            'helper': '/synthetic/url-cleaner', 'signal_cli': '/synthetic/signal-cli',
            'settings': {'mode': 'all', 'baseURLs': []},
            'paused': False, 'start_at_login': True,
            'notes': decrumb.notes_settings({'discard_on_pause': True}),
            'phone_commands': {'enabled': True},
        }
        decrumb.write_json(self.root / 'config.json', self.config)
        with contextlib.closing(decrumb.Store(self.root / 'outbox.sqlite3')) as store:
            store.enqueue('synthetic-pending', decrumb.now_ms(), ['https://example.invalid/clean'])
            store.db.execute("INSERT INTO meta VALUES ('synthetic-receipt', 123)")
            store.db.commit()
        self.database = (self.root / 'outbox.sqlite3').read_bytes()
        self.original_config = (self.root / 'config.json').read_bytes()
        self.control = Mock()
        self.emit = Mock()
        self.recovery = service.UpdateRecovery(self.root, self.resources.parent / 'MacOS/Decrumb')
        self.recovery_factory = Mock(return_value=self.recovery)
        self.recovery_launch = Mock(return_value=Mock(returncode=1))

    def quit(self, control=None, payload=None):
        with patch.object(sys, 'argv', ['desktop.py', '--root', str(self.root),
                '--resources', str(self.resources), 'quit']), \
                patch.object(service, 'Service', return_value=control or self.control) as factory, \
                patch.object(service, 'UpdateRecovery', self.recovery_factory), \
                patch.object(self.recovery, 'launch', self.recovery_launch), \
                patch.object(service, 'configure_app_login', side_effect=AssertionError('Login preference changed')), \
                patch.object(desktop.diagnostics, 'configure'), \
                patch.object(decrumb, 'maintain_outbox', side_effect=AssertionError('Queue maintenance ran')), \
                patch.object(desktop, 'request', return_value=payload or {}), \
                patch.object(desktop, 'emit', self.emit):
            desktop.main()
        return factory

    def pending_update(self):
        value = {
            'version': 1, 'created': 123, 'owner': 4321, 'identity': 'synthetic owner',
            'token': 'synthetic-token', 'target_build': '10', 'resume': True, 'ready': False,
        }
        decrumb.write_json(self.root / updater.MARKER, value)
        service.write_plist(self.recovery.path, {
            'Label': self.recovery.label, 'WorkingDirectory': str(self.root),
        })
        return value

    def assert_preserved(self):
        self.assertEqual((self.root / 'outbox.sqlite3').read_bytes(), self.database)
        self.control.start.assert_not_called()

    def test_quit_stops_worker_and_preserves_queue_receipts_and_preferences(self):
        self.quit()
        self.control.stop.assert_called_once_with(disable_login=True)
        expected = copy.deepcopy(self.config)
        expected['paused'] = True
        self.assertEqual(decrumb.load_config(self.root, validate_helper=False), expected)
        self.emit.assert_called_once_with({'paused': True})
        self.recovery_factory.assert_not_called()
        self.assert_preserved()

    def test_stop_failure_does_not_report_success_or_change_pause(self):
        self.control.stop.side_effect = decrumb.SafeError('Synthetic worker could not stop.')
        with self.assertRaisesRegex(decrumb.SafeError, 'could not stop'):
            self.quit()
        self.emit.assert_not_called()
        self.assertEqual((self.root / 'config.json').read_bytes(), self.original_config)
        self.assert_preserved()

    def test_worker_must_release_lock_before_quit_can_succeed(self):
        with decrumb.exclusive(self.root), self.assertRaises(decrumb.SafeError):
            self.quit()
        self.control.stop.assert_called_once_with(disable_login=True)
        self.emit.assert_not_called()
        self.assertEqual((self.root / 'config.json').read_bytes(), self.original_config)
        self.assert_preserved()

    def test_unlinked_config_can_quit_without_starting_or_pairing(self):
        self.config['account'] = None
        decrumb.write_json(self.root / 'config.json', self.config)
        self.quit()
        self.control.stop.assert_called_once_with(disable_login=True)
        saved = decrumb.load_config(self.root, validate_helper=False)
        self.assertIsNone(saved['account'])
        self.assertTrue(saved['paused'])
        self.assertTrue(saved['start_at_login'])
        self.assert_preserved()

    def test_fresh_setup_quits_without_controlling_any_service(self):
        (self.root / 'config.json').unlink()
        factory = self.quit()
        factory.assert_not_called()
        self.emit.assert_called_once_with({'paused': True})
        self.assertFalse((self.root / 'config.json').exists())
        self.assert_preserved()

    def test_other_runtime_service_is_never_stopped(self):
        with patch.object(Path, 'home', return_value=Path(self.folder.name) / 'home'):
            other_control = service.Service(self.root)
        service.write_plist(other_control.login_plist, {
            'Label': service.LABEL, 'WorkingDirectory': str(Path(self.folder.name) / 'other-runtime'),
        })
        with patch.object(other_control, 'launch') as launch:
            with self.assertRaisesRegex(decrumb.SafeError, 'different runtime'):
                self.quit(other_control)
        launch.assert_not_called()
        self.emit.assert_not_called()
        self.assertEqual((self.root / 'config.json').read_bytes(), self.original_config)
        self.assert_preserved()

    def test_quit_waits_for_update_coordination(self):
        self.pending_update()
        original = (self.root / updater.MARKER).read_bytes()
        for payload in ({}, {'token': None}, {'token': 'wrong-token'}, {'token': True}):
            with self.subTest(payload=payload), self.assertRaisesRegex(decrumb.SafeError, 'Finish or cancel the update'):
                self.quit(payload=payload)
        self.control.stop.assert_not_called()
        self.emit.assert_not_called()
        self.recovery_factory.assert_not_called()
        self.assertEqual((self.root / 'config.json').read_bytes(), self.original_config)
        self.assertEqual((self.root / updater.MARKER).read_bytes(), original)
        self.assert_preserved()

    def test_owned_pending_update_is_retained_without_watchdog_or_worker_restart(self):
        transition = self.pending_update()
        self.quit(payload={'token': transition['token']})
        self.control.stop.assert_called_once_with(disable_login=True)
        self.assertEqual(updater.marker(self.root), {**transition, 'resume': False, 'ready': True})
        self.assertTrue(decrumb.load_config(self.root, validate_helper=False)['paused'])
        self.recovery_factory.assert_called_once_with(self.root, self.resources.parent / 'MacOS/Decrumb')
        target = self.recovery.domain + '/' + self.recovery.label
        self.assertEqual(self.recovery_launch.call_args_list, [call('bootout', target), call('print', target)])
        self.assertFalse(self.recovery.path.exists())
        self.emit.assert_called_once_with({'paused': True})
        self.assert_preserved()

    def test_downloaded_update_quit_creates_checkpoint_without_arming_watchdog(self):
        with patch.object(updater, 'process_identity', return_value='synthetic GUI') as identity, \
                patch.object(self.recovery, 'arm') as arm:
            self.quit(payload={'target_build': '10', 'owner_pid': 4321})
        identity.assert_called_once_with(4321)
        arm.assert_not_called()
        self.recovery_launch.assert_not_called()
        self.control.stop.assert_called_once_with(disable_login=True)
        transition = updater.marker(self.root)
        self.assertEqual({key: transition[key] for key in ('version', 'owner', 'identity', 'target_build', 'resume', 'ready')}, {
            'version': 1, 'owner': 4321, 'identity': 'synthetic GUI', 'target_build': '10', 'resume': False, 'ready': True,
        })
        self.assertRegex(transition['token'], r'^[a-f0-9]{32}$')
        self.assertGreater(transition['created'], 0)
        self.assertTrue(decrumb.load_config(self.root, validate_helper=False)['paused'])
        self.emit.assert_called_once_with({'paused': True})
        self.assert_preserved()

    def test_downloaded_update_quit_requires_valid_build_before_service_effects(self):
        with patch.object(updater, 'process_identity') as identity:
            for target in (None, '', 0, 10, True, '0', '-1', '1.2', '1000000000', 'synthetic'):
                with self.subTest(target=target), self.assertRaisesRegex(decrumb.SafeError, 'build number'):
                    self.quit(payload={'target_build': target, 'owner_pid': 4321})
        identity.assert_not_called()
        self.control.stop.assert_not_called()
        self.recovery_factory.assert_not_called()
        self.emit.assert_not_called()
        self.assertIsNone(updater.marker(self.root))
        self.assertEqual((self.root / 'config.json').read_bytes(), self.original_config)
        self.assert_preserved()

    def test_downloaded_update_quit_requires_valid_live_owner_before_service_effects(self):
        with patch.object(updater, 'process_identity', return_value=None) as identity:
            for owner in (None, 0, 1, -1, True, '4321', 4321.0, 2**31, 4321):
                with self.subTest(owner=owner), self.assertRaises(decrumb.SafeError):
                    self.quit(payload={'target_build': '10', 'owner_pid': owner})
        identity.assert_called_once_with(4321)
        self.control.stop.assert_not_called()
        self.recovery_factory.assert_not_called()
        self.emit.assert_not_called()
        self.assertIsNone(updater.marker(self.root))
        self.assertEqual((self.root / 'config.json').read_bytes(), self.original_config)
        self.assert_preserved()

    def test_downloaded_update_quit_stop_failure_does_not_create_checkpoint(self):
        self.control.stop.side_effect = decrumb.SafeError('Synthetic worker could not stop.')
        with patch.object(updater, 'process_identity', return_value='synthetic GUI'), \
                self.assertRaisesRegex(decrumb.SafeError, 'could not stop'):
            self.quit(payload={'target_build': '10', 'owner_pid': 4321})
        self.assertIsNone(updater.marker(self.root))
        self.assertEqual((self.root / 'config.json').read_bytes(), self.original_config)
        self.recovery_factory.assert_not_called()
        self.emit.assert_not_called()
        self.assert_preserved()

    def test_pending_quit_stop_failure_leaves_config_and_transition_unchanged(self):
        transition = self.pending_update()
        original = (self.root / updater.MARKER).read_bytes()
        self.control.stop.side_effect = decrumb.SafeError('Synthetic worker could not stop.')
        with self.assertRaisesRegex(decrumb.SafeError, 'could not stop'):
            self.quit(payload={'token': transition['token']})
        self.assertEqual((self.root / 'config.json').read_bytes(), self.original_config)
        self.assertEqual((self.root / updater.MARKER).read_bytes(), original)
        self.recovery_factory.assert_not_called()
        self.assertTrue(self.recovery.path.exists())
        self.emit.assert_not_called()
        self.assert_preserved()

    def test_disarm_failure_retains_recovery_metadata_and_reports_stopped_state(self):
        transition = self.pending_update()
        original_plist = self.recovery.path.read_bytes()
        self.recovery_launch.return_value.returncode = 0
        with self.assertRaisesRegex(decrumb.SafeError, 'still stopping'):
            self.quit(payload={'token': transition['token']})
        self.assertEqual(updater.marker(self.root), {**transition, 'resume': False, 'ready': True})
        self.assertEqual(self.recovery.path.read_bytes(), original_plist)
        self.assertTrue(decrumb.load_config(self.root, validate_helper=False)['paused'])
        self.emit.assert_not_called()
        self.assert_preserved()

    def test_pending_quit_never_disarms_another_runtime_recovery_service(self):
        transition = self.pending_update()
        service.write_plist(self.recovery.path, {
            'Label': self.recovery.label, 'WorkingDirectory': str(Path(self.folder.name) / 'other-runtime'),
        })
        original_plist = self.recovery.path.read_bytes()
        with self.assertRaisesRegex(decrumb.SafeError, 'another runtime'):
            self.quit(payload={'token': transition['token']})
        self.recovery_launch.assert_not_called()
        self.assertEqual(self.recovery.path.read_bytes(), original_plist)
        self.assertEqual(updater.marker(self.root), {**transition, 'resume': False, 'ready': True})
        self.emit.assert_not_called()
        self.assert_preserved()

    def test_quit_is_serialized_with_other_operations(self):
        with updater.operation(self.root), self.assertRaisesRegex(decrumb.SafeError, 'Another action'):
            self.quit()
        self.control.stop.assert_not_called()
        self.emit.assert_not_called()
        self.assertEqual((self.root / 'config.json').read_bytes(), self.original_config)
        self.assert_preserved()


if __name__ == '__main__':
    unittest.main()
