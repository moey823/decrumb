#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Build Decrumb's Swift components; --app also bundles Python and Signal CLI."""
import argparse
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from tools import build_app

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / 'build'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', action='store_true', help='Build a standalone .app, fetching pinned dependencies as needed')
    build_app.add_release_arguments(parser)
    args = parser.parse_args()
    if args.production and not args.app:
        raise SystemExit('Production requires --app.')
    try:
        options = build_app.release_options(args)
        if args.production:
            build_app.validate_release_materials(options['materials'], options['version'], options['build_number'])
            build_app.resolve_developer_identity(options['identity'])
    except build_app.ReleaseError as error:
        raise SystemExit(str(error)) from None
    OUTPUT.mkdir(parents=True, exist_ok=True)
    target_minimum = args.minimum_macos or '14.0'
    compiler = ['xcrun', 'swiftc', '-O', '-swift-version', '5', '-target', platform.machine() + '-apple-macos' + target_minimum,
                '-module-cache-path', str(OUTPUT / 'ModuleCache')]
    subprocess.run(compiler + [str(ROOT / 'swift/DecrumbURLCleaner.swift'), str(ROOT / 'swift/main.swift'),
                              '-o', str(OUTPUT / 'url-cleaner')], check=True)
    shutil.copyfile(ROOT / 'rules/defaults.json', OUTPUT / 'rules.json')
    subprocess.run(compiler + ['-parse-as-library', str(ROOT / 'app/WorkerStatus.swift'), str(ROOT / 'app/DecrumbApp.swift'), '-o', str(OUTPUT / 'Decrumb')], check=True)
    subprocess.run(compiler + ['-parse-as-library', str(ROOT / 'app/WorkerStatus.swift'), str(ROOT / 'tests/StatusTests.swift'), '-o', str(OUTPUT / 'status-tests')], check=True)
    if args.app:
        subprocess.run(compiler + [str(ROOT / 'app/MakeIcon.swift'), '-o', str(OUTPUT / 'make-icon')], check=True)
        subprocess.run([str(OUTPUT / 'make-icon'), str(OUTPUT / 'AppIcon.iconset')], check=True)
        subprocess.run(['iconutil', '-c', 'icns', str(OUTPUT / 'AppIcon.iconset'), '-o', str(OUTPUT / 'AppIcon.icns')], check=True)
        arguments = []
        if args.production:
            arguments.append('--production')
        for name in ('version', 'build_number', 'minimum_macos', 'signing_identity', 'release_materials'):
            value = getattr(args, name)
            if value is not None:
                arguments += ['--' + name.replace('_', '-'), str(value)]
        subprocess.run([sys.executable, '-B', str(ROOT / 'tools/build_app.py'), *arguments], check=True)
    else:
        print('Swift helper and interface built. Use --app for the standalone bundle.')


if __name__ == '__main__':
    main()
