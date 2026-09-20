# SPDX-License-Identifier: AGPL-3.0-only
"""Synthetic, offline regression tests for rules, app bridge and service lifecycle."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import desktop
import service
import sidelet
from test_sidelet import HELPER, SETTINGS, SELF, StubRpc, event


class RulesTests(unittest.TestCase):
    def clean(self, text, **kwargs):
        return sidelet.clean(HELPER, text, {**SETTINGS, **kwargs})

    def test_normalized_selected_rules(self):
        for base in ['example.com/news', 'example.com/news/', ' example.com/news/ ']:
            self.assertEqual(self.clean('https://example.com/news/a?utm_source=x', mode='selected', baseURLs=[base]), ['https://example.com/news/a'])
            self.assertEqual(self.clean('https://example.com/newsroom?utm_source=x', mode='selected', baseURLs=[base]), [])

    def test_schemeless_nested_url_is_preserved(self):
        self.assertEqual(self.clean('www.example.com/?next=https://other.example/path&utm_source=x'), ['http://www.example.com/?next=https://other.example/path'])

    def test_exclusion_precedes_custom_and_global_rules(self):
        rules = [{'site': 'example.com', 'remove': ['ref'], 'keep': []}]
        self.assertEqual(self.clean('https://sub.example.com/news/a?utm_source=x&ref=y', excludedURLs=[' example.com/news/ '], rules=rules), [])
        self.assertEqual(self.clean('https://example.com/other?utm_source=x', excludedURLs=['example.com/news']), ['https://example.com/other'])
        self.assertEqual(self.clean('https://notexample.com/?utm_source=x', excludedURLs=['example.com']), ['https://notexample.com/'])

    def test_custom_keep_wins_and_scope_is_bounded(self):
        rules = [{'site': 'example.com', 'remove': ['share_id', 'utm_source'], 'keep': ['UTM_SOURCE']}]
        self.assertEqual(self.clean('https://example.com/?share_id=secret&utm_source=a&id=2', rules=rules), ['https://example.com/?utm_source=a&id=2'])
        self.assertEqual(self.clean('https://another.example/?share_id=x', rules=rules), [])

    def test_signatures_protected_even_with_custom_rule(self):
        rules = [{'site': 'example.com', 'remove': ['signature', 'share_id'], 'keep': []}]
        self.assertEqual(self.clean('https://example.com/?signature=x&share_id=y&utm_source=z', rules=rules), [])

    def test_keep_preserves_builtin_instagram_parameter(self):
        rules = [{'site': 'instagram.com', 'remove': [], 'keep': ['igsh']}]
        self.assertEqual(self.clean('https://instagram.com/p/a?igsh=x&utm_source=y', rules=rules), ['https://instagram.com/p/a?igsh=x'])

    def test_preview_explanation_and_settings_normalization(self):
        result = sidelet.clean_result(HELPER, 'https://example.com/?%75tm_source=x&id=a%2Bb&id=2#anchor',
                                     {**SETTINGS, 'excludedURLs': [' other.example/news/ ']})
        self.assertEqual(result['changes'][0]['removed'], ['utm_source'])
        self.assertEqual(result['changes'][0]['cleaned'], 'https://example.com/?id=a%2Bb&id=2#anchor')
        self.assertEqual(result['settings']['excludedURLs'], ['https://other.example/news'])
        self.assertEqual(result['revision'], '2026-09-20')

    def test_empty_parameter_name_does_not_crash_explanation(self):
        self.assertEqual(self.clean('https://example.com/?=keep&utm_source=x'), ['https://example.com/?=keep'])

    def test_control_heavy_message_fits_encoded_limit(self):
        self.assertEqual(self.clean('\0' * 45000 + ' https://example.com/?utm_source=x'), ['https://example.com/'])

    def test_invalid_custom_rule_rejected(self):
        for rule in [{'site': '*.example.com', 'remove': ['x'], 'keep': []},
                     {'site': 'example.com', 'remove': ['.*'], 'keep': []},
                     {'site': 'https://example.com/?x=y', 'remove': ['x'], 'keep': []}]:
            with self.assertRaises(sidelet.SafeError):
                self.clean('', rules=[rule])


class ReliabilityTests(unittest.TestCase):
    def test_opening_store_expires_content_before_any_network_call(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'queue.sqlite3'
            with contextlib.closing(sidelet.Store(path)) as store:
                store.enqueue('expired', sidelet.now_ms() - 2 * sidelet.MAX_AGE_MS, ['https://example.com/private'])
                store.enqueue('fresh', sidelet.now_ms(), ['https://example.com/fresh'])
            with contextlib.closing(sidelet.Store(path)) as store:
                self.assertEqual(store.db.execute("SELECT state,body FROM outbox WHERE id='expired'").fetchone(), ('expired', None))
                self.assertEqual(store.db.execute("SELECT state FROM outbox WHERE id='fresh'").fetchone()[0], 'pending')

    def test_local_maintenance_respects_worker_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with contextlib.closing(sidelet.Store(root / 'outbox.sqlite3')) as store:
                store.enqueue('expired', sidelet.now_ms() - 2 * sidelet.MAX_AGE_MS, ['https://example.com/private'])
            with sidelet.exclusive(root):
                self.assertIsNone(sidelet.maintain_outbox(root))
            self.assertEqual(sidelet.maintain_outbox(root)['counts'], {'expired': 1})

    def test_predispatch_cancel_writes_no_request(self):
        cancelled = threading.Event()
        cancelled.set()
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / 'request-received'
            script = 'import sys; from pathlib import Path; line=sys.stdin.readline(); Path(sys.argv[1]).write_text("received") if line else None'
            with sidelet.Rpc(Path(folder), {}, [sys.executable, '-c', script, str(marker)], cancelled) as rpc:
                with self.assertRaises(sidelet.NotDispatched):
                    rpc.call('send', {'noteToSelf': True})
                self.assertFalse(marker.exists())

    def test_cancelled_unattempted_note_remains_pending(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.closing(sidelet.Store(Path(folder) / 'queue.sqlite3')) as store:
            store.enqueue('synthetic', sidelet.now_ms(), ['https://example.com/'])
            rpc = StubRpc()
            rpc.cancel_event = threading.Event()
            rpc.cancel_event.set()
            self.assertFalse(sidelet.deliver_one(store, rpc, SELF))
            self.assertEqual(rpc.calls, [])
            self.assertEqual(store.counts(), {'pending': 1})

    def test_cancellation_between_claim_and_dispatch_restores_body(self):
        class CancelBeforeWrite:
            def call(self, *args):
                raise sidelet.NotDispatched('Signal command interrupted before dispatch.')
        with tempfile.TemporaryDirectory() as folder, contextlib.closing(sidelet.Store(Path(folder) / 'queue.sqlite3')) as store:
            store.enqueue('synthetic', sidelet.now_ms(), ['https://example.com/'])
            self.assertFalse(sidelet.deliver_one(store, CancelBeforeWrite(), SELF))
            state, body = store.db.execute('SELECT state,body FROM outbox').fetchone()
            self.assertEqual(state, 'pending')
            self.assertIn('https://example.com/', body)
            self.assertIn('#decrumb_', body)

    def test_loss_metrics_survive_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'queue.sqlite3'
            with contextlib.closing(sidelet.Store(path)) as store:
                for index in range(256):
                    store.enqueue(str(index), sidelet.now_ms(), ['https://example.com/'])
                self.assertFalse(store.enqueue('overflow', sidelet.now_ms(), ['https://example.com/']))
            with contextlib.closing(sidelet.Store(path)) as store:
                self.assertEqual(store.metrics()['outbox_dropped'], 1)

    def test_status_survives_missing_helper_and_redacts_extra_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = {'version': 1, 'helper': str(root / 'missing'), 'signal_cli': str(root / 'missing-signal'), 'account': 'synthetic', 'settings': SETTINGS}
            sidelet.write_json(root / 'config.json', config)
            sidelet.write_json(root / 'status.json', {'state': 'starting', 'updated_at': 1, 'pid': 12345,
                               'private': 'do-not-show', 'counts': {'sent': 1, 'private': 'do-not-show'}})
            read = sidelet.load_config(root, validate_helper=False)
            result = sidelet.read_status(root, read)
            self.assertEqual(result['state'], 'stale')
            self.assertFalse(result['helper_available'])
            self.assertTrue(result['needs_attention'])
            self.assertNotIn('do-not-show', json.dumps(result))

    def test_private_metadata_fails_closed(self):
        now = sidelet.now_ms()
        for key, bad in [('viewOnce', None), ('viewOnce', 0), ('textStyles', {}), ('textStyles', [{}]),
                         ('textStyles', [{'style': 'UNKNOWN'}])]:
            value = event(now)
            value['params']['result']['envelope']['dataMessage'][key] = bad
            self.assertIsNone(sidelet.candidate(value, {SELF}, now - 1, now))


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / 'synthetic-home'
        self.config = {'version': 1, 'helper': str(HELPER.resolve()), 'signal_cli': str(self.root / 'synthetic-signal'),
                       'account': SELF, 'settings': SETTINGS}
        sidelet.write_json(self.root / 'config.json', self.config)
        self.patch = patch.object(Path, 'home', return_value=self.home)
        self.patch.start()
        self.control = service.Service(self.root, ['/synthetic/worker', 'run'])

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_stopped_install_can_be_updated(self):
        with patch.object(self.control, 'loaded', return_value=False):
            self.control.install()
            self.control.worker_command = ['/synthetic/new-worker', 'run']
            self.control.install()
        plist = plistlib.loads(self.control.login_plist.read_bytes())
        self.assertEqual(plist['ProgramArguments'][0], '/synthetic/new-worker')

    def test_no_login_uses_only_session_plist(self):
        with patch.object(self.control, 'loaded', return_value=False):
            self.control.install(login=False)
        self.assertTrue(self.control.session_plist.exists())
        self.assertFalse(self.control.login_plist.exists())

    def test_other_root_is_not_controlled(self):
        service.write_plist(self.control.login_plist, {'Label': service.LABEL, 'WorkingDirectory': '/different/runtime'})
        with patch.object(self.control, 'launch') as launch:
            with self.assertRaises(sidelet.SafeError):
                self.control.stop()
            launch.assert_not_called()

    def test_unknown_loaded_job_is_not_stopped(self):
        with patch.object(self.control, 'loaded', return_value=True), patch.object(self.control, 'launch') as launch:
            with self.assertRaises(sidelet.SafeError):
                self.control.stop()
            launch.assert_not_called()

    def test_pause_removes_login_job(self):
        with patch.object(self.control, 'loaded', return_value=False):
            self.control.install()
        with patch.object(self.control, 'launch', return_value=subprocess.CompletedProcess([], 0)):
            self.control.stop(disable_login=True)
        self.assertFalse(self.control.login_plist.exists())


class BridgeTests(unittest.TestCase):
    def test_paused_cleanup_attempts_three_own_notes_without_subscribing(self):
        class CleanupRpc:
            def __init__(self): self.calls = []
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def call(self, method, params=None, timeout=None):
                self.calls.append((method, params))
                if method == 'listAccounts': return [{'number': SELF}]
                if method == 'remoteDelete': return {'timestamp': sidelet.now_ms(), 'results': [{'type': 'SUCCESS'}]}
                raise AssertionError('Unexpected Signal operation in cleanup-only mode')
        with tempfile.TemporaryDirectory() as folder:
            root, control, rpc = Path(folder), Mock(), CleanupRpc()
            sent_at = sidelet.now_ms() - 1000
            with contextlib.closing(sidelet.Store(root / 'outbox.sqlite3')) as store:
                for index in range(4):
                    store.enqueue(str(index), sidelet.now_ms(), ['https://example.com/private'])
                    sidelet.deliver_one(store, StubRpc({'timestamp': sent_at + index, 'results': [{'type': 'SUCCESS'}]}), SELF)
            with patch.object(sidelet, 'Rpc', return_value=rpc):
                result = desktop.change_notes(root, {'account': SELF, 'paused': True}, control, 'cleanup', {})
            self.assertEqual(result['changed'], 4)
            deletes = [params for method, params in rpc.calls if method == 'remoteDelete']
            self.assertEqual(len(deletes), 3)
            self.assertTrue(all(set(params) == {'account', 'noteToSelf', 'targetTimestamp'} and params['noteToSelf'] is True for params in deletes))
            self.assertTrue(all(sent_at <= params['targetTimestamp'] <= sent_at + 3 for params in deletes))
            control.start.assert_not_called()
            counts = sidelet.read_notes(root / 'outbox.sqlite3')['note_counts']
            self.assertEqual(counts['deletion_requested'], 3)
            self.assertEqual(counts['cleanup_pending'], 1)

    def test_note_preferences_preserve_pause_without_creating_an_outbox(self):
        with tempfile.TemporaryDirectory() as folder:
            root, control = Path(folder), Mock()
            config = {'account': SELF, 'paused': True}
            desktop.change_notes(root, config, control, 'notes-settings', {'notes': {'cleanup_mode': 'lifetime', 'lifetime_hours': 6}})
            self.assertEqual(json.loads((root / 'config.json').read_text())['notes']['lifetime_hours'], 6)
            self.assertTrue(config['paused'])
            self.assertFalse((root / 'outbox.sqlite3').exists())
            control.stop.assert_called_once()
            control.start.assert_not_called()

    def test_invalid_preferences_do_not_stop_the_service(self):
        control = Mock()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(sidelet.SafeError):
                desktop.change_notes(Path(folder), {'paused': False, 'account': SELF}, control,
                                     'notes-settings', {'notes': {'cleanup_mode': 'lifetime', 'lifetime_hours': 48}})
        control.stop.assert_not_called()

    def test_clear_queue_does_not_open_signal_and_restarts_active_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            root, control = Path(folder), Mock()
            config = {'account': SELF, 'paused': False, 'start_at_login': False}
            with contextlib.closing(sidelet.Store(root / 'outbox.sqlite3')) as store:
                store.enqueue('queued', sidelet.now_ms(), ['https://example.com/private'])
            with patch.object(sidelet, 'Rpc') as rpc:
                result = desktop.change_notes(root, config, control, 'clear-queue', {})
                rpc.assert_not_called()
            self.assertEqual(result['changed'], 1)
            control.start.assert_called_once_with(False)
            with contextlib.closing(sidelet.Store(root / 'outbox.sqlite3')) as store:
                self.assertEqual(store.db.execute('SELECT state,body FROM outbox').fetchone(), ('cancelled', None))

    def test_invalid_note_mutation_still_restores_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            root, control = Path(folder), Mock()
            with contextlib.closing(sidelet.Store(root / 'outbox.sqlite3')):
                pass
            with self.assertRaises(sidelet.SafeError):
                desktop.change_notes(root, {'account': SELF, 'paused': False}, control, 'note-lifetime',
                                     {'id': 'not-a-recorded-note', 'hours': 1})
            control.start.assert_called_once_with(False)

    def test_pause_can_discard_queued_links_without_signal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sidelet.write_json(root / 'config.json', {'version': 1, 'helper': '/missing/synthetic-helper',
                'signal_cli': '/missing/synthetic-signal', 'account': SELF, 'settings': SETTINGS,
                'notes': {'discard_on_pause': True}, 'paused': False})
            with contextlib.closing(sidelet.Store(root / 'outbox.sqlite3')) as store:
                store.enqueue('queued', sidelet.now_ms(), ['https://example.com/private'])
            args = ['desktop.py', '--root', str(root), '--resources', str(root), 'pause']
            with patch.object(sys, 'argv', args), patch.object(service, 'Service') as control, patch('sys.stdout', new_callable=io.StringIO):
                desktop.main()
                control.return_value.stop.assert_called_once_with(disable_login=True)
            with contextlib.closing(sidelet.Store(root / 'outbox.sqlite3')) as store:
                self.assertEqual(store.counts(), {'cancelled': 1})

    def test_snapshot_maintenance_needs_no_signal_or_helper(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sidelet.write_json(root / 'config.json', {'version': 1, 'helper': '/missing/synthetic-helper',
                'signal_cli': '/missing/synthetic-signal', 'account': None, 'settings': SETTINGS, 'paused': True})
            with contextlib.closing(sidelet.Store(root / 'outbox.sqlite3')) as store:
                store.enqueue('expired', sidelet.now_ms() - 2 * sidelet.MAX_AGE_MS, ['https://example.com/private'])
            command = [sys.executable, '-B', str(Path(desktop.__file__)), '--root', str(root), '--resources', str(root), 'snapshot']
            result = subprocess.run(command, capture_output=True, check=True)
            self.assertEqual(json.loads(result.stdout)['counts'], {'expired': 1})
            self.assertNotIn(b'example.com', (root / 'outbox.sqlite3').read_bytes())

    def test_bootstrap_preview_and_snapshot_are_local_and_private(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            command = [sys.executable, '-B', str(Path(desktop.__file__)), '--root', str(root), '--resources', str(HELPER.parent.resolve())]
            bootstrap = subprocess.run(command + ['bootstrap'], capture_output=True, check=True)
            self.assertFalse(json.loads(bootstrap.stdout)['linked'])
            config = json.loads((root / 'config.json').read_text())
            config['account'] = 'synthetic-account-do-not-expose'
            sidelet.write_json(root / 'config.json', config)
            snapshot = subprocess.run(command + ['snapshot'], capture_output=True, check=True)
            self.assertNotIn(b'synthetic-account-do-not-expose', snapshot.stdout + snapshot.stderr)
            result = subprocess.run(command + ['preview'], input=json.dumps({'text': 'https://example.com/?utm_source=x', 'settings': SETTINGS}).encode(), capture_output=True, check=True)
            self.assertEqual(json.loads(result.stdout)['urls'], ['https://example.com/'])
            self.assertFalse((root / 'outbox.sqlite3').exists())

    def test_settings_update_cancels_pending_but_preserves_account(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = {'version': 1, 'account': SELF, 'settings': SETTINGS}
            with contextlib.closing(sidelet.Store(root / 'outbox.sqlite3')) as store:
                store.enqueue('synthetic', sidelet.now_ms(), ['https://example.com/'])
            desktop.configure(root, config, {'mode': 'off', 'baseURLs': []})
            self.assertEqual(json.loads((root / 'config.json').read_text())['account'], SELF)
            with contextlib.closing(sidelet.Store(root / 'outbox.sqlite3')) as store:
                self.assertEqual(store.db.execute('SELECT state,body FROM outbox').fetchone(), ('cancelled', None))
