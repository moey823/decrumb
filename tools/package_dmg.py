#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Package and verify a local development DMG. Never uploads or notarizes it."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(*arguments):
    subprocess.run(arguments, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, default=ROOT / 'build/Decrumb.app')
    args = parser.parse_args()
    app = args.app.resolve()
    with (app / 'Contents/Info.plist').open('rb') as source:
        info = plistlib.load(source)
    manifest = json.loads((app / 'Contents/Resources/build-manifest.json').read_text())
    version, architecture = info['CFBundleShortVersionString'], manifest['architecture']
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,2}', version) or architecture != 'arm64':
        raise SystemExit('Unsupported version or architecture for this development packager.')
    if app.name != 'Decrumb.app':
        raise SystemExit('The app must be named Decrumb.app.')
    run('/usr/bin/codesign', '--verify', '--deep', '--strict', str(app))
    output_dir = ROOT / 'build'
    output_dir.mkdir(exist_ok=True)
    output = output_dir / f'Decrumb-{version}-{architecture}-dev.dmg'
    with tempfile.TemporaryDirectory(prefix='dmg-', dir=output_dir) as folder:
        temporary = Path(folder)
        stage = temporary / 'contents'
        stage.mkdir()
        run('/usr/bin/ditto', str(app), str(stage / app.name))
        (stage / 'Applications').symlink_to('/Applications', target_is_directory=True)
        (stage / 'Read me first.txt').write_text(
            'DECRUMB — DEVELOPMENT BUILD\n\n'
            'This is a local test build, not a notarized public release.\n'
            f"Requires Apple Silicon and macOS {info['LSMinimumSystemVersion']} or later.\n\n"
            'Copy Decrumb to Applications before opening it, then eject this disk image.\n'
            'For a manual upgrade: pause the existing cleaner, quit its interface, replace\n'
            'the application, open the replacement and resume if desired.\n'
            'Your linked account and settings remain in Application Support.\n\n'
            'In-app updating is not integrated yet. See the bundled source documentation\n'
            'for the release and update plan. This image has not been published.\n', encoding='utf-8')
        image = temporary / 'Decrumb.dmg'
        run('/usr/bin/hdiutil', 'create', '-volname', 'Decrumb', '-fs', 'APFS',
            '-format', 'ULFO', '-srcfolder', str(stage), str(image))
        run('/usr/bin/hdiutil', 'verify', str(image))
        image.replace(output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.dmg.sha256').write_text(f'{digest}  {output.name}\n')
    print(f'{output}\n{output.stat().st_size / 1_000_000:.2f} MB; SHA-256 sidecar written.')


if __name__ == '__main__':
    main()
