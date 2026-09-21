#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Native per-user Windows CLI. No listener, administrator rights or hosted service."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import cli_common
import decrumb
import diagnostics
import runtime_platform as runtime
import windows_native

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_NAME = 'Decrumb'
APP = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent


@contextlib.contextmanager
def operation(root, name='control.lock'):
    with (root / name).open('a+b') as lock:
        try:
            runtime.lock_file(lock)
        except BlockingIOError:
            raise decrumb.SafeError('Another Decrumb operation is running.') from None
        yield


def busy(root, name):
    with (root / name).open('a+b') as lock:
        try:
            runtime.lock_file(lock)
        except BlockingIOError:
            return True
    return False


def background_command(root):
    if getattr(sys, 'frozen', False):
        command = [str(APP / 'decrumb-background.exe')]
    else:
        python = Path(sys.executable).with_name('pythonw.exe')
        command = [str(python), '-B', str(APP / 'windows.py')]
    if not Path(command[0]).is_file():
        raise decrumb.SafeError('The background executable is missing. Restore the complete Windows bundle.')
    return command + ['--root', str(root), '_background']


def startup_value():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, kind = winreg.QueryValueEx(key, RUN_NAME)
            return value if kind == winreg.REG_SZ else '<unrecognized>'
    except FileNotFoundError:
        return None


def set_startup(root, config, enabled):
    import winreg
    command = subprocess.list2cmdline(background_command(root)) if enabled else None
    if command and len(command) > 260:
        raise decrumb.SafeError('The startup command is too long. Move the app to a shorter path, then run setup.')
    previous = startup_value()
    owned = {config.get('startup_command'), command}
    if previous is not None and previous not in owned:
        raise decrumb.SafeError('The Decrumb startup entry belongs to another installation.')
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, command)
        elif previous is not None:
            winreg.DeleteValue(key, RUN_NAME)
    config['startup_command'] = command
    decrumb.write_json(root / 'config.json', config)


class WindowsService:
    def __init__(self, root):
        self.root = root

    def loaded(self):
        return busy(self.root, 'background.lock')

    def stop(self, disable=False):
        # A private marker cancels only this runtime; no PID lookup or taskkill.
        (self.root / 'stop.request').touch()
        deadline = time.monotonic() + 25
        while self.loaded() and time.monotonic() < deadline:
            time.sleep(0.1)
        if self.loaded():
            raise decrumb.SafeError('Cleaning has not stopped yet. Retry in a few seconds.')
        with decrumb.exclusive(self.root):
            pass

    def start(self):
        if self.loaded():
            return
        (self.root / 'stop.request').unlink(missing_ok=True)
        requested = decrumb.now_ms()
        process = subprocess.Popen(background_command(self.root), cwd=self.root,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, close_fds=True,
                                   **runtime.child_options())
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            config = decrumb.load_config(self.root, validate_helper=False)
            status = decrumb.read_status(self.root, config)
            if status.get('updated_at', 0) >= requested and status['state'] == 'running' and self.loaded():
                return
            if process.poll() is not None:
                raise decrumb.SafeError('The background worker could not start. Run decrumb diagnostics.')
            time.sleep(0.25)
        raise decrumb.SafeError('Cleaning is still trying to connect. Check decrumb status and diagnostics.')


def supervise(root):
    stopped = threading.Event()
    finished = threading.Event()
    def watch_stop():
        while not finished.wait(0.1):
            if (root / 'stop.request').exists():
                stopped.set()
                return
    with operation(root, 'background.lock'):
        # Contain the supervisor's whole tree too: forced termination must not
        # leave a bridge/Java process holding the linked-account database open.
        windows_native.contain_children()
        watcher = threading.Thread(target=watch_stop, daemon=True)
        watcher.start()
        try:
            while not stopped.is_set() and not (root / 'stop.request').exists():
                config = decrumb.load_config(root)
                if config.get('paused') or not config.get('account'):
                    return
                try:
                    decrumb.run(root, config, stopped)
                except Exception as error:
                    diagnostics.failure(root, error)
                if stopped.wait(30):
                    break
        finally:
            finished.set()
            watcher.join(timeout=1)


