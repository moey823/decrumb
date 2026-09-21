# SPDX-License-Identifier: AGPL-3.0-only
"""Synthetic update lifecycle and release security regression tests."""
import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

import decrumb
import service
import updater
import desktop
import sys
from tools import sparkle, prepare_update
from test_decrumb import HELPER, SETTINGS, SELF


class WorkerUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='decrumb-update-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.resources = self.root / 'new/Decrumb.app/Contents/Helpers'
        self.resources.mkdir(parents=True)
        self.config = {'version': 1, 'account': SELF, 'helper': str(HELPER), 'signal_cli': '/synthetic/signal-cli',
                       'settings': SETTINGS, 'paused': False, 'start_at_login': True, 'notes': decrumb.notes_settings()}
        decrumb.write_json(self.root / 'config.json', self.config)
        self.control = Mock()
        self.watchdog = patch.object(service, 'UpdateRecovery').start()
        self.login = patch.object(service, 'configure_app_login').start()
        self.identity = patch.object(updater, 'process_identity', return_value='synthetic process start').start()
        self.addCleanup(patch.stopall)
        with contextlib.closing(decrumb.Store(self.root / 'outbox.sqlite3')) as store:
            store.enqueue('pending', decrumb.now_ms(), ['https://example.com/?id=synthetic'])
            store.db.execute("INSERT OR REPLACE INTO meta VALUES ('synthetic-receipt', 123)")
            store.db.execute("UPDATE generated_notes SET state='cleanup_pending', sent_at=123")
            store.db.commit()
        self.database = (self.root / 'outbox.sqlite3').read_bytes()

    def prepare(self):
        with updater.operation(self.root):
            return updater.prepare(self.root, self.control, self.resources, '3', owner=4321)

    def recover(self, **kwargs):
        with updater.operation(self.root):
            return updater.recover(self.root, self.resources, self.control, **kwargs)

    def test_active_worker_quiesces_and_resumes_without_mutating_queue_or_preferences(self):
        result = self.prepare()
        self.control.stop.assert_called_once_with()
        self.assertEqual(decrumb.load_config(self.root, validate_helper=False), self.config)
        self.recover(token=result['token'])
        self.control.start.assert_called_once_with(True)
        current = decrumb.load_config(self.root, validate_helper=False)
        self.assertEqual(current['paused'], False)
        self.assertEqual(current['start_at_login'], True)
        self.assertEqual(current['account'], SELF)
        self.assertEqual(current['helper'], str(self.resources / 'url-cleaner'))
        self.assertEqual(current['signal_cli'], str(self.resources / 'signal-cli'))
        self.assertEqual((self.root / 'outbox.sqlite3').read_bytes(), self.database)
        self.assertIsNone(updater.marker(self.root))
        self.watchdog.return_value.disarm.assert_called()

    def test_relaunch_starts_paused_worker_without_enabling_login(self):
        self.config.update(paused=True, start_at_login=False)
        decrumb.write_json(self.root / 'config.json', self.config)
        self.prepare()
        self.identity.return_value = None
        self.recover(bootstrap=True, current_build="3")
        self.control.start.assert_called_once_with(False)
        self.login.assert_called_once_with(self.resources.parent / 'MacOS/Decrumb', False)
        self.assertFalse(decrumb.load_config(self.root, validate_helper=False)['paused'])
        self.assertEqual((self.root / 'outbox.sqlite3').read_bytes(), self.database)

    def test_pairing_or_settings_operation_defers_before_stopping_worker(self):
        with updater.operation(self.root):
            with self.assertRaises(decrumb.SafeError):
                self.prepare()
        self.control.stop.assert_not_called()
        self.watchdog.assert_not_called()

    def test_live_marker_blocks_other_mutations_and_bootstrap(self):
        self.prepare()
        with self.assertRaises(decrumb.SafeError):
            updater.guard(self.root)
        with self.assertRaises(decrumb.SafeError):
            self.recover(bootstrap=True)
        self.control.start.assert_not_called()

    def test_elapsed_time_alone_never_resumes_worker_during_installation(self):
        self.prepare()
        self.identity.return_value = None
        self.assertFalse(self.recover(now=10**20))
        self.control.start.assert_not_called()
        self.assertIsNotNone(updater.marker(self.root))

    def test_abort_requires_matching_transition_and_preserves_state(self):
        result = self.prepare()
        with self.assertRaises(decrumb.SafeError):
            self.recover(token='wrong-transition')
        self.assertIsNotNone(updater.marker(self.root))
        self.recover(token=result['token'])
        self.assertEqual((self.root / 'outbox.sqlite3').read_bytes(), self.database)

    def test_cancelled_update_keeps_pause_until_app_is_reopened(self):
        self.config['paused'] = True
        decrumb.write_json(self.root / 'config.json', self.config)
        result = self.prepare()
        self.recover(token=result['token'])
        self.control.start.assert_not_called()
        self.assertTrue(decrumb.load_config(self.root, validate_helper=False)['paused'])
        self.assertEqual((self.root / 'outbox.sqlite3').read_bytes(), self.database)

    def test_restart_failure_is_actionable_without_discarding_account_or_queue(self):
        result = self.prepare()
        self.control.start.side_effect = decrumb.SafeError('synthetic restart failure')
        with self.assertRaisesRegex(decrumb.SafeError, 'Retry connection'):
            self.recover(token=result['token'])
        self.assertIsNone(updater.marker(self.root))
        self.assertEqual((self.root / 'outbox.sqlite3').read_bytes(), self.database)
        self.assertEqual(decrumb.load_config(self.root, validate_helper=False)['account'], SELF)

    def test_failed_stop_recovers_without_persistently_pausing(self):
        self.control.stop.side_effect = decrumb.SafeError('synthetic stop failure')
        with self.assertRaises(decrumb.SafeError):
            self.prepare()
        self.assertFalse(decrumb.load_config(self.root, validate_helper=False)['paused'])
        self.assertIsNone(updater.marker(self.root))

    def test_worker_lock_prevents_ready_handoff(self):
        with decrumb.exclusive(self.root):
            with self.assertRaises(decrumb.SafeError):
                self.prepare()
        self.assertFalse(decrumb.load_config(self.root, validate_helper=False)['paused'])

    def test_repeated_prepare_is_idempotent(self):
        first = self.prepare()
        self.assertEqual(self.prepare(), first)
        self.assertEqual(self.control.stop.call_count, 2)

    def test_failed_lock_then_retry_never_reports_ready_until_worker_releases(self):
        with decrumb.exclusive(self.root):
            for _ in range(2):
                with self.assertRaises(decrumb.SafeError):
                    self.prepare()
                self.assertFalse(updater.marker(self.root)['ready'])
        result = self.prepare()
        self.assertTrue(result['ready'])
        self.assertTrue(updater.marker(self.root)['ready'])
        self.assertEqual(self.control.stop.call_count, 3)

    def test_spawned_worker_does_not_contend_with_parent_operation_lock(self):
        with updater.operation(self.root), patch.object(sys, 'argv', ['desktop.py', '--root', str(self.root),
                '--resources', str(self.resources), 'run']), patch.object(decrumb, 'run') as run:
            desktop.main()
        run.assert_called_once()
        # Close the fixture-only rotating handler installed by the real bridge.
        for handler in list(decrumb.LOG.handlers):
            if getattr(handler, 'baseFilename', '') == str(self.root / 'worker.log'):
                decrumb.LOG.removeHandler(handler)
                handler.close()

    def test_old_build_recovery_reattaches_without_resuming_early(self):
        self.prepare()
        self.identity.return_value = None
        self.assertFalse(self.recover(bootstrap=True, current_build="2"))
        self.control.start.assert_not_called()
        self.assertIsNotNone(updater.marker(self.root))
        self.identity.side_effect = lambda pid: 'replacement GUI' if pid == 5432 else None
        with updater.operation(self.root):
            claimed = updater.claim(self.root, owner=5432)
        self.assertEqual(claimed['target_build'], '3')
        self.recover(token=claimed['token'])
        self.control.start.assert_called_once_with(True)

    def test_target_build_relaunch_recovers_interrupted_install(self):
        self.prepare()
        self.identity.return_value = None
        self.assertTrue(self.recover(bootstrap=True, current_build="3"))
        self.assertIsNone(updater.marker(self.root))
        self.control.start.assert_called_once_with(True)
        self.assertEqual((self.root / 'outbox.sqlite3').read_bytes(), self.database)

    def test_worker_start_rechecks_marker_after_lock_before_database_open(self):
        self.prepare()
        with patch.object(decrumb, 'Store') as store, self.assertRaises(decrumb.SafeError):
            decrumb.run(self.root, self.config)
        store.assert_not_called()

    def test_zombie_owner_is_dead_for_relaunch_recovery(self):
        patch.stopall()
        for status, expected in [('S', 'Sun Sep 20 12:00:00 2026'), ('Z', None), ('X', None)]:
            with patch.object(updater.subprocess, 'run', return_value=Mock(returncode=0, stdout=status + ' Sun Sep 20 12:00:00 2026')):
                self.assertEqual(updater.process_identity(4321), expected)


