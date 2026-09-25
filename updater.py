# SPDX-License-Identifier: AGPL-3.0-only
"""Durable worker quiescence for Sparkle; never touches messages or account keys."""
import contextlib
import fcntl
import json
import re
import plistlib
from pathlib import Path
import subprocess
import time
import uuid

import decrumb

MARKER = 'update-transition.json'


def process_identity(pid):
    if type(pid) is not int or not 1 < pid <= 2**31 - 1:
        return None
    result = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'stat=', '-o', 'lstart='],
                            capture_output=True, text=True, check=False)
    fields = result.stdout.strip().split(maxsplit=1)
    if result.returncode or len(fields) != 2 or fields[0].startswith(('Z', 'X')):
        return None
    return fields[1]


def owner_identity(owner):
    # The one-file Python executable has its own short-lived parent process.
    # Only the native app can supply the stable owner of the whole transition.
    if type(owner) is not int or not 1 < owner <= 2**31 - 1:
        raise decrumb.SafeError('The app update coordinator is invalid. Reopen Decrumb and try again.')
    identity = process_identity(owner)
    if identity is None:
        raise decrumb.SafeError('The app is no longer available to coordinate its update.')
    return identity


@contextlib.contextmanager
def operation(root):
    """Serialize pairing/settings/start/stop against the update preparation."""
    with (root / 'operation.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise decrumb.SafeError('Another action is still finishing. Retry the update shortly.') from None
        yield


def marker(root):
    try:
        value = json.loads((root / MARKER).read_text())
        if (value.get('version') != 1 or type(value.get('created')) not in (int, float)
                or type(value.get('owner')) is not int or not isinstance(value.get('identity'), str)
                or not isinstance(value.get('token'), str)
                or not re.fullmatch(r'[1-9][0-9]{0,8}', value.get('target_build', ''))):
            raise ValueError()
        return value
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, AttributeError):
        raise decrumb.SafeError('Update recovery information is unreadable. Reopen Decrumb before continuing.') from None


def live(value):
    return process_identity(value['owner']) == value['identity']


def guard(root):
    value = marker(root)
    if value:
        raise decrumb.SafeError('An app update is preparing to install. Finish or cancel the update first.')


def validate_target_build(target_build):
    if not isinstance(target_build, str) or not re.fullmatch(r"[1-9][0-9]{0,8}", target_build):
        raise decrumb.SafeError("The update build number is invalid.")
    return target_build


def prepare(root, control, resources, target_build, owner=None):
    target_build = validate_target_build(target_build)
    identity = owner_identity(owner)
    previous = marker(root)
    if previous and (previous['owner'] != owner or previous['identity'] != identity):
        raise decrumb.SafeError('Another app instance is coordinating an update. Reopen Decrumb after it finishes.')
    config = decrumb.load_config(root, validate_helper=False)
    import service
    watchdog = service.UpdateRecovery(root, resources.parent / 'MacOS/Decrumb')
    watchdog.arm()
    value = previous or {'version': 1, 'created': time.time(), 'owner': owner, 'identity': identity,
                          'token': uuid.uuid4().hex,
                          'resume': bool(config.get('account')) and not config.get('paused', False)}
    value.update(target_build=str(max(int(value.get('target_build', '0')), int(target_build))), ready=False)
    decrumb.write_json(root / MARKER, value)
    try:
        control.stop()
        with decrumb.exclusive(root):
            value['ready'] = True
            decrumb.write_json(root / MARKER, value)
    except Exception:
        # Recovery can itself be blocked by an independent worker. Retain an
        # unready marker in that case; a retry must stop and verify the lock again.
        recover(root, resources, control, token=value['token'])
        raise
    return {'token': value['token'], 'ready': True}


def recover(root, resources, control, *, token=None, bootstrap=False, current_build=None, now=None):
    value = marker(root)
    if not value:
        if bootstrap:
            import service
            service.UpdateRecovery(root, resources.parent / 'MacOS/Decrumb').disarm()
        return False
    if token is not None:
        if token != value['token']:
            raise decrumb.SafeError('This update recovery request is no longer current.')
    elif live(value):
        raise decrumb.SafeError('Another app instance is still preparing an update.')
    elif not bootstrap:
        # Only the relaunched interface may reconcile an interrupted install.
        # Elapsed time is never evidence that Sparkle finished replacing files.
        return False
    if bootstrap and token is None:
        if current_build is None:
            try:
                current_build = plistlib.loads((resources.parent / 'Info.plist').read_bytes())['CFBundleVersion']
            except (OSError, ValueError, KeyError):
                return False
        if not str(current_build).isdigit() or int(current_build) < int(value['target_build']):
            return False
    config = decrumb.load_config(root, validate_helper=False)
    with decrumb.exclusive(root):
        config['helper'] = str(resources / 'url-cleaner')
        config['signal_cli'] = str(resources / 'signal-cli')
        if bootstrap:
            # Opening the app ends a pause, including the verified relaunch of
            # an installed update. Cancelling an update still preserves pause.
            config['paused'] = False
        decrumb.write_json(root / 'config.json', config)
    login = config.get('start_at_login', False)
    import service
    service.UpdateRecovery(root, resources.parent / 'MacOS/Decrumb').disarm()
    service.configure_app_login(resources.parent / 'MacOS/Decrumb', login)
    (root / MARKER).unlink()
    # A relaunch starts cleaning; an abort restores the original preference.
    # Neither path discards queued work, receipts, or deduplication records.
    if (bootstrap or value['resume']) and config.get('account') and not config.get('paused', False):
        try:
            control.start(login)
        except decrumb.SafeError:
            raise decrumb.SafeError('The update finished, but cleaning could not restart. Choose Retry connection.') from None
    return True


def claim(root, owner=None):
    """A new interface reattaches Sparkle to the interrupted transition."""
    identity = owner_identity(owner)
    value = marker(root)
    if value is None:
        return {}
    if live(value) and value['owner'] != owner:
        raise decrumb.SafeError('Another app instance is still coordinating the update.')
    value.update(owner=owner, identity=identity)
    decrumb.write_json(root / MARKER, value)
    return {'token': value['token'], 'target_build': value['target_build']}
