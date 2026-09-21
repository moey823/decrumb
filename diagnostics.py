# SPDX-License-Identifier: AGPL-3.0-only
"""Bounded local error codes and an explicitly allowlisted, user-shared report.

No network access, exception strings, message data, or persistent identifiers.
The lock is shared by the worker and controls so clearing never races a writer.
"""
import contextlib
import json
import logging
import os
from pathlib import Path
import platform
import re
import sqlite3
import time
import runtime_platform as runtime

MAX_BYTES = 64 * 1024
MAX_EVENTS = 128
RETENTION_DAYS = 7
CODES = {
    'rpc_oversize': 'connection', 'receive_buffer_full': 'connection',
    'rpc_reader_failed': 'connection', 'connection_failed': 'connection',
    'connection_closed': 'connection', 'connection_timeout': 'connection',
    'signal_command_failed': 'connection', 'signal_command_interrupted': 'connection',
    'account_mismatch': 'connection', 'pairing_expired': 'pairing',
    'outbox_full': 'queue', 'cleaned_message_oversize': 'cleaner',
    'message_cleanup_failed': 'cleaner', 'phone_command_cleanup_failed': 'cleaner',
    'helper_failed': 'cleaner', 'send_unconfirmed_no_retry': 'delivery',
    'note_cleanup_unconfirmed': 'cleanup', 'storage_failed': 'storage',
    'configuration_failed': 'configuration', 'operation_failed': 'app',
    'unexpected_failure': 'app',
}


def release():
    try:
        value = json.loads(Path(__file__).with_name('release.json').read_text())
        version, build = value['version'], value['build']
        if (isinstance(version, str) and re.fullmatch(r'\d{1,4}\.\d{1,4}\.\d{1,4}', version)
                and type(build) is int and 1 <= build <= 999999999):
            return {'version': version, 'build': build}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {'version': 'unknown', 'build': 0}


def _read(path):
    with path.open('rb') as source:
        data = source.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError()
    return json.loads(data)


@contextlib.contextmanager
def _locked(root):
    root = Path(root)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (root / 'diagnostics.lock').open('a') as lock:
        runtime.private_mode(lock.fileno())
        runtime.lock_file(lock, blocking=True)
        yield root


def _events(root, day):
    try:
        values = _read(root / 'worker.log')
    except (OSError, ValueError, UnicodeError, RecursionError):
        return []
    if not isinstance(values, list):
        return []
    safe = []
    for value in values[-MAX_EVENTS:]:
        if not isinstance(value, dict):
            continue
        code, stamp = value.get('code'), value.get('day')
        version, build = value.get('version'), value.get('build')
        if (not isinstance(code, str) or code not in CODES or type(stamp) is not int
                or not day - RETENTION_DAYS < stamp <= day
                or not isinstance(version, str)
                or not (version == 'unknown' or re.fullmatch(r'\d{1,4}\.\d{1,4}\.\d{1,4}', version))
                or type(build) is not int or not 0 <= build <= 999999999):
            continue
        # Reconstruct, never forward arbitrary saved fields, including component.
        safe.append({'day': stamp, 'code': code, 'version': version, 'build': build})
    return safe


def _save(root, events):
    # One fixed staging file under the same lock: repeated hard crashes cannot
    # accumulate unbounded temporary copies of the history.
    name = root / '.diagnostics.tmp'
    if name.is_symlink():
        raise OSError('Invalid diagnostic staging file.')
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(fd, 'w') as output:
            runtime.private_mode(output.fileno())
            json.dump(events[-MAX_EVENTS:], output, separators=(',', ':'))
            output.write('\n')
        os.replace(name, root / 'worker.log')
        # Remove legacy rotating logs, including their successful-send timestamps.
        for suffix in ('.1', '.2'):
            (root / ('worker.log' + suffix)).unlink(missing_ok=True)
    finally:
        Path(name).unlink(missing_ok=True)


def maintain(root, *, clear=False, code=None):
    """Return safe records or raise a storage error; callers choose how to show it."""
    with _locked(root) as root:
        day = int(time.time() // 86400)
        events = [] if clear else _events(root, day)
        if isinstance(code, str) and code in CODES:
            event = {'day': day, 'code': code, **release()}
            # Repeated failures need no per-message timeline or event count.
            if event not in events:
                events.append(event)
        events = events[-MAX_EVENTS:]
        _save(root, events)
        return events


def record(root, code):
    if not isinstance(code, str) or code not in CODES:
        return
    try:
        maintain(root, code=code)
    except OSError:
        pass  # Diagnostics must never interrupt cleaning or print private paths.


def failure_code(error):
    code = getattr(error, 'diagnostic_code', None)
    if isinstance(error, (OSError, sqlite3.Error)):
        code = 'storage_failed'
    return code if isinstance(code, str) and code in CODES else 'unexpected_failure'


def failure(root, error):
    record(root, failure_code(error))


class ErrorHandler(logging.Handler):
    def __init__(self, root):
        super().__init__(logging.WARNING)
        self.root = Path(root)

    def emit(self, record_value):
        # Never format an exception, interpolate args or invoke __str__ on input.
        if not record_value.args and isinstance(record_value.msg, str):
            record(self.root, record_value.msg)


def configure(root, logger):
    for handler in list(logger.handlers):
        if isinstance(handler, ErrorHandler):
            logger.removeHandler(handler)
            handler.close()
    logger.addHandler(ErrorHandler(root))
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    try:
        maintain(root)
    except OSError:
        pass


def report(root):
    """Only this object may be exported. No config, database or raw log export."""
    try:
        events = maintain(root)
        history = 'available'
    except OSError:
        events, history = [], 'unavailable'
    state = 'unknown'
    try:
        saved = _read(Path(root) / 'status.json')
        if isinstance(saved, dict) and saved.get('state') in ('starting', 'running', 'stopped', 'error'):
            state = saved['state']
            stamp = saved.get('updated_at')
            if state in ('starting', 'running') and (type(stamp) is not int or not 0 <= time.time() * 1000 - stamp <= 90000):
                state = 'stale'
    except (OSError, ValueError, UnicodeError, RecursionError):
        pass
    system = platform.system()
    system = system if system in ('Darwin', 'Linux') else 'unknown'
    raw_version = platform.mac_ver()[0] if system == 'Darwin' else platform.release()
    match = re.match(r'\d{1,4}(?:\.\d{1,4}){0,2}', raw_version)
    machine = platform.machine()
    unique = {(e['code'], e['version'], e['build']) for e in events}
    return {'schema': 1, 'app': 'Decrumb', 'release': release(),
            'platform': {'os': 'macOS' if system == 'Darwin' else system,
                         'os_version' if system == 'Darwin' else 'kernel_version': match[0] if match else 'unknown',
                         'architecture': machine if machine in ('arm64', 'aarch64', 'x86_64', 'AMD64') else 'unknown'},
            'dependencies': {'signal_cli_pinned': '0.14.8', 'python': platform.python_version()},
            'health': {'worker': state, 'error_history': history},
            'recent_errors': [{'code': code, 'component': CODES[code], 'version': version, 'build': build}
                              for code, version, build in sorted(unique)],
            'sharing': 'Nothing is uploaded. Review this report before sharing it yourself.'}