class RecoveryServiceTests(unittest.TestCase):
    def test_failed_bootout_preserves_metadata_for_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            recovery = service.UpdateRecovery(root, root / 'Decrumb.app/Contents/MacOS/Decrumb')
            service.write_plist(recovery.path, {'Label': recovery.label, 'WorkingDirectory': str(root)})
            with patch.object(service.subprocess, 'run', side_effect=[Mock(returncode=1), Mock(returncode=0)]):
                with self.assertRaises(decrumb.SafeError):
                    recovery.disarm()
            self.assertTrue(recovery.path.exists())
            with patch.object(service.subprocess, 'run', side_effect=[Mock(returncode=0), Mock(returncode=1)]):
                recovery.disarm()
            self.assertFalse(recovery.path.exists())

    def test_unknown_loaded_recovery_job_is_not_overwritten_or_stopped(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            recovery = service.UpdateRecovery(root, root / 'Decrumb.app/Contents/MacOS/Decrumb')
            with patch.object(service.subprocess, 'run', return_value=Mock(returncode=0)) as command:
                with self.assertRaises(decrumb.SafeError):
                    recovery.arm()
            self.assertEqual(command.call_count, 1)
            self.assertFalse(recovery.path.exists())


class UpdateReleaseTests(unittest.TestCase):
    def test_release_configuration_requires_all_security_and_privacy_controls(self):
        sparkle.validate_configuration(sparkle.configuration())
        for key in ('SUFeedURL', 'SUPublicEDKey', 'SURequireSignedFeed', 'SUVerifyUpdateBeforeExtraction', 'SUEnableSystemProfiling'):
            value = sparkle.configuration()
            value[key] = 'https://example.com/untrusted' if isinstance(value[key], str) else not value[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                sparkle.validate_configuration(value)

    def test_feed_must_bind_archive_version_os_architecture_signature_and_url(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive, feed = root / 'update.zip', root / 'appcast.xml'
            archive.write_bytes(b'synthetic archive')
            info = {'CFBundleVersion': '3', 'CFBundleShortVersionString': '1.0.1', 'LSMinimumSystemVersion': '26.4'}
            url = 'https://github.com/moey823/decrumb/releases/download/v1.0.1/update.zip'
            xml = ('<rss xmlns:sparkle="' + prepare_update.SPARKLE_NS + '"><channel><item>'
                   '<sparkle:version>3</sparkle:version><sparkle:shortVersionString>1.0.1</sparkle:shortVersionString>'
                   '<sparkle:minimumSystemVersion>26.4</sparkle:minimumSystemVersion>'
                   '<sparkle:hardwareRequirements>arm64</sparkle:hardwareRequirements>'
                   '<enclosure url="' + url + '" length="17" sparkle:edSignature="' + 'A' * 86 + '=="/>'
                   '</item></channel></rss>')
            feed.write_text(xml)
            prepare_update.validate_feed(feed, archive, info, url)
            modern = xml.replace('>26.4<', '>27.0<').replace('<sparkle:hardwareRequirements>arm64</sparkle:hardwareRequirements>', '')
            feed.write_text(modern)
            prepare_update.validate_feed(feed, archive, {**info, 'LSMinimumSystemVersion': '27.0'}, url)
            for before, after in [('>3<', '>2<'), ('>26.4<', '>27.0<'), ('>arm64<', '>x86_64<'), ('length="17"', 'length="18"'), ('https://github.com/', 'http://github.com/'), ('A' * 86, 'bad')]:
                feed.write_text(xml.replace(before, after))
                with self.subTest(before=before), self.assertRaises(ValueError):
                    prepare_update.validate_feed(feed, archive, info, url)
