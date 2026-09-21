# Desktop app validation — 2026-09-20

Environment: Apple Silicon, macOS 27.0, Swift 6.4 compiler (Swift 5 language mode),
Python 3.14.6, PyInstaller 6.22.3, bundled native signal-cli 0.14.8.

## Completed

- `python3 build.py --app`: compiled both Swift executables and icon; packaged the
  Python runtime and checksum-verified native Signal CLI; ad-hoc signing and strict
  recursive signature verification succeeded.
- `python3 -B -m unittest discover -s tests -p 'test_*.py' -v`: **134 tests passed**.
  Covers baseline behavior, normalized site rules, exclusions, keep/remove precedence,
  signed links, nested URLs, input limits, cancellation, durable metrics, private
  status output, service ownership, installation updates, rule persistence and
  local retention cleanup independent of Signal connectivity. Lifecycle tests
  cover receipt allowlists, mismatched accounts, ambiguous acknowledgements,
  lifetime/Keep overrides, persisted sweeps, retry/backoff/window limits,
  metadata retention, sender sanitization and read-only status. Bridge tests
  cover paused cleanup batches, no receive subscription, queue clearing,
  discard-on-pause and restoration of the active worker after invalid mutations.
  Release tests cover source/notice checksums, private-file exclusions, signing
  requirements, deployment floors, notarization failure, and immutable outputs.
- Sparkle 2.10.0 updater checks passed on macOS 27.0. The isolated signed
  integration harness passed **10 scenarios**: active install, paused install,
  dismissed manual update followed by ordinary quit, automatic install-on-quit,
  unsaved settings deferral, pairing deferral, forced GUI crash during handoff,
  cancellation, tampered feed and tampered archive. It uses the production Swift
  coordinator and Python transition code, Developer ID signed fixture builds
  1 and 2, official EdDSA signing and actual Sparkle replacement/relaunch.
  Synthetic account, queued-work and receipt bytes survived unchanged. A real
  synthetic process held the worker lock; Signal and LaunchAgents were replaced
  by fixture adapters. See [UPDATE-ACCEPTANCE.md](UPDATE-ACCEPTANCE.md).
- The official appcast generator was exercised against a packaged development
  app in a temporary, unpublished directory. Public-key matching, generated
  version/OS/architecture/URL/size validation, and official archive/feed signature
  verification passed. Production packaging repeats these checks on the actual
  notarized release; a development fixture is never published.
- `build/status-tests`: passed native status parsing, field filtering, bounded
  reads, stale/dead-worker detection and atomic-replacement notification checks.
  A 1,000-read synthetic benchmark averaged 33.83 microseconds per read.
- `python3 -B tools/smoke_app.py`: packaged worker bootstrapped and previewed with
  no Homebrew on PATH. Fake Signal pairing produced a local QR and cancellation
  removed it. Two identical synthetic incoming events produced exactly one Note
  to Self send; worker shutdown and content-free output passed. The real bundled
  Signal executable passed `--version` and `listAccounts` against an isolated,
  empty temporary configuration, which also exercises its native JNI library.
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
- A development DMG built successfully, passed image checksum verification, and
  measured 57.40 MB before adding production source notices.
- Hardened-runtime probing established that the bundled Signal executable needs
  `com.apple.security.cs.disable-library-validation` to load its embedded JNI
  library. Only that helper receives the exception; the empty-configuration
  native-library check is required during production builds and packaging.
- The corresponding-source collector verified 2,010 dependency/source/notice
  files with no unresolved dependency gaps. Production rebuilds validate their
  hashes against the exact application source and frozen native dependencies.
- The packaged smoke test also passed on an Apple Silicon Mac running macOS
  26.4, using a temporary copy built with an explicit 26.4 deployment target.
  The copy was removed afterward. No application was installed or real runtime
  opened during this compatibility test.
- Release candidate 1.0.0, build 1, is Developer ID signed using the personal
  publisher team. Apple accepted both app and DMG submissions. Both tickets were
  stapled and validated, and Gatekeeper accepted the app and image. The hosted
  66,800,212-byte DMG SHA-256 is
  `e0a937e3b2e2694a0b573b9fdfa65fc811b7b0bf5abbbb0fee0828d5794b53af`.
  The release tag `v1.0.0-rc.1` identifies its source commit and matching materials;
  subsequent documentation updates do not alter those immutable artifacts.
