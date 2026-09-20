#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Collect pinned public source/notices; never infer completeness from downloads.

Writes a version-bound manifest, exits 2 while requirements remain unresolved.
Reads build inputs and public source only; never opens the Signal runtime.
"""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = ROOT / "tools/release-dependencies.json"
HEX = re.compile(r"[0-9a-f]{64}\Z")
NOTICE = re.compile(r"^(?:LICEN[CS]E|COPYING|NOTICE|COPYRIGHT)(?:$|[._-])", re.I)
SOURCE_FILES = ("sidelet.py", "notes.py", "desktop.py", "service.py", "build.py", "README.md",
                "CONTRIBUTING.md", "SECURITY.md", "LICENSE")
SOURCE_DIRECTORIES = ("app", "swift", "rules", "tools", "tests", "docs", "branding")
PRIVATE_SUFFIXES = {".pem", ".key", ".p8", ".p12", ".pfx", ".crt", ".cer", ".der", ".db", ".sqlite",
                    ".sqlite3", ".log", ".mobileprovision"}
PRIVATE_NAMES = {"config.json", "configuration.json", "accounts.json", "account.json", "credentials.json",
                 "credentials", "secrets.json", "runtime.json", "runtime", "logs", "secrets", "private"}


def source_inventory(root=ROOT):
    """Stable public source allowlist shared with the production packager."""
    root = Path(root)
    git_files = None
    if (root / ".git").exists():
        # In a checkout, respect Git's existing runtime/credential exclusions too.
        git_files = set(subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root
        ).decode().split("\0"))
    paths = [root / name for name in SOURCE_FILES]
    for name in SOURCE_DIRECTORIES:
        paths.extend((root / name).rglob("*"))
    records = []
    for path in sorted(set(paths)):
        relative = path.relative_to(root)
        if (path.is_file() and not path.is_symlink() and "__pycache__" not in relative.parts
                and path.suffix.lower() not in PRIVATE_SUFFIXES | {".pyc"}
                and not any(part.startswith(".") or part.lower() in PRIVATE_NAMES for part in relative.parts)
                and (git_files is None or relative.as_posix() in git_files)):
            records.append({"path": relative.as_posix(), "sha256": digest(path)})
    if not set(SOURCE_FILES).issubset({item["path"] for item in records}):
        raise ValueError("Source snapshot is missing required files")
    return records


def source_inventory_sha256(root=ROOT):
    return inventory_sha256(source_inventory(root))


def inventory_sha256(inventory):
    encoded = json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def safe_relative(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("Unsafe artifact path")
    return path


def is_notice(name):
    path = PurePosixPath(name)
    return bool(NOTICE.match(path.name) or path.name in ("ASSEMBLY_EXCEPTION", "THIRD_PARTY_README", "UNLICENSE", "DEPENDENCIES")
                or "legal" in path.parts or "licenses" in path.parts)


def source_header_notices(archive, output):
    """Retain original legal comments when a source JAR uses file-level notices."""
    comments = {}
    for member in archive.infolist():
        if PurePosixPath(member.filename).suffix not in (".java", ".kt", ".kts") or member.is_dir():
            continue
        with archive.open(member) as source:
            header = source.read(16384).decode("utf-8", errors="replace")
        for match in re.finditer(r"/\*[\s\S]*?\*/|(?m:(?://[^\n]*\n)+)", header):
            comment = match.group()
            if re.search(r"copyright|licen[sc]ed?\b|permission is hereby|redistribution and use", comment, re.I):
                comments.setdefault(comment, []).append(member.filename)
    if comments:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("Original legal comments from the matching upstream source JAR.\n\n" +
                          "\n\n".join("Files: " + ", ".join(names) + "\n" + comment for comment, names in comments.items()) + "\n")


def fetch(item, cache, offline):
    name = safe_relative(item["filename"])
    if len(name.parts) != 1 or not HEX.fullmatch(item["sha256"]):
        raise ValueError("Invalid dependency lock entry")
    target = cache / name.name
    if target.exists() and digest(target) == item["sha256"]:
        return target
    if offline:
        raise ValueError("Pinned source is not in the verified cache")
    if not item["url"].startswith("https://"):
        raise ValueError("Source URL must use HTTPS")
    cache.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".partial")
    try:
        with urllib.request.urlopen(item["url"], timeout=90) as response, temporary.open("wb") as output:
            if not response.url.startswith("https://"):
                raise ValueError("Source redirected outside HTTPS")
            shutil.copyfileobj(response, output)
        if digest(temporary) != item["sha256"]:
            raise ValueError("Pinned source checksum does not match")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def archive_notices(source, component, output):
    """Copy regular notice files only; never extract archive paths or symlinks."""
    count = 0
    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            for member in archive.infolist():
                if member.is_dir() or not is_notice(member.filename):
                    continue
                relative = safe_relative(member.filename)
                if member.file_size > 2 * 1024 * 1024:
                    raise ValueError("Unexpectedly large notice")
                target = output / "notices" / component / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))
                count += 1
        return count
    with tarfile.open(source) as archive:
        for member in archive:
            if not member.isfile() or not is_notice(member.name):
                continue
            relative = safe_relative(member.name)
            if member.size > 2 * 1024 * 1024:
                raise ValueError("Unexpectedly large notice")
            target = output / "notices" / component / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
            count += 1
        if component == "sqlite":
            member = next(m for m in archive.getmembers() if m.name.endswith("/sqlite3.c"))
            text = archive.extractfile(member).read(4096).decode()
            target = output / "notices/sqlite/blessing.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text[:text.index("*/") + 2] + "\n")
            count += 1
    return count


def bottle_materials(bottle, lock, output):
    if digest(bottle) != lock["signal_cli_bottle_sha256"]:
        raise ValueError("Signal bottle does not match the dependency lock")
    prefix = "signal-cli/0.14.8/"
    with tarfile.open(bottle) as archive:
        for source, destination in (
            (".brew/signal-cli.rb", "build-recipes/signal-cli.rb"),
            ("sbom.spdx.json", "inventories/signal-cli-bottle.spdx.json"),
            ("LICENSE", "notices/signal-cli-bottle/LICENSE"),
        ):
            member = archive.getmember(prefix + source)
            if not member.isfile():
                raise ValueError("Missing regular bottle material")
            target = output / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
    recipe = (output / "build-recipes/signal-cli.rb").read_text()
    for name in ("signal-cli", "libsignal"):
        item = next(x for x in lock["sources"] if x["component"] == name)
        if item["sha256"] not in recipe:
            raise ValueError("Signal source lock differs from bottle recipe")


def frozen_inventory(toc_path, lock, output):
    """Read only the packager's build TOC; omit local paths from public output."""
    value = ast.literal_eval(toc_path.read_text())
    inventory, formulas = [], {}
    for sequence in value:
        if not isinstance(sequence, list):
            continue
        for row in sequence:
            if not isinstance(row, tuple) or len(row) != 3 or row[2] not in ("BINARY", "EXTENSION"):
                continue
            name, source, kind = row
            record = {"name": name, "kind": kind, "sha256": digest(Path(source))}
            resolved = Path(source).resolve()
            parts = resolved.parts
            if "Cellar" in parts:
                index = parts.index("Cellar")
                formula, version = parts[index + 1:index + 3]
                if lock["frozen_libraries"].get(formula) != version:
                    raise ValueError("Frozen native dependency is absent or differs from the lock")
                record.update({"package": formula, "version": version})
                formulas[formula] = Path(*parts[:index + 3]) / ".brew" / (formula + ".rb")
            else:
                raise ValueError("Frozen native dependency provenance is not a locked Homebrew package")
            inventory.append(record)
    if not inventory or set(formulas) != set(lock["frozen_libraries"]):
        raise ValueError("Frozen dependency inventory does not cover the locked package set")
    write_json(output / "inventories/frozen-worker-native.json", inventory)
    for name, recipe in formulas.items():
        destination = output / "build-recipes" / (name + ".rb")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(recipe, destination)


