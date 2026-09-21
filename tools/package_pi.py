#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Create the small Raspberry Pi source installer, without private state or third-party binaries."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import prepare_release_materials as materials

ROOT_FILES = list(materials.SOURCE_FILES)
TOOLS = ['tools/install_pi.py', 'tools/package_pi.py', 'tools/prepare_release_materials.py']


def source_files(root):
    # Use the same reviewed private-file boundaries as macOS source releases.
    return {item['path']: root / item['path'] for item in materials.source_inventory(root)}


def package(root, output, version, build):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version) or not re.fullmatch(r'[1-9]\d*', str(build)):
        raise ValueError('Use a three-part numeric version and a positive build number.')
    files = source_files(root)
    manifest = {'schema': 1, 'version': version, 'build': str(build), 'platform': 'linux-arm64',
                'signal_dependency': 'downloaded separately from pinned upstream URL',
                'files': {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sorted(files.items())}}
    prefix = 'Decrumb-' + version + '-' + str(build) + '-linux-arm64'
    output.mkdir(parents=True, exist_ok=True)
    archive = output / (prefix + '.tar.gz')
    with archive.open('wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as bundle:
            content = {name: path.read_bytes() for name, path in files.items()}
            content['pi-manifest.json'] = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()
            for name, data in sorted(content.items()):
                entry = tarfile.TarInfo(prefix + '/' + name)
                entry.size = len(data)
                entry.mode = 0o755 if name in ('portable_cleaner.py', 'tools/install_pi.py') else 0o644
                entry.mtime = 0
                bundle.addfile(entry, io.BytesIO(data))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(archive.suffix + '.sha256').write_text(checksum + '  ' + archive.name + '\n')
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--build-number', required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'build')
    args = parser.parse_args()
    print(package(ROOT, args.output, args.version, args.build_number))


if __name__ == '__main__':
    main()
