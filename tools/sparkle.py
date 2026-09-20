# SPDX-License-Identifier: AGPL-3.0-only
"""Pinned official Sparkle distribution and non-secret updater configuration."""
import base64
import hashlib
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tarfile
import urllib.request

VERSION = '2.10.0'
SHA256 = 'c2bf58aa8387266ac179357b1415d6f2635f044da8be41042af32425dae6da0c'
URL = 'https://github.com/sparkle-project/Sparkle/releases/download/' + VERSION + '/Sparkle-' + VERSION + '.tar.xz'
PUBLIC_KEY = 'Nax0dpWvp5V9jk0bnbKtEUIBDI2BHXDAaeQXJlarWFQ='
FEED_URL = 'https://mkships.app/decrumb/appcast.xml'
ROOT = Path(__file__).resolve().parents[1]


def distribution():
    archive = ROOT / 'build/downloads' / ('Sparkle-' + VERSION + '.tar.xz')
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        temporary = archive.with_suffix('.partial')
        try:
            with urllib.request.urlopen(URL, timeout=90) as response, temporary.open('wb') as output:
                shutil.copyfileobj(response, output)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != SHA256:
                raise ValueError('Sparkle distribution checksum mismatch')
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    # Compare the cached tree with verified archive bytes before reuse. This
    # keeps concurrent build/release checks from deleting tools in another run.
    target = ROOT / 'build/sparkle'
    with tarfile.open(archive) as source:
        members = source.getmembers()
        valid = target.is_dir()
        expected = set()
        for member in members:
            relative = Path(member.name)
            candidate = target / relative
            if member.isdir():
                continue
            expected.add(relative.as_posix().removeprefix('./'))
            if member.issym():
                valid = valid and candidate.is_symlink() and os.readlink(candidate) == member.linkname
            elif member.isfile():
                valid = (valid and candidate.is_file() and not candidate.is_symlink()
                         and candidate.resolve().is_relative_to(target.resolve())
                         and candidate.stat().st_size == member.size
                         and hashlib.sha256(candidate.read_bytes()).digest() == hashlib.sha256(source.extractfile(member).read()).digest())
            else:
                valid = False
        if valid:
            actual = {p.relative_to(target).as_posix() for p in target.rglob('*') if not p.is_dir() or p.is_symlink()}
            valid = actual == expected
        if not valid:
            if target.exists():
                shutil.rmtree(target)
            target.mkdir()
            source.extractall(target, filter='data')
    return target


def configuration():
    assert len(base64.b64decode(PUBLIC_KEY, validate=True)) == 32
    return {'SUFeedURL': FEED_URL, 'SUPublicEDKey': PUBLIC_KEY,
            'SURequireSignedFeed': True, 'SUSignedFeedFailureExpirationInterval': 0, 'SUVerifyUpdateBeforeExtraction': True,
            'SUEnableAutomaticChecks': False, 'SUAutomaticallyUpdate': False,
            'SUAllowsAutomaticUpdates': True, 'SUEnableSystemProfiling': False,
            'SUShowReleaseNotes': True}


def copy_framework(distribution_root, app):
    folder = app / 'Contents/Frameworks'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / 'Sparkle.framework'
    shutil.copytree(distribution_root / 'Sparkle.framework', target, symlinks=True)
    return target


def nested_code(framework):
    base = framework / 'Versions/B'
    return [base / 'XPCServices/Downloader.xpc', base / 'XPCServices/Installer.xpc',
            base / 'Updater.app', base / 'Autoupdate', framework]


def validate_configuration(info):
    expected = configuration()
    if any(info.get(k) != v for k, v in expected.items()):
        raise ValueError('The update security settings do not match the pinned release configuration')
