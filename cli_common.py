# SPDX-License-Identifier: AGPL-3.0-only
"""Shared local CLI controls for Pi and Windows."""
import contextlib
import json
import decrumb


def guard_runtime(root, *code_roots):
    runtime = root.resolve()
    for code in code_roots:
        code = code.resolve()
        if runtime.is_relative_to(code) or code.is_relative_to(runtime):
            raise decrumb.SafeError('Private runtime must be separate from the installed app and extracted source.')


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
        return json.loads(path.read_text(encoding='utf-8-sig'))
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