def initialize(root, bundle):
    with decrumb.exclusive(root):
        if (root / 'config.json').exists():
            config = decrumb.load_config(root, validate_helper=False)
        else:
            config = {'version': 1, 'account': None, 'paused': False,
                      'settings': {'mode': 'all', 'baseURLs': [], 'excludedURLs': [], 'rules': []},
                      'notes': decrumb.notes_settings(), 'phone_commands': {'enabled': False}}
        helper = APP / ('url-cleaner.exe' if getattr(sys, 'frozen', False) else 'windows_helper.py')
        signal_cli = bundle / 'signal-cli/bin/signal-cli.bat'
        java = bundle / 'jre/bin/java.exe'
        if not all(path.is_file() for path in (helper, signal_cli, java)):
            raise decrumb.SafeError('Windows dependencies are missing. Use the complete bundle or run build.py --windows first.')
        config.update(helper=str(helper), signal_cli=str(signal_cli), java=str(java))
        decrumb.clean(helper, '', config['settings'])
        for name in ('signal-cli', 'tmp'):
            (root / name).mkdir(exist_ok=True)
        decrumb.write_json(root / 'config.json', config)
        return config


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--root', type=Path, default=decrumb.DEFAULT_ROOT, help=argparse.SUPPRESS)
    result.add_argument('--version', action='version', version='Decrumb ' + diagnostics.release()['version'])
    commands = result.add_subparsers(dest='command', required=True, metavar='COMMAND')
    setup = commands.add_parser('setup', help='Initialize private storage, pair Signal and start cleaning')
    setup.add_argument('--start-at-login', action='store_true', help='Also start automatically when you sign in')
    setup.add_argument('--bundle', type=Path, default=APP if getattr(sys, 'frozen', False) else APP / 'build/windows/Decrumb',
                       help=argparse.SUPPRESS)
    for name, description in {
        'pair': 'Link or recover Signal and start cleaning', 'resume': 'Start cleaning in the background',
        'pause': 'Stop cleaning until resumed', 'status': 'Show connection, queue and startup status',
        'run': 'Run in this terminal until Ctrl+C', 'notes': 'List tracked generated notes',
        'clear-queue': 'Discard unsent links', 'diagnostics': 'Preview a content-free report; nothing uploaded',
        'clear-diagnostics': 'Clear local error history',
    }.items():
        commands.add_parser(name, help=description)
    commands.add_parser('_background')
    for name in ('configure', 'notes-settings'):
        commands.add_parser(name, help='Import ' + ('cleaning rules' if name == 'configure' else 'note settings') + ' from JSON').add_argument('file', type=Path)
    commands.add_parser('export-rules', help='Print versioned cleaning rules without account state')
    commands.add_parser('cleanup', help='Request removal of tracked generated notes').add_argument('ids', nargs='+')
    for name in ('phone-commands', 'start-at-login'):
        commands.add_parser(name, help='Enable or disable ' + name.replace('-', ' ')).add_argument('state', choices=('enable', 'disable'))
    commands.add_parser('preview', help='Read UTF-8 text from stdin; no URLs are fetched')
    return result


