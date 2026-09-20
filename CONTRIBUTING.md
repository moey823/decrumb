# Contributing to Decrumb

Decrumb is an AGPL-3.0-only macOS project. Bug reports, focused fixes, and cleaner
rule improvements are welcome. For a larger feature, open an issue describing
the user problem before starting an implementation.

## Safe reports and fixtures

Use invented messages, contacts, account identifiers, and example.org URLs.
Never attach account files, pairing QR codes, real messages, runtime databases,
or raw logs. For a cleaning bug, provide a synthetic input URL, the current
output, and the expected output. A public issue is visible to everyone.

Security vulnerabilities should use [private vulnerability reporting](SECURITY.md);
do not publish account data or an exploit against a real user.

## Local checks

On macOS with Apple command-line tools and Python 3.13 or newer:

```sh
python3 build.py
build/status-tests
python3 -B -m unittest discover -s tests -p 'test_*.py' -v
```

The suite uses synthetic offline fixtures. Building an app with `--app` fetches
pinned public dependencies; the normal source checks do not need a Signal
account. See [README.md](README.md) for packaging and the isolated fake-Signal
smoke test. Do not use a live linked account for automated tests.

Preserve Note to Self as the only automated send destination, outgoing-message
loop protection, privacy exclusions, account-bound removal receipts, and bounded
local storage. Rules must remain data rather than executable plugins. Add a
regression test when changing these behaviors.

Keep generated files and all runtime state out of commits. Preserve license
headers and update [source provenance](docs/PROVENANCE.md) when importing code.
Describe what changed and which checks passed in your pull request.
