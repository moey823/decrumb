# SPDX-License-Identifier: AGPL-3.0-only
"""Prevent public platform packages from drifting onto separate versions."""
import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import build_app, package_pi, release_version


class SharedReleaseTests(unittest.TestCase):
    def test_checked_in_store_and_mac_defaults_match_shared_release(self):
        release_version.umbrel()
        release = release_version.load()
        parser = argparse.ArgumentParser()
        build_app.add_release_arguments(parser)
        with patch.object(build_app.platform, 'mac_ver', return_value=('26.4', (), '')):
            options = build_app.release_options(parser.parse_args([]))
        self.assertEqual((options['version'], options['build_number']), (release['version'], release['build']))

    def test_explicit_platform_overrides_cannot_create_another_version(self):
        parser = argparse.ArgumentParser()
        build_app.add_release_arguments(parser)
        release = release_version.load()
        for version, build in [('99.0.0', release['build']), (release['version'], str(int(release['build']) + 1))]:
            with self.subTest(version=version, build=build):
                with self.assertRaises(build_app.ReleaseError):
                    build_app.release_options(parser.parse_args(['--version', version, '--build-number', build]))
                with tempfile.TemporaryDirectory() as output:
                    with self.assertRaises(ValueError):
                        package_pi.package(release_version.ROOT, Path(output), version, build)
                    self.assertFalse(list(Path(output).glob('*.tar.gz')))

    def test_future_release_updates_store_and_preserves_other_manifest_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'release.json').write_text(json.dumps({'version': '1.1.0', 'build': 9, 'channel': 'rc'}))
            directory = root / 'mkships-decrumb'
            directory.mkdir()
            manifest = directory / 'umbrel-app.yml'
            manifest.write_text('name: Decrumb\nversion: "0.1.0"\nport: 8857\n')
            with self.assertRaises(ValueError):
                release_version.umbrel(root)
            release_version.umbrel(root, write=True)
            release_version.umbrel(root)
            self.assertEqual(manifest.read_text(), 'name: Decrumb\nversion: "1.1.0-rc.9"\nport: 8857\n')
            self.assertEqual(release_version.load(root)['pi_archive'], 'build/Decrumb-1.1.0-9-linux-arm64.tar.gz')

    def test_stable_release_and_invalid_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            metadata = root / 'release.json'
            value = {'version': '1.0.0', 'build': 10, 'channel': 'stable'}
            metadata.write_text(json.dumps(value))
            self.assertEqual(release_version.load(root)['tag'], 'v1.0.0')
            for update in ({'build': True}, {'build': 0}, {'version': '1.0.0-rc.5'}, {'channel': 'other'}):
                metadata.write_text(json.dumps({**value, **update}))
                with self.subTest(update=update), self.assertRaises(ValueError):
                    release_version.load(root)
