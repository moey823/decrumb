"""Synthetic offline checks for source/material boundaries; no account data."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import prepare_release_materials as materials


def tar_bytes(path, files):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as archive:
        for name, data in files.items():
            data = data.encode()
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))


class ReleaseMaterialsTests(unittest.TestCase):
    def test_frozen_inventory_is_identical_for_reordered_toc(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            package = root / "Cellar/python@3.14/3.14.6"
            recipe = package / ".brew/python@3.14.rb"
            recipe.parent.mkdir(parents=True)
            recipe.write_text("# synthetic build recipe\n")
            rows = []
            for name in ("_pickle.so", "_codecs_tw.so"):
                source = package / name
                source.write_bytes(("synthetic binary " + name).encode())
                rows.append((name, str(source), "EXTENSION"))
            lock = {"frozen_libraries": {"python@3.14": "3.14.6"}}
            outputs = []
            for index, ordered_rows in enumerate((rows, list(reversed(rows)))):
                toc = root / ("analysis-" + str(index) + ".toc")
                toc.write_text(repr((ordered_rows,)))
                output = root / ("output-" + str(index))
                materials.frozen_inventory(toc, lock, output)
                outputs.append((output / "inventories/frozen-worker-native.json").read_bytes())
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual([item["name"] for item in json.loads(outputs[0])],
                             ["_codecs_tw.so", "_pickle.so"])

    def test_offline_cache_rejects_altered_source(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            item = {"filename": "public.tar.gz", "sha256": hashlib.sha256(b"expected").hexdigest(),
                    "url": "https://example.invalid/public.tar.gz"}
            (cache / item["filename"]).write_bytes(b"altered")
            with patch.object(materials.urllib.request, "urlopen", side_effect=AssertionError("Network forbidden")):
                with self.assertRaises(ValueError):
                    materials.fetch(item, cache, True)

    def test_source_inventory_excludes_runtime_build_and_symlinks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in materials.SOURCE_FILES:
                (root / name).write_text("public source\n")
            for name in ("build/private-prepublication-docs/private.txt", "runtime/account.db",
                         "tools/__pycache__/cached.pyc", "tools/local.pem", "tools/config.json",
                         "tools/secrets/token.txt", "tools/accounts.sqlite3"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("synthetic private placeholder")
            (root / "tools/public.py").write_text("# public\n")
            (root / "tools/linked-private.py").symlink_to(root / "runtime/account.db")
            records = materials.source_inventory(root)
            paths = {item["path"] for item in records}
            self.assertEqual(paths, set(materials.SOURCE_FILES) | {"tools/public.py"})
            self.assertTrue(all(not Path(item["path"]).is_absolute() for item in records))
            before = materials.source_inventory_sha256(root)
            (root / "tools/public.py").write_text("# changed public source\n")
            self.assertNotEqual(before, materials.source_inventory_sha256(root))

    def test_git_checkout_omits_ignored_source_area_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".git").mkdir()
            (root / "tools").mkdir()
            for name in materials.SOURCE_FILES:
                (root / name).write_text("public\n")
            (root / "tools/private-build.txt").write_text("synthetic ignored placeholder")
            tracked = ("\0".join(materials.SOURCE_FILES) + "\0").encode()
            with patch.object(materials.subprocess, "check_output", return_value=tracked):
                self.assertEqual({x["path"] for x in materials.source_inventory(root)}, set(materials.SOURCE_FILES))

    def test_cargo_git_source_requires_explicit_pinned_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cargo = ('version = 4\n[[package]]\nname = "synthetic"\nversion = "1.0.0"\n'
                     'source = "git+https://example.invalid/source#abc"\n')
            tar_bytes(root / "sources/libsignal.tar.gz", {"libsignal/Cargo.lock": cargo})
            lock = {"sources": [{"component": "libsignal", "filename": "libsignal.tar.gz"}]}
            with self.assertRaisesRegex(ValueError, "missing from the pinned source lock"):
                materials.cargo_materials(lock, root / "cache", True, root)

    def test_cargo_registry_requires_lockfile_checksum(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cargo = ('version = 4\n[[package]]\nname = "synthetic"\nversion = "1.0.0"\n'
                     'source = "registry+https://github.com/rust-lang/crates.io-index"\n')
            tar_bytes(root / "sources/libsignal.tar.gz", {"libsignal/Cargo.lock": cargo})
            lock = {"sources": [{"component": "libsignal", "filename": "libsignal.tar.gz"}]}
            with self.assertRaises(KeyError):
                materials.cargo_materials(lock, root / "cache", True, root)

    def test_jvm_inventory_cannot_omit_distribution_artifact(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "jvm.tar.gz"
            tar_bytes(archive, {"distribution/lib/synthetic-1.0.jar": "placeholder"})
            lock = {"jvm_distribution": {"filename": archive.name, "sha256": materials.digest(archive),
                                         "url": "https://example.invalid/jvm.tar.gz"}, "jvm_artifacts": []}
            with self.assertRaisesRegex(ValueError, "untracked JAR"):
                materials.jvm_materials(lock, root, True, root / "output")

    def test_notice_paths_cannot_escape_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "unsafe.tar.gz"
            tar_bytes(archive, {"../../LICENSE": "synthetic notice"})
            with self.assertRaises(ValueError):
                materials.archive_notices(archive, "synthetic", root / "output")

    def test_failed_preparation_invalidates_old_ready_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "output"
            output.mkdir()
            (output / ".decrumb-release-materials").write_text("owned\n")
            (output / "manifest.json").write_text(json.dumps({"status": "ready"}))
            lock = root / "lock.json"
            lock.write_text(json.dumps({"schema_version": 1, "unresolved": [], "sources": [],
                                        "signal_cli_bottle_sha256": "0" * 64, "python_version": "0.0.0"}))
            with patch.object(materials, "source_inventory_sha256", return_value="0" * 64):
                code = materials.main(["--version", "1.0.0", "--build", "1", "--lock", str(lock),
                                       "--output", str(output), "--cache", str(root / "cache"),
                                       "--bottle", str(root / "missing-bottle"),
                                       "--worker-toc", str(root / "missing-toc"), "--offline"])
            self.assertEqual(code, 2)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "blocked")
            self.assertTrue(manifest["blockers"])


if __name__ == "__main__":
    unittest.main()
