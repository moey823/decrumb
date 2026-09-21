# SPDX-License-Identifier: AGPL-3.0-only
"""Synthetic privacy, retention, concurrency and control-boundary checks."""
import argparse
import contextlib
import io
import json
import logging
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import decrumb
import desktop
import diagnostics
import pi

PRIVATE = 'synthetic-secret https://private.example/?token=secret +15550000001'


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.logger = logging.Logger('diagnostics-test')
        diagnostics.configure(self.root, self.logger)

    def tearDown(self):
        self.temp.cleanup()

    def events(self):
        return json.loads((self.root / 'worker.log').read_text())

    def test_only_known_error_codes_cross_log_boundary(self):
        self.logger.info('note_sent')
        self.logger.warning(PRIVATE)
        self.logger.error('%s', PRIVATE)
        try:
            raise ValueError(PRIVATE)
        except ValueError:
            self.logger.exception('helper_failed')
        self.assertEqual([e['code'] for e in self.events()], ['helper_failed'])
        self.assertNotIn(PRIVATE, (self.root / 'worker.log').read_text())
        self.assertEqual((self.root / 'worker.log').stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.logger.propagate)

    def test_exception_classification_never_formats_private_error(self):
        class PrivateError(Exception):
            def __str__(self):
                raise AssertionError('Must not format exceptions')
        for error, code in [(PrivateError(), 'unexpected_failure'),
                            (sqlite3.OperationalError(PRIVATE), 'storage_failed'),
                            (decrumb.SafeError(PRIVATE, 'connection_timeout'), 'connection_timeout')]:
            diagnostics.failure(self.root, error)
            self.assertEqual(self.events()[-1]['code'], code)
        self.assertNotIn(PRIVATE, json.dumps(diagnostics.report(self.root)))

    def test_report_rebuilds_allowlist_and_excludes_activity_and_identifiers(self):
        day = int(time.time() // 86400)
        (self.root / 'worker.log').write_text(json.dumps([
            {'day': day, 'code': 'helper_failed', 'version': '1.0.0', 'build': 5,
             'component': PRIVATE, 'message': PRIVATE, 'stack': PRIVATE},
            {'day': day, 'code': PRIVATE, 'version': '1.0.0', 'build': 5},
            {'day': day, 'code': ['helper_failed'], 'version': '1.0.0', 'build': 5},
            {'day': day, 'code': 'helper_failed', 'version': PRIVATE, 'build': 5}]))
        (self.root / 'config.json').write_text(PRIVATE)
        (self.root / 'outbox.sqlite3').write_bytes(PRIVATE.encode())
        (self.root / 'status.json').write_text(json.dumps({'state': 'running', 'pid': 123,
            'updated_at': int(time.time() * 1000), 'counts': {'sent': 50}, 'metrics': {'last_sent_at': 123},
            'settings': PRIVATE, 'account': PRIVATE}))
        report = diagnostics.report(self.root)
        self.assertEqual(report['recent_errors'], [
            {'code': 'helper_failed', 'component': 'cleaner', 'version': '1.0.0', 'build': 5}])
        self.assertEqual(report['health']['worker'], 'running')
        for excluded in (PRIVATE, 'updated_at', 'last_sent_at', 'counts', 'pid', str(self.root), '"day"'):
            self.assertNotIn(excluded, json.dumps(report))

    def test_retention_deduplicates_bounds_and_expires(self):
        base = 30000 * 86400
        with patch.object(diagnostics.time, 'time', return_value=base):
            for _ in range(8):
                diagnostics.record(self.root, 'connection_closed')
            self.assertEqual(len(self.events()), 1)
            for build in range(200):
                with patch.object(diagnostics, 'release', return_value={'version': '1.0.0', 'build': build + 1}):
                    diagnostics.record(self.root, 'helper_failed')
            self.assertEqual(len(self.events()), diagnostics.MAX_EVENTS)
            self.assertLess((self.root / 'worker.log').stat().st_size, diagnostics.MAX_BYTES)
        with patch.object(diagnostics.time, 'time', return_value=base + 7 * 86400):
            self.assertEqual(diagnostics.maintain(self.root), [])

    def test_legacy_logs_and_oversized_or_malformed_history_are_removed(self):
        for data in (PRIVATE, 'x' * (diagnostics.MAX_BYTES + 1), '{"invalid":true}', '\ud800'):
            (self.root / 'worker.log').write_bytes(data.encode('utf-8', errors='surrogatepass'))
            for suffix in ('.1', '.2'):
                (self.root / ('worker.log' + suffix)).write_text(PRIVATE)
            self.assertEqual(diagnostics.maintain(self.root), [])
            self.assertFalse((self.root / 'worker.log.1').exists())
            self.assertFalse((self.root / 'worker.log.2').exists())

    def test_interrupted_staging_file_is_reused_and_cleared(self):
        temporary = self.root / '.diagnostics.tmp'
        temporary.write_text(PRIVATE)
        diagnostics.maintain(self.root, clear=True)
        self.assertFalse(temporary.exists())
        self.assertEqual(self.events(), [])

    def test_clear_preserves_private_runtime_and_new_errors_can_be_recorded(self):
        paths = ['config.json', 'outbox.sqlite3', 'status.json', 'signal-cli/account']
        for name in paths:
            path = self.root / name
            path.parent.mkdir(exist_ok=True)
            path.write_text(PRIVATE)
        diagnostics.record(self.root, 'helper_failed')
        diagnostics.maintain(self.root, clear=True)
        self.assertEqual(self.events(), [])
        for name in paths:
            self.assertEqual((self.root / name).read_text(), PRIVATE)
        self.logger.error('connection_closed')
        self.assertEqual([e['code'] for e in self.events()], ['connection_closed'])

    def test_concurrent_processes_preserve_distinct_errors(self):
        script = 'import diagnostics,sys; diagnostics.record(sys.argv[1],sys.argv[2])'
        codes = list(diagnostics.CODES)[:8]
        processes = [subprocess.Popen([sys.executable, '-B', '-c', script, str(self.root), code],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE) for code in codes]
        for process in processes:
            self.assertEqual(process.communicate(timeout=10), (b'', b''))
            self.assertEqual(process.returncode, 0)
        self.assertEqual({e['code'] for e in self.events()}, set(codes))

    def test_missing_storage_does_not_break_error_handler(self):
        with patch.object(diagnostics, 'maintain', side_effect=PermissionError(PRIVATE)):
            self.logger.error('helper_failed')
            report = diagnostics.report(self.root)
            self.assertEqual(report['health']['error_history'], 'unavailable')
            self.assertNotIn(PRIVATE, json.dumps(report))

    def test_untrusted_os_strings_do_not_export_hostnames(self):
        with patch.object(diagnostics.platform, 'system', return_value='Linux'), \
                patch.object(diagnostics.platform, 'release', return_value='6.12.34-private-host'), \
                patch.object(diagnostics.platform, 'machine', return_value=PRIVATE):
            platform = diagnostics.report(self.root)['platform']
        self.assertEqual(platform, {'os': 'Linux', 'kernel_version': '6.12.34', 'architecture': 'unknown'})

    def test_stale_or_corrupt_status_still_allows_support_report(self):
        for status in ({'state': 'running', 'updated_at': 1}, {'state': 'running', 'updated_at': PRIVATE}):
            (self.root / 'status.json').write_text(json.dumps(status))
            self.assertEqual(diagnostics.report(self.root)['health']['worker'], 'stale')
        (self.root / 'status.json').write_text(PRIVATE)
        self.assertEqual(diagnostics.report(self.root)['health']['worker'], 'unknown')

    def test_controls_work_with_broken_configuration_without_starting_service(self):
        (self.root / 'config.json').write_text(PRIVATE)
        for command in ('diagnostics', 'clear-diagnostics'):
            with patch.object(sys, 'argv', ['desktop.py', '--root', str(self.root), '--resources', '/synthetic', command]), \
                    patch.object(desktop.service, 'Service', side_effect=AssertionError('No service access')), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                desktop.main()
            self.assertEqual(json.loads(output.getvalue())['app'], 'Decrumb')
            with patch.object(pi, 'PiService', side_effect=AssertionError('No service access')), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                pi.dispatch(argparse.Namespace(command=command), self.root)
            self.assertEqual(json.loads(output.getvalue())['app'], 'Decrumb')
            self.assertEqual((self.root / 'config.json').read_text(), PRIVATE)

    def test_worker_failure_is_recorded_even_before_database_opens(self):
        with patch.object(decrumb, '_run', side_effect=sqlite3.OperationalError(PRIVATE)):
            with self.assertRaises(sqlite3.OperationalError):
                decrumb.run(self.root, {})
        self.assertEqual(self.events()[0]['code'], 'storage_failed')


if __name__ == '__main__':
    unittest.main()
