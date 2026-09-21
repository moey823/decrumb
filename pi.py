#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Local Raspberry Pi controls. No network listener or remote shell commands."""
import argparse
import contextlib
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import sys
import time

import decrumb

UNIT = 'decrumb.service'
MARKER = '# Managed by Decrumb; private linked-device worker.'
APP = Path(__file__).resolve().parent


def guard_runtime(root, *code_roots):
    runtime = root.resolve()
    for code in code_roots:
        code = code.resolve()
        if runtime.is_relative_to(code) or code.is_relative_to(runtime):
            raise decrumb.SafeError('Private runtime must be separate from the installed app and extracted source.')


@contextlib.contextmanager
def operation(root):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    with (root / 'control.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise decrumb.SafeError('Another Decrumb setup or control operation is running.') from None
        yield


def unit_quote(value, *, command=False):
    """Quote one systemd argument, including literal specifier and dollar signs."""
    value = str(value)
    if any(ord(char) < 32 for char in value):
        raise decrumb.SafeError('Installation paths must not contain control characters.')
    escaped = value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    return '"' + (escaped.replace('$', '$$') if command else escaped) + '"'


def unit_text(root, app):
    return '\n'.join([
        MARKER, '[Unit]', 'Description=Decrumb Signal link cleaner',
        'After=network-online.target', '', '[Service]', 'Type=simple',
        'WorkingDirectory=' + unit_quote(root),
        'ExecStart=/usr/bin/python3 -B ' + unit_quote(app / 'pi.py', command=True) + ' --root ' + unit_quote(root, command=True) + ' run',
        'Restart=on-failure', 'RestartSec=30', 'TimeoutStopSec=25', 'UMask=0077',
        'NoNewPrivileges=true', 'PrivateTmp=true',
        'StandardOutput=null', 'StandardError=null', '', '[Install]', 'WantedBy=default.target', '',
    ])


class PiService:
    def __init__(self, root, app=APP, unit_path=None):
        self.root = Path(root)
        self.app = Path(app)
        self.path = unit_path or Path.home() / '.config/systemd/user' / UNIT

    def call(self, *args, check=True):
        try:
            result = subprocess.run(['/usr/bin/systemctl', '--user', *args],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=35)
        except (OSError, subprocess.SubprocessError):
            raise decrumb.SafeError('The user service manager is unavailable. Log in as your normal Pi user.') from None
        if check and result.returncode:
            raise decrumb.SafeError('The background service could not be updated. Check your systemd user session.')
        return result.returncode == 0

    def loaded(self):
        return self.call('is-active', '--quiet', UNIT, check=False)

    def check_owned(self):
        if self.path.exists() or self.path.is_symlink():
            try:
                value = self.path.read_text()
                if self.path.is_symlink() or not value.startswith(MARKER + '\n') or (
                    '\nWorkingDirectory=' + unit_quote(self.root) + '\n') not in value:
                    raise ValueError()
            except (OSError, ValueError):
                raise decrumb.SafeError('The existing Decrumb service belongs to another installation.') from None
        elif self.loaded():
            raise decrumb.SafeError('The running Decrumb service belongs to another installation.')

    def install(self):
        self.check_owned()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        if temporary.is_symlink():
            raise decrumb.SafeError('The service temporary path must not be a symbolic link.')
        temporary.write_text(unit_text(self.root, self.app))
        temporary.chmod(0o600)
        temporary.replace(self.path)
        self.call('daemon-reload')

    def stop(self, disable=False):
        self.check_owned()
        if self.path.exists():
            self.call('disable' if disable else 'stop', *(('--now', UNIT) if disable else (UNIT,)))
        if self.root.exists():
            # systemctl stop waits for the process, but also reject stray workers.
            with decrumb.exclusive(self.root):
                pass

    def wait_ready(self, requested_at, timeout=30):
        config = decrumb.load_config(self.root, validate_helper=False)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = decrumb.read_status(self.root, config)
            fresh = status.get('updated_at', 0) >= requested_at
            active = self.loaded()
            if fresh and status['state'] == 'running' and active:
                return
            if not active or (fresh and status['state'] in ('error', 'stopped', 'stale')):
                raise decrumb.SafeError('Cleaning failed to start. Check decrumb status, then retry decrumb resume.')
            time.sleep(0.25)
        raise decrumb.SafeError('Cleaning has not connected yet. Check decrumb status, then retry decrumb resume.')

    def start(self):
        self.check_owned()
        self.install()
        requested_at = decrumb.now_ms()
        self.call('enable', '--now', UNIT)
        self.wait_ready(requested_at)


def initialize(root, app=APP):
    guard_runtime(root, app)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    helper = app / 'portable_cleaner.py'
    signal_cli = app / 'signal-cli'
    with decrumb.exclusive(root):
        if (root / 'config.json').exists():
            config = decrumb.load_config(root, validate_helper=False)
        else:
            config = {'version': 1, 'account': None,
                      'settings': {'mode': 'all', 'baseURLs': [], 'excludedURLs': [], 'rules': []},
                      'notes': decrumb.notes_settings(), 'paused': False,
                      'phone_commands': {'enabled': False}}
        config.update(helper=str(helper), signal_cli=str(signal_cli))
        decrumb.clean(helper, '', config['settings'])
        (root / 'signal-cli').mkdir(mode=0o700, exist_ok=True)
        decrumb.write_json(root / 'config.json', config)
    return config


def resume(root, config, service):
    if not config.get('account'):
        raise decrumb.SafeError('Connect Signal first: run decrumb pair.')
    service.stop()
    with decrumb.exclusive(root):
        config['paused'] = False
        decrumb.write_json(root / 'config.json', config)
    service.start()


def change_settings(root, config, service, field, value):
    was_running = service.loaded()
    service.stop()
    try:
        with decrumb.exclusive(root):
            config[field] = value
            if field == 'settings' and (root / 'outbox.sqlite3').exists():
                with contextlib.closing(decrumb.Store(root / 'outbox.sqlite3')) as store:
                    store.clear_pending()
            if field == 'notes' and (root / 'outbox.sqlite3').exists():
                with contextlib.closing(decrumb.Store(root / 'outbox.sqlite3')) as store:
                    store.update_schedule(value)
            decrumb.write_json(root / 'config.json', config)
    finally:
        if was_running:
            service.start()


def read_settings(path):
    try:
        if path.stat().st_size > 64 * 1024:
            raise ValueError()
        return json.loads(path.read_text())
    except (OSError, ValueError):
        raise decrumb.SafeError('Settings must be a JSON file smaller than 64 KiB.') from None


def read_cleaning_settings(path):
    value = read_settings(path)
    if not isinstance(value, dict):
        raise decrumb.SafeError('Cleaning rules must be a settings object or a version 1 rules export.')
    if 'version' in value or 'settings' in value:
        if (set(value) != {'version', 'settings'} or type(value['version']) is not int or
                value['version'] != 1 or not isinstance(value['settings'], dict)):
            raise decrumb.SafeError('Cleaning rules export must contain version 1 and a settings object.')
        return value['settings']
    return value


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=decrumb.DEFAULT_ROOT)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('pair', 'resume', 'pause', 'status', 'run', 'notes', 'clear-queue'):
        commands.add_parser(name)
    configure = commands.add_parser('configure', help='Apply a cleaning-settings JSON file')
    configure.add_argument('file', type=Path)
    lifecycle = commands.add_parser('notes-settings', help='Apply a generated-note settings JSON file')
    lifecycle.add_argument('file', type=Path)
    phones = commands.add_parser('phone-commands', help='Enable or disable commands from Note to Self')
    phones.add_argument('state', choices=['enable', 'disable'])
    cleanup = commands.add_parser('cleanup', help='Request removal of Decrumb notes; identifiers come from decrumb notes')
    cleanup.add_argument('ids', nargs='+')
    commands.add_parser('preview', help='Read sample text on stdin; no network requests')
    args = parser.parse_args()
    if sys.platform != 'linux' or os.getuid() == 0:
        raise decrumb.SafeError('Run Decrumb as your normal user on 64-bit Raspberry Pi OS, without sudo.')
    root = args.root.expanduser().resolve()
    guard_runtime(root, APP)
    # A long-running worker owns worker.lock, not the short control-operation lock.
    with contextlib.nullcontext() if args.command == 'run' else operation(root):
        dispatch(args, root)


