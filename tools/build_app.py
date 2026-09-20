#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Build a self-contained macOS app. Downloads only pinned public build inputs."""
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import venv

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build'
APP = BUILD / 'Decrumb.app'
VERSION = '0.1.0'
SIGNAL_VERSION = '0.14.8'
SIGNAL_SHA = '3d77c18866fca4366128b2e716c5cffc63ae937af65172e197594d0802faddea'
SIGNAL_URL = 'https://ghcr.io/v2/homebrew/core/signal-cli/blobs/sha256:' + SIGNAL_SHA


def fetch(url, path, checksum, headers=None):
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == checksum:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers=headers or {})
    temporary = path.with_suffix('.partial')
    try:
        with urllib.request.urlopen(request, timeout=90) as response, temporary.open('wb') as output:
            shutil.copyfileobj(response, output)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != checksum:
            raise RuntimeError('A downloaded build dependency failed its checksum check.')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise SystemExit('This release build currently supports Apple Silicon macOS only.')
    python = BUILD / 'tooling/bin/python3'
    if not python.exists():
        venv.create(BUILD / 'tooling', with_pip=True)
    subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check', '--no-cache-dir', '-r', str(ROOT / 'tools/requirements-build.txt')], check=True)
    identity = os.environ.get('DECRUMB_SIGNING_IDENTITY', os.environ.get('SIDELET_SIGNING_IDENTITY', '-'))
    subprocess.run([str(python), '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
                    '--name', 'sidelet-worker', '--distpath', str(BUILD / 'frozen'),
                    '--workpath', str(BUILD / 'freeze-work'), '--specpath', str(BUILD),
                    '--target-architecture', 'arm64', '--codesign-identity', identity,
                    str(ROOT / 'desktop.py')], check=True, env={**os.environ, 'PYINSTALLER_CONFIG_DIR': str(BUILD / 'pyinstaller-cache')})
    bottle = BUILD / 'downloads' / 'signal-cli-0.14.8-arm64-sonoma.tar.gz'
    if not bottle.exists() or hashlib.sha256(bottle.read_bytes()).hexdigest() != SIGNAL_SHA:
        with urllib.request.urlopen('https://ghcr.io/token?service=ghcr.io&scope=repository:homebrew/core/signal-cli:pull', timeout=30) as response:
            token = json.load(response)['token']
        fetch(SIGNAL_URL, bottle, SIGNAL_SHA, {'Authorization': 'Bearer ' + token})
    if APP.exists():
        shutil.rmtree(APP)
    contents = APP / 'Contents'
    macos, helpers, resources = (contents / name for name in ('MacOS', 'Helpers', 'Resources'))
    for directory in (macos, helpers, resources):
        directory.mkdir(parents=True)
    shutil.copy2(BUILD / 'Decrumb', macos / 'Decrumb')
    shutil.copy2(BUILD / 'url-cleaner', helpers / 'url-cleaner')
    shutil.copy2(BUILD / 'rules.json', helpers / 'rules.json')
    shutil.copy2(BUILD / 'frozen/sidelet-worker', helpers / 'sidelet-worker')
    with tarfile.open(bottle) as archive:
        # Select only known files; never extract arbitrary archive paths.
        member = archive.getmember('signal-cli/0.14.8/bin/signal-cli')
        with archive.extractfile(member) as source, (helpers / 'signal-cli').open('wb') as output:
            shutil.copyfileobj(source, output)
        for member in archive.getmembers():
            if Path(member.name).name in ('LICENSE', 'COPYING', 'AUTHORS') and member.isfile():
                with archive.extractfile(member) as source:
                    (resources / ('signal-cli-' + Path(member.name).name + '.txt')).write_bytes(source.read())
    (helpers / 'signal-cli').chmod(0o755)
    # Include our complete source snapshot, omitting every generated/private path.
    source_dir = resources / 'Source'
    source_dir.mkdir()
    for name in ('sidelet.py', 'notes.py', 'desktop.py', 'service.py', 'build.py', 'README.md', 'CONTRIBUTING.md', 'SECURITY.md', 'LICENSE'):
        shutil.copy2(ROOT / name, source_dir / name)
    for name in ('app', 'swift', 'rules', 'tools', 'tests', 'docs', 'branding'):
        shutil.copytree(ROOT / name, source_dir / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(ROOT / 'LICENSE', resources / 'LICENSE.txt')
    shutil.copy2(BUILD / 'AppIcon.icns', resources / 'AppIcon.icns')
    shutil.copy2(ROOT / 'docs/THIRD-PARTY.md', resources / 'THIRD-PARTY.txt')
    # Python's redistributable license is part of its installed standard library.
    import sysconfig
    for candidate in (Path(sys.base_prefix) / 'LICENSE.txt', Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt'):
        if candidate.is_file():
            shutil.copy2(candidate, resources / 'Python-LICENSE.txt')
            break
    # The minimum is deliberately the build host version until cross-version QA is done.
    minimum = platform.mac_ver()[0]
    # Keep the bundle identifier and internal helper name stable across the public rename.
    info = {'CFBundleIdentifier': 'com.matthew.sidelet.desktop', 'CFBundleName': 'Decrumb',
            'CFBundleDisplayName': 'Decrumb', 'CFBundleExecutable': 'Decrumb',
            'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': VERSION,
            'CFBundleVersion': '1', 'LSMinimumSystemVersion': minimum, 'LSUIElement': True,
            'NSHighResolutionCapable': True, 'CFBundleIconFile': 'AppIcon',
            'NSHumanReadableCopyright': 'Sidelet and Decrumb contributors. AGPL-3.0-only. See bundled licenses.'}
    with (contents / 'Info.plist').open('wb') as output:
        plistlib.dump(info, output)
    manifest = {'app_version': VERSION, 'signal_cli_version': SIGNAL_VERSION, 'signal_cli_sha256': SIGNAL_SHA,
                'signal_cli_package': 'arm64_sonoma', 'python_version': platform.python_version(),
                'architecture': 'arm64', 'minimum_macos': minimum, 'signing': 'ad-hoc' if identity == '-' else 'Developer ID'}
    (resources / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for executable in (helpers / 'signal-cli', helpers / 'url-cleaner', helpers / 'sidelet-worker'):
        subprocess.run(['/usr/bin/codesign', '--force', '--sign', identity, str(executable)], check=True)
    subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', identity, str(APP)], check=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(APP)], check=True)
    print(APP)


if __name__ == '__main__':
    main()