def own_source(output, version):
    inventory = source_inventory()
    write_json(output / "inventories/decrumb-source.json", inventory)
    destination = output / "sources" / ("decrumb-" + version + "-source.tar.gz")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        for record in inventory:
            name = record["path"]
            path = ROOT / name
            info = archive.gettarinfo(str(path), arcname="decrumb-" + version + "/" + name)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise ValueError("Source changed while preparing materials")
            archive.addfile(info, io.BytesIO(data))
    return destination


def native_source_inventory(output):
    """Record unresolved dependency declarations instead of calling them complete."""
    selected = {
        "signal-cli": {"gradle/libs.versions.toml", "build.gradle.kts", "lib/build.gradle.kts",
                       "settings.gradle.kts", "gradle/wrapper/gradle-wrapper.properties"},
        "libsignal": {"Cargo.lock", "Cargo.toml", "rust-toolchain", "rust-toolchain.toml",
                      "java/build.gradle", "java/build.gradle.kts", "java/gradle/libs.versions.toml"},
    }
    for component, names in selected.items():
        candidates = list((output / "sources").glob(component + "-*.tar.gz"))
        if not candidates:
            continue
        with tarfile.open(candidates[0]) as archive:
            for member in archive:
                parts = PurePosixPath(member.name).parts
                relative = "/".join(parts[1:])
                if member.isfile() and relative in names:
                    target = output / "inventories" / component / safe_relative(relative)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(member).read())


