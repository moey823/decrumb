#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Package a development DMG, or explicitly sign and notarize a production release.

Production authenticates only through an existing notarytool Keychain profile.
Nothing is published; production outputs appear only after every release gate passes.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import tempfile
import zipfile

try:
    from tools import build_app
except ModuleNotFoundError:  # Direct invocation from tools/.
    import build_app

ROOT = Path(__file__).resolve().parents[1]
ReleaseError = build_app.ReleaseError


def run(*arguments):
    subprocess.run(arguments, check=True)


def load_app(app):
    try:
        with (app / 'Contents/Info.plist').open('rb') as source:
            info = plistlib.load(source)
        manifest = json.loads((app / 'Contents/Resources/build-manifest.json').read_text())
        version, architecture = info['CFBundleShortVersionString'], manifest['architecture']
        if (not re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,2}', version) or architecture != 'arm64' or
                app.name != 'Decrumb.app' or info['CFBundleIdentifier'] != 'com.matthew.decrumb.desktop'):
            raise ValueError()
        return info, manifest
    except (OSError, ValueError, TypeError, KeyError, plistlib.InvalidFileException):
        raise ReleaseError('The app is missing or its version, architecture, name, or bundle metadata is invalid.') from None


def production_preflight(app, info, manifest, materials_dir, identity, profile):
    """No signing, upload, or staging occurs until all local release inputs agree."""
    if not isinstance(profile, str) or not profile.strip():
        raise ReleaseError('Production requires an existing notarytool Keychain profile via --notary-profile.')
    version, build_number = info['CFBundleShortVersionString'], info.get('CFBundleVersion')
    minimum = info.get('LSMinimumSystemVersion', '')
    if (not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version) or
            not isinstance(build_number, str) or not re.fullmatch(r'[1-9][0-9]{0,8}', build_number) or
            not isinstance(minimum, str) or not re.fullmatch(r'[0-9]+\.[0-9]+(?:\.[0-9]+)?', minimum) or
            manifest.get('distribution') != 'production-candidate' or manifest.get('signing') != 'Developer ID' or
            manifest.get('notarized') is not False or manifest.get('app_version') != version or
            manifest.get('build_number') != build_number or manifest.get('minimum_macos') != minimum or
            not isinstance(manifest.get('python_version'), str) or
            manifest.get('dependency_lock_sha256') != build_app.sha256(app / 'Contents/Resources/Source/tools/release-dependencies.json') or
            manifest.get('requirements_build_sha256') != build_app.sha256(app / 'Contents/Resources/Source/tools/requirements-build.txt') or
            manifest.get('decrumb_source_sha256') != build_app.source_inventory_sha256(app / 'Contents/Resources/Source')):
        raise ReleaseError('Production requires a matching signed production-candidate build; development or edited metadata is rejected.')
    materials = build_app.validate_release_materials(materials_dir, version, build_number,
                                                    python_version=manifest['python_version'],
                                                    dependency_hash=manifest['dependency_lock_sha256'],
                                                    requirements_hash=manifest['requirements_build_sha256'],
                                                    source_hash=manifest['decrumb_source_sha256'])
    digest = build_app.sha256(Path(materials_dir) / 'manifest.json')
    bundled = app / 'Contents/Resources/ReleaseMaterials'
    if (manifest.get('release_materials_manifest_sha256') != digest or
            build_app.sha256(bundled / 'manifest.json') != digest):
        raise ReleaseError('The app and corresponding-source materials were built from different release manifests.')
    for item in materials['files']:
        if item['role'] in ('notice', 'license') and build_app.sha256(bundled / item['path']) != item['sha256']:
            raise ReleaseError('A bundled release notice does not match the complete release materials.')
    signer = build_app.resolve_developer_identity(identity)
    if manifest.get('team_id') != signer['team_id'] or manifest.get('signing_identity_sha1') != signer['identity']:
        raise ReleaseError('The packaging identity must match the production candidate signing identity and team.')
    verify_app(app, signer)
    return materials, signer


def verify_app(app, signer):
    for executable in (app, *(app / 'Contents/Helpers' / name for name in
                              ('signal-cli', 'url-cleaner', 'decrumb-worker'))):
        build_app.verify_distribution_signature(executable, signer['team_id'],
                                              allow_library_validation_disable=executable.name == 'signal-cli')
    with (app / 'Contents/Info.plist').open('rb') as source:
        minimum = plistlib.load(source)['LSMinimumSystemVersion']
    for executable in (app / 'Contents/MacOS/Decrumb', *(app / 'Contents/Helpers' / name for name in
                          ('signal-cli', 'url-cleaner', 'decrumb-worker'))):
        build_app.verify_deployment_target(executable, minimum)


