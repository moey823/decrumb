#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Install the Raspberry Pi source release for the current user, preserving private state."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from urllib.request import urlopen

SOURCE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SOURCE))
import decrumb
from pi import PiService, initialize, operation, guard_runtime, UNIT

KIND = 'decrumb-pi-install-v1'
LAUNCHER_MARKER = '# Decrumb managed launcher'
MAX_DOWNLOAD = 150 * 1024 * 1024
MAX_BINARY = 250 * 1024 * 1024


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_manifest(source):
    try:
        manifest = json.loads((source / 'pi-manifest.json').read_text())
        if manifest['schema'] != 1 or not isinstance(manifest['files'], dict):
            raise ValueError()
        for name, checksum in manifest['files'].items():
            path = source / name
            if Path(name).is_absolute() or '..' in Path(name).parts or path.is_symlink() or not path.is_file():
                raise ValueError()
            if digest(path) != checksum:
                raise ValueError()
        required = {'decrumb.py', 'runtime_platform.py', 'cli_common.py', 'diagnostics.py', 'release.json', 'notes.py', 'pi.py', 'portable_cleaner.py', 'phone_commands.py',
                    'rules/defaults.json', 'linux/dependencies.json', 'tools/install_pi.py', 'LICENSE'}
        if not required <= manifest['files'].keys():
            raise ValueError()
        return manifest
    except (OSError, ValueError, KeyError, TypeError):
        raise decrumb.SafeError('Release files are missing or changed. Download and extract a fresh Pi release.') from None