def cargo_materials(lock, cache, offline, output):
    """Conservatively include the full pinned workspace, not just linked crates."""
    source = next(x for x in lock["sources"] if x["component"] == "libsignal")
    with tarfile.open(output / "sources" / source["filename"]) as archive:
        member = next(m for m in archive if m.name.endswith("/Cargo.lock") and m.name.count("/") == 1)
        cargo = tomllib.loads(archive.extractfile(member).read().decode())
    packages = [p for p in cargo["package"] if "source" in p]
    git_sources = {item["cargo_source"]: item for item in lock["sources"] if "cargo_source" in item}
    records = []
    for package in packages:
        origin = package["source"]
        if origin.startswith("git+"):
            if origin not in git_sources:
                raise ValueError("Cargo git source is missing from the pinned source lock")
            pinned = git_sources[origin]
            if not (output / "sources" / pinned["filename"]).is_file():
                raise ValueError("Cargo git source was not collected")
            records.append({"name": package["name"], "version": package["version"],
                            "source": origin, "path": "sources/" + pinned["filename"], "sha256": pinned["sha256"]})
        elif origin == "registry+https://github.com/rust-lang/crates.io-index":
            name = package["name"] + "-" + package["version"] + ".crate"
            records.append({"name": package["name"], "version": package["version"], "source": origin,
                            "path": "sources/cargo/" + name, "sha256": package["checksum"],
                            "url": "https://static.crates.io/crates/" + package["name"] + "/" + name})
        else:
            raise ValueError("Unrecognized Cargo registry")

    def collect(record):
        if "url" not in record:
            return
        item = {"filename": PurePosixPath(record["path"]).name, "sha256": record["sha256"], "url": record["url"]}
        source = fetch(item, cache, offline)
        target = output / record["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        record["notice_files"] = archive_notices(target, "cargo/" + item["filename"][:-6], output)
        # Original source comments and Cargo license/license-file declarations are preserved
        # even when a crate does not ship a separate LICENSE filename.
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(collect, records))
    write_json(output / "inventories/cargo-workspace-sources.json", records)
    print("Cargo: verified " + str(len(records)) + " locked external workspace entries", flush=True)


