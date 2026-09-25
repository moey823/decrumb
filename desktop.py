#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Private stdio interface used by the native Decrumb app and its bundled worker."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

import service
import decrumb
import phone_commands
import updater
import diagnostics


def emit(value):
    print(json.dumps(value, separators=(',', ':')), flush=True)


def request():
    data = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise decrumb.SafeError('Settings or sample exceed the allowed size.')
    try:
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise decrumb.SafeError('The settings file is not valid JSON.') from None


def configure(root, config, settings):
    with decrumb.exclusive(root):
        if (root / 'outbox.sqlite3').exists():
            with contextlib.closing(decrumb.Store(root / 'outbox.sqlite3')) as store:
                store.clear_pending()
        config['settings'] = settings
        decrumb.write_json(root / 'config.json', config)


def start_cleaning(root, config, control, resources, *, resume=False):
    """Opening resumes a linked installation; an already running worker stays up."""
    if not config.get('account') or (config.get('paused', False) and not resume):
        return None
    updater.guard(root)
    paths = {'helper': str(resources / 'url-cleaner'), 'signal_cli': str(resources / 'signal-cli')}
    if config.get('paused', False) or any(config.get(key) != value for key, value in paths.items()):
        # A manually moved/replaced app must not keep launching an old helper.
        control.stop()
        with decrumb.exclusive(root):
            decrumb.clean(paths['helper'], '', config['settings'])
            config.update(paths)
            config['paused'] = False
            decrumb.write_json(root / 'config.json', config)
        service.configure_app_login(resources.parent / 'MacOS/Decrumb', config.get('start_at_login', False))
    requested_at = decrumb.now_ms()
    return requested_at if control.start(config.get('start_at_login', False)) else None


