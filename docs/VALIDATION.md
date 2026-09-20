# Desktop app validation — 2026-09-20

Environment: Apple Silicon, macOS 27.0, Swift 6.4 compiler (Swift 5 language mode),
Python 3.14.6, PyInstaller 6.22.3, bundled native signal-cli 0.14.8.

## Completed

- `python3 build.py --app`: compiled both Swift executables and icon; packaged the
  Python runtime and checksum-verified native Signal CLI; ad-hoc signing and strict
  recursive signature verification succeeded.
- `python3 -B -m unittest discover -s tests -p 'test_*.py' -v`: **72 tests passed**.
  Covers legacy behavior, normalized site rules, exclusions, keep/remove precedence,
  signed links, nested URLs, input limits, cancellation, durable metrics, private
  status output, service ownership, installation updates, rule persistence and
  local retention cleanup independent of Signal connectivity. Lifecycle tests
  cover receipt allowlists, mismatched accounts, ambiguous acknowledgements,
  lifetime/Keep overrides, persisted sweeps, retry/backoff/window limits,
  metadata retention, sender sanitization and read-only status. Bridge tests
  cover paused cleanup batches, no receive subscription, queue clearing,
  discard-on-pause and restoration of the active worker after invalid mutations.
- `build/status-tests`: passed native status parsing, field filtering, bounded
  reads, stale/dead-worker detection and atomic-replacement notification checks.
  A 1,000-read synthetic benchmark averaged 33.83 microseconds per read.
- `python3 -B tools/smoke_app.py`: packaged worker bootstrapped and previewed with
  no Homebrew on PATH. Fake Signal pairing produced a local QR and cancellation
  removed it. Two identical synthetic incoming events produced exactly one Note
  to Self send; worker shutdown and content-free output passed. The real bundled
  Signal executable was invoked only with `--version`.
- Packaged lifecycle smoke checks the attributed Decrumb note and random marker,
  content-free receipt listing, and a fake-Signal removal request restricted to
  Note to Self and the original acknowledged send timestamp. The expected state
  is `deletion_requested`, not an erasure confirmation.
- Native app UI inspected in `--demo`: onboarding layout and synthetic QR, settings
  fields, custom rule validation, and local preview showing removal of `igsh` while
  preserving `img_index`. Demo mode does not read or change the real runtime.
- Renamed Decrumb interface inspected in its unlinked setup state: Saved notes,
  sender option, manual/lifetime/sweep selectors, local queue controls and empty
  receipt state render correctly. Draft mode changes were not saved; no pairing
  or service controls were invoked during this visual check.
- `git diff --check`: passed.

macOS graphics and process semaphore operations need normal OS access. The
restricted tool sandbox failed QR rendering and frozen-runtime startup; both
passed when run with normal OS access. These are not skipped application tests.

## Boundaries

No real Signal account was opened, paired, or messaged. No production/Mac mini
runtime was read or deployed. No shared flight log or business wiki was changed.
LaunchAgent mutations were tested through mocks; an actual login/logout cycle was
not performed on this user's account. A live incoming-message acceptance check
remains necessary when an installation is explicitly deployed.
Real-device removal, deleted-message marker rendering and timing while devices
are offline remain unverified; the interface describes requests as best effort.

The development bundle declares macOS 27.0 because that is the only OS tested for
this packaging build. Build/test on older supported macOS before lowering the
minimum; the live mini's macOS 26.4 is not covered by this artifact. Public release
also requires Developer ID signing, notarization, and complete source/notices for
redistributed dependencies (see THIRD-PARTY.md).
