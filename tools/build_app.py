#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Build a self-contained macOS app. Downloads only pinned public build inputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import venv

try:
    from tools import sparkle, release_version
except ModuleNotFoundError:
    import sparkle, release_version

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build'
APP = BUILD / 'Decrumb.app'
RELEASE = release_version.load()
VERSION = RELEASE['version']
SIGNAL_VERSION = '0.14.8'
SIGNAL_SHA = '3d77c18866fca4366128b2e716c5cffc63ae937af65172e197594d0802faddea'
SIGNAL_URL = 'https://ghcr.io/v2/homebrew/core/signal-cli/blobs/sha256:' + SIGNAL_SHA


class ReleaseError(Exception):
    """Fixed release diagnostics; never include credential or subprocess output."""


def add_release_arguments(parser):
    parser.add_argument('--production', action='store_true', help='Require distribution signing and complete release materials')
    parser.add_argument('--version', help='Release version, for example 1.0.0')
    parser.add_argument('--build-number', help='Positive, monotonically increasing release build number')
    parser.add_argument('--minimum-macos', help='Explicit tested minimum macOS version for a production build')
    parser.add_argument('--signing-identity', help='Existing Developer ID Application identity name or fingerprint; never a private key')
    parser.add_argument('--release-materials', type=Path, help='Validated corresponding-source/notice directory containing manifest.json')


def release_options(args):
    if args.production and any(not getattr(args, key, None) for key in
                               ('version', 'build_number', 'minimum_macos', 'release_materials')):
        raise ReleaseError('Production requires an explicit version, build number, tested minimum macOS, and release-material directory.')
    version = args.version or VERSION
    build_number = args.build_number or RELEASE['build']
    minimum = args.minimum_macos or platform.mac_ver()[0]
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ReleaseError('Version must have three numeric components.')
    if not re.fullmatch(r'[1-9][0-9]{0,8}', build_number):
        raise ReleaseError('Build number must be a positive integer of at most nine digits.')
    try:
        release_version.resolve(version, build_number)
    except ValueError as error:
        raise ReleaseError(str(error)) from None
    if not re.fullmatch(r'[0-9]+\.[0-9]+(?:\.[0-9]+)?', minimum):
        raise ReleaseError('Minimum macOS must be a numeric operating-system version.')
    identity = args.signing_identity or os.environ.get('DECRUMB_SIGNING_IDENTITY', '-')
    if args.production and identity == '-':
        raise ReleaseError('Production requires an existing Developer ID Application signing identity.')
    return {'production': args.production, 'version': version, 'build_number': build_number,
            'minimum_macos': minimum, 'identity': identity, 'materials': args.release_materials}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def material_tools():
    try:
        from tools import prepare_release_materials
    except ModuleNotFoundError:
        import prepare_release_materials
    return prepare_release_materials


def source_inventory_sha256(root):
    return material_tools().source_inventory_sha256(root)


