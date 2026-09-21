#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Build an unsigned experimental Windows x64 bundle on Windows, without accounts."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import prepare_release_materials, release_version

MAX_ARCHIVE = 300 * 1024 * 1024
MAX_EXPANDED = 900 * 1024 * 1024


def download(dependency, cache):
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / (dependency['sha256'] + '.' + dependency['archive'])
    if archive.exists() and hashlib.sha256(archive.read_bytes()).hexdigest() == dependency['sha256']:
        return archive
    temporary = archive.with_suffix('.download')
    try:
        with urllib.request.urlopen(dependency['url'], timeout=90) as response, temporary.open('wb') as output:
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_ARCHIVE:
                    raise ValueError('Dependency download exceeded its size limit')
                output.write(chunk)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != dependency['sha256']:
            raise ValueError('Dependency checksum did not match the reviewed lock')
        temporary.replace(archive)
        return archive
    finally:
        temporary.unlink(missing_ok=True)


def relative_member(name, prefix):
    path = PurePosixPath(name)
    # Reject Windows drive, ADS, reserved names and path aliases before writing.
    reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {p + str(n) for p in ('COM', 'LPT') for n in range(1, 10)}
    if (not path.parts or path.parts[0] != prefix or path.is_absolute() or '\\' in name or
            any(part in ('.', '..') or ':' in part or part.endswith((' ', '.')) or
                part.split('.')[0].upper() in reserved for part in path.parts)):
        raise ValueError('Unsafe dependency archive path')
    return Path(*path.parts[1:])


def extract(archive, dependency, destination):
    destination.mkdir(parents=True)
    seen, total = set(), 0
    def write(name, size, source):
        nonlocal total
        relative = relative_member(name, dependency['prefix'])
        key = relative.as_posix().casefold()
        if relative == Path('.') or key in seen:
            raise ValueError('Duplicate dependency file')
        seen.add(key)
        total += size
        if total > MAX_EXPANDED:
            raise ValueError('Dependency expansion exceeded its size limit')
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as output:
            shutil.copyfileobj(source, output)
    if dependency['archive'] == 'zip':
        with zipfile.ZipFile(archive) as bundle:
            for item in bundle.infolist():
                relative_member(item.filename.rstrip('/'), dependency['prefix'])
                if stat.S_ISLNK(item.external_attr >> 16):
                    raise ValueError('Dependency links are not supported')
                if not item.is_dir():
                    with bundle.open(item) as source:
                        write(item.filename, item.file_size, source)
    else:
        with tarfile.open(archive, 'r:gz') as bundle:
            for item in bundle:
                if item.name in ('.', './') and item.isdir():
                    continue
                relative_member(item.name.rstrip('/'), dependency['prefix'])
                if item.isdir():
                    continue
                if not item.isfile():
                    raise ValueError('Dependency links and special files are not supported')
                with bundle.extractfile(item) as source:
                    write(item.name, item.size, source)


def prepare_dependencies(target, cache):
    lock = json.loads((ROOT / 'windows/dependencies.json').read_text())
    target.mkdir(parents=True, exist_ok=True)
    for name, directory in (('signal_cli', 'signal-cli'), ('java', 'jre')):
        dependency = lock[name]
        archive = download(dependency, cache)
        with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
            staged = Path(temporary) / directory
            extract(archive, dependency, staged)
            destination = target / directory
            if destination.exists():
                shutil.rmtree(destination)
            shutil.move(str(staged), destination)
    required = [target / 'signal-cli/bin/signal-cli.bat', target / 'jre/bin/java.exe']
    if not all(path.is_file() for path in required):
        raise ValueError('The dependency archive layout did not match the reviewed lock')
    # Verify the Java PE machine type before packaging the x64 runtime.
    java = required[1].read_bytes()
    offset = int.from_bytes(java[60:64], 'little')
    if java[:2] != b'MZ' or java[offset:offset + 6] != b'PE\0\0\x64\x86':
        raise ValueError('Expected an x64 Windows Java executable')


def copy_notices(target):
    notices = target / 'licenses'
    notices.mkdir(exist_ok=True)
    for package in ('pyinstaller', 'segno', 'pywin32'):
        distribution = importlib.metadata.distribution(package)
        folder = notices / package
        for entry in distribution.files or []:
            if any(word in entry.name.lower() for word in ('license', 'copying', 'notice')):
                source = Path(distribution.locate_file(entry))
                if source.is_file():
                    if entry.is_absolute() or '..' in entry.parts:
                        raise ValueError('Unsafe dependency notice path')
                    destination = folder / entry
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
        if not folder.exists():
            raise ValueError('Missing dependency license: ' + package)
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if not python_license.is_file():
        raise ValueError('Missing Python license')
    shutil.copy2(python_license, notices / 'Python-LICENSE.txt')


def package(target, output):
    release = release_version.resolve(root=ROOT)
    source = target / 'source'
    source.mkdir(exist_ok=True)
    for item in prepare_release_materials.source_inventory(ROOT):
        path = Path(item['path'])
        (source / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, source / path)
    shutil.copy2(ROOT / 'LICENSE', target / 'LICENSE.txt')
    guide = (ROOT / 'docs/WINDOWS.md').read_text()
    for name in ('URL-CLEANUP.md', 'NOTE-LIFECYCLE.md', 'PROVENANCE.md'):
        guide = guide.replace('](' + name + ')', '](source/docs/' + name + ')')
    (target / 'README.md').write_text(guide)
    shutil.copy2(ROOT / 'windows/dependencies.json', target / 'dependencies.json')
    copy_notices(target)
    manifest = {'schema': 1, 'platform': 'windows-x64', 'version': release['version'],
                'build': release['build'], 'status': 'unsigned experimental development build',
                'python': platform.python_version(),
                'files': {p.relative_to(target).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(target.rglob('*')) if p.is_file()}}
    (target / 'windows-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    archive = output / Path(release['windows_archive']).name
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(target.rglob('*')):
            if path.is_file():
                bundle.write(path, 'Decrumb/' + path.relative_to(target).as_posix())
    archive.with_suffix('.zip.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name + '\n')
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dependencies-only', action='store_true', help='Prepare and verify public dependencies without freezing Windows executables')
    args = parser.parse_args()
    build = ROOT / 'build/windows'
    target = build / 'Decrumb'
    if not args.dependencies_only:
        if sys.platform != 'win32' or platform.machine().lower() not in ('amd64', 'x86_64'):
            raise SystemExit('Build the native bundle on Windows x64. Cross-compiling from macOS/Linux is not supported.')
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                        '--distpath', str(build), '--workpath', str(build / 'freeze'),
                        str(ROOT / 'windows/decrumb.spec')], check=True, cwd=ROOT)
    prepare_dependencies(target, build / 'cache')
    if not args.dependencies_only:
        print(package(target, build))
    else:
        print('Pinned Windows Signal and Java dependencies verified.')


if __name__ == '__main__':
    main()
