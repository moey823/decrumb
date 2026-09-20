# SPDX-License-Identifier: AGPL-3.0-only
"""Offline release gates: never access Keychain, Apple, or a user's runtime."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import build_app as builder
from tools import package_dmg as packager

FINGERPRINT = 'A' * 40
TEAM = 'SYNTHETIC1'
SIGNER = {'identity': FINGERPRINT, 'team_id': TEAM}
SUBMISSION = {'id': '11111111-2222-3333-4444-555555555555', 'status': 'Accepted'}


class ReleaseFixture(unittest.TestCase):
    def setUp(self):
        digest = patch.object(builder, 'source_inventory_sha256', return_value='d' * 64)
        digest.start()
        self.addCleanup(digest.stop)
        python = patch.object(builder, 'tooling_python_version', return_value=builder.platform.python_version())
        python.start()
        self.addCleanup(python.stop)
        self.directory = tempfile.TemporaryDirectory(prefix='decrumb-release-test-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.materials = self.root / 'materials'
        self.materials.mkdir()
        (self.materials / 'NOTICE').write_text('Synthetic notice\n')
        (self.materials / 'source.tar').write_bytes(b'synthetic source')
        self.material_manifest = {
            'schema_version': 1, 'version': '1.0.0', 'build': '1', 'status': 'ready', 'blockers': [],
            'dependency_lock_sha256': builder.sha256(builder.ROOT / 'tools/release-dependencies.json'),
            'app_inputs': {'signal_cli_bottle_sha256': builder.SIGNAL_SHA,
                           'python_version': builder.platform.python_version(),
                           'requirements_build_sha256': builder.sha256(builder.ROOT / 'tools/requirements-build.txt'),
                           'decrumb_source_sha256': 'd' * 64},
            'files': [{'path': name, 'role': role, 'component': 'synthetic',
                       'sha256': builder.sha256(self.materials / name)}
                      for name, role in (('NOTICE', 'notice'), ('source.tar', 'source'))]}
        self.save_materials()
        self.app = self.root / 'Decrumb.app'
        self.resources = self.app / 'Contents/Resources'
        source = self.resources / 'Source/tools'
        source.mkdir(parents=True)
        shutil.copy2(builder.ROOT / 'tools/requirements-build.txt', source / 'requirements-build.txt')
        shutil.copy2(builder.ROOT / 'tools/release-dependencies.json', source / 'release-dependencies.json')
        for name in builder.material_tools().SOURCE_FILES:
            (self.resources / 'Source' / name).write_text('# synthetic source\n')
        self.info = {'CFBundleIdentifier': 'com.matthew.decrumb.desktop', 'CFBundleShortVersionString': '1.0.0',
                     'CFBundleVersion': '1', 'LSMinimumSystemVersion': '26.4'}
        with (self.app / 'Contents/Info.plist').open('wb') as output:
            plistlib.dump(self.info, output)
        self.build_manifest = {
            'app_version': '1.0.0', 'build_number': '1', 'architecture': 'arm64', 'minimum_macos': '26.4',
            'distribution': 'production-candidate', 'signing': 'Developer ID', 'notarized': False,
            'team_id': TEAM, 'signing_identity_sha1': FINGERPRINT,
            'python_version': builder.platform.python_version(),
            'dependency_lock_sha256': self.material_manifest['dependency_lock_sha256'],
            'requirements_build_sha256': self.material_manifest['app_inputs']['requirements_build_sha256'],
            'decrumb_source_sha256': 'd' * 64,
            'release_materials_manifest_sha256': builder.sha256(self.materials / 'manifest.json')}
        self.save_app()
        builder.copy_release_notices(self.materials, self.resources / 'ReleaseMaterials', self.material_manifest)
        self.output = self.root / 'release'
        self.output.mkdir()

    def save_materials(self):
        (self.materials / 'manifest.json').write_text(json.dumps(self.material_manifest))

    def save_app(self):
        (self.resources / 'build-manifest.json').write_text(json.dumps(self.build_manifest))

    def preflight(self, **kwargs):
        values = {'materials_dir': self.materials, 'identity': FINGERPRINT, 'profile': 'synthetic-profile'}
        values.update(kwargs)
        return packager.production_preflight(self.app, self.info, self.build_manifest, **values)


class ReleaseInputTests(ReleaseFixture):
    def options(self, *arguments):
        parser = argparse.ArgumentParser()
        builder.add_release_arguments(parser)
        return parser.parse_args(arguments)

    def test_default_development_remains_ad_hoc(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(builder.platform, 'mac_ver', return_value=('27.0', (), '')):
            result = builder.release_options(self.options())
        self.assertFalse(result['production'])
        self.assertEqual((result['version'], result['build_number'], result['identity']), ('0.1.0', '1', '-'))

    def test_production_requires_explicit_version_build_os_and_materials(self):
        for flag in ('--version', '--build-number', '--minimum-macos', '--release-materials'):
            values = {'--version': '1.0.0', '--build-number': '1', '--minimum-macos': '26.4',
                      '--release-materials': str(self.materials), '--signing-identity': FINGERPRINT}
            values.pop(flag)
            args = ['--production'] + [value for pair in values.items() for value in pair]
            with self.subTest(flag=flag), self.assertRaises(builder.ReleaseError):
                builder.release_options(self.options(*args))

    def test_production_rejects_ad_hoc_identity_and_invalid_version_build(self):
        base = ['--production', '--minimum-macos', '26.4', '--release-materials', str(self.materials)]
        for version, number, identity in (('1.0', '1', FINGERPRINT), ('1.0.0', '0', FINGERPRINT),
                                           ('1.0.0', '-1', FINGERPRINT), ('1.0.0', '1', '-')):
            with self.subTest(version=version, build=number, identity=identity), self.assertRaises(builder.ReleaseError):
                builder.release_options(self.options(*base, '--version', version, '--build-number', number,
                                                     '--signing-identity', identity))

    def test_materials_must_be_complete_current_and_match_checksums(self):
        cases = [('status', 'blocked'), ('blockers', [{'id': 'missing', 'detail': 'Synthetic'}]),
                 ('version', '0.9.0'), ('build', '2'), ('schema_version', True), ('files', [])]
        for field, value in cases:
            original = self.material_manifest[field]
            self.material_manifest[field] = value
            self.save_materials()
            with self.subTest(field=field), self.assertRaises(builder.ReleaseError):
                builder.validate_release_materials(self.materials, '1.0.0', '1')
            self.material_manifest[field] = original
        self.save_materials()
        (self.materials / 'NOTICE').write_text('Changed after manifest')
        with self.assertRaises(builder.ReleaseError):
            builder.validate_release_materials(self.materials, '1.0.0', '1')

    def test_missing_materials_fails_before_identity_or_upload(self):
        with patch.object(builder, 'resolve_developer_identity') as identity, patch.object(packager, 'notarize') as notarize:
            with self.assertRaises(builder.ReleaseError):
                self.preflight(materials_dir=None)
        identity.assert_not_called()
        notarize.assert_not_called()

    def test_materials_must_match_exact_current_source_and_toolchain(self):
        for field in ('decrumb_source_sha256', 'requirements_build_sha256', 'signal_cli_bottle_sha256', 'python_version'):
            original = self.material_manifest['app_inputs'][field]
            self.material_manifest['app_inputs'][field] = 'stale'
            self.save_materials()
            with self.subTest(field=field), self.assertRaises(builder.ReleaseError):
                builder.validate_release_materials(self.materials, '1.0.0', '1')
            self.material_manifest['app_inputs'][field] = original

    def test_source_paths_cannot_escape_materials(self):
        for unsafe in ('../NOTICE', '/tmp/NOTICE'):
            self.material_manifest['files'][0]['path'] = unsafe
            self.save_materials()
            with self.subTest(path=unsafe), self.assertRaises(builder.ReleaseError):
                builder.validate_release_materials(self.materials, '1.0.0', '1')
        self.material_manifest['files'][0]['path'] = 'linked'
        (self.materials / 'linked').symlink_to(self.materials / 'NOTICE')
        self.save_materials()
        with self.assertRaises(builder.ReleaseError):
            builder.validate_release_materials(self.materials, '1.0.0', '1')

    def test_only_notices_are_bundled_with_app(self):
        bundled = self.resources / 'ReleaseMaterials'
        self.assertTrue((bundled / 'NOTICE').is_file())
        self.assertTrue((bundled / 'manifest.json').is_file())
        self.assertFalse((bundled / 'source.tar').exists())

    def test_notary_profile_required_before_keychain_access(self):
        with patch.object(builder, 'resolve_developer_identity') as identity:
            with self.assertRaises(builder.ReleaseError):
                self.preflight(profile=None)
        identity.assert_not_called()

    def test_unnotarized_development_app_cannot_be_promoted(self):
        self.build_manifest.update(distribution='development', signing='ad-hoc')
        with patch.object(builder, 'resolve_developer_identity') as identity:
            with self.assertRaises(builder.ReleaseError):
                self.preflight()
        identity.assert_not_called()

    def test_packaging_identity_must_match_build(self):
        with patch.object(builder, 'resolve_developer_identity', return_value={'identity': 'B' * 40, 'team_id': TEAM}), \
                patch.object(packager, 'verify_app') as verify:
            with self.assertRaises(builder.ReleaseError):
                self.preflight()
        verify.assert_not_called()

    def test_altered_bundled_notice_is_rejected(self):
        (self.resources / 'ReleaseMaterials/NOTICE').write_text('Altered notice')
        with patch.object(builder, 'resolve_developer_identity') as identity:
            with self.assertRaises(builder.ReleaseError):
                self.preflight()
        identity.assert_not_called()

    def test_production_build_numbers_are_monotonic_and_versions_do_not_regress(self):
        receipt = {'distribution': 'production', 'notarized': True, 'build_number': '5', 'version': '1.2.0'}
        (self.output / 'Decrumb-1.2.0-5-arm64-release.json').write_text(json.dumps(receipt))
        for version, number in (('1.3.0', '5'), ('1.3.0', '4'), ('1.1.0', '6')):
            with self.subTest(version=version, number=number), self.assertRaises(builder.ReleaseError):
                packager.check_release_number(self.output, version, number)
        packager.check_release_number(self.output, '1.2.0', '6')
        packager.check_release_number(self.output, '1.3.0', '7')


class SignatureTests(unittest.TestCase):
    def test_actual_tooling_python_is_used_even_when_caller_differs(self):
        with tempfile.TemporaryDirectory() as folder:
            build = Path(folder)
            python = build / 'tooling/bin/python3'
            python.parent.mkdir(parents=True)
            python.touch()
            with patch.object(builder, 'BUILD', build), \
                    patch.object(builder.platform, 'python_version', return_value='3.99.0'), \
                    patch.object(builder.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '3.14.6\n', '')):
                self.assertEqual(builder.tooling_python_version(), '3.14.6')

    def test_new_frozen_inventory_must_match_prepared_materials(self):
        def inventory(toc, lock, output):
            target = output / 'inventories/frozen-worker-native.json'
            target.parent.mkdir()
            target.write_text('new library inventory')
        with patch.object(builder.material_tools(), 'frozen_inventory', side_effect=inventory):
            with self.assertRaises(builder.ReleaseError):
                builder.verify_frozen_materials({'files': [{'path': 'inventories/frozen-worker-native.json', 'sha256': '0' * 64}]})
    def test_only_valid_developer_id_application_identity_is_accepted(self):
        names = ('Apple Development: Synthetic (SYNTHETIC1)', 'Apple Distribution: Synthetic (SYNTHETIC1)',
                 'Developer ID Installer: Synthetic (SYNTHETIC1)', 'Developer ID Application: Synthetic (SYNTHETIC1)')
        for name in names:
            result = subprocess.CompletedProcess([], 0, f'  1) {FINGERPRINT} "{name}"\n', '')
            with self.subTest(identity=name), patch.object(builder.subprocess, 'run', return_value=result):
                if name.startswith('Developer ID Application:'):
                    self.assertEqual(builder.resolve_developer_identity(FINGERPRINT), SIGNER)
                else:
                    with self.assertRaises(builder.ReleaseError):
                        builder.resolve_developer_identity(FINGERPRINT)

    def test_production_signing_adds_hardened_runtime_and_secure_timestamp(self):
        with patch.object(builder.subprocess, 'run') as run:
            builder.sign_code(Path('/synthetic/helper'), FINGERPRINT, production=True)
        command = run.call_args.args[0]
        self.assertIn('--timestamp', command)
        self.assertEqual(command[command.index('--options') + 1], 'runtime')

    def test_distribution_signature_requires_team_timestamp_hardening_and_no_debugging(self):
        valid = ('Authority=Developer ID Application: Synthetic (SYNTHETIC1)\nTeamIdentifier=SYNTHETIC1\n'
                 'Timestamp=Sep 20, 2026 at 12:00:00 PM\nCodeDirectory v=20500 size=1 flags=0x10000(runtime)\n')
        for details, debug in ((valid.replace('Timestamp=', 'Signed Time='), False),
                               (valid.replace('runtime', 'adhoc'), False),
                               (valid.replace('TeamIdentifier=SYNTHETIC1', 'TeamIdentifier=WRONGTEAM1'), False),
                               (valid, True), (valid, False)):
            responses = [subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 0, '', details),
                         subprocess.CompletedProcess([], 0, plistlib.dumps({'com.apple.security.get-task-allow': debug}), b'')]
            with self.subTest(details=details, debug=debug), patch.object(builder.subprocess, 'run', side_effect=responses):
                if details == valid and not debug:
                    builder.verify_distribution_signature(Path('/synthetic/app'), TEAM)
                else:
                    with self.assertRaises(builder.ReleaseError):
                        builder.verify_distribution_signature(Path('/synthetic/app'), TEAM)

    def test_minimum_macos_cannot_understate_executable_target(self):
        output = 'cmd LC_BUILD_VERSION\n platform MACOS\n minos 27.0\n sdk 27.0\n version 2703.1\n'
        with patch.object(builder.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, '')):
            with self.assertRaises(builder.ReleaseError):
                builder.verify_deployment_target(Path('/synthetic/helper'), '26.4')
            builder.verify_deployment_target(Path('/synthetic/helper'), '27.0')

    def test_library_validation_exception_is_confined_to_signal_helper(self):
        details = ('Authority=Developer ID Application: Synthetic (SYNTHETIC1)\nTeamIdentifier=SYNTHETIC1\n'
                   'Timestamp=synthetic\nCodeDirectory v=20500 size=1 flags=0x10000(runtime)\n')
        for allowed in (False, True):
            responses = [subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 0, '', details),
                         subprocess.CompletedProcess([], 0, plistlib.dumps({'com.apple.security.cs.disable-library-validation': True}), b'')]
            with patch.object(builder.subprocess, 'run', side_effect=responses):
                if allowed:
                    builder.verify_distribution_signature(Path('/synthetic/signal-cli'), TEAM,
                                                          allow_library_validation_disable=True)
                else:
                    with self.assertRaises(builder.ReleaseError):
                        builder.verify_distribution_signature(Path('/synthetic/gui'), TEAM)

    def test_native_probe_uses_empty_temporary_config_and_requires_success(self):
        def success(command, **kwargs):
            config = Path(command[command.index('--config') + 1])
            self.assertEqual(list(config.iterdir()), [])
            self.assertEqual(command[-3:], ['--output', 'json', 'listAccounts'])
            return subprocess.CompletedProcess([], 0, '[]', '')
        with patch.object(builder.subprocess, 'run', side_effect=success):
            builder.verify_native_helper(Path('/synthetic/signal-cli'))
        with patch.object(builder.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'JNI failure')):
                with self.assertRaises(builder.ReleaseError):
                    builder.verify_native_helper(Path('/synthetic/signal-cli'))


class BundleLayoutTests(unittest.TestCase):
    def test_rules_are_resources_and_helpers_contain_only_executables(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            build = root / 'build'
            (build / 'frozen').mkdir(parents=True)
            for name in ('Decrumb', 'url-cleaner', 'rules.json', 'frozen/decrumb-worker'):
                (build / name).write_text('synthetic ' + name)
            macos, helpers, resources = (root / 'Decrumb.app/Contents' / name for name in ('MacOS', 'Helpers', 'Resources'))
            for path in (macos, helpers, resources):
                path.mkdir(parents=True)
            builder.copy_runtime_components(build, macos, helpers, resources)
            self.assertEqual((resources / 'rules.json').read_text(), 'synthetic rules.json')
            self.assertEqual({path.name for path in helpers.iterdir()}, {'url-cleaner', 'decrumb-worker'})

    def test_source_copy_uses_public_inventory_and_verifies_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'checkout'
            root.mkdir()
            materials = builder.material_tools()
            for name in materials.SOURCE_FILES:
                (root / name).write_text('synthetic public source')
            (root / '.git').mkdir()
            (root / 'tools').mkdir()
            for name in ('public.py', '.env', 'ignored-secret.txt', 'local.pem', 'config.json'):
                (root / 'tools' / name).write_text('synthetic ' + name)
            public = set(materials.SOURCE_FILES) | {'tools/public.py', 'tools/.env', 'tools/local.pem', 'tools/config.json'}
            git_files = ('\0'.join(sorted(public)) + '\0').encode()
            copied = Path(folder) / 'Source'
            with patch.object(materials.subprocess, 'check_output', return_value=git_files):
                builder.copy_public_source(root, copied)
                expected = materials.source_inventory_sha256(root)
            self.assertEqual(materials.source_inventory_sha256(copied), expected)
            self.assertEqual({path.relative_to(copied).as_posix() for path in copied.rglob('*') if path.is_file()},
                             set(materials.SOURCE_FILES) | {'tools/public.py'})
            with patch.object(materials, 'source_inventory', return_value=[{'path': 'tools/public.py', 'sha256': '0' * 64}]):
                with self.assertRaises(builder.ReleaseError):
                    builder.copy_public_source(root, Path(folder) / 'changed-Source')


class NotarizationTests(unittest.TestCase):
    def test_only_keychain_profile_authentication_is_used(self):
        result = subprocess.CompletedProcess([], 0, json.dumps(SUBMISSION), '')
        with patch.object(packager.subprocess, 'run', return_value=result) as run:
            self.assertEqual(packager.notarize(Path('/synthetic/app.zip'), 'synthetic-profile'), SUBMISSION)
        command = run.call_args.args[0]
        self.assertIn('--keychain-profile', command)
        self.assertIn('--wait', command)
        for forbidden in ('--password', '--apple-id', '--key', '--issuer'):
            self.assertNotIn(forbidden, command)

    def test_non_accepted_and_malformed_results_never_release(self):
        for value, returncode in (({**SUBMISSION, 'status': 'Invalid'}, 0),
                                  ({**SUBMISSION, 'status': 'In Progress'}, 0),
                                  ({'status': 'Accepted'}, 0), (SUBMISSION, 1), ([], 0)):
            result = subprocess.CompletedProcess([], returncode, json.dumps(value), 'Private diagnostic')
            with self.subTest(result=value), patch.object(packager.subprocess, 'run', return_value=result):
                with self.assertRaises(builder.ReleaseError) as error:
                    packager.notarize(Path('/synthetic/app.zip'), 'synthetic-profile')
                self.assertNotIn('Private diagnostic', str(error.exception))

    def test_timeout_fails_closed(self):
        with patch.object(packager.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['tool'], 1)):
            with self.assertRaises(builder.ReleaseError):
                packager.notarize(Path('/synthetic/app.zip'), 'synthetic-profile')


class PackagingSequenceTests(ReleaseFixture):
    def simulate(self, *, fail_dmg=False, production=True):
        self.events = []

        def command(*arguments):
            self.events.append(arguments)
            if arguments[0] == '/usr/bin/ditto':
                if '-c' in arguments:
                    Path(arguments[-1]).write_bytes(b'zip for notary')
                else:
                    shutil.copytree(arguments[1], arguments[2])
            if arguments[:2] == ('/usr/bin/hdiutil', 'create'):
                Path(arguments[-1]).write_bytes(b'synthetic disk image')

        def notarize(path, profile):
            self.events.append(('notarize', str(path)))
            if fail_dmg and path.suffix == '.dmg':
                raise builder.ReleaseError('Synthetic notarization failure')
            return SUBMISSION

        def staple(path):
            self.events.append(('staple', str(path)))
            if path.suffix == '.dmg':
                with path.open('ab') as output:
                    output.write(b' stapled ticket')

        with patch.object(packager, 'run', side_effect=command), \
                patch.object(builder, 'resolve_developer_identity', return_value=SIGNER), \
                patch.object(packager, 'verify_app'), \
                patch.object(builder, 'verify_native_helper'), \
                patch.object(builder, 'verify_distribution_signature'), \
                patch.object(packager, 'notarize', side_effect=notarize), \
                patch.object(packager, 'staple', side_effect=staple):
            return packager.package(self.app, self.output, production=production, identity=FINGERPRINT,
                                    profile='synthetic-profile', materials_dir=self.materials)

    def test_release_orders_notarization_and_emits_complete_matching_assets(self):
        original = (self.resources / 'build-manifest.json').read_bytes()
        output = self.simulate()
        self.assertEqual(output.name, 'Decrumb-1.0.0-1-arm64.dmg')
        receipt = json.loads((self.output / 'Decrumb-1.0.0-1-arm64-release.json').read_text())
        self.assertTrue(receipt['notarized'])
        for record in receipt['assets']:
            self.assertEqual(record['sha256'], builder.sha256(self.output / record['file']))
            self.assertEqual((self.output / (record['file'] + '.sha256')).read_text(),
                             f"{record['sha256']}  {record['file']}\n")
        source_zip = self.output / 'Decrumb-1.0.0-1-arm64-sources.zip'
        with zipfile.ZipFile(source_zip) as archive:
            self.assertIn('materials/source.tar', archive.namelist())
            self.assertIn('materials/NOTICE', archive.namelist())
            self.assertIn('decrumb/decrumb.py', archive.namelist())
        self.assertEqual((self.resources / 'build-manifest.json').read_bytes(), original)
        app_notary, dmg_notary = [i for i, event in enumerate(self.events) if event[0] == 'notarize']
        create = next(i for i, event in enumerate(self.events) if event[:2] == ('/usr/bin/hdiutil', 'create'))
        self.assertLess(app_notary, create)
        self.assertLess(create, dmg_notary)
        self.assertTrue(output.read_bytes().endswith(b'stapled ticket'))
        self.assertFalse(list(self.output.glob('dmg-*')))

    def test_failed_notarization_leaves_no_production_outputs(self):
        with self.assertRaises(builder.ReleaseError):
            self.simulate(fail_dmg=True)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_corresponding_source_archive_excludes_private_files(self):
        source = self.resources / 'Source/tools'
        for name in ('.env', 'local.pem', 'config.json'):
            (source / name).write_text('synthetic private placeholder')
        self.simulate()
        with zipfile.ZipFile(self.output / 'Decrumb-1.0.0-1-arm64-sources.zip') as archive:
            names = set(archive.namelist())
        self.assertIn('decrumb/decrumb.py', names)
        for name in ('.env', 'local.pem', 'config.json'):
            self.assertNotIn('decrumb/tools/' + name, names)

    def test_development_build_preserves_dev_filename_and_does_not_notarize(self):
        output = self.simulate(production=False)
        self.assertEqual(output.name, 'Decrumb-1.0.0-arm64-dev.dmg')
        self.assertFalse(any(event[0] == 'notarize' for event in self.events))
        self.assertFalse(list(self.output.glob('*-release.json')))

    def test_existing_release_cannot_be_overwritten(self):
        existing = self.output / 'Decrumb-1.0.0-1-arm64.dmg'
        existing.write_bytes(b'previous release')
        with self.assertRaises(builder.ReleaseError):
            self.simulate()
        self.assertEqual(existing.read_bytes(), b'previous release')

    def test_output_created_during_atomic_publication_is_never_overwritten(self):
        staging = self.root / 'staging'
        staging.mkdir()
        (staging / 'release.dmg').write_bytes(b'new candidate')

        def conflict(source, destination):
            destination.write_bytes(b'concurrent release')
            raise FileExistsError()

        with patch.object(packager.os, 'link', side_effect=conflict):
            with self.assertRaises(builder.ReleaseError):
                packager.publish_production(staging, self.output, ['release.dmg'], '1.0.0', '1')
        self.assertEqual((self.output / 'release.dmg').read_bytes(), b'concurrent release')

    def test_concurrent_release_finalization_fails_without_waiting(self):
        with (self.output / '.decrumb-release.lock').open('a') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(builder.ReleaseError):
                packager.publish_production(self.root, self.output, [], '1.0.0', '1')


if __name__ == '__main__':
    unittest.main()
