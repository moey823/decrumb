#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""One release identity for Mac, Raspberry Pi, Umbrel and Windows."""
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def load(root=ROOT):
    value = json.loads((Path(root) / 'release.json').read_text())
    if (not isinstance(value, dict) or set(value) != {'version', 'build', 'channel'} or
            not isinstance(value['version'], str) or
            not re.fullmatch(r'(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)', value['version']) or
            type(value['build']) is not int or not 1 <= value['build'] <= 999999999 or
            value['channel'] not in ('alpha', 'beta', 'rc', 'stable')):
        raise ValueError('release.json must contain a numeric version, positive build number and release channel.')
    version, build, channel = value['version'], str(value['build']), value['channel']
    public = version if channel == 'stable' else version + '-' + channel + '.' + build
    return {'version': version, 'build': build, 'channel': channel, 'public_version': public,
            'tag': 'v' + public,
            'display': version if channel == 'stable' else version + ' ' + channel.upper() + build,
            'pi_archive': 'build/Decrumb-' + version + '-' + build + '-linux-arm64.tar.gz',
            'windows_archive': 'build/windows/Decrumb-' + version + '-' + build + '-windows-x64.zip'}


def resolve(version=None, build=None, root=ROOT):
    release = load(root)
    if ((version is not None and version != release['version']) or
            (build is not None and str(build) != release['build'])):
        raise ValueError('Version and build must match release.json; update the shared release before packaging.')
    return release


def umbrel(root=ROOT, write=False):
    expected = load(root)['public_version']
    path = Path(root) / 'mkships-decrumb/umbrel-app.yml'
    source = path.read_text()
    matches = list(re.finditer(r'^version: "([^"]+)"$', source, flags=re.MULTILINE))
    if len(matches) != 1:
        raise ValueError('Umbrel manifest must contain exactly one quoted version field.')
    if write:
        match = matches[0]
        path.write_text(source[:match.start(1)] + expected + source[match.end(1):])
    elif matches[0].group(1) != expected:
        raise ValueError('Umbrel version differs from release.json. Run tools/release_version.py --write-umbrel.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--field', choices=('version', 'build', 'channel', 'public_version', 'display', 'tag', 'pi_archive', 'windows_archive'))
    actions.add_argument('--check', action='store_true', help='Reject an Umbrel version that differs from the shared release')
    actions.add_argument('--write-umbrel', action='store_true', help='Update the checked-in store version from release.json')
    args = parser.parse_args()
    release = load()
    if args.check or args.write_umbrel:
        umbrel(write=args.write_umbrel)
        print('Mac, Pi, Umbrel and Windows release: ' + release['display'] + ' (build ' + release['build'] + ')')
    elif args.field:
        print(release[args.field])
    else:
        print(json.dumps(release, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError):
        raise SystemExit('Release metadata is invalid or inconsistent; check release.json and the Umbrel manifest.')
