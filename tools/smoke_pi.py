#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Smoke a Pi release using temporary state, real native dependencies, and synthetic Signal only."""
import argparse
import contextlib
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tarfile
import tempfile


class SmokeError(Exception):
    """Fixed, content-free smoke diagnostics."""


PHASE = 'preflight'


def stage(label):
    global PHASE
    PHASE = label
    print('Pi smoke: ' + label + '.', flush=True)


def require(value, message):
    if not value:
        raise SmokeError(message)


def run(command, *, data=None, timeout=45, action='Subprocess', allowed_returncodes=(0,)):
    try:
        result = subprocess.run(command, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=timeout, env={**os.environ, 'PATH': '/usr/bin:/bin'})
    except (OSError, subprocess.SubprocessError):
        raise SmokeError(action + ' could not run or timed out.') from None
    require(result.returncode in allowed_returncodes, action + ' failed.')
    return result.stdout


def extract(archive, destination):
    """Accept the release packager's single-directory, regular-file-only format."""
    total = 0
    prefix = None
    names = set()
    with tarfile.open(archive, 'r:gz') as bundle:
        entries = bundle.getmembers()
        require(0 < len(entries) <= 4096, 'Release archive has an invalid file count.')
        for entry in entries:
            parts = Path(entry.name).parts
            require(entry.isfile() and not Path(entry.name).is_absolute() and len(parts) >= 2
                    and '..' not in parts and entry.name not in names,
                    'Release archive contains an unsafe member.')
            names.add(entry.name)
            if prefix is None:
                prefix = parts[0]
            require(parts[0] == prefix, 'Release archive has multiple roots.')
            total += entry.size
            require(entry.size >= 0 and total <= 64 * 1024 * 1024, 'Release archive exceeds the smoke limit.')
            target = destination / entry.name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with bundle.extractfile(entry) as source, target.open('xb') as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
            target.chmod(0o700 if entry.mode & 0o111 else 0o600)
    source = destination / prefix
    require((source / 'pi-manifest.json').is_file(), 'Release archive has no source manifest.')
    return source


