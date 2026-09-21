# SPDX-License-Identifier: AGPL-3.0-only
"""Release smoke safety gates; the native ARM64 smoke runs separately on Linux."""
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import smoke_pi


class PiSmokeSafetyTests(unittest.TestCase):
    def archive(self, folder, names):
        path = Path(folder) / 'release.tar.gz'
        with tarfile.open(path, 'w:gz') as bundle:
            for name, kind in names:
                entry = tarfile.TarInfo(name)
                if kind == 'link':
                    entry.type = tarfile.SYMTYPE
                    entry.linkname = '/synthetic-outside'
                    bundle.addfile(entry)
                else:
                    content = b'{}' if name.endswith('pi-manifest.json') else b'synthetic'
                    entry.size = len(content)
                    entry.mode = 0o755 if kind == 'executable' else 0o644
                    bundle.addfile(entry, io.BytesIO(content))
        return path

    def test_extraction_accepts_release_layout_with_private_modes(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = self.archive(folder, [('release/pi-manifest.json', 'file'), ('release/helper', 'executable')])
            source = smoke_pi.extract(archive, Path(folder) / 'extracted')
            self.assertEqual((source / 'helper').read_bytes(), b'synthetic')
            self.assertEqual((source / 'helper').stat().st_mode & 0o777, 0o700)
            self.assertEqual((source / 'pi-manifest.json').stat().st_mode & 0o777, 0o600)

    def test_unsafe_archive_members_never_escape_temporary_directory(self):
        for name, kind in (('../outside', 'file'), ('/absolute', 'file'), ('release/link', 'link')):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                archive = self.archive(folder, [(name, kind)])
                with self.assertRaises(smoke_pi.SmokeError):
                    smoke_pi.extract(archive, Path(folder) / 'extracted')
                self.assertFalse((Path(folder) / 'outside').exists())

    def test_multiple_roots_and_duplicate_members_are_rejected(self):
        for names in ([('release/pi-manifest.json', 'file'), ('other/file', 'file')],
                      [('release/pi-manifest.json', 'file'), ('release/pi-manifest.json', 'file')]):
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(smoke_pi.SmokeError):
                    smoke_pi.extract(self.archive(folder, names), Path(folder) / 'extracted')

    def test_real_systemd_requires_explicit_disposable_arm_runner(self):
        with patch.dict(smoke_pi.os.environ, {}, clear=True), patch.object(smoke_pi, 'run') as run:
            with self.assertRaises(smoke_pi.SmokeError):
                smoke_pi.systemd_guard()
            run.assert_not_called()

    def test_existing_user_unit_is_never_replaced_even_on_ci(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            unit = home / '.config/systemd/user/decrumb.service'
            unit.parent.mkdir(parents=True)
            unit.write_text('synthetic-foreign-unit')
            with patch.dict(smoke_pi.os.environ, {'GITHUB_ACTIONS': 'true', 'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'ARM64'}), \
                    patch.object(smoke_pi.os, 'getuid', return_value=1000), patch.object(Path, 'home', return_value=home), \
                    patch.object(smoke_pi, 'run') as run:
                with self.assertRaises(smoke_pi.SmokeError):
                    smoke_pi.systemd_guard()
                run.assert_not_called()
            self.assertEqual(unit.read_text(), 'synthetic-foreign-unit')

    def test_subprocess_failure_does_not_expose_output(self):
        with patch.object(smoke_pi.subprocess, 'run', return_value=Mock(returncode=1, stdout=b'synthetic-secret', stderr=b'synthetic-secret')):
            with self.assertRaises(smoke_pi.SmokeError) as caught:
                smoke_pi.run(['/synthetic/command'])
        self.assertNotIn('synthetic-secret', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