def dispatch(args, root):
    config = decrumb.load_config(root, validate_helper=args.command != 'status')
    service = PiService(root)
    if args.command == 'pair':
        if not sys.stdout.isatty():
            raise decrumb.SafeError('Pairing requires an interactive terminal. Do not redirect or record the QR code.')
        service.stop()
        print('In Signal on your phone: Settings → Linked Devices → Link New Device. Scan the private QR below.', flush=True)
        decrumb.pair(root, config, terminal_qr=True)
        resume(root, config, service)
        print('Connected. Cleaning is running and will start with your user service session.')
    elif args.command == 'resume':
        resume(root, config, service)
        print('Cleaning is running. Keep this Pi powered on and connected to the internet.')
    elif args.command == 'pause':
        service.stop(disable=True)
        with decrumb.exclusive(root):
            config['paused'] = True
            decrumb.write_json(root / 'config.json', config)
            if decrumb.notes_settings(config.get('notes'))['discard_on_pause'] and (root / 'outbox.sqlite3').exists():
                with contextlib.closing(decrumb.Store(root / 'outbox.sqlite3')) as store:
                    store.clear_pending()
        print('Cleaning paused, including after reboot. Run decrumb resume to start again.')
    elif args.command == 'run':
        if not config.get('account') or config.get('paused', False):
            return
        handler = RotatingFileHandler(root / 'worker.log', maxBytes=128 * 1024, backupCount=2)
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        decrumb.LOG.addHandler(handler)
        decrumb.LOG.setLevel(logging.INFO)
        decrumb.run(root, config)
    elif args.command == 'status':
        print(json.dumps({**decrumb.read_status(root, config), 'paused': config.get('paused', False),
                          'phone_commands': config.get('phone_commands', {'enabled': False}),
                          'service_active': service.loaded()}, indent=2))
    elif args.command == 'configure':
        normalized = decrumb.clean_result(config['helper'], '', read_cleaning_settings(args.file))['settings']
        change_settings(root, config, service, 'settings', normalized)
        print('Cleaning rules saved. Previously queued links were discarded.')
    elif args.command == 'notes-settings':
        change_settings(root, config, service, 'notes', decrumb.notes_settings(read_settings(args.file)))
        print('Generated-note settings saved.')
    elif args.command == 'phone-commands':
        change_settings(root, config, service, 'phone_commands', {'enabled': args.state == 'enable'})
        print('Phone commands enabled.' if args.state == 'enable' else 'Phone commands disabled.')
    elif args.command == 'notes':
        print(json.dumps(decrumb.read_notes(root / 'outbox.sqlite3'), indent=2))
    elif args.command in ('cleanup', 'clear-queue'):
        was_running = service.loaded()
        service.stop()
        try:
            with decrumb.exclusive(root):
                changed = 0
                if (root / 'outbox.sqlite3').exists():
                    with contextlib.closing(decrumb.Store(root / 'outbox.sqlite3')) as store:
                        changed = store.clear_pending() if args.command == 'clear-queue' else store.request_cleanup(args.ids)
            print(str(changed) + (' queued links discarded.' if args.command == 'clear-queue' else ' note removals queued. Cleaning must be running to process removals.'))
        finally:
            if was_running:
                service.start()
    elif args.command == 'preview':
        data = sys.stdin.buffer.read(64 * 1024 + 1)
        if len(data) > 64 * 1024:
            raise decrumb.SafeError('Sample exceeds 64 KiB.')
        try:
            sample = data.decode('utf-8')
        except UnicodeError:
            raise decrumb.SafeError('Sample must be UTF-8 text.') from None
        print(json.dumps(decrumb.clean_result(config['helper'], sample, config['settings']), indent=2))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except decrumb.SafeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except Exception:
        print('Decrumb operation failed. No private diagnostic content was printed.', file=sys.stderr)
        sys.exit(1)