def tooling_python_version():
    python = BUILD / 'tooling/bin/python3'
    if not python.exists():
        return platform.python_version()  # A new venv will use this interpreter.
    result = subprocess.run([str(python), '-I', '-c', 'import platform; print(platform.python_version())'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    version = result.stdout.strip()
    if result.returncode or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ReleaseError('The frozen worker tooling Python version could not be verified.')
    return version


def verify_frozen_materials(manifest):
    """Bind newly rebuilt native inputs to the complete source/notice packet."""
    try:
        lock = json.loads((ROOT / 'tools/release-dependencies.json').read_text())
        expected = {item['path']: item['sha256'] for item in manifest['files']}
        with tempfile.TemporaryDirectory(prefix='decrumb-frozen-check-') as folder:
            root = Path(folder)
            material_tools().frozen_inventory(BUILD / 'freeze-work/decrumb-worker/Analysis-00.toc', lock, root)
            for item in root.rglob('*'):
                if item.is_file() and expected.get(item.relative_to(root).as_posix()) != sha256(item):
                    raise ValueError()
    except (OSError, ValueError, TypeError, KeyError):
        raise ReleaseError('The rebuilt worker native inputs differ from the release materials. Regenerate and review the materials before production packaging.') from None


def validate_release_materials(folder, version, build_number, *, python_version=None, dependency_hash=None,
                               requirements_hash=None, source_hash=None):
    """A readiness attestation is necessary, but never substitutes for file checks."""
    try:
        folder = Path(folder).resolve(strict=True)
        manifest_path = folder / 'manifest.json'
        if manifest_path.is_symlink():
            raise ValueError()
        manifest = json.loads(manifest_path.read_text())
        if (type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1 or
                manifest.get('status') != 'ready' or manifest.get('blockers') != [] or
                manifest.get('version') != version or manifest.get('build') != build_number):
            raise ValueError()
        inputs = manifest.get('app_inputs', {})
        if (inputs.get('signal_cli_bottle_sha256') != SIGNAL_SHA or
                inputs.get('sparkle_distribution_sha256') != sparkle.SHA256 or
                inputs.get('python_version') != (python_version or tooling_python_version()) or
                inputs.get('requirements_build_sha256') != (requirements_hash or sha256(ROOT / 'tools/requirements-build.txt')) or
                inputs.get('decrumb_source_sha256') != (source_hash or source_inventory_sha256(ROOT)) or
                manifest.get('dependency_lock_sha256') != (dependency_hash or sha256(ROOT / 'tools/release-dependencies.json'))):
            raise ValueError()
        files = manifest.get('files')
        if not isinstance(files, list) or not files:
            raise ValueError()
        seen = set()
        for item in files:
            relative = item.get('path')
            if (not isinstance(relative, str) or not relative or Path(relative).is_absolute() or
                    '..' in Path(relative).parts or relative == 'manifest.json' or relative in seen or
                    not isinstance(item.get('role'), str) or not isinstance(item.get('component'), str) or
                    not isinstance(item.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', item['sha256'])):
                raise ValueError()
            candidate = folder / relative
            if candidate.is_symlink() or not candidate.resolve(strict=True).is_relative_to(folder) or not candidate.is_file():
                raise ValueError()
            if sha256(candidate) != item['sha256']:
                raise ValueError()
            seen.add(relative)
        return manifest
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise ReleaseError('Release materials are incomplete, mismatched, unsafe, or fail checksum verification. Production is blocked.') from None


def resolve_developer_identity(identity):
    """Read identity references only; never export certificates, keys or passwords."""
    if not isinstance(identity, str) or identity == '-':
        raise ReleaseError('A valid Developer ID Application identity is required.')
    result = subprocess.run(['/usr/bin/security', 'find-identity', '-v', '-p', 'codesigning'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode:
        raise ReleaseError('The signing identity list could not be read from Keychain.')
    for fingerprint, name in re.findall(r'\b([0-9A-Fa-f]{40})\s+"([^"]+)"', result.stdout):
        team = re.search(r'\(([A-Z0-9]{10})\)$', name)
        if ((identity == name or identity.upper() == fingerprint.upper()) and
                name.startswith('Developer ID Application: ') and team):
            return {'identity': fingerprint.upper(), 'team_id': team.group(1)}
    raise ReleaseError('The requested Developer ID Application identity is not available with a valid private key in Keychain.')


def sign_code(path, identity, production=False, *, entitlements=None):
    command = ['/usr/bin/codesign', '--force', '--sign', identity]
    if production:
        command += ['--options', 'runtime', '--timestamp']
    if entitlements is None:
        subprocess.run(command + [str(path)], check=True)
    else:
        with tempfile.TemporaryDirectory(prefix='decrumb-sign-') as folder:
            entitlement_file = Path(folder) / 'entitlements.plist'
            entitlement_file.write_bytes(plistlib.dumps(entitlements))
            subprocess.run(command + ['--entitlements', str(entitlement_file), str(path)], check=True)


def verify_distribution_signature(path, team_id, hardened=True, *, allow_library_validation_disable=False):
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(path)], check=True)
    result = subprocess.run(['/usr/bin/codesign', '--display', '--verbose=4', str(path)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    details = result.stdout + result.stderr
    if (result.returncode or 'Authority=Developer ID Application:' not in details or
            not re.search(r'^TeamIdentifier=' + re.escape(team_id) + r'$', details, re.MULTILINE) or
            not re.search(r'^Timestamp=.+', details, re.MULTILINE) or
            (hardened and not re.search(r'^CodeDirectory .*flags=.*\bruntime\b', details, re.MULTILINE))):
        raise ReleaseError('Distribution signature verification failed: Developer ID, team, timestamp, or hardened runtime is missing.')
    if hardened:
        entitlements = subprocess.run(['/usr/bin/codesign', '--display', '--entitlements', ':-', str(path)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        try:
            value = plistlib.loads(entitlements.stdout) if entitlements.stdout.strip() else {}
            if (entitlements.returncode or not isinstance(value, dict) or value.get('com.apple.security.get-task-allow') or
                    bool(value.get('com.apple.security.cs.disable-library-validation')) != allow_library_validation_disable):
                raise ValueError()
        except (ValueError, plistlib.InvalidFileException):
            raise ReleaseError('Distribution entitlements are invalid or permit debugging.') from None


def verify_native_helper(path):
    """Exercise JNI loading using an empty temporary configuration, without networking."""
    with tempfile.TemporaryDirectory(prefix='decrumb-native-check-') as folder:
        try:
            result = subprocess.run([str(path), '--config', folder, '--output', 'json', 'listAccounts'],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=45, check=False)
            if result.returncode or json.loads(result.stdout) != []:
                raise ValueError()
        except (OSError, ValueError, subprocess.TimeoutExpired):
            raise ReleaseError('The signed Signal helper failed its isolated native-library loading check.') from None


def verify_deployment_target(path, minimum):
    """Reject a declared OS older than a bundled executable's actual load command.

    This is a compatibility floor, not a substitute for testing on the target OS.
    """
    result = subprocess.run(['/usr/bin/xcrun', 'vtool', '-show-build', str(path)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    targets = re.findall(r'^\s*(?:minos|version)\s+([0-9]+(?:\.[0-9]+){1,2})\s*$', result.stdout, re.MULTILINE)
    # vtool also prints linker tool versions. Only consume minos, or the legacy
    # LC_VERSION_MIN_MACOSX version field when there is no LC_BUILD_VERSION.
    if 'LC_BUILD_VERSION' in result.stdout:
        targets = re.findall(r'^\s*minos\s+([0-9]+(?:\.[0-9]+){1,2})\s*$', result.stdout, re.MULTILINE)
    elif 'LC_VERSION_MIN_MACOSX' not in result.stdout:
        targets = []
    version = lambda value: tuple((list(map(int, value.split('.'))) + [0, 0])[:3])
    if result.returncode or not targets or any(version(value) > version(minimum) for value in targets):
        raise ReleaseError('The declared minimum macOS is lower than a bundled executable requires, or its deployment target cannot be verified.')


def copy_release_notices(folder, destination, manifest):
    destination.mkdir(parents=True)
    shutil.copy2(Path(folder) / 'manifest.json', destination / 'manifest.json')
    for item in manifest['files']:
        if item['role'] not in ('notice', 'license'):
            continue
        target = destination / item['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(folder) / item['path'], target)


def copy_public_source(root, destination):
    """Copy only the shared public inventory and verify the copied bytes."""
    destination.mkdir(parents=True)
    for item in material_tools().source_inventory(root):
        source = root / item['path']
        target = destination / item['path']
        if source.is_symlink():
            raise ReleaseError('A source file became a symlink during packaging.')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if sha256(target) != item['sha256']:
            raise ReleaseError('A source file changed during packaging.')


def copy_runtime_components(build, macos, helpers, resources):
    shutil.copy2(build / 'Decrumb', macos / 'Decrumb')
    shutil.copy2(build / 'url-cleaner', helpers / 'url-cleaner')
    # Helpers is a nested-code location: non-code rules belong in Resources.
    shutil.copy2(build / 'rules.json', resources / 'rules.json')
    shutil.copy2(build / 'frozen/decrumb-worker', helpers / 'decrumb-worker')


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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_release_arguments(parser)
    args = parser.parse_args(argv)
    options = release_options(args)
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise SystemExit('This release build currently supports Apple Silicon macOS only.')
    materials = signer = None
    if options['production']:
        materials = validate_release_materials(options['materials'], options['version'], options['build_number'])
        signer = resolve_developer_identity(options['identity'])
        options['identity'] = signer['identity']
    python = BUILD / 'tooling/bin/python3'
    if not python.exists():
        venv.create(BUILD / 'tooling', with_pip=True)
    subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check', '--no-cache-dir', '-r', str(ROOT / 'tools/requirements-build.txt')], check=True)
    python_version = tooling_python_version()
    if materials and materials['app_inputs']['python_version'] != python_version:
        raise ReleaseError('The actual tooling Python differs from the complete release materials.')
    identity = options['identity']
    subprocess.run([str(python), '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
                    '--name', 'decrumb-worker', '--distpath', str(BUILD / 'frozen'),
                    '--workpath', str(BUILD / 'freeze-work'), '--specpath', str(BUILD),
                    '--target-architecture', 'arm64', '--codesign-identity', identity,
                    str(ROOT / 'desktop.py')], check=True, env={**os.environ, 'PYINSTALLER_CONFIG_DIR': str(BUILD / 'pyinstaller-cache')})
    if materials:
        verify_frozen_materials(materials)
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
    copy_runtime_components(BUILD, macos, helpers, resources)
    sparkle_root = sparkle.distribution()
    framework = sparkle.copy_framework(sparkle_root, APP)
    shutil.copy2(sparkle_root / 'LICENSE', resources / 'Sparkle-LICENSE.txt')
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
    copy_public_source(ROOT, source_dir)
    shutil.copy2(ROOT / 'LICENSE', resources / 'LICENSE.txt')
    shutil.copy2(BUILD / 'AppIcon.icns', resources / 'AppIcon.icns')
    shutil.copy2(ROOT / 'docs/THIRD-PARTY.md', resources / 'THIRD-PARTY.txt')
    if materials:
        copy_release_notices(options['materials'], resources / 'ReleaseMaterials', materials)
    # Python's redistributable license is part of its installed standard library.
    import sysconfig
    for candidate in (Path(sys.base_prefix) / 'LICENSE.txt', Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt'):
        if candidate.is_file():
            shutil.copy2(candidate, resources / 'Python-LICENSE.txt')
            break
    # The minimum is deliberately the build host version until cross-version QA is done.
    minimum = options['minimum_macos']
    info = {'CFBundleIdentifier': 'com.matthew.decrumb.desktop', 'CFBundleName': 'Decrumb',
            'CFBundleDisplayName': 'Decrumb', 'CFBundleExecutable': 'Decrumb',
            'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': options['version'],
            'CFBundleVersion': options['build_number'], 'LSMinimumSystemVersion': minimum, 'LSUIElement': True,
            'NSHighResolutionCapable': True, 'CFBundleIconFile': 'AppIcon',
            'NSHumanReadableCopyright': 'Decrumb contributors. AGPL-3.0-only. See bundled licenses.'}
    info.update(sparkle.configuration())
    with (contents / 'Info.plist').open('wb') as output:
        plistlib.dump(info, output)
    manifest = {'app_version': options['version'], 'build_number': options['build_number'],
                'signal_cli_version': SIGNAL_VERSION, 'signal_cli_sha256': SIGNAL_SHA,
                'signal_cli_package': 'arm64_sonoma', 'python_version': python_version,
                'architecture': 'arm64', 'minimum_macos': minimum,
                'sparkle_version': sparkle.VERSION, 'sparkle_sha256': sparkle.SHA256,
                'signing': 'Developer ID' if signer else ('ad-hoc' if identity == '-' else 'custom development'),
                'distribution': 'production-candidate' if signer else 'development', 'notarized': False,
                'dependency_lock_sha256': sha256(ROOT / 'tools/release-dependencies.json'),
                'requirements_build_sha256': sha256(ROOT / 'tools/requirements-build.txt')}
    if signer:
        if source_inventory_sha256(source_dir) != materials['app_inputs']['decrumb_source_sha256']:
            raise ReleaseError('Source files changed during the release build. Regenerate release materials and rebuild.')
        manifest.update({'team_id': signer['team_id'], 'signing_identity_sha1': signer['identity'],
                         'decrumb_source_sha256': source_inventory_sha256(source_dir),
                         'release_materials_manifest_sha256': sha256(Path(options['materials']) / 'manifest.json')})
    (resources / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for executable in (helpers / 'signal-cli', helpers / 'url-cleaner', helpers / 'decrumb-worker'):
        # GraalVM extracts JNI dylibs at runtime. Signing its outer executable cannot
        # sign those embedded libraries; only this helper needs the library exception.
        entitlements = ({'com.apple.security.cs.disable-library-validation': True}
                        if options['production'] and executable.name == 'signal-cli' else None)
        sign_code(executable, identity, options['production'], entitlements=entitlements)
    for nested in sparkle.nested_code(framework):
        sign_code(nested, identity, options['production'])
        if options['production']:
            verify_distribution_signature(nested, signer['team_id'])
    if options['production']:
        sign_code(APP, identity, True)
        for executable in (APP, helpers / 'signal-cli', helpers / 'url-cleaner', helpers / 'decrumb-worker'):
            verify_distribution_signature(executable, signer['team_id'],
                                          allow_library_validation_disable=executable.name == 'signal-cli')
        for executable in (macos / 'Decrumb', helpers / 'signal-cli', helpers / 'url-cleaner', helpers / 'decrumb-worker'):
            verify_deployment_target(executable, minimum)
        verify_native_helper(helpers / 'signal-cli')
    else:
        subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', identity, str(APP)], check=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(APP)], check=True)
    print(APP)


if __name__ == '__main__':
    try:
        main()
    except ReleaseError as error:
        raise SystemExit(str(error)) from None
