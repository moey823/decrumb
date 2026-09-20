#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Build Decrumb's Swift components; --app also bundles Python and Signal CLI."""
import argparse
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / 'build'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', action='store_true', help='Build a standalone .app, fetching pinned dependencies as needed')
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    compiler = ['xcrun', 'swiftc', '-O', '-swift-version', '5', '-target', platform.machine() + '-apple-macos14.0',
                '-module-cache-path', str(OUTPUT / 'ModuleCache')]
    subprocess.run(compiler + [str(ROOT / 'swift/SidecarURLCleaner.swift'), str(ROOT / 'swift/main.swift'),
                              '-o', str(OUTPUT / 'url-cleaner')], check=True)
    shutil.copyfile(ROOT / 'rules/defaults.json', OUTPUT / 'rules.json')
    subprocess.run(compiler + ['-parse-as-library', str(ROOT / 'app/WorkerStatus.swift'), str(ROOT / 'app/SideletApp.swift'), '-o', str(OUTPUT / 'Decrumb')], check=True)
    subprocess.run(compiler + ['-parse-as-library', str(ROOT / 'app/WorkerStatus.swift'), str(ROOT / 'tests/StatusTests.swift'), '-o', str(OUTPUT / 'status-tests')], check=True)
    if args.app:
        subprocess.run(compiler + [str(ROOT / 'app/MakeIcon.swift'), '-o', str(OUTPUT / 'make-icon')], check=True)
        subprocess.run([str(OUTPUT / 'make-icon'), str(OUTPUT / 'AppIcon.iconset')], check=True)
        subprocess.run(['iconutil', '-c', 'icns', str(OUTPUT / 'AppIcon.iconset'), '-o', str(OUTPUT / 'AppIcon.icns')], check=True)
        subprocess.run([sys.executable, '-B', str(ROOT / 'tools/build_app.py')], check=True)
    else:
        print('Swift helper and interface built. Use --app for the standalone bundle.')


if __name__ == '__main__':
    main()