def tree_digest(folder):
    result = {}
    for path in sorted(folder.rglob('*')):
        if path.is_file():
            with path.open('rb') as stream:
                result[path.relative_to(folder).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


class FakeService:
    """Exercises installer transitions without creating any real user service."""
    def __init__(self, root, app, path, pi):
        self.root, self.app, self.path, self.pi = root, app, path, pi
        self.running = False
        self.stops = 0

    def check_owned(self):
        if self.path.exists():
            require(self.path.read_text() == self.pi.unit_text(self.root, self.app),
                    'The temporary unit changed unexpectedly.')

    def call(self, *args, **kwargs):
        return True

    def loaded(self):
        return self.running

    def stop(self, disable=False):
        self.stops += 1
        self.running = False

    def install(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.write_text(self.pi.unit_text(self.root, self.app))
        self.path.chmod(0o600)

    def start(self):
        self.running = True


def systemd_guard():
    # The real service test owns the production unit name. Keep it confined to an
    # explicitly opted-in disposable CI runner and never replace an existing unit.
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('RUNNER_OS') == 'Linux'
            and os.environ.get('RUNNER_ARCH') == 'ARM64',
            'The systemd smoke option is restricted to a disposable GitHub ARM64 Linux runner.')
    require(os.getuid() != 0, 'Run the smoke test as the disposable runner user, without sudo.')
    path = Path.home() / '.config/systemd/user/decrumb.service'
    require(not path.exists() and not path.is_symlink(), 'A Decrumb user unit already exists; systemd smoke refused.')
    # systemctl show returns 1 for a missing unit on some systemd versions, even
    # though its exact LoadState is available. Accept that specific missing-unit
    # result; an inaccessible user bus has no LoadState and must still fail.
    state = run(['/usr/bin/systemctl', '--user', 'show', 'decrumb.service', '--property=LoadState', '--value'],
                action='Systemd ownership probe', allowed_returncodes=(0, 1)).strip()
    require(bool(state), 'Systemd ownership probe could not reach the user service manager.')
    require(state == b'not-found', 'A Decrumb user unit is already known; systemd smoke refused.')


def workspace(real_systemd=False):
    # PrivateTmp=true intentionally hides the host's /tmp from the real worker.
    # Only an explicitly checked disposable runner may stage fixtures in HOME,
    # where the service can read them. TemporaryDirectory still owns all cleanup.
    if real_systemd:
        systemd_guard()
    return tempfile.TemporaryDirectory(prefix='decrumb-pi-smoke-', dir=Path.home() if real_systemd else None)


def systemd_smoke(root, target, launcher, decrumb, pi):
    global PHASE
    stage('systemd ownership check')
    systemd_guard()
    fake = root / 'synthetic-signal'
    fake.write_text(r'''#!/usr/bin/python3
import json,re,sys,time
from pathlib import Path
root=Path(__file__).parent
for line in sys.stdin:
 request=json.loads(line); method=request['method']; result={}
 if method=='listAccounts': result=[{'number':'+15550000001'}]
 elif method=='subscribeReceive': result=0
 elif method=='send':
  params=request['params']
  assert set(params)=={'account','noteToSelf','message'}
  assert params['account']=='+15550000001' and params['noteToSelf'] is True
  assert re.fullmatch(r'Decrumb\nhttps://example.com/\?id=smoke\n#decrumb_[0-9a-f]{24}',params['message'])
  assert not (root/'synthetic-send').exists()
  (root/'synthetic-send').write_text('acknowledged')
  result={'timestamp':int(time.time()*1000),'results':[{'type':'SUCCESS'}]}
 else: raise RuntimeError('Unexpected synthetic RPC operation')
 print(json.dumps({'id':request['id'],'result':result}),flush=True)
 if method=='subscribeReceive' and not (root/'synthetic-event').exists():
  (root/'synthetic-event').touch()
  timestamp=int(time.time()*1000)
  data={'timestamp':timestamp,'message':'https://example.com/?utm_source=synthetic&id=smoke','expiresInSeconds':0,'viewOnce':False,'textStyles':[]}
  event={'method':'receive','params':{'account':'+15550000001','envelope':{'sourceUuid':'synthetic-peer','dataMessage':data}}}
  print(json.dumps(event),flush=True)
  print(json.dumps(event),flush=True)
''')
    fake.chmod(0o700)
    config = decrumb.load_config(root)
    config.update(account='+15550000001', signal_cli=str(fake), paused=True)
    with contextlib.closing(decrumb.Store(root / 'outbox.sqlite3')) as store:
        store.clear_pending()
    decrumb.write_json(root / 'config.json', config)
    service = pi.PiService(root, target)
    require(service.path == Path.home() / '.config/systemd/user/decrumb.service', 'Unexpected systemd unit path.')
    try:
        stage('systemd unit installation')
        service.install()
        stage('systemd initial startup')
        run([str(launcher), '--root', str(root), 'resume'], timeout=50, action='Systemd initial resume')
        status = decrumb.read_status(root, decrumb.load_config(root))
        require(status['state'] == 'running' and service.loaded(), 'Systemd worker did not report a fresh running heartbeat.')
        stage('systemd synthetic delivery')
        import time
        deadline = time.monotonic() + 12
        acknowledged = False
        while time.monotonic() < deadline:
            # Never construct a worker Store while the service owns its database:
            # that constructor recovers interrupted sends. Observe read-only.
            with contextlib.closing(sqlite3.connect((root / 'outbox.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
                acknowledged = db.execute("SELECT count(*) FROM outbox WHERE state='sent'").fetchone()[0] == 1
            if acknowledged:
                break
            time.sleep(0.1)
        require(acknowledged and (root / 'synthetic-send').exists(), 'Systemd synthetic Note to Self delivery failed.')
        stage('systemd pause')
        run([str(launcher), '--root', str(root), 'pause'], action='Systemd pause')
        require(not service.loaded() and decrumb.load_config(root)['paused'], 'Systemd pause did not stop and persist.')
        requested_at = decrumb.now_ms()
        stage('systemd restart after pause')
        run([str(launcher), '--root', str(root), 'resume'], timeout=50, action='Systemd resume after pause')
        status = decrumb.read_status(root, decrumb.load_config(root))
        require(status['state'] == 'running' and status['updated_at'] >= requested_at and service.loaded(),
                'Systemd resume did not produce a fresh running heartbeat.')
    finally:
        failed_phase = PHASE if sys.exc_info()[0] is not None else None
        stage('systemd owned-unit cleanup')
        # Ownership is checked again by stop; a changed/foreign unit is untouched.
        if service.path.exists():
            service.stop(disable=True)
            service.check_owned()
            service.path.unlink()
            service.call('daemon-reload')
            service.call('reset-failed', pi.UNIT, check=False)
        require(not service.loaded() and not service.path.exists(), 'The temporary systemd worker was not cleaned up.')
        if failed_phase is not None:
            PHASE = failed_phase


def smoke(archive, signal_archive, *, real_systemd=False):
    require(sys.platform == 'linux' and platform.machine() in ('aarch64', 'arm64'),
            'Run this release smoke on Linux ARM64 with the real native dependency.')
    require(os.getuid() != 0, 'Run this release smoke as a normal user, without sudo.')
    require(Path('/usr/bin/qrencode').is_file(), 'Install qrencode before running the Pi smoke.')
    os.umask(0o077)
    with workspace(real_systemd) as folder:
        base = Path(folder)
        stage('archive extraction')
        source = extract(archive, base / 'extracted')
        # Test the source delivered inside the archive, not the checkout's modules.
        require(not any(name in sys.modules for name in ('decrumb', 'pi', 'tools.install_pi')),
                'Run the Pi smoke in its own fresh Python process.')
        sys.path.insert(0, str(source))
        import decrumb
        import pi
        from tools import install_pi
        require(Path(install_pi.__file__).resolve() == source / 'tools/install_pi.py', 'Smoke imported the wrong installer.')
        target, launcher, root = base / 'lib/decrumb', base / 'bin/decrumb', base / 'private $literal %value'
        service = FakeService(root, target, base / 'units/decrumb.service', pi)
        stage('fresh installation and native dependency')
        install_pi.install(source, target, launcher, root, signal_archive, service=service)
        config = decrumb.load_config(root)
        require(config['account'] is None and not service.running, 'An unlinked installation unexpectedly started.')
        require(config['phone_commands'] == {'enabled': False}, 'Phone commands did not default off.')
        require(root.stat().st_mode & 0o777 == 0o700 and (root / 'config.json').stat().st_mode & 0o777 == 0o600,
                'Private runtime permissions are incorrect.')
        sample = b'https://example.com/?utm_source=synthetic&id=smoke'
        stage('installed local preview')
        preview = json.loads(run([str(launcher), '--root', str(root), 'preview'], data=sample, action='Installed local preview'))
        require(preview['urls'] == ['https://example.com/?id=smoke'], 'Installed portable preview changed a functional value.')
        qr = root / 'synthetic-pairing.png'
        stage('private QR generation')
        run([str(target / 'portable_cleaner.py'), '--qr', str(qr)], data=b'sgnl://linkdevice?uuid=synthetic&pub_key=synthetic',
            action='Private QR generation')
        require(qr.read_bytes().startswith(b'\x89PNG\r\n\x1a\n') and qr.stat().st_mode & 0o777 == 0o600,
                'Installed portable QR generation or permissions failed.')
        qr.unlink()
        empty = base / 'empty-native-account'
        empty.mkdir(mode=0o700)
        stage('isolated native account listing')
        accounts = run([str(target / 'signal-cli'), '--config', str(empty), '--scrub-log', '--disable-send-log',
                        '--output', 'json', 'listAccounts'], action='Isolated native account listing')
        require(json.loads(accounts) == [], 'The isolated native account list was not empty.')
        # Preserve only synthetic account/state fixtures through an actual reinstall.
        config.update(account='+15550000001', paused=True, phone_commands={'enabled': True})
        config['settings']['excludedURLs'] = ['https://example.org']
        config['notes']['include_sender'] = False
        decrumb.write_json(root / 'config.json', config)
        (root / 'signal-cli/synthetic-state').write_text('synthetic-private-state')
        with contextlib.closing(decrumb.Store(root / 'outbox.sqlite3')) as store:
            store.enqueue('synthetic-pending', decrumb.now_ms(), ['https://example.com/?id=smoke'])
        before = tree_digest(root)
        stage('reinstall state preservation')
        install_pi.install(source, target, launcher, root, signal_archive, service=service)
        require(decrumb.load_config(root) == config and tree_digest(root) == before,
                'Reinstall changed private state or preferences.')
        require(not service.running, 'Reinstall resumed a paused synthetic account.')
        old_target, old_launcher, old_unit = tree_digest(target), launcher.read_bytes(), service.path.read_bytes()
        stopped = service.stops
        bad = base / 'bad-dependency.gz'
        bad.write_bytes(gzip.compress(b'synthetic-not-a-dependency'))
        stage('corrupt dependency rejection')
        try:
            install_pi.install(source, target, launcher, root, bad, service=service)
        except decrumb.SafeError as error:
            require(str(error) == 'Signal dependency checksum mismatch. No installation was changed.',
                    'Corrupt dependency failed at an unexpected boundary.')
        else:
            raise SmokeError('A corrupt dependency archive was accepted.')
        require(service.stops == stopped and tree_digest(target) == old_target and tree_digest(root) == before
                and launcher.read_bytes() == old_launcher and service.path.read_bytes() == old_unit,
                'Dependency rejection mutated the installation or stopped its service.')
        print('Pi archive install, native dependency, local preview, private QR, state preservation and checksum rejection passed.', flush=True)
        if real_systemd:
            systemd_smoke(root, target, launcher, decrumb, pi)
            print('Real systemd startup, fresh heartbeat, synthetic delivery, pause, resume and owned-unit cleanup passed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--signal-archive', type=Path, required=True)
    parser.add_argument('--systemd', action='store_true', help='Exercise the real user service on a disposable GitHub ARM64 runner')
    args = parser.parse_args()
    try:
        smoke(args.archive.resolve(strict=True), args.signal_archive.resolve(strict=True), real_systemd=args.systemd)
    except SmokeError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print('Pi release smoke failed during ' + PHASE + '. No private diagnostic content was printed.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