def jvm_materials(lock, cache, offline, output):
    """Verify full upstream JAR inventory; retain notices and matching sources."""
    distribution = fetch(lock["jvm_distribution"], cache, offline)
    expected = {item["filename"]: item for item in lock["jvm_artifacts"]}
    observed = set()
    with tarfile.open(distribution) as archive:
        for member in archive:
            if not member.isfile() or not member.name.endswith(".jar"):
                continue
            name = PurePosixPath(member.name).name
            if name not in expected:
                raise ValueError("Upstream distribution has an untracked JAR")
            data = archive.extractfile(member).read()
            item = expected[name]
            if hashlib.sha256(data).hexdigest() != item["jar_sha256"]:
                raise ValueError("Upstream distribution JAR checksum differs")
            archive_notices(io.BytesIO(data), "jvm/" + name[:-4] + "/binary", output)
            if "covered_by" in item:
                covered = next(x for x in lock["sources"] if x["component"] == item["covered_by"])
                if not (output / "sources" / covered["filename"]).is_file():
                    raise ValueError("JVM source coverage is missing")
            observed.add(name)
    if observed != set(expected):
        raise ValueError("Pinned upstream JAR inventory is incomplete")

    def collect(item):
        for material in item.get("materials", []):
            source = fetch(material, cache, offline)
            area = "sources/jvm" if material["role"] == "source" else "inventories/jvm"
            target = output / area / material["filename"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if material["role"] == "source":
                archive_notices(target, "jvm/" + item["filename"][:-4] + "/source", output)
                with zipfile.ZipFile(target) as source_archive:
                    source_header_notices(source_archive, output / "notices/jvm" / item["filename"][:-4] / "SOURCE-LEGAL-HEADERS.txt")
        if "covered_by" not in item and {m["role"] for m in item.get("materials", [])} != {"source", "inventory"}:
            raise ValueError("JVM source or POM material missing")
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(collect, expected.values()))
    write_json(output / "inventories/jvm-distribution.json", lock["jvm_artifacts"])
    declarations = [{"artifact": item.get("group", "org.asamk") + ":" + item["artifact"] + ":" + item["version"],
                     "licenses": item.get("license_declarations", []), "source_coverage": item.get("covered_by", "matching source JAR")}
                    for item in expected.values()]
    write_json(output / "notices/jvm/LICENSE-DECLARATIONS.json", declarations)
    print("JVM: verified " + str(len(expected)) + " upstream distribution JARs and source coverage", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--build", required=True)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--output", type=Path, default=ROOT / "build/release-materials")
    parser.add_argument("--cache", type=Path, default=ROOT / "build/release-source-cache")
    parser.add_argument("--bottle", type=Path, default=ROOT / "build/downloads/signal-cli-0.14.8-arm64-sonoma.tar.gz")
    parser.add_argument("--worker-toc", type=Path, default=ROOT / "build/freeze-work/sidelet-worker/Analysis-00.toc")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version) or not re.fullmatch(r"[1-9]\d*", args.build):
        parser.error("Use a numeric three-part version and a positive build number")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    marker = output / ".decrumb-release-materials"
    if marker.is_symlink() or (output / "manifest.json").is_symlink():
        parser.error("Release metadata must not contain symlinks")
    if not marker.exists() and any(output.iterdir()):
        parser.error("Output must be empty or owned by this producer")
    marker.write_text("Decrumb release materials producer v1\n")
    # Immediately invalidate any older manifest, including when a new run fails.
    write_json(output / "manifest.json", {"schema_version": 1, "version": args.version,
               "build": args.build, "status": "blocked", "files": [],
               "blockers": [{"id": "preparation-incomplete", "detail": "Preparation has not completed."}]})
    try:
        lock = json.loads(args.lock.read_text())
        if (not isinstance(lock, dict) or lock.get("schema_version") != 1
                or not isinstance(lock.get("unresolved"), list)
                or not isinstance(lock.get("sources"), list)
                or not isinstance(lock.get("frozen_libraries"), dict)
                or not isinstance(lock.get("jvm_distribution"), dict)
                or not isinstance(lock.get("jvm_artifacts"), list)
                or not HEX.fullmatch(lock.get("signal_cli_bottle_sha256", ""))
                or not isinstance(lock.get("python_version"), str)):
            raise ValueError("Unsupported or incomplete dependency lock")
    except (OSError, ValueError, TypeError):
        write_json(output / "manifest.json", {"schema_version": 1, "version": args.version,
                   "build": args.build, "status": "blocked", "files": [],
                   "blockers": [{"id": "dependency-lock", "detail": "Dependency lock is missing, malformed, or incomplete."}]})
        print("Release materials: blocked; dependency lock is missing, malformed, or incomplete.")
        return 2
    blockers = list(lock["unresolved"])
    with tempfile.TemporaryDirectory(prefix="release-materials-", dir=output.parent) as folder:
        stage = Path(folder)
        for item in lock["sources"]:
            try:
                source = fetch(item, args.cache, args.offline)
                target = stage / "sources" / item["filename"]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                count = archive_notices(target, item["component"], stage)
                if not count:
                    raise ValueError("Source archive contains no recognized notice files")
                print(item["component"] + ": verified source; " + str(count) + " notice files", flush=True)
            except (OSError, ValueError, tarfile.TarError) as error:
                blockers.append({"id": "source-" + item["component"], "detail": type(error).__name__ + ": pinned source/notice collection failed."})
        for item in lock.get("materials", []):
            try:
                source = fetch(item, args.cache, args.offline)
                area = {"build_recipe": "build-recipes", "notice": "notices/standard-licenses"}.get(item["role"], "inventories")
                target = stage / area / item["filename"]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            except (OSError, ValueError):
                blockers.append({"id": "material-" + item["filename"], "detail": "Pinned public build/inventory material could not be verified."})
        for name, action in (
            ("signal-bottle", lambda: bottle_materials(args.bottle, lock, stage)),
            ("frozen-worker", lambda: frozen_inventory(args.worker_toc, lock, stage)),
            ("cargo-workspace", lambda: cargo_materials(lock, args.cache, args.offline, stage)),
            ("jvm-distribution", lambda: jvm_materials(lock, args.cache, args.offline, stage)),
            ("decrumb-source", lambda: own_source(stage, args.version)),
            ("native-declarations", lambda: native_source_inventory(stage)),
        ):
            try:
                action()
            except (OSError, ValueError, KeyError, StopIteration, tarfile.TarError, zipfile.BadZipFile, subprocess.SubprocessError):
                blockers.append({"id": name, "detail": "Required build/source evidence could not be collected or verified."})
        shutil.copy2(args.lock, stage / "dependency-lock.json")
        readme = ("Decrumb release source and notices\n\n"
                  "This directory contains pinned upstream sources, extracted notices, exact available Homebrew build recipes,\n"
                  "a path-scrubbed frozen-worker native inventory, and this Decrumb source snapshot.\n"
                  "Read manifest.json: downloaded sources do not by themselves establish complete dependency coverage.\n"
                  "The producer exits nonzero while blockers remain. Do not publish a production binary against a blocked manifest.\n"
                  "PyInstaller's bootloader exception applies as described in its supplied COPYING.txt;\n"
                  "its presence here does not mean PyInstaller requires source distribution for every frozen application.\n"
                  "No account keys, messages, runtime databases, signing credentials, or private history are included.\n")
        (stage / "README.txt").write_text(readme)
        source_record_path = stage / "inventories/decrumb-source.json"
        source_hash = inventory_sha256(json.loads(source_record_path.read_text())) if source_record_path.is_file() else None
        if source_hash != source_inventory_sha256():
            blockers.append({"id": "source-changed", "detail": "Decrumb source changed during material preparation; rerun after edits finish."})
        roles = {"sources": "source", "notices": "notice", "inventories": "inventory", "build-recipes": "build_recipe"}
        files = [{"path": str(path.relative_to(stage)), "sha256": digest(path),
                  "role": roles.get(path.relative_to(stage).parts[0], "release"), "component": path.relative_to(stage).parts[1] if len(path.relative_to(stage).parts) > 1 else "release"}
                 for path in sorted(stage.rglob("*")) if path.is_file()]
        manifest = {"schema_version": 1, "version": args.version, "build": args.build,
                    "status": "blocked" if blockers else "ready", "files": files, "blockers": blockers,
                    "dependency_lock_sha256": digest(args.lock), "app_inputs": {
                        "signal_cli_bottle_sha256": lock["signal_cli_bottle_sha256"], "python_version": lock["python_version"],
                        "decrumb_source_sha256": source_hash,
                        "requirements_build_sha256": digest(ROOT / "tools/requirements-build.txt")}}
        # Only producer-owned output subdirectories are replaced; no arbitrary deletion.
        for name in ("sources", "notices", "inventories", "build-recipes"):
            destination = output / name
            if destination.is_symlink():
                raise ValueError("Release output must not contain symlinks")
            if destination.exists():
                shutil.rmtree(destination)
            if (stage / name).exists():
                shutil.move(str(stage / name), destination)
        for name in ("dependency-lock.json", "README.txt"):
            shutil.copy2(stage / name, output / name)
        write_json(output / "manifest.json", manifest)
    print("Release materials: " + manifest["status"] + "; " + str(len(files)) + " files; " + str(len(blockers)) + " blockers.")
    for blocker in blockers:
        print("- " + blocker["id"] + ": " + blocker["detail"])
    return 2 if blockers else 0


if __name__ == "__main__":
    sys.exit(main())