def notarize(path, profile):
    # Capture tool output: an authentication failure must not echo account details.
    # --wait waits for a terminal result; timeout and every non-Accepted status fail closed.
    try:
        result = subprocess.run(['/usr/bin/xcrun', 'notarytool', 'submit', str(path),
                                 '--keychain-profile', profile, '--wait', '--timeout', '20m',
                                 '--output-format', 'json'], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, timeout=1260, check=False)
        receipt = json.loads(result.stdout)
        submission = receipt.get('id')
        if (result.returncode or receipt.get('status') != 'Accepted' or not isinstance(submission, str) or
                not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', submission)):
            raise ValueError()
        return {'id': submission, 'status': 'Accepted'}
    except (subprocess.TimeoutExpired, OSError, ValueError, TypeError, AttributeError):
        raise ReleaseError('Apple notarization was not confirmed Accepted. No production artifact was released; inspect the submission using your existing Keychain profile.') from None


def staple(path):
    run('/usr/bin/xcrun', 'stapler', 'staple', str(path))
    run('/usr/bin/xcrun', 'stapler', 'validate', str(path))


def corresponding_source(app, materials_dir, manifest, output):
    """Include only checked materials and the exact source already sealed in the app."""
    current = build_app.validate_release_materials(materials_dir, manifest['version'], manifest['build'],
                                                   python_version=manifest['app_inputs']['python_version'],
                                                   dependency_hash=manifest['dependency_lock_sha256'],
                                                   requirements_hash=manifest['app_inputs']['requirements_build_sha256'],
                                                   source_hash=manifest['app_inputs']['decrumb_source_sha256'])
    bundled_manifest = app / 'Contents/Resources/ReleaseMaterials/manifest.json'
    if current != manifest or build_app.sha256(Path(materials_dir) / 'manifest.json') != build_app.sha256(bundled_manifest):
        raise ReleaseError('Release materials changed during packaging.')
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        archive.write(Path(materials_dir) / 'manifest.json', 'materials/manifest.json')
        for item in manifest['files']:
            source = Path(materials_dir) / item['path']
            # Recheck immediately before archiving, after potentially long notarization.
            if build_app.sha256(source) != item['sha256']:
                raise ReleaseError('Release materials changed during packaging.')
            archive.write(source, 'materials/' + item['path'])
        source_root = app / 'Contents/Resources/Source'
        for item in build_app.material_tools().source_inventory(source_root):
            source = source_root / item['path']
            if source.is_symlink():
                raise ReleaseError('Bundled corresponding source contains an unexpected symlink.')
            if build_app.sha256(source) != item['sha256']:
                raise ReleaseError('Bundled corresponding source changed during packaging.')
            archive.write(source, 'decrumb/' + item['path'])


def asset(path):
    return {'file': path.name, 'sha256': build_app.sha256(path), 'bytes': path.stat().st_size}


def check_release_number(output_dir, version, build_number):
    """Do not reuse or move backwards from any locally recorded production release.

    A publisher must retain prior receipts here; this cannot see remote releases.
    """
    for previous in output_dir.glob('Decrumb-*-release.json'):
        try:
            receipt = json.loads(previous.read_text())
            if receipt.get('distribution') != 'production' or receipt.get('notarized') is not True:
                raise ValueError()
            old_build = int(receipt['build_number'])
            old_version = tuple(int(part) for part in receipt['version'].split('.'))
            if old_build >= int(build_number) or old_version > tuple(int(part) for part in version.split('.')):
                raise ReleaseError('Production version/build must advance beyond retained release receipts; build numbers may never be reused.')
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise ReleaseError('An existing production release receipt is invalid; restore it before packaging another release.') from None


def readme(info, production):
    heading = ('DECRUMB\n\nDeveloper ID signed and notarized macOS release.\n' if production else
               'DECRUMB — DEVELOPMENT BUILD\n\nThis is a local test build, not a notarized public release.\n')
    return (heading + f"Requires Apple Silicon and macOS {info['LSMinimumSystemVersion']} or later.\n\n"
            'Copy Decrumb to Applications before opening it, then eject this disk image.\n'
            'For a manual upgrade: pause the existing cleaner, quit its interface, replace\n'
            'the application, open the replacement and resume if desired.\n'
            'Your linked account and settings remain in Application Support.\n\n'
            'In-app updating is not integrated yet. Source and third-party notices are\n'
            'included in the app; the complete corresponding-source archive accompanies\n'
            'production releases. https://github.com/moey823/decrumb\n')


def publish_production(temporary, output_dir, names, version, build_number):
    """Serialize the final release transaction; never replace any existing asset."""
    # Keep this empty lock file in place: unlinking a lock permits different
    # processes to lock different inodes under the same filename.
    with (output_dir / '.decrumb-release.lock').open('a') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ReleaseError('Another production release is being finalized in this output directory.') from None
        check_release_number(output_dir, version, build_number)
        if any((output_dir / name).exists() for name in names):
            raise ReleaseError('A production output appeared during packaging; existing artifacts were preserved.')
        for name in names:
            try:
                # Stage and destination are on the same filesystem. Hard-link
                # creation is atomic and fails on an existing destination.
                os.link(temporary / name, output_dir / name)
            except FileExistsError:
                raise ReleaseError('A production output appeared during finalization; existing artifacts were preserved. No completed release receipt was written.') from None


def package(app, output_dir, *, production=False, identity=None, profile=None, materials_dir=None):
    app = app.resolve()
    info, manifest = load_app(app)
    version, architecture = info['CFBundleShortVersionString'], manifest['architecture']
    materials = signer = None
    output_dir.mkdir(parents=True, exist_ok=True)
    if production:
        materials, signer = production_preflight(app, info, manifest, materials_dir, identity, profile)
        build_number = info['CFBundleVersion']
        check_release_number(output_dir, version, build_number)
        stem = f'Decrumb-{version}-{build_number}-{architecture}'
        final_names = [stem + suffix for suffix in ('.dmg', '.dmg.sha256', '-sources.zip', '-sources.zip.sha256', '-release.json')]
        if any((output_dir / name).exists() for name in final_names):
            raise ReleaseError('A production output already exists; release artifacts are immutable. Choose a new build number.')
    else:
        run('/usr/bin/codesign', '--verify', '--deep', '--strict', str(app))
        stem = f'Decrumb-{version}-{architecture}-dev'
    with tempfile.TemporaryDirectory(prefix='dmg-', dir=output_dir) as folder:
        temporary = Path(folder)
        stage = temporary / 'contents'
        stage.mkdir()
        staged_app = stage / app.name
        run('/usr/bin/ditto', str(app), str(staged_app))
        (stage / 'Applications').symlink_to('/Applications', target_is_directory=True)
        (stage / 'Read me first.txt').write_text(readme(info, production), encoding='utf-8')
        app_receipt = None
        if production:
            app_zip = temporary / 'Decrumb-notarization.zip'
            run('/usr/bin/ditto', '-c', '-k', '--keepParent', str(staged_app), str(app_zip))
            app_receipt = notarize(app_zip, profile)
            staple(staged_app)
            verify_app(staged_app, signer)
            build_app.verify_native_helper(staged_app / 'Contents/Helpers/signal-cli')
            run('/usr/sbin/spctl', '--assess', '--type', 'execute', '--verbose=2', str(staged_app))
        image = temporary / (stem + '.dmg')
        run('/usr/bin/hdiutil', 'create', '-volname', 'Decrumb', '-fs', 'APFS',
            '-format', 'ULFO', '-srcfolder', str(stage), str(image))
        run('/usr/bin/hdiutil', 'verify', str(image))
        if production:
            run('/usr/bin/codesign', '--force', '--sign', signer['identity'], '--timestamp', str(image))
            build_app.verify_distribution_signature(image, signer['team_id'], hardened=False)
            dmg_receipt = notarize(image, profile)
            staple(image)
            run('/usr/bin/hdiutil', 'verify', str(image))
            build_app.verify_distribution_signature(image, signer['team_id'], hardened=False)
            run('/usr/sbin/spctl', '--assess', '--type', 'open', '--context', 'context:primary-signature',
                '--verbose=2', str(image))
            sources = temporary / (stem + '-sources.zip')
            corresponding_source(staged_app, materials_dir, materials, sources)
            records = [asset(image), asset(sources)]
            receipt = {'schema_version': 1, 'distribution': 'production', 'notarized': True,
                       'version': version, 'build_number': build_number, 'architecture': architecture,
                       'minimum_macos': info['LSMinimumSystemVersion'], 'team_id': signer['team_id'],
                       'release_materials_manifest_sha256': manifest['release_materials_manifest_sha256'],
                       'notarization': {'app': app_receipt, 'dmg': dmg_receipt}, 'assets': records}
            for record in records:
                (temporary / (record['file'] + '.sha256')).write_text(f"{record['sha256']}  {record['file']}\n")
            (temporary / (stem + '-release.json')).write_text(json.dumps(receipt, indent=2) + '\n')
            # All gates complete. Publish the receipt last so it is the completion marker.
            publish_production(temporary, output_dir, final_names, version, build_number)
        else:
            image.replace(output_dir / image.name)
            output = output_dir / image.name
            output.with_suffix('.dmg.sha256').write_text(f'{build_app.sha256(output)}  {output.name}\n')
    return output_dir / (stem + '.dmg')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, default=ROOT / 'build/Decrumb.app')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'build')
    parser.add_argument('--production', action='store_true', help='Require complete source materials, notarize app and DMG, and verify Gatekeeper')
    parser.add_argument('--signing-identity', help='Existing Developer ID Application name or fingerprint')
    parser.add_argument('--notary-profile', help='Existing notarytool Keychain profile name; never an account password or private key')
    parser.add_argument('--release-materials', type=Path, help='Complete corresponding-source materials matching the app build')
    args = parser.parse_args(argv)
    identity = args.signing_identity or os.environ.get('DECRUMB_SIGNING_IDENTITY', '-')
    profile = args.notary_profile or os.environ.get('DECRUMB_NOTARY_PROFILE')
    output = package(args.app, args.output_dir, production=args.production, identity=identity,
                     profile=profile, materials_dir=args.release_materials)
    print(f'{output}\n{output.stat().st_size / 1_000_000:.2f} MB; SHA-256 checksum file written.')
    if args.production:
        print('Signed, notarized, stapled and verified. Publish the DMG, source ZIP, checksums and release receipt together.')


if __name__ == '__main__':
    try:
        main()
    except (ReleaseError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error) if isinstance(error, ReleaseError) else 'Packaging failed. No completed release receipt was written.') from None
