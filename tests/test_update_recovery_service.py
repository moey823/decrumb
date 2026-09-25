# SPDX-License-Identifier: AGPL-3.0-only
"""Synthetic launchctl outcomes; never manages an actual LaunchAgent."""
import plistlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import decrumb
import service


class UpdateRecoveryServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.recovery = service.UpdateRecovery(
            self.root, self.root / 'Decrumb.app/Contents/MacOS/Decrumb')
        patcher = patch.object(service.subprocess, 'run')
        self.command = patcher.start()
        self.addCleanup(patcher.stop)

    def owned_plist(self):
        service.write_plist(self.recovery.path, {
            'Label': self.recovery.label, 'WorkingDirectory': str(self.root)})
        return self.recovery.path.read_bytes()

    def timeout(self):
        return subprocess.TimeoutExpired('synthetic-launchctl', 20)

    def assert_bounded_calls(self, commands):
        self.assertEqual([call.args[0][1] for call in self.command.call_args_list], commands)
        for call in self.command.call_args_list:
            self.assertEqual(call.args[0][0], '/bin/launchctl')
            self.assertEqual(call.kwargs['timeout'], 20)
            self.assertEqual(call.kwargs['stdout'], subprocess.DEVNULL)
            self.assertEqual(call.kwargs['stderr'], subprocess.DEVNULL)
            self.assertFalse(call.kwargs['check'])

    def test_normal_arm_and_disarm_bound_each_launchctl_operation(self):
        self.command.side_effect = [Mock(returncode=1), Mock(returncode=0),
                                    Mock(returncode=0), Mock(returncode=1)]
        self.recovery.arm()
        metadata = plistlib.loads(self.recovery.path.read_bytes())
        self.assertEqual(metadata['WorkingDirectory'], str(self.root))
        self.assertEqual(metadata['ProgramArguments'],
                         ['/usr/bin/open', '-g', str(self.root / 'Decrumb.app')])
        self.recovery.disarm()
        self.assertFalse(self.recovery.path.exists())
        self.assert_bounded_calls(['print', 'bootstrap', 'bootout', 'print'])
        target = self.recovery.domain + '/' + self.recovery.label
        for call in (self.command.call_args_list[0], *self.command.call_args_list[2:]):
            self.assertEqual(call.args[0][2], target)

    def test_initial_ownership_query_timeout_does_not_create_or_stop_a_job(self):
        self.command.side_effect = self.timeout()
        with self.assertRaisesRegex(decrumb.SafeError, 'Reopen Decrumb and retry'):
            self.recovery.arm()
        self.assertFalse(self.recovery.path.exists())
        self.assert_bounded_calls(['print'])

    def test_bootstrap_timeout_preserves_new_ownership_metadata(self):
        self.command.side_effect = [Mock(returncode=1), self.timeout()]
        with self.assertRaisesRegex(decrumb.SafeError, 'took too long'):
            self.recovery.arm()
        metadata = plistlib.loads(self.recovery.path.read_bytes())
        self.assertEqual(metadata['Label'], self.recovery.label)
        self.assertEqual(metadata['WorkingDirectory'], str(self.root))
        self.assert_bounded_calls(['print', 'bootstrap'])

    def test_failed_bootstrap_with_uncertain_query_preserves_metadata(self):
        self.command.side_effect = [Mock(returncode=1), Mock(returncode=1), self.timeout()]
        with self.assertRaisesRegex(decrumb.SafeError, 'took too long'):
            self.recovery.arm()
        self.assertTrue(self.recovery.path.exists())
        self.assert_bounded_calls(['print', 'bootstrap', 'print'])

    def test_bootout_or_confirmation_timeout_preserves_existing_metadata(self):
        for stage in ('bootout', 'confirmation'):
            with self.subTest(stage=stage):
                before = self.owned_plist()
                self.command.reset_mock()
                self.command.side_effect = ([self.timeout()] if stage == 'bootout'
                                            else [Mock(returncode=0), self.timeout()])
                with self.assertRaisesRegex(decrumb.SafeError, 'took too long'):
                    self.recovery.disarm()
                self.assertEqual(self.recovery.path.read_bytes(), before)
                self.assert_bounded_calls(['bootout'] if stage == 'bootout' else ['bootout', 'print'])

    def test_confirmed_failed_bootstrap_removes_only_its_ownership_metadata(self):
        self.command.side_effect = [Mock(returncode=1), Mock(returncode=1), Mock(returncode=1)]
        with self.assertRaisesRegex(decrumb.SafeError, 'could not be enabled'):
            self.recovery.arm()
        self.assertFalse(self.recovery.path.exists())
        self.assert_bounded_calls(['print', 'bootstrap', 'print'])

    def test_unowned_loaded_job_is_not_stopped_or_overwritten(self):
        self.command.return_value = Mock(returncode=0)
        with self.assertRaisesRegex(decrumb.SafeError, 'another runtime directory'):
            self.recovery.arm()
        self.assertFalse(self.recovery.path.exists())
        self.assert_bounded_calls(['print'])

    def test_absent_or_unrelated_plist_does_not_control_launchd(self):
        self.recovery.disarm()
        service.write_plist(self.recovery.path, {
            'Label': self.recovery.label, 'WorkingDirectory': str(self.root / 'other')})
        before = self.recovery.path.read_bytes()
        with self.assertRaisesRegex(decrumb.SafeError, 'another runtime directory'):
            self.recovery.disarm()
        self.assertEqual(self.recovery.path.read_bytes(), before)
        self.command.assert_not_called()

    def test_launch_error_preserves_metadata_without_exposing_exception_details(self):
        before = self.owned_plist()
        self.command.side_effect = OSError('synthetic private detail')
        with self.assertRaisesRegex(decrumb.SafeError, 'Reopen Decrumb and retry') as error:
            self.recovery.disarm()
        self.assertNotIn('synthetic private detail', str(error.exception))
        self.assertEqual(self.recovery.path.read_bytes(), before)
        self.assert_bounded_calls(['bootout'])


if __name__ == '__main__':
    unittest.main()
