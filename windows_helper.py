#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Portable cleanup with a bundled pure-Python QR encoder for Windows."""
import json
from pathlib import Path
import sys

import portable_cleaner


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        data = sys.stdin.buffer.read(portable_cleaner.MAX_REQUEST + 1)
        if len(data) > portable_cleaner.MAX_REQUEST:
            raise ValueError()
        if sys.argv[1:2] in (['--qr'], ['--qr-terminal']):
            if len(data) > 4096 or not data.startswith(b'sgnl://linkdevice?'):
                raise ValueError()
            import segno
            qr = segno.make(data.decode('utf-8'), error='m', micro=False)
            if sys.argv[1:] == ['--qr-terminal'] and sys.stdout.isatty():
                qr.terminal(out=sys.stdout, compact=True)
            elif len(sys.argv) == 3 and sys.argv[1] == '--qr':
                qr.save(sys.argv[2], kind='png', scale=10, border=4)
            else:
                raise ValueError()
        elif len(sys.argv) == 1:
            rules = portable_cleaner.load_rules(Path(__file__).resolve().parent / 'rules/defaults.json')
            print(json.dumps(portable_cleaner.request(json.loads(data), rules), ensure_ascii=False))
        else:
            raise ValueError()
    except Exception:
        print('Invalid cleanup request.', file=sys.stderr)
        return 65
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