def verify_binary(path):
    with path.open('rb') as stream:
        header = stream.read(20)
    if len(header) != 20 or header[:6] != b'\x7fELF\x02\x01' or header[18:20] != b'\xb7\x00':
        raise decrumb.SafeError('The Signal dependency is not a Linux ARM64 executable.')
    path.chmod(0o700)
    try:
        result = subprocess.run([str(path), '--version'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=45, check=True)
        if not result.stdout.decode('utf-8').strip().startswith('signal-cli 0.14.8'):
            raise ValueError()
    except (OSError, ValueError, subprocess.SubprocessError):
        raise decrumb.SafeError('The pinned Signal dependency cannot run. Check the Pi OS version and libstdc++6 package.') from None


def obtain_signal(source, destination, archive=None):
    dependency = json.loads((source / 'linux/dependencies.json').read_text())['signal_cli']
    with tempfile.TemporaryDirectory(prefix='decrumb-dependency-') as temporary:
        packed = Path(temporary) / 'signal-cli.gz'
        if archive:
            if archive.stat().st_size > MAX_DOWNLOAD:
                raise decrumb.SafeError('Dependency archive exceeds the size limit.')
            shutil.copyfile(archive, packed)
        else:
            try:
                with urlopen(dependency['url'], timeout=90) as response, packed.open('wb') as output:
                    size = 0
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > MAX_DOWNLOAD:
                            raise decrumb.SafeError('Dependency archive exceeds the size limit.')
                        output.write(chunk)
            except OSError:
                raise decrumb.SafeError('Could not download the pinned Signal dependency. No installation was changed.') from None
        if digest(packed) != dependency['sha256']:
            raise decrumb.SafeError('Signal dependency checksum mismatch. No installation was changed.')
        try:
            with gzip.open(packed, 'rb') as compressed, destination.open('wb') as output:
                size = 0
                while chunk := compressed.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_BINARY:
                        raise decrumb.SafeError('Signal dependency exceeds the size limit.')
                    output.write(chunk)
        except (OSError, EOFError):
            raise decrumb.SafeError('The Signal dependency archive is invalid.') from None
    verify_binary(destination)


def check_target(target):
    if target.is_symlink():
        raise decrumb.SafeError('The installation directory must not be a symbolic link.')
    if target.exists():
        try:
            marker = target / 'decrumb-install.json'
            if marker.is_symlink() or json.loads(marker.read_text()).get('kind') != KIND:
                raise ValueError()
        except (OSError, ValueError, AttributeError):
            raise decrumb.SafeError('The installation directory is not owned by Decrumb. Nothing was replaced.') from None


def check_launcher(launcher):
    if launcher.is_symlink():
        raise decrumb.SafeError('The command path is already a symbolic link. Nothing was replaced.')
    if launcher.exists():
        try:
            if not launcher.read_text().startswith('#!/usr/bin/python3\n' + LAUNCHER_MARKER + '\n'):
                raise ValueError()
        except (OSError, ValueError, UnicodeError):
            raise decrumb.SafeError('Another command uses the Decrumb command path. Nothing was replaced.') from None


def launcher_text(target):
    # Python literals avoid shell interpolation of spaces, quotes or metacharacters.
    return ('#!/usr/bin/python3\n' + LAUNCHER_MARKER + '\nimport os, sys\n'
            'os.execv("/usr/bin/python3", ["/usr/bin/python3", "-B", ' + repr(str(target / 'pi.py')) + '] + sys.argv[1:])\n')


def atomic_text(path, content, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.decrumb-tmp')
    if temporary.is_symlink():
        raise decrumb.SafeError('A temporary installation path is a symbolic link.')
    temporary.write_text(content)
    temporary.chmod(mode)
    temporary.replace(path)


def install(source, target, launcher, root, archive=None, service=None):
    guard_runtime(root, source, target)
    with operation(root):
        return install_locked(source, target, launcher, root, archive, service)


def install_locked(source, target, launcher, root, archive=None, service=None):
    manifest = read_manifest(source)
    check_target(target)
    check_launcher(launcher)
    service = service or PiService(root, target)
    service.check_owned()
    service.call('show-environment')
    if (root / 'config.json').exists():
        current = decrumb.load_config(root, validate_helper=False)
        if current['helper'] != str(target / 'portable_cleaner.py') or current['signal_cli'] != str(target / 'signal-cli'):
            raise decrumb.SafeError('The private runtime belongs to a different installation. Nothing was replaced.')
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.decrumb-stage-', dir=target.parent))
    backup = target.with_name('.decrumb-previous')
    if backup.exists() or backup.is_symlink():
        shutil.rmtree(stage)
        raise decrumb.SafeError('A previous installation backup needs attention. Nothing was replaced.')
    swapped = False
    service_stopped = False
    old_config = (root / 'config.json').read_bytes() if (root / 'config.json').exists() else None
    old_unit = service.path.read_bytes() if service.path.exists() else None
    old_launcher = launcher.read_bytes() if launcher.exists() else None
    was_running = service.loaded()
    try:
        for name in manifest['files']:
            destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, destination)
            destination.chmod(0o700 if name == 'portable_cleaner.py' else 0o600)
        shutil.copyfile(source / 'pi-manifest.json', stage / 'pi-manifest.json')
        (stage / 'decrumb-install.json').write_text(json.dumps({'kind': KIND, 'version': manifest['version']}))
        obtain_signal(source, stage / 'signal-cli', archive)
        # Validate the helper before any worker stop or installation replacement.
        decrumb.clean(stage / 'portable_cleaner.py', '', {'mode': 'all', 'baseURLs': []})
        service.stop()
        service_stopped = True
        if target.exists():
            target.rename(backup)
        stage.rename(target)
        swapped = True
        config = initialize(root, target)
        service.install()
        atomic_text(launcher, launcher_text(target), 0o700)
        if config.get('account') and not config.get('paused', False):
            service.start()
    except BaseException:
        if swapped:
            # Stop any new worker before replacing code or restoring configuration.
            try:
                service.stop()
            except decrumb.SafeError:
                raise decrumb.SafeError('Update could not be rolled back because the worker would not stop. Pause Decrumb before retrying.') from None
            shutil.rmtree(target)
            if backup.exists():
                backup.rename(target)
            if old_config is not None:
                atomic_text(root / 'config.json', old_config.decode('utf-8'))
            else:
                (root / 'config.json').unlink(missing_ok=True)
            if old_unit is not None:
                atomic_text(service.path, old_unit.decode('utf-8'))
            else:
                service.call('disable', UNIT, check=False)
                service.path.unlink(missing_ok=True)
            if old_launcher is not None:
                atomic_text(launcher, old_launcher.decode('utf-8'), 0o700)
            else:
                launcher.unlink(missing_ok=True)
            service.call('daemon-reload')
        elif backup.exists() and not target.exists():
            backup.rename(target)
        if service_stopped and was_running:
            service.start()
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    # A cleanup failure must never trigger rollback after the backup was removed.
    if backup.exists():
        shutil.rmtree(backup)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--signal-archive', type=Path, help='Use an already downloaded, checksum-verified dependency archive')
    args = parser.parse_args()
    os.umask(0o077)
    if sys.platform != 'linux' or platform.machine() not in ('aarch64', 'arm64') or os.getuid() == 0:
        raise decrumb.SafeError('Install as your normal user on 64-bit Raspberry Pi OS. Do not use sudo.')
    if sys.version_info < (3, 11):
        raise decrumb.SafeError('Python 3.11 or newer is required; use Raspberry Pi OS Bookworm or newer.')
    if not Path('/usr/bin/qrencode').is_file() or not Path('/usr/bin/systemctl').is_file():
        raise decrumb.SafeError('Install the OS dependencies first: sudo apt install python3 qrencode libstdc++6')
    target = Path.home() / '.local/lib/decrumb'
    launcher = Path.home() / '.local/bin/decrumb'
    root = decrumb.DEFAULT_ROOT.expanduser().resolve()
    install(SOURCE, target, launcher, root, args.signal_archive)
    print('Decrumb installed. Private state and existing pairing are preserved.')
    print('Run ~/.local/bin/decrumb pair, then scan its terminal QR with Signal on your phone.')
    print('To start at boot without an SSH login: sudo loginctl enable-linger "$USER"')
    print('Keep the Pi powered on and online. Pause with ~/.local/bin/decrumb pause.')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except decrumb.SafeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except Exception:
        print('Installation failed. No private diagnostic content was printed.', file=sys.stderr)
        sys.exit(1)
