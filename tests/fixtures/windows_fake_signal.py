#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Offline stdio fixture. All identities and messages below are synthetic."""
import copy
import json
from pathlib import Path
import sys
import time

SELF = '+15550000001'
root = Path(sys.argv[sys.argv.index('--config') + 1])
root.mkdir(exist_ok=True)
for line in sys.stdin:
    request = json.loads(line)
    method, params = request['method'], request.get('params', {})
    result = {}
    if method == 'listAccounts':
        result = [{'number': SELF}] if (root / 'linked.test').exists() else []
    elif method == 'startLink':
        result = {'deviceLinkUri': 'sgnl://linkdevice?uuid=synthetic&pub_key=synthetic'}
    elif method == 'finishLink':
        (root / 'linked.test').touch()
    elif method == 'subscribeReceive':
        result = 0
    elif method == 'send':
        if set(params) != {'account', 'noteToSelf', 'message'} or params.get('noteToSelf') is not True or params.get('account') != SELF:
            raise SystemExit(3)
        calls = root / 'calls.test'
        values = json.loads(calls.read_text()) if calls.exists() else []
        values.append(params)
        calls.write_text(json.dumps(values))
        result = {'timestamp': int(time.time() * 1000), 'results': [{'type': 'SUCCESS'}]}
    print(json.dumps({'id': request['id'], 'result': result}), flush=True)
    if method == 'subscribeReceive':
        timestamp = int(time.time() * 1000)
        event = {'method': 'receive', 'params': {'result': {'account': SELF, 'envelope': {
            'sourceNumber': '+15550000002', 'dataMessage': {'timestamp': timestamp,
            'message': 'https://example.invalid/?utm_source=synthetic&id=1',
            'expiresInSeconds': 0, 'viewOnce': False, 'textStyles': []}}}}}
        # Duplicate delivery plus the three privacy exclusions.
        for item in (event, event):
            print(json.dumps(item), flush=True)
        for index, (key, value) in enumerate((('expiresInSeconds', 60), ('viewOnce', True),
                ('textStyles', [{'style': 'SPOILER', 'start': 0, 'length': 4}]))):
            item = copy.deepcopy(event)
            item['params']['result']['envelope']['dataMessage'].update({key: value, 'timestamp': timestamp + index + 1})
            print(json.dumps(item), flush=True)
