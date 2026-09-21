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

## RC4 Raspberry Pi and phone-command validation

Published 2026-09-20 from source commit
`d78fe487dbfed0f9df0d58c8997b474f0ece9876`, tagged `v1.0.0-rc.4`.

- The 215-case synthetic suite completed on macOS, Linux x86_64 and Linux ARM64,
  with one platform-specific skip on each. Native Swift status tests passed.
  [The final source CI run](https://github.com/moey823/decrumb/actions/runs/35550700233)
  also passed real ARM64 user-systemd startup, fresh heartbeat readiness,
  self-only synthetic delivery, pause, resume and cleanup.
- The portable cleaner matches the Mac helper on 186 shared synthetic cases.
  Conservative URL detection differences, including leaving raw Unicode hosts
  untouched, are documented in [URL-CLEANUP.md](URL-CLEANUP.md).
- Independent code review covered installer ownership and rollback, runtime/code
  separation, service escaping/readiness, portable URL handling and phone-command
  authentication. Regression checks cover malformed and Unicode hosts, real
  systemd parsing of special paths, failed activation, forged or private events,
  replay, duplicate suppression and reply-loop protection.
- The public Pi archive was downloaded and matched its checksum. In an isolated,
  unprivileged ARM64 Debian Bookworm container with networking disabled, it passed
  fresh installation, real native Signal dependency loading with an empty account,
  local preview, private QR generation, reinstall preservation of synthetic state,
  and rejection of a corrupt dependency before changing the installation.
  Terminal QR output was also verified using a synthetic pairing URI.
- The Pi archive is 494,370 bytes; SHA-256:
  `bef353018a71148b9bf610dbdfa2115bba5a6a0439ea7b3dfba2ea6bf6630351`.
- The Mac release verified 2,010 source/dependency/notice files with no unresolved
  gaps. Apple accepted both the app and DMG. Their tickets were stapled and
  validated, and Gatekeeper accepted both. The DMG is 69,501,285 bytes; SHA-256:
  `7711a8d4df3bc9abb6a66afd8b19f45aa9f53395971c850345dd59703527d8bf`.
- All eleven GitHub asset sizes and SHA-256 digests match the local artifacts.
  The public Mac DMG, update archive and signed feed were downloaded independently.
  The downloaded app passed signature, ticket, Gatekeeper and packaged synthetic
  smoke checks from a read-only mount: preview, pairing cancellation, self-only
  delivery/removal, incoming and command deduplication, optional phone commands,
  and actual native dependency loading. The mount was detached afterward.
  Official Sparkle tools accepted both downloaded feed and archive signatures.
- mkships publication `6ae6fdb8bf903823bcadd1becad11ae5b0d81290` passed 30
  headless layout/link checks across six pages and five viewport widths. The live
  homepage, Decrumb overview, download, help and privacy pages, and signed updater
  feed returned HTTP 200 and matched the published files byte for byte.

These checks use synthetic fixtures and empty native account stores. They do not
establish physical Pi pairing, boot/logout, network recovery, sustained resource
use, or live Signal behavior. The Pi edition remains experimental. Later
release-documentation commits do not change the immutable RC4 source tag or assets.

## RC5 phone-command regression

RC4's fake transport incorrectly included an account UUID in `listAccounts`;
the pinned upstream 0.14.8 response provides only `number`. Authentic Note to
Self transcripts contain UUID fields too, so the strict owner check rejected
them. A content-free diagnostic on the deployed Mac confirmed the number-only
response and a single matching self-recipient record containing its UUID.

The transport and packaged fixtures now reproduce that upstream contract.
RC5 looks up only the linked account, verifies a unique number/UUID match, and
fails closed on missing, malformed, conflicting or ambiguous identity data.
Existing tests still reject peer commands, conflicting aliases, non-self
recipients, private/control events, stale/replayed commands and reply loops.
No actual message content or account identifiers were printed or committed.

- The 219-case suite passed on macOS, Linux x86_64 and Linux ARM64, with one
  platform-specific skip each. The actual ARM systemd service checks passed in
  [final-source CI](https://github.com/moey823/decrumb/actions/runs/35552431025).
- RC5 is published from `80303eece3a9e87d456bec3d2ccf4bbeff440765`.
  All eleven asset sizes and SHA-256 digests match their local counterparts.
  Both Apple notarization submissions were accepted and stapled. The
  68,476,895-byte DMG SHA-256 is
  `a9df61c275d72e3ab43ffd91d35877589fb6843b45dc606a36431b7b212988b7`.
- The public Mac download passed image integrity, Gatekeeper, stapled tickets,
  strict signatures and packaged synthetic tests, including number-only account
  listing followed by verified UUID lookup and a UUID-bearing command reply.
  Official Sparkle tools verified the downloaded update archive and signed feed.
  The downloaded Pi archive passed the isolated ARM64 installation checks.
- The deployed Mac downloaded the public DMG, verified its checksum, publisher,
  signatures and notarization, then replaced RC4 with RC5. Pairing configuration
  and queue/receipt database bytes remained unchanged across replacement; all
  existing configuration values survived relaunch. With commands enabled, the
  real self-identity lookup completed and the new worker reported a fresh running
  heartbeat. A fresh phone-to-Note-to-Self command test remains separate from
  these startup and synthetic checks.
- The RC5 website passed 30 local headless checks. The public download and help
  pages and signed feed match publication `036f5b3f2f8a658e415991a56d22d97f2dc31439`
  byte for byte and return HTTP 200.

## Umbrel community preview, 2026-09-21

- Image source: `0b717d11e685ef02af20eaad11f5f0792e6735d9`. The full
  [Mac/AMD64/ARM64 regression run](https://github.com/moey823/decrumb/actions/runs/35596751982)
  passed, including 237 Python tests (one platform-specific skip) and native Mac
  status checks. Eighteen browser/backend tests cover authentication, same-origin
  controls, input bounds, privacy, pairing transitions, recovery, persistence,
  checksum rejection, and native subprocess cleanup.
- [Container checks](https://github.com/moey823/decrumb/actions/runs/35596751734)
  built and tested both architectures natively. Each verified its pinned real
  signal-cli binary and an isolated empty account, then exercised browser login,
  real QR rendering with a synthetic link, cancellation, synthetic pairing,
  automatic startup, phone-command enablement, preview, pause/resume, and state
  preservation across controller recreation. No real Signal account was linked.
- The first native runs caught an over-strict ARM version-display check and an
  undersized RAM-backed temporary directory for AMD64's extracted native library.
  The final package accepts the pinned build's display suffix, retains exact
  archive verification, and uses private disk-backed temporary storage.
- The public multiarchitecture image is pinned in `mkships-decrumb/docker-compose.yml`.
  Anonymous registry checks verified both architecture manifests. Compressed
  layers total 44,339,195 bytes (AMD64) and 44,828,565 bytes (ARM64); the Signal
  dependency is downloaded separately, not bundled in those layers.
- Local headless browser checks passed login, offline preview, saving/reloading
  settings, conditional controls, logout, and layouts at 375/768/1280 pixels.
  The Umbrel YAML and merged Compose config passed validation with synthetic
  credentials, including the proxy target, UID, private mounts, read-only image,
  enabled proxy authentication, and absence of host-published backend ports.
- Updated mkships pages passed 30 headless layout/link checks. The preview is a
  community-store distribution, not an official Umbrel listing. Installation on
  an actual Umbrel device, its login proxy, and real phone-to-Signal behavior still
  need acceptance testing. Existing Mac mini linking and runtime were untouched.

## RC6 private local diagnostics

Published 2026-09-21 from source commit
`a0766e98e8577e834a14716010228151b266b0e2`, tagged `v1.0.0-rc.6`.

- The 257-case suite passed on macOS, Linux AMD64 and Linux ARM64, with
  platform-specific skips, in [final-source release checks](https://github.com/moey823/decrumb/actions/runs/35616482898).
  Native Mac status checks and the ARM64 Pi installation/systemd smoke passed.
  New cases cover report allowlisting, raw-error exclusion, legacy log removal,
  bounded retention, concurrent writers, interrupted writes, broken configuration,
  and clearing diagnostics without altering account or application state.
- Both native architectures passed [container checks](https://github.com/moey823/decrumb/actions/runs/35616089916)
  from image source `dcd4195c379fd0585f82b54f06db8d6e8c000385`.
  The container smoke verifies the diagnostic report's release identity as well
  as the existing authenticated dashboard and synthetic Signal lifecycle.
  The first RC6 container run exposed missing build-context allowlist entries;
  the tested image includes both diagnostics and release metadata.
- Native Mac Diagnostics was inspected using the synthetic demo profile.
  Headless dashboard checks passed report preview, copy/fallback, clearing,
  logout cleanup, and mobile layout. The mkships pages passed 48 local layout
  checks across light/dark themes and 320/390/768/1440-pixel widths, plus
  13 internal-link checks.
- All eleven hosted asset sizes and SHA-256 digests match their local files.
  Both Apple notarization submissions were accepted and stapled. The
  66,794,007-byte DMG SHA-256 is
  `bdce3bdd019721b48add95a0a224d8f063f1974dd090b8751675549fa7589b65`.
  The public 519,068-byte Pi archive matches the tested local package.
- The downloaded Mac DMG and app passed image integrity, strict code signatures,
  Gatekeeper, stapled-ticket checks and packaged synthetic smoke. Official Sparkle
  tools verified both the downloaded update archive and the signed appcast.
- The public mkships pages and build 6 update feed return HTTP 200 and match
  publication `f37ef7b02a2b478319401699e4c1606e160dfa9b` byte for byte, including
  the new release-notes page. The hosted feed is identical to the verified,
  signed release asset.
- No linked installation was updated during this release. Updating an existing
  linked installation through Check for Updates remains an owner-run acceptance
  check. Physical Pi, Umbrel-device and real Signal acceptance remain separate.

## Boundaries

The automated release suites use synthetic fixtures and isolated empty Signal
stores. The separately authorized RC5 deployment and self-identity diagnostic
above accessed the existing linked installation without exposing its identifiers
or message contents. They did not relink it or initiate test messages.
No shared flight log or business wiki was changed.
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
