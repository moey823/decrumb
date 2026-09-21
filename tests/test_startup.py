# SPDX-License-Identifier: AGPL-3.0-only
"""Automatic startup uses only temporary runtimes and mocked LaunchAgents/Signal."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import decrumb
import desktop
import service
import updater
from test_decrumb import HELPER, SETTINGS, SELF


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='decrumb-startup-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.resources = self.root / 'Decrumb.app/Contents/Helpers'
        self.resources.mkdir(parents=True)
        (self.resources / 'url-cleaner').symlink_to(HELPER.resolve())
        self.config = {'version': 1, 'account': SELF, 'helper': str(self.resources / 'url-cleaner'),
                       'signal_cli': str(self.resources / 'signal-cli'), 'settings': SETTINGS,
                       'paused': False, 'start_at_login': False, 'notes': decrumb.notes_settings()}
        self.control = Mock()
        self.control.start.return_value = True
        self.login = patch.object(service, 'configure_app_login').start()
        patch.object(service, 'UpdateRecovery').start()
        self.addCleanup(patch.stopall)

    def call(self, command, *, save=True):
        if save:
            decrumb.write_json(self.root / 'config.json', self.config)
        args = ['desktop.py', '--root', str(self.root), '--resources', str(self.resources), command]
        with patch.object(sys, 'argv', args), patch.object(service, 'Service', return_value=self.control), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            desktop.main()
        return [json.loads(line) for line in output.getvalue().splitlines()]

    def test_fresh_install_is_enabled_but_cannot_receive_before_linking(self):
        result = self.call('bootstrap', save=False)[0]
        self.assertFalse(result['linked'])
        self.assertFalse(result['paused'])
        self.assertFalse(result['start_at_login'])
        self.control.start.assert_not_called()
        self.assertFalse((self.root / 'outbox.sqlite3').exists())

    def test_reopen_linked_app_starts_without_resume_or_enabling_login(self):
        result = self.call('bootstrap')[0]
        self.control.start.assert_called_once_with(False)
        self.control.stop.assert_not_called()
        self.assertIsInstance(result['startup_requested_at'], int)
        self.assertTrue(result['linked'])
        self.assertNotIn(SELF, json.dumps(result))

    def test_reopen_does_not_interrupt_a_running_worker(self):
        self.control.start.return_value = False
        with decrumb.exclusive(self.root):
            result = self.call('bootstrap')[0]
        self.control.start.assert_called_once_with(False)
        self.control.stop.assert_not_called()
        self.assertIsNone(result['startup_requested_at'])

    def test_reopen_ends_pause_and_preserves_login_preference(self):
        self.config.update(paused=True, start_at_login=True)
        result = self.call('bootstrap')[0]
        self.assertFalse(result['paused'])
        self.control.start.assert_called_once_with(True)
        self.control.stop.assert_called_once_with()

    def test_start_failure_keeps_link_and_shows_retry_instead_of_onboarding(self):
        self.control.start.side_effect = decrumb.SafeError('Synthetic service failure')
        result = self.call('bootstrap')[0]
        self.assertTrue(result['linked'])
        self.assertFalse(result['paused'])
        self.assertIn('Retry connection', result['startup_error'])
        self.assertEqual(decrumb.load_config(self.root, validate_helper=False)['account'], SELF)

    def test_pending_update_never_starts_worker_before_replacement(self):
        value = {'version': 1, 'created': 1, 'owner': 4321, 'identity': 'synthetic',
                 'token': 'synthetic', 'target_build': '99', 'ready': True, 'resume': True}
        decrumb.write_json(self.root / updater.MARKER, value)
        with patch.object(updater, 'recover', return_value=False):
            result = self.call('bootstrap')[0]
        self.assertTrue(result['update_pending'])
        self.control.start.assert_not_called()

    def test_completed_update_is_not_started_twice_by_bootstrap(self):
        with patch.object(updater, 'recover', return_value=True):
            self.call('bootstrap')
        self.control.start.assert_not_called()

    def test_failed_update_recovery_keeps_link_visible_without_bypassing_handoff(self):
        with patch.object(updater, 'recover', side_effect=decrumb.SafeError('Update could not restart. Choose Retry connection.')):
            result = self.call('bootstrap')[0]
        self.assertTrue(result['linked'])
        self.assertIn('Retry connection', result['startup_error'])
        self.control.start.assert_not_called()

    def test_pairing_starts_after_releasing_lock_even_with_old_setup_default(self):
        self.config.update(account=None, paused=True)
        def linked(root, config, emit):
            with decrumb.exclusive(root):
                config['account'] = SELF
                decrumb.write_json(root / 'config.json', config)
                emit('linked')
        def started(login):
            with decrumb.exclusive(self.root):
                self.assertFalse(decrumb.load_config(self.root, validate_helper=False)['paused'])
            return True
        self.control.start.side_effect = started
        with patch.object(decrumb, 'pair', side_effect=linked):
            result = self.call('pair')
        self.control.start.assert_called_once_with(False)
        self.assertEqual([item['event'] for item in result], ['linked', 'cleaning_started'])

    def test_failed_or_cancelled_pairing_does_not_start(self):
        self.config.update(account=None)
        with patch.object(decrumb, 'pair', side_effect=decrumb.SafeError('Pairing cancelled')):
            with self.assertRaises(decrumb.SafeError):
                self.call('pair')
        self.control.start.assert_not_called()

    def test_successful_pair_with_failed_start_preserves_connection_for_retry(self):
        self.control.start.side_effect = decrumb.SafeError('Synthetic failure')
        with patch.object(decrumb, 'pair'):
            with self.assertRaisesRegex(decrumb.SafeError, 'Signal connected.*Retry connection'):
                self.call('pair')
        self.assertEqual(decrumb.load_config(self.root, validate_helper=False)['account'], SELF)

    def test_moved_app_refreshes_paths_without_clearing_queued_links(self):
        self.config.update(helper='/old/Decrumb.app/url-cleaner', signal_cli='/old/Decrumb.app/signal-cli', start_at_login=True)
        decrumb.write_json(self.root / 'config.json', self.config)
        with contextlib.closing(decrumb.Store(self.root / 'outbox.sqlite3')) as store:
            store.enqueue('synthetic', decrumb.now_ms(), ['https://example.org/?id=1'])
        original = (self.root / 'outbox.sqlite3').read_bytes()
        desktop.start_cleaning(self.root, self.config, self.control, self.resources)
        self.control.stop.assert_called_once_with()
        self.control.start.assert_called_once_with(True)
        self.login.assert_called_once_with(self.resources.parent / 'MacOS/Decrumb', True)
        self.assertEqual(self.config['helper'], str(self.resources / 'url-cleaner'))
        self.assertEqual((self.root / 'outbox.sqlite3').read_bytes(), original)
        self.assertEqual(self.config['account'], SELF)

    def test_status_reads_never_start_cleaning(self):
        self.call('snapshot')
        self.control.start.assert_not_called()

    def test_failed_resume_reports_enabled_connection_failure_not_pause(self):
        self.config['paused'] = True
        self.control.start.side_effect = decrumb.SafeError('Synthetic service failure')
        result = self.call('resume')[0]
        self.assertFalse(result['paused'])
        self.assertTrue(result['linked'])
        self.assertIn('Retry connection', result['startup_error'])

    def test_service_start_is_idempotent_for_an_owned_running_service(self):
        decrumb.write_json(self.root / 'config.json', self.config)
        control = service.Service(self.root)
        with patch.object(control, 'check_owned'), patch.object(control, 'loaded', return_value=True), \
                patch.object(control, 'install') as install, patch.object(control, 'launch') as launch:
            self.assertFalse(control.start(False))
            install.assert_not_called()
            launch.assert_not_called()

    def test_service_start_bootstraps_stopped_worker_once(self):
        decrumb.write_json(self.root / 'config.json', self.config)
        control = service.Service(self.root)
        with patch.object(control, 'check_owned'), patch.object(control, 'loaded', return_value=False), \
                patch.object(control, 'install') as install, patch.object(control, 'launch') as launch:
            self.assertTrue(control.start(False))
            install.assert_called_once_with(False)
            launch.assert_called_once_with('bootstrap', control.domain, str(control.session_plist))
