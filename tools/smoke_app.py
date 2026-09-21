#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Verify a packaged app with synthetic fixtures and an isolated empty native CLI."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import decrumb

ENV = {**os.environ, 'PATH': '/usr/bin:/bin'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, default=ROOT / 'build/Decrumb.app')
    app = parser.parse_args(argv).app.resolve()
    helpers = app / 'Contents/Helpers'
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / 'runtime'
        resources = Path(directory) / 'helpers'
        resources.mkdir()
        for name in ('url-cleaner',):
            (resources / name).symlink_to(helpers / name)
        command = [str(helpers / 'decrumb-worker'), '--root', str(root), '--resources', str(resources)]
        def call(name, payload=None):
            result = subprocess.run(command + [name], input=json.dumps(payload).encode() if payload else None,
                                    capture_output=True, check=True, env=ENV, timeout=20)
            return json.loads(result.stdout)
        assert not call('bootstrap')['linked']
        result = call('preview', {'text': 'https://example.com/?utm_source=synthetic&id=1', 'settings': {'mode': 'all', 'baseURLs': []}})
        assert result['urls'] == ['https://example.com/?id=1']
        assert not (root / 'outbox.sqlite3').exists()
        print('Packaged bootstrap and local preview passed with no Homebrew on PATH.')
        fake = resources / 'signal-cli'
        fake.write_text('#!' + sys.executable + '''
import json,sys,time
from pathlib import Path
for line in sys.stdin:
 r=json.loads(line); result={}
 if r['method']=='listAccounts': result=[]
 elif r['method']=='startLink': result={'deviceLinkUri':'sgnl://linkdevice?uuid=synthetic&pub_key=synthetic'}
 elif r['method']=='finishLink': time.sleep(60)
 print(json.dumps({'id':r['id'],'result':result}),flush=True)
''')
        fake.chmod(0o700)
        pairing = subprocess.Popen(command + ['pair'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ENV)
        try:
            deadline = time.monotonic() + 15
            while not (root / 'pairing.png').exists() and pairing.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            assert (root / 'pairing.png').exists(), 'Synthetic pairing never created a QR image'
        finally:
            pairing.terminate()
            pairing.communicate(timeout=15)
        assert not (root / 'pairing.png').exists(), 'Pairing cancellation left its QR image behind'
        print('Packaged pairing cancellation removed the QR and stopped its fake Signal child.')
        config_path = root / 'config.json'
        config = json.loads(config_path.read_text())
        config.update(account='+15550000001', paused=False)
        config_path.write_text(json.dumps(config))
        fake.write_text('#!' + sys.executable + '''
import json,re,sys,time
from pathlib import Path
root=Path(sys.argv[sys.argv.index('--config')+1]).parent
for line in sys.stdin:
 r=json.loads(line); method=r['method']; result={}
 if method=='listAccounts': result=[{'number':'+15550000001'}]
 elif method=='subscribeReceive': result=0
 elif method=='send':
  assert set(r['params'])=={'account','noteToSelf','message'}
  assert r['params']['noteToSelf'] is True and r['params']['account']=='+15550000001'
  lines=r['params']['message'].splitlines()
  assert len(lines)==3
  assert lines[0]=='Decrumb · From Synthetic Sender'
  assert lines[1]=='https://example.com/?id=1'
  assert re.fullmatch(r'#decrumb_[0-9a-f]{24}',lines[2])
  assert not (root/'synthetic-sends').exists(), 'Duplicate synthetic send'
  receipt={'timestamp':int(time.time()*1000),'marker':lines[2]}
  (root/'synthetic-sends').write_text(json.dumps(receipt))
  result={'timestamp':receipt['timestamp'],'results':[{'type':'SUCCESS'}]}
 elif method=='remoteDelete':
  assert set(r['params'])=={'account','noteToSelf','targetTimestamp'}
  receipt=json.loads((root/'synthetic-sends').read_text())
  assert r['params']['account']=='+15550000001' and r['params']['noteToSelf'] is True
  assert r['params']['targetTimestamp']==receipt['timestamp']
  assert not (root/'synthetic-deletes').exists(), 'Duplicate synthetic removal'
  (root/'synthetic-deletes').write_text(json.dumps({'targetTimestamp':receipt['timestamp']}))
  result={'timestamp':int(time.time()*1000),'results':[{'type':'SUCCESS'}]}
 print(json.dumps({'id':r['id'],'result':result}),flush=True)
 if method=='subscribeReceive' and not (root/'synthetic-event-emitted').exists():
  (root/'synthetic-event-emitted').touch()
  timestamp=int(time.time()*1000)
  data={'timestamp':timestamp,'message':'https://example.com/?utm_source=x&id=1','expiresInSeconds':0,'viewOnce':False,'textStyles':[]}
  event={'method':'receive','params':{'account':'+15550000001','envelope':{'sourceUuid':'synthetic-peer','sourceName':'Synthetic Sender','dataMessage':data}}}
  print(json.dumps(event),flush=True); print(json.dumps(event),flush=True)
''')
        worker = subprocess.Popen(command + ['run'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ENV)
        try:
            deadline = time.monotonic() + 15
            while not (root / 'synthetic-sends').exists() and worker.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            assert (root / 'synthetic-sends').exists(), 'Packaged worker did not send its synthetic note'
            deadline = time.monotonic() + 15
            ledger = {'notes': []}
            while time.monotonic() < deadline:
                ledger = call('notes-list')
                if ledger['notes'] and ledger['notes'][0]['state'] == 'available':
                    break
                assert worker.poll() is None, 'Packaged worker stopped before recording its receipt'
            assert len(ledger['notes']) == 1 and ledger['notes'][0]['state'] == 'available'
        finally:
            worker.terminate()
            stdout, stderr = worker.communicate(timeout=15)
        assert not stdout + stderr, 'Packaged worker emitted unexpected output'
        receipt = json.loads((root / 'synthetic-sends').read_text())
        note = ledger['notes'][0]
        assert note['sent_at'] == receipt['timestamp']
        assert note['marker'] == receipt['marker'] == '#' + note['id']
        assert note['can_cleanup'] is True
        metadata = json.dumps(ledger)
        for private_value in ('example.com', 'utm_source', 'Synthetic Sender', 'synthetic-peer', '+15550000001'):
            assert private_value not in metadata, 'Receipt metadata included synthetic private content'
        assert not {'body', 'message', 'url', 'urls', 'sender', 'account', 'account_hash'} & set(note)
        status = call('snapshot')
        assert status['counts'] == {'sent': 1}
        assert status['state'] == 'stopped'
        print('Packaged incoming-message processing, deduplication, Note to Self delivery, and shutdown passed.')
        # Seed only this temporary installation's own recorded receipt. Avoid desktop
        # lifecycle commands here: they manage real LaunchAgents even with --root.
        with decrumb.exclusive(root), contextlib.closing(decrumb.Store(root / 'outbox.sqlite3')) as store:
            assert store.request_cleanup([note['id']]) == 1
        assert call('notes-list')['notes'][0]['state'] == 'cleanup_pending'
        worker = subprocess.Popen(command + ['run'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ENV)
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                ledger = call('notes-list')
                if ledger['notes'][0]['state'] == 'deletion_requested':
                    break
                assert worker.poll() is None, 'Packaged worker stopped before cleanup acknowledgement'
            assert ledger['notes'][0]['state'] == 'deletion_requested'
        finally:
            worker.terminate()
            stdout, stderr = worker.communicate(timeout=15)
        assert not stdout + stderr, 'Packaged cleanup worker emitted unexpected output'
        assert json.loads((root / 'synthetic-deletes').read_text()) == {'targetTimestamp': receipt['timestamp']}
        assert ledger['notes'][0]['can_cleanup'] is False
        assert ledger['notes'][0]['attempts'] == 1
        assert ledger['note_counts']['deletion_requested'] == 1
        assert call('snapshot')['counts'] == {'sent': 1}
        print('Packaged receipt metadata and self-only targeted removal acknowledgement passed with fake Signal.')
        config = json.loads(config_path.read_text())
        config['phone_commands'] = {'enabled': True}
        config_path.write_text(json.dumps(config))
        fake.write_text('#!' + sys.executable + '''
import json,sys,time
from pathlib import Path
root=Path(sys.argv[sys.argv.index('--config')+1]).parent
for line in sys.stdin:
 r=json.loads(line); method=r['method']; result={}
 if method=='listAccounts': result=[{'number':'+15550000001'}]
 elif method=='subscribeReceive': result=0
 elif method=='send':
  params=r['params']
  assert set(params)=={'account','noteToSelf','message'}
  assert params['noteToSelf'] is True and params['account']=='+15550000001'
  assert 'helper is running and received your command' in params['message']
  assert not (root/'synthetic-command-reply').exists()
  (root/'synthetic-command-reply').touch()
  result={'timestamp':int(time.time()*1000),'results':[{'type':'SUCCESS'}]}
 print(json.dumps({'id':r['id'],'result':result}),flush=True)
 if method=='subscribeReceive':
  data={'destinationNumber':'+15550000001','timestamp':int(time.time()*1000),'message':'/decrumb status','expiresInSeconds':0,'viewOnce':False,'textStyles':[]}
  event={'method':'receive','params':{'account':'+15550000001','envelope':{'sourceNumber':'+15550000001','syncMessage':{'sentMessage':data}}}}
  print(json.dumps(event),flush=True); print(json.dumps(event),flush=True)
''')
        worker = subprocess.Popen(command + ['run'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ENV)
        try:
            deadline = time.monotonic() + 15
            while not (root / 'synthetic-command-reply').exists() and worker.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            assert (root / 'synthetic-command-reply').exists(), 'Packaged phone command did not reply'
            deadline = time.monotonic() + 10
            acknowledged = False
            while time.monotonic() < deadline:
                command_notes = call('notes-list')['notes']
                acknowledged = len(command_notes) == 2 and any(note['state'] == 'available' for note in command_notes)
                if acknowledged:
                    break
                time.sleep(0.05)
            assert acknowledged, 'Packaged phone command acknowledgement was not recorded'
        finally:
            worker.terminate()
            stdout, stderr = worker.communicate(timeout=15)
        assert not stdout + stderr, 'Packaged phone command emitted unexpected diagnostics'
        assert call('snapshot')['counts']['sent'] == 2
        print('Packaged optional phone command and duplicate suppression passed with fake Signal.')
    result = subprocess.run([str(helpers / 'signal-cli'), '--version'], capture_output=True, check=True, env=ENV, timeout=30)
    assert result.stdout.strip() == b'signal-cli 0.14.8'
    with tempfile.TemporaryDirectory(prefix='decrumb-native-smoke-') as directory:
        # Native-image libraries are loaded here, unlike --version. Explicit empty
        # config keeps the real linked account outside this packaging check.
        result = subprocess.run([str(helpers / 'signal-cli'), '--config', str(Path(directory) / 'empty-state'),
                                 '--output', 'json', 'listAccounts'], capture_output=True,
                                check=True, env=ENV, timeout=30)
        assert result.stdout.strip() == b'[]', 'Isolated native Signal check did not return an empty account list'
        assert not result.stderr, 'Isolated native Signal check emitted an unexpected diagnostic'
    print('Bundled native Signal CLI version and library loading verified with an isolated empty configuration.')


if __name__ == '__main__':
    main()