def change_notes(root, config, control, command, value):
    """Serialize local lifecycle edits with the receiver, preserving pause state."""
    options = decrumb.notes_settings(value.get('notes') if command == 'notes-settings' else config.get('notes'))
    was_running = bool(config.get('account')) and not config.get('paused', False)
    control.stop()
    result = {}
    try:
        with decrumb.exclusive(root):
            if command == 'notes-settings':
                config['notes'] = options
                decrumb.write_json(root / 'config.json', config)
            path = root / 'outbox.sqlite3'
            if not path.exists():
                if command == 'note-lifetime':
                    raise decrumb.SafeError('This note is not in Decrumb’s local records.')
                return {'changed': 0}
            with contextlib.closing(decrumb.Store(path)) as store:
                if command == 'clear-queue':
                    result['changed'] = store.clear_pending()
                elif command == 'notes-settings':
                    store.update_schedule(options)
                elif command == 'note-lifetime':
                    store.set_note_lifetime(value.get('id'), value.get('hours'))
                elif command == 'cleanup':
                    result['changed'] = store.request_cleanup(value.get('ids'))
                    # An active worker drains all requests after restart. When paused,
                    # make a small one-shot attempt without subscribing to messages.
                    if not was_running and config.get('account') and result['changed']:
                        try:
                            with decrumb.Rpc(root, config) as rpc:
                                for _ in range(3):
                                    if not decrumb.cleanup_one(store, rpc, config['account'], options):
                                        break
                        except decrumb.SafeError:
                            result['cleanup_notice'] = 'Some requests remain queued. Retry cleanup when connected, or resume the worker.'
    finally:
        if was_running:
            control.start(config.get('start_at_login', False))
    return result


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=decrumb.DEFAULT_ROOT)
    parser.add_argument('--resources', type=Path, required=True)
    parser.add_argument('command', choices=['bootstrap', 'snapshot', 'pair', 'pause', 'quit', 'resume', 'apply', 'preview', 'run',
                                           'notes-list', 'notes-settings', 'clear-queue', 'cleanup', 'note-lifetime',
                                           'update-prepare', 'update-abort', 'update-claim',
                                           'diagnostics', 'clear-diagnostics'])
    args = parser.parse_args()
    root, resources = args.root.expanduser().resolve(), args.resources.resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    diagnostics.configure(root, decrumb.LOG)
    # Support remains available even when setup/configuration cannot be loaded.
    if args.command in ('diagnostics', 'clear-diagnostics'):
        if args.command == 'clear-diagnostics':
            diagnostics.maintain(root, clear=True)
        emit(diagnostics.report(root))
        return
    helper, signal_cli = resources / 'url-cleaner', resources / 'signal-cli'
    if not (root / 'config.json').exists():
        if args.command == 'quit':
            # Setup has not created a worker for this runtime. In particular,
            # do not try to stop a service owned by another runtime directory.
            with updater.operation(root):
                updater.guard(root)
                emit({'paused': True})
            return
        if args.command != 'bootstrap':
            raise decrumb.SafeError('Finish app setup first.')
        with decrumb.exclusive(root):
            decrumb.clean(helper, '', {'mode': 'all', 'baseURLs': []})
            (root / 'signal-cli').mkdir(mode=0o700, exist_ok=True)
            decrumb.write_json(root / 'config.json', {
                'version': 1, 'helper': str(helper), 'signal_cli': str(signal_cli), 'account': None,
                'settings': {'mode': 'all', 'baseURLs': [], 'excludedURLs': [], 'rules': []},
                'paused': False, 'start_at_login': False,
                'notes': decrumb.notes_settings(),
                'phone_commands': phone_commands.normalize_settings(),
            })
    config = decrumb.load_config(root, validate_helper=False)
    entry = [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, '-B', str(Path(__file__).resolve())]
    control = service.Service(root, entry + ['--root', str(root), '--resources', str(resources), 'run'])

    with contextlib.ExitStack() as operations:
        if args.command not in ('snapshot', 'preview', 'notes-list', 'run'):
            operations.enter_context(updater.operation(root))
            if args.command == 'quit':
                quit_transition = updater.marker(root)
                value = request()
                if quit_transition:
                    if value.get('token') != quit_transition['token']:
                        updater.guard(root)
                elif 'target_build' in value:
                    target_build = updater.validate_target_build(value['target_build'])
                    owner = value.get('owner_pid')
                    identity = updater.owner_identity(owner)
                    # An update waiting to install on normal exit needs a durable
                    # checkpoint, but must not arm a watchdog that reopens the app.
                    quit_transition = {
                        'version': 1, 'created': time.time(), 'owner': owner, 'identity': identity,
                        'token': uuid.uuid4().hex, 'target_build': target_build,
                        'resume': False, 'ready': True,
                    }
            elif args.command not in ('bootstrap', 'update-prepare', 'update-abort', 'update-claim'):
                updater.guard(root)
        def snapshot():
            maintenance = decrumb.maintain_outbox(root)
            value = decrumb.read_status(root, config)
            if maintenance:
                value.update(maintenance)
                value['needs_attention'] = (value['needs_attention'] or bool(value['counts'].get('uncertain')) or
                                            any(v for k, v in value['metrics'].items() if k != 'last_sent_at'))
            value.update({'settings': config['settings'], 'paused': config.get('paused', False),
                          'start_at_login': config.get('start_at_login', True),
                          'phone_commands_enabled': phone_commands.normalize_settings(config.get('phone_commands'))['enabled'],
                          'notes_options': decrumb.notes_settings(config.get('notes'))})
            value['note_counts'] = decrumb.read_notes(root / 'outbox.sqlite3')['note_counts']
            value['needs_attention'] = value['needs_attention'] or any(
                value['note_counts'].get(key, 0) for key in ('delete_uncertain', 'cleanup_failed', 'account_mismatch'))
            # No account identifiers or key paths are returned to the interface.
            return value

        def use_bundled_paths():
            config['helper'], config['signal_cli'] = str(helper), str(signal_cli)

        if args.command == 'update-claim':
            emit(updater.claim(root, owner=request().get('owner_pid')))
        elif args.command == 'update-prepare':
            value = request()
            emit(updater.prepare(root, control, resources, value.get('target_build'), owner=value.get('owner_pid')))
        elif args.command == 'update-abort':
            updater.recover(root, resources, control, token=request().get('token'))
            emit(snapshot())
        elif args.command == 'bootstrap':
            result = {}
            recovery_failed = False
            try:
                recovered = updater.recover(root, resources, control, bootstrap=True)
            except decrumb.SafeError as error:
                # Keep the linked-account status visible even if recovery cannot
                # restart the service. Do not bypass a failed update handoff.
                recovered = recovery_failed = True
                result['startup_error'] = str(error)
            config = decrumb.load_config(root, validate_helper=False)
            pending = updater.marker(root) is not None
            if not pending and not recovered:
                try:
                    result['startup_requested_at'] = start_cleaning(root, config, control, resources, resume=True)
                except decrumb.SafeError:
                    result['startup_error'] = 'Cleaning could not start. Check your connection and choose Retry connection.'
            emit({**snapshot(), 'update_pending': pending and not recovery_failed, **result})
        elif args.command == 'snapshot':
            emit(snapshot())
        elif args.command == 'notes-list':
            emit(decrumb.read_notes(root / 'outbox.sqlite3'))
        elif args.command in ('notes-settings', 'clear-queue', 'cleanup', 'note-lifetime'):
            value = {} if args.command == 'clear-queue' else request()
            result = change_notes(root, config, control, args.command, value)
            emit({**snapshot(), **decrumb.read_notes(root / 'outbox.sqlite3'), **result})
        elif args.command == 'preview':
            value = request()
            text = value.get('text', '')
            if not isinstance(text, str) or len(text.encode()) > 64 * 1024:
                raise decrumb.SafeError('Sample exceeds 64 KiB.')
            emit(decrumb.clean_result(helper, text, value.get('settings', config['settings'])))
        elif args.command == 'pair':
            # Pairing shares the lock with the worker; never forcibly unlinks an account.
            with decrumb.exclusive(root):
                use_bundled_paths()
                decrumb.write_json(root / 'config.json', config)
            decrumb.pair(root, config, lambda state: emit({'event': state}))
            # Pairing must finish and release its worker lock before receiving.
            # A successful connection is the last setup step, including an
            # unlinked configuration created by an earlier release.
            if config.get('account'):
                with decrumb.exclusive(root):
                    config['paused'] = False
                    decrumb.write_json(root / 'config.json', config)
                try:
                    started_at = start_cleaning(root, config, control, resources)
                    emit({'event': 'cleaning_started', 'startup_requested_at': started_at})
                except decrumb.SafeError:
                    raise decrumb.SafeError('Signal connected, but cleaning could not start. Choose Retry connection.') from None
        elif args.command == 'quit':
            control.stop(disable_login=True)
            with decrumb.exclusive(root):
                config['paused'] = True
                decrumb.write_json(root / 'config.json', config)
                if quit_transition:
                    # Keep the transition until the next explicit app launch
                    # reconciles it, with cleaning stopped in the meantime.
                    quit_transition.update(resume=False, ready=True)
                    decrumb.write_json(root / updater.MARKER, quit_transition)
            if quit_transition:
                service.UpdateRecovery(root, resources.parent / 'MacOS/Decrumb').disarm()
            # Quitting must preserve queued links even if pausing would discard
            # them. Avoid snapshot maintenance, which can also prune the queue.
            emit({'paused': True})
        elif args.command == 'pause':
            control.stop(disable_login=True)
            with decrumb.exclusive(root):
                config['paused'] = True
                decrumb.write_json(root / 'config.json', config)
                if decrumb.notes_settings(config.get('notes'))['discard_on_pause'] and (root / 'outbox.sqlite3').exists():
                    with contextlib.closing(decrumb.Store(root / 'outbox.sqlite3')) as store:
                        store.clear_pending()
            emit(snapshot())
        elif args.command == 'resume':
            control.stop()
            with decrumb.exclusive(root):
                use_bundled_paths()
                decrumb.clean(helper, '', config['settings'])
                config['paused'] = False
                decrumb.write_json(root / 'config.json', config)
            result = {}
            try:
                result['startup_requested_at'] = start_cleaning(root, config, control, resources)
            except decrumb.SafeError:
                result['startup_error'] = 'Cleaning could not start. Check your connection and choose Retry connection.'
            emit({**snapshot(), **result})
        elif args.command == 'apply':
            value = request()
            settings = decrumb.clean_result(helper, '', value.get('settings', {}))['settings']
            login = value.get('start_at_login', False)
            if type(login) is not bool:
                raise decrumb.SafeError('Start at login must be on or off.')
            try:
                phone_options = phone_commands.normalize_settings(value.get('phone_commands', config.get('phone_commands')))
            except ValueError:
                raise decrumb.SafeError('Phone commands must be on or off.') from None
            was_running = not config.get('paused', False) and bool(config.get('account'))
            control.stop(disable_login=True)
            use_bundled_paths()
            config['start_at_login'] = login
            config['phone_commands'] = phone_options
            configure(root, config, settings)
            app_executable = resources.parent / 'MacOS/Decrumb'
            service.configure_app_login(app_executable, login)
            if was_running:
                control.start(login)
            emit(snapshot())
        elif args.command == 'run':
            # The worker owns worker.lock, not operation.lock: its parent may
            # still be in a serialized resume/recovery command while spawning it.
            # decrumb.run checks the transition after acquiring worker.lock.
            config = decrumb.load_config(root, validate_helper=False)
            if config.get('paused', False):
                return
            decrumb.run(root, decrumb.load_config(root))


if __name__ == '__main__':
    try:
        main()
    except decrumb.SafeError as error:
        decrumb.LOG.error(error.diagnostic_code)
        emit({'error': str(error)})
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as error:
        # Never serialize an exception containing private upstream data.
        decrumb.LOG.error(diagnostics.failure_code(error))
        emit({'error': 'Operation failed. Check the app status and try again.'})
        sys.exit(1)
