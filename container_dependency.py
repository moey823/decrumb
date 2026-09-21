# SPDX-License-Identifier: AGPL-3.0-only
"""Fetch a fixed, checksum-pinned dependency into private container state.

No archive paths are extracted, no submitted URL is used, and no dependency
binary is redistributed in the Decrumb container image.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tarfile
from urllib.request import urlopen

import decrumb

APP = Path(__file__).resolve().parent
MAX_DOWNLOAD = 150 * 1024 * 1024
MAX_BINARY = 400 * 1024 * 1024


def architecture():
    value = {'aarch64': 'arm64', 'arm64': 'arm64', 'x86_64': 'amd64', 'amd64': 'amd64'}.get(platform.machine())
    if value is None:
        raise decrumb.SafeError('Decrumb requires a 64-bit ARM or Intel/AMD system.')
    return value


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def copy_bounded(source, output, limit):
    size = 0
    while chunk := source.read(1024 * 1024):
        size += len(chunk)
        if size > limit:
            raise decrumb.SafeError('Signal dependency exceeds its size limit.')
        output.write(chunk)


def unpack(packed, target, kind):
    with target.open('wb') as output:
        if kind == 'gz':
            with gzip.open(packed, 'rb') as source:
                copy_bounded(source, output, MAX_BINARY)
        elif kind == 'tar.gz':
            # Read only one regular executable; never extract archive paths or links.
            with tarfile.open(packed, 'r:gz') as archive:
                files = [member for member in archive if member.isfile() and Path(member.name).name == 'signal-cli']
                if len(files) != 1 or files[0].size > MAX_BINARY:
                    raise decrumb.SafeError('Unexpected Signal dependency archive.')
                with archive.extractfile(files[0]) as source:
                    copy_bounded(source, output, MAX_BINARY)
        else:
            raise decrumb.SafeError('Unexpected Signal dependency format.')


def verify(path, arch):
    with path.open('rb') as source:
        header = source.read(20)
    machine = b'\xb7\x00' if arch == 'arm64' else b'\x3e\x00'
    if len(header) != 20 or header[:6] != b'\x7fELF\x02\x01' or header[18:20] != machine:
        raise decrumb.SafeError('Signal dependency does not match this system.')
    path.chmod(0o700)
    result = subprocess.run([str(path), '--version'], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=45, check=True)
    # Community native builds append their build metadata to the same version.
    # The archive hash, above, pins the exact bytes rather than this display text.
    if not re.match(r'\Asignal-cli 0\.14\.8(?:[ +(-]|$)', result.stdout.decode().strip()):
        raise decrumb.SafeError('Signal dependency version does not match.')


def install(root, archive=None):
    arch = architecture()
    dep = json.loads((APP / 'container/dependencies.json').read_text())[arch]
    directory = root / 'dependency'
    directory.mkdir(mode=0o700, exist_ok=True)
    binary, receipt = directory / 'signal-cli', directory / 'receipt.json'
    try:
        saved = json.loads(receipt.read_text())
        if saved['archive_sha256'] == dep['sha256'] and saved['binary_sha256'] == checksum(binary):
            verify(binary, arch)
            return
    except (OSError, ValueError, KeyError, decrumb.SafeError, subprocess.SubprocessError):
        pass
    # A killed/interrupted bootstrap leaves only these replaceable download files.
    packed, temporary = directory / 'download.part', directory / 'binary.part'
    try:
        with (archive.open('rb') if archive else urlopen(dep['url'], timeout=60)) as source, packed.open('wb') as output:
            copy_bounded(source, output, MAX_DOWNLOAD)
        if checksum(packed) != dep['sha256']:
            raise decrumb.SafeError('Signal dependency checksum did not match. Retry setup.')
        unpack(packed, temporary, dep['format'])
        verify(temporary, arch)
        digest = checksum(temporary)
        os.replace(temporary, binary)
        decrumb.write_json(receipt, {'archive_sha256': dep['sha256'], 'binary_sha256': digest})
    finally:
        packed.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)