- The exact public DMG was downloaded independently on macOS 26.4 (Apple
  Silicon). Its published checksum, image integrity, app/image signatures,
  stapled tickets, and Gatekeeper assessments passed. The complete synthetic
  packaged smoke passed from its read-only mount using system Python 3.9.6,
  including Decrumb names, resource loading, pairing cancellation, self-only
  delivery/removal, and native Signal library loading. The mount and temporary
  files were removed. This was not an installation or real-account test.
- RC2/build 2 is published from source commit `a464bd4f5d035d23cc17528c9e7fe30f786500f4`.
  Apple accepted and stapled its app and DMG; Gatekeeper accepted both. All nine
  GitHub assets match their local SHA-256 hashes. The 67,561,986-byte DMG SHA-256
  is `b3ca25454b5f2bcd403ede544c1995a703e18aabfcfba46fc274cfaf06bb9116`.
  The public DMG and update archive were downloaded independently and their
  checksums verified. The downloaded image passed integrity, stapled-ticket,
  Gatekeeper and complete packaged smoke checks from a read-only mount, which
  was then detached. The live HTTPS appcast matches the release byte for byte;
  official Sparkle verification accepted its signature and the downloaded
  update archive's signature. The RC2 download, privacy and support pages are
  live. Later documentation commits do not change the immutable RC2 artifacts.

macOS graphics and process semaphore operations need normal OS access. The
restricted tool sandbox failed QR rendering and frozen-runtime startup; both
passed when run with normal OS access. These are not skipped application tests.

## RC3 automatic-start validation

RC3 starts cleaning after successful pairing and every time the
linked app is opened, including Finder/menu-bar reopen and update relaunch.
Pause now lasts until reopening or choosing Resume cleaning. Start at login
remains optional. Opening an already running cleaner does not restart it.

- The 150-test offline suite passed, followed by the updated 21-test updater
  suite including one additional paused-cancellation regression: 151 tests total.
- Startup fixtures cover unlinked setup, old paused setup after pairing, paused
  and active reopen, failed starts, moved helper paths, pending update exclusion,
  and read-only status. They use temporary accounts and mocked LaunchAgents.
- Native status tests cover starting, running, paused, failed, and expired-start
  states. Connection failures offer Retry connection instead of Resume cleaning.
- The packaged synthetic Signal smoke passed: pairing cancellation, local
  preview, self-only delivery/removal, deduplication, and native library loading.
- Four signed Sparkle scenarios passed again: active install, paused install
  that starts on relaunch, forced GUI interruption/recovery, and cancellation.
  Synthetic account, queue, and receipt bytes survived unchanged.

- RC3/build 3 is published from source commit
  `79e54b98bf7399199eae3ee19c59f1cb2d6ee1bf`. Apple accepted both app and DMG;
  their tickets were stapled and verified. The 67,772,336-byte public DMG SHA-256
  is `803f4ec233079fa5af1d1044384d095b14037d3ed6bf70733d5caf8bf262c21c`.
- All nine GitHub asset sizes and SHA-256 digests match the local artifacts. The
  public DMG, update archive and feed were downloaded independently and verified.
  The downloaded DMG passed integrity, stapled-ticket, Gatekeeper and packaged
  synthetic smoke checks from a read-only mount, then was detached. Official
  Sparkle tools accepted the downloaded feed and archive signatures.

These checks do not establish real-account or actual login-session behavior.

## Boundaries

No real Signal account was opened, paired, or messaged. No live runtime was read
or deployed. No shared flight log or business wiki was changed.
LaunchAgent mutations were tested through mocks; an actual login/logout cycle was
not performed on this user's account. A live incoming-message acceptance check
remains necessary when an installation is explicitly deployed.
Real-device removal, deleted-message marker rendering and timing while devices
are offline remain unverified; the interface describes requests as best effort.

The release candidate targets Apple Silicon and macOS 26.4 or later. Packaged
worker checks pass on macOS 26.4 and 27.0; the native interface was inspected on
27.0. Downloaded installation, real-account behavior, and interface acceptance
on 26.4 remain separate release checks. Candidate signing and notarization have
completed successfully; real-device acceptance remains before stable release.
