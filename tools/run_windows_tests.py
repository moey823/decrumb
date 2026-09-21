#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Native Windows suite plus shared portable behavior; offline synthetic data only."""
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
os.environ['DECRUMB_TEST_HELPER'] = str(ROOT / 'build/windows/Decrumb/url-cleaner.exe')


def main():
    if sys.platform != 'win32':
        raise SystemExit('Run this native suite on Windows.')
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in ('test_windows', 'test_decrumb.CleanerTests', 'test_decrumb.FilteringTests',
                 'test_decrumb.OutboxTests', 'test_notes.NotesTests',
                 'test_phone_commands.OwnerIdentityTests', 'test_phone_commands.CommandParsingTests',
                 'test_phone_commands.CommandDeliveryTests', 'test_portable_cleaner.PortableCleanerTests'):
        suite.addTests(loader.loadTestsFromName(name))
    import test_decrumb
    for name in loader.getTestCaseNames(test_decrumb.TransportTests):
        if name != 'test_full_worker_with_fake_signal_server':
            suite.addTest(test_decrumb.TransportTests(name))
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
