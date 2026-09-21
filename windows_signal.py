#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Private stdio bridge: contain Java before launch; never print upstream errors."""
import argparse
import subprocess
import sys
import windows_native


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--java', required=True)
    parser.add_argument('--libraries', required=True)
    parser.add_argument('--temporary', required=True)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    windows_native.contain_children()
    arguments = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    return subprocess.call([args.java, '-Djava.io.tmpdir=' + args.temporary,
                            '-cp', args.libraries, 'org.asamk.signal.Main', *arguments],
                           stdin=sys.stdin.buffer, stdout=sys.stdout.buffer,
                           stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        raise SystemExit(1) from None
