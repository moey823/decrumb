#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Control Decrumb's dedicated per-user LaunchAgent using its Decrumb service identifier."""
import argparse
import fcntl
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time

from decrumb import DEFAULT_ROOT, SafeError, exclusive, load_config

LABEL = "com.matthew.decrumb.link-cleaner"
APP_LABEL = "com.matthew.decrumb.app"


def write_plist(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with temporary.open('wb') as output:
        os.chmod(temporary, 0o600)
        plistlib.dump(value, output)
    temporary.replace(path)


class Service:
    def __init__(self, root, worker_command=None):
        self.root = root
        self.domain = 'gui/' + str(os.getuid())
        self.target = self.domain + '/' + LABEL
        self.login_plist = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
        self.session_plist = root / 'worker.plist'
        self.worker_command = worker_command or [sys.executable, '-B', str(Path(__file__).with_name('decrumb.py')), '--root', str(root), 'run']

    def launch(self, *arguments, check=True):
        try:
            return subprocess.run(['/bin/launchctl', *arguments], check=check,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        except subprocess.SubprocessError:
            raise SafeError('The background service could not be updated. Try again.') from None

    def loaded(self):
        return self.launch('print', self.target, check=False).returncode == 0

    def check_owned(self):
        # A custom --root must never control a job belonging to another root.
        known = False
        for path in (self.login_plist, self.session_plist):
            if path.exists():
                try:
                    value = plistlib.loads(path.read_bytes())
                    if value.get('Label') != LABEL or value.get('WorkingDirectory') != str(self.root):
                        raise ValueError()
                    known = True
                except (OSError, ValueError, plistlib.InvalidFileException):
                    raise SafeError('An existing Decrumb service belongs to a different runtime directory.') from None
        if not known and self.loaded():
            raise SafeError('A running Decrumb service cannot be matched to this runtime directory.')

    def stop(self, disable_login=False):
        self.check_owned()
        result = self.launch('bootout', self.target, check=False)
        if result.returncode and self.loaded():
            raise SafeError('Could not stop the background service.')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.root / 'worker.lock').open('a') as lock:
            deadline = time.monotonic() + 15
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise SafeError('Worker is still shutting down; try again shortly.')
                    time.sleep(0.1)
        if disable_login:
            self.login_plist.unlink(missing_ok=True)

    def install(self, login=True):
        self.check_owned()
        load_config(self.root)
        if self.loaded():
            raise SafeError('Pause the worker before updating its installation.')
        with exclusive(self.root):
            value = {
                'Label': LABEL, 'ProgramArguments': self.worker_command,
                'WorkingDirectory': str(self.root),
                'EnvironmentVariables': {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin'},
                'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 30,
                'ProcessType': 'Background', 'Umask': 0o077,
                'StandardOutPath': '/dev/null', 'StandardErrorPath': '/dev/null',
            }
            write_plist(self.session_plist, value)
            if login:
                write_plist(self.login_plist, value)
            else:
                self.login_plist.unlink(missing_ok=True)

    def start(self, login=True):
        if not load_config(self.root).get('account'):
            raise SafeError('Connect Signal before starting the background service.')
        self.check_owned()
        if not self.loaded():
            self.install(login)
            self.launch('bootstrap', self.domain, str(self.login_plist if login else self.session_plist))
            return True
        return False


def configure_app_login(executable, enabled):
    path = Path.home() / 'Library/LaunchAgents' / (APP_LABEL + '.plist')
    if enabled:
        write_plist(path, {'Label': APP_LABEL, 'ProgramArguments': [str(executable), '--background'],
                          'RunAtLoad': True, 'StandardOutPath': '/dev/null', 'StandardErrorPath': '/dev/null'})
    else:
        path.unlink(missing_ok=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['install', 'start', 'stop', 'restart', 'status'])
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--no-login', action='store_true')
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    service = Service(root)
    if args.command == 'status':
        print('LaunchAgent loaded.' if service.loaded() else 'LaunchAgent not loaded.')
    elif args.command == 'stop':
        service.stop()
        print('Stopped. The existing login preference is unchanged.')
    elif args.command == 'install':
        service.install(not args.no_login)
        print('LaunchAgent installed.')
    else:
        if args.command == 'restart':
            service.stop()
        service.start(not args.no_login)
        print('LaunchAgent started.')


if __name__ == '__main__':
    try:
        main()
    except SafeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except Exception:
        print('Background service operation failed.', file=sys.stderr)
        sys.exit(1)


class UpdateRecovery:
    """Short-lived login-session watchdog: reopen the app after interrupted update."""
    def __init__(self, root, executable):
        self.root = root
        self.executable = executable
        self.label = 'com.matthew.decrumb.update-recovery'
        self.domain = 'gui/' + str(os.getuid())
        self.path = root / 'update-recovery.plist'

    def launch(self, *arguments):
        try:
            return subprocess.run(['/bin/launchctl', *arguments],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  check=False, timeout=20)
        except subprocess.TimeoutExpired:
            # A timed-out bootstrap/bootout may still have changed launchd state.
            # Keep the ownership plist until a later check confirms removal.
            raise SafeError('Update recovery took too long. Reopen Decrumb and retry the update.') from None
        except (OSError, subprocess.SubprocessError):
            raise SafeError('Update recovery could not be checked. Reopen Decrumb and retry the update.') from None

    def arm(self):
        if not self.path.exists():
            loaded = self.launch('print', self.domain + '/' + self.label)
            if loaded.returncode == 0:
                raise SafeError('A running update recovery service belongs to another runtime directory.')
        self.disarm()
        write_plist(self.path, {'Label': self.label, 'WorkingDirectory': str(self.root),
                              'ProgramArguments': ['/usr/bin/open', '-g', str(self.executable.parent.parent.parent)],
                              'StartInterval': 120, 'RunAtLoad': False,
                              'StandardOutPath': '/dev/null', 'StandardErrorPath': '/dev/null'})
        result = self.launch('bootstrap', self.domain, str(self.path))
        if result.returncode:
            loaded = self.launch('print', self.domain + '/' + self.label)
            if loaded.returncode == 0:
                raise SafeError('Update recovery is still stopping. Reopen Decrumb to retry cleanup.')
            self.path.unlink(missing_ok=True)
            raise SafeError('Update recovery could not be enabled. Cleaning is unchanged; try again.')

    def disarm(self):
        if self.path.exists():
            try:
                value = plistlib.loads(self.path.read_bytes())
                if value.get('Label') != self.label or value.get('WorkingDirectory') != str(self.root):
                    raise ValueError()
            except (OSError, ValueError, plistlib.InvalidFileException):
                raise SafeError('Update recovery belongs to another runtime directory.') from None
            self.launch('bootout', self.domain + '/' + self.label)
            loaded = self.launch('print', self.domain + '/' + self.label)
            if loaded.returncode == 0:
                raise SafeError('Update recovery is still stopping. Reopen Decrumb to retry cleanup.')
            self.path.unlink(missing_ok=True)
