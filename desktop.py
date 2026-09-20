#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Private stdio interface used by the native Decrumb app and its bundled worker."""
import argparse
import contextlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys

import service
import sidelet


def emit(value):
    print(json.dumps(value, separators=(',', ':')), flush=True)


def request():
    data = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise sidelet.SafeError('Settings or sample exceed the allowed size.')
    try:
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise sidelet.SafeError('The settings file is not valid JSON.') from None


def configure(root, config, settings):
    with sidelet.exclusive(root):
        if (root / 'outbox.sqlite3').exists():
            with contextlib.closing(sidelet.Store(root / 'outbox.sqlite3')) as store:
                store.clear_pending()
        config['settings'] = settings
        sidelet.write_json(root / 'config.json', config)


def change_notes(root, config, control, command, value):
    """Serialize local lifecycle edits with the receiver, preserving pause state."""
    options = sidelet.notes_settings(value.get('notes') if command == 'notes-settings' else config.get('notes'))
    was_running = bool(config.get('account')) and not config.get('paused', False)
    control.stop()
    result = {}
    try:
        with sidelet.exclusive(root):
            if command == 'notes-settings':
                config['notes'] = options
                sidelet.write_json(root / 'config.json', config)
            path = root / 'outbox.sqlite3'
            if not path.exists():
                if command == 'note-lifetime':
                    raise sidelet.SafeError('This note is not in Decrumb’s local records.')
                return {'changed': 0}
            with contextlib.closing(sidelet.Store(path)) as store:
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
                            with sidelet.Rpc(root, config) as rpc:
                                for _ in range(3):
                                    if not sidelet.cleanup_one(store, rpc, config['account'], options):
                                        break
                        except sidelet.SafeError:
                            result['cleanup_notice'] = 'Some requests remain queued. Retry cleanup when connected, or resume the worker.'
    finally:
        if was_running:
            control.start(config.get('start_at_login', False))
    return result


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=sidelet.DEFAULT_ROOT)
    parser.add_argument('--resources', type=Path, required=True)
    parser.add_argument('command', choices=['bootstrap', 'snapshot', 'pair', 'pause', 'resume', 'apply', 'preview', 'run',
                                           'notes-list', 'notes-settings', 'clear-queue', 'cleanup', 'note-lifetime'])
    args = parser.parse_args()
    root, resources = args.root.expanduser().resolve(), args.resources.resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    helper, signal_cli = resources / 'url-cleaner', resources / 'signal-cli'
    if not (root / 'config.json').exists():
        if args.command != 'bootstrap':
            raise sidelet.SafeError('Finish app setup first.')
        with sidelet.exclusive(root):
            sidelet.clean(helper, '', {'mode': 'all', 'baseURLs': []})
            (root / 'signal-cli').mkdir(mode=0o700, exist_ok=True)
            sidelet.write_json(root / 'config.json', {
                'version': 1, 'helper': str(helper), 'signal_cli': str(signal_cli), 'account': None,
                'settings': {'mode': 'all', 'baseURLs': [], 'excludedURLs': [], 'rules': []},
                'paused': True, 'start_at_login': False,
                'notes': sidelet.notes_settings(),
            })
    config = sidelet.load_config(root, validate_helper=False)
    entry = [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, '-B', str(Path(__file__).resolve())]
    control = service.Service(root, entry + ['--root', str(root), '--resources', str(resources), 'run'])

    def snapshot():
        maintenance = sidelet.maintain_outbox(root)
        value = sidelet.read_status(root, config)
        if maintenance:
            value.update(maintenance)
            value['needs_attention'] = (value['needs_attention'] or bool(value['counts'].get('uncertain')) or
                                        any(v for k, v in value['metrics'].items() if k != 'last_sent_at'))
        value.update({'settings': config['settings'], 'paused': config.get('paused', False),
                      'start_at_login': config.get('start_at_login', True),
                      'notes_options': sidelet.notes_settings(config.get('notes'))})
        value['note_counts'] = sidelet.read_notes(root / 'outbox.sqlite3')['note_counts']
        value['needs_attention'] = value['needs_attention'] or any(
            value['note_counts'].get(key, 0) for key in ('delete_uncertain', 'cleanup_failed', 'account_mismatch'))
        # No account identifiers or key paths are returned to the interface.
        return value

    def use_bundled_paths():
        config['helper'], config['signal_cli'] = str(helper), str(signal_cli)

    if args.command in ('bootstrap', 'snapshot'):
        emit(snapshot())
    elif args.command == 'notes-list':
        emit(sidelet.read_notes(root / 'outbox.sqlite3'))
    elif args.command in ('notes-settings', 'clear-queue', 'cleanup', 'note-lifetime'):
        value = {} if args.command == 'clear-queue' else request()
        result = change_notes(root, config, control, args.command, value)
        emit({**snapshot(), **sidelet.read_notes(root / 'outbox.sqlite3'), **result})
    elif args.command == 'preview':
        value = request()
        text = value.get('text', '')
        if not isinstance(text, str) or len(text.encode()) > 64 * 1024:
            raise sidelet.SafeError('Sample exceeds 64 KiB.')
        emit(sidelet.clean_result(helper, text, value.get('settings', config['settings'])))
    elif args.command == 'pair':
        # Pairing shares the lock with the worker; never forcibly unlinks an account.
        with sidelet.exclusive(root):
            use_bundled_paths()
            sidelet.write_json(root / 'config.json', config)
        sidelet.pair(root, config, lambda state: emit({'event': state}))
    elif args.command == 'pause':
        control.stop(disable_login=True)
        with sidelet.exclusive(root):
            config['paused'] = True
            sidelet.write_json(root / 'config.json', config)
            if sidelet.notes_settings(config.get('notes'))['discard_on_pause'] and (root / 'outbox.sqlite3').exists():
                with contextlib.closing(sidelet.Store(root / 'outbox.sqlite3')) as store:
                    store.clear_pending()
        emit(snapshot())
    elif args.command == 'resume':
        control.stop()
        with sidelet.exclusive(root):
            use_bundled_paths()
            sidelet.clean(helper, '', config['settings'])
            config['paused'] = False
            sidelet.write_json(root / 'config.json', config)
        control.start(config.get('start_at_login', False))
        emit(snapshot())
    elif args.command == 'apply':
        value = request()
        settings = sidelet.clean_result(helper, '', value.get('settings', {}))['settings']
        login = value.get('start_at_login', False)
        if type(login) is not bool:
            raise sidelet.SafeError('Start at login must be on or off.')
        was_running = not config.get('paused', False) and bool(config.get('account'))
        control.stop(disable_login=True)
        use_bundled_paths()
        config['start_at_login'] = login
        configure(root, config, settings)
        app_executable = resources.parent / 'MacOS/Decrumb'
        service.configure_app_login(app_executable, login)
        if was_running:
            control.start(login)
        emit(snapshot())
    elif args.command == 'run':
        if config.get('paused', False):
            return
        handler = RotatingFileHandler(root / 'worker.log', maxBytes=128 * 1024, backupCount=2)
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        sidelet.LOG.addHandler(handler)
        sidelet.LOG.setLevel(logging.INFO)
        sidelet.run(root, sidelet.load_config(root))


if __name__ == '__main__':
    try:
        main()
    except sidelet.SafeError as error:
        emit({'error': str(error)})
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception:
        # Never serialize an exception containing private upstream data.
        emit({'error': 'Operation failed. Check the app status and try again.'})
        sys.exit(1)