def dispatch(args, root):
    service = WindowsService(root)
    if args.command == 'setup':
        if not sys.stdout.isatty():
            raise decrumb.SafeError('Pairing requires an interactive terminal. Do not redirect or record the QR code.')
        service.stop()
        windows_native.secure_directory(root)
        config = initialize(root, args.bundle.resolve())
        if args.start_at_login:
            set_startup(root, config, True)
    else:
        config = decrumb.load_config(root, validate_helper=False)
    if args.command in ('setup', 'pair'):
        if not sys.stdout.isatty():
            raise decrumb.SafeError('Pairing requires an interactive terminal. Do not redirect or record the QR code.')
        service.stop()
        print('In Signal on your phone: Settings > Linked devices > Link a new device. Scan the private QR below.', flush=True)
        decrumb.pair(root, config, terminal_qr=True)
        cli_common.resume(root, config, service)
        print('Connected. Cleaning runs in the background; you can close this terminal.')
    elif args.command == 'resume':
        cli_common.resume(root, config, service)
        print('Cleaning is running. Keep Windows awake, online and signed in.')
    elif args.command == 'pause':
        service.stop()
        with decrumb.exclusive(root):
            config['paused'] = True
            decrumb.write_json(root / 'config.json', config)
            if decrumb.notes_settings(config.get('notes'))['discard_on_pause'] and (root / 'outbox.sqlite3').exists():
                with contextlib.closing(decrumb.Store(root / 'outbox.sqlite3')) as store:
                    store.clear_pending()
        print('Cleaning paused, including after sign-in. Run decrumb resume to start again.')
    elif args.command == 'start-at-login':
        set_startup(root, config, args.state == 'enable')
        print('Start at login ' + ('enabled.' if args.state == 'enable' else 'disabled.'))
    elif args.command == 'status':
        print(json.dumps({**decrumb.read_status(root, config), 'paused': config.get('paused', False),
                          'service_active': service.loaded(),
                          'start_at_login': bool(config.get('startup_command')) and startup_value() == config['startup_command'],
                          'phone_commands': config.get('phone_commands', {'enabled': False})}, indent=2))
    elif args.command in ('configure', 'notes-settings', 'phone-commands'):
        if args.command == 'configure':
            field, value = 'settings', decrumb.clean_result(config['helper'], '', cli_common.read_cleaning_settings(args.file))['settings']
        elif args.command == 'notes-settings':
            field, value = 'notes', decrumb.notes_settings(cli_common.read_settings(args.file))
        else:
            field, value = 'phone_commands', {'enabled': args.state == 'enable'}
        cli_common.change_settings(root, config, service, field, value)
        print('Settings saved.')
    elif args.command == 'export-rules':
        print(json.dumps({'version': 1, 'settings': config['settings']}, indent=2))
    elif args.command == 'notes':
        print(json.dumps(decrumb.read_notes(root / 'outbox.sqlite3'), indent=2))
    elif args.command in ('cleanup', 'clear-queue'):
        active = service.loaded()
        service.stop()
        try:
            with decrumb.exclusive(root):
                count = 0
                if (root / 'outbox.sqlite3').exists():
                    with contextlib.closing(decrumb.Store(root / 'outbox.sqlite3')) as store:
                        count = store.clear_pending() if args.command == 'clear-queue' else store.request_cleanup(args.ids)
            print(str(count) + (' queued links discarded.' if args.command == 'clear-queue' else ' note removals queued. Cleaning must be running to process removals.'))
        finally:
            if active:
                service.start()
    elif args.command == 'preview':
        data = sys.stdin.buffer.read(64 * 1024 + 1)
        if len(data) > 64 * 1024:
            raise decrumb.SafeError('Sample exceeds 64 KiB.')
        try:
            sample = data.decode('utf-8-sig')
        except UnicodeError:
            raise decrumb.SafeError('Sample must be UTF-8 text.') from None
        print(json.dumps(decrumb.clean_result(config['helper'], sample, config['settings']), indent=2))


def main():
    args = parser().parse_args()
    if sys.platform != 'win32':
        raise decrumb.SafeError('This CLI requires Windows. Use the Mac or Raspberry Pi edition on this system.')
    root = args.root.expanduser().absolute()
    windows_native.reject_links(root)
    cli_common.guard_runtime(root, APP)
    if args.command == 'setup':
        cli_common.guard_runtime(root, args.bundle.resolve())
        windows_native.secure_directory(root)
    if not root.is_dir():
        raise decrumb.SafeError('Run decrumb setup first.')
    windows_native.check_private_directory(root)
    diagnostics.configure(root, decrumb.LOG)
    if args.command in ('diagnostics', 'clear-diagnostics'):
        if args.command == 'clear-diagnostics':
            diagnostics.maintain(root, clear=True)
        print(json.dumps(diagnostics.report(root), indent=2))
    elif args.command == '_background':
        supervise(root)
    elif args.command == 'run':
        with operation(root):
            service = WindowsService(root)
            config = decrumb.load_config(root)
            if not config.get('account'):
                raise decrumb.SafeError('Run decrumb setup first.')
            service.stop()
            config['paused'] = False
            decrumb.write_json(root / 'config.json', config)
            (root / 'stop.request').unlink(missing_ok=True)
        print('Cleaning in this terminal. Press Ctrl+C to stop.', flush=True)
        supervise(root)
    else:
        with operation(root):
            dispatch(args, root)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except decrumb.SafeError as error:
        decrumb.LOG.error(error.diagnostic_code)
        if sys.stderr is not None:
            print(str(error), file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        decrumb.LOG.error(diagnostics.failure_code(error))
        if sys.stderr is not None:
            print('Decrumb operation failed. No private diagnostic content was printed.', file=sys.stderr)
        sys.exit(1)
