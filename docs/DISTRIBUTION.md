# Decrumb distribution and updates

## One version for every platform

`release.json` is the release source of truth for Mac, Raspberry Pi, Umbrel, and Windows.
The current source release is **Decrumb 1.1.3**: Mac/Pi/Windows version `1.1.3`,
build `10`, and Umbrel version `1.1.3`. This release is in preparation; see the
[release preparation record](RELEASE-1.1.3.md).
Platform names belong in artifact names, not in
independent version sequences. Experimental platform support does not change the
shared application version. Release 1.1.2 Mac/Pi artifacts remain published; the Mac
app and DMG are signed, Apple-notarized and stapled. The tested Umbrel image is
published and pinned. Hosted acceptance passed, and the verified signed Mac feed
now offers 1.1.2/build 9 through **Check for Updates**.
Source version changes alone do not update installed apps or containers.

For the next release, update the version, monotonically increasing build number,
and channel in `release.json`, then run:

```sh
python3 tools/release_version.py --write-umbrel
python3 tools/release_version.py --check
```

Mac and Windows builds and Pi packaging use these defaults. Explicit version or
build arguments must match the file. CI rejects a divergent Umbrel manifest and
derives the Pi archive path from the same metadata. Container CI supplies the
same public version to the OCI version label; immutable source-commit image tags
and digests still identify the exact platform build.

Keep published binaries and tags immutable. The original Umbrel `0.1.0` preview
is historical. Store updates must pin a tested image of the matching new release;
changing only the store's version label is not a platform update.
Release notes group all platform downloads under one Decrumb tag.

## 1.1.3: Mac update recovery and complete Quit

Build 10 keeps update coordination with the native app across helper launches,
bounds recovery-service operations and makes blocked-install reasons and retry
actions visible. **Quit Decrumb** stops cleaning and preserves queued links,
sent-note records, the linked account, settings and Start at login preference.
**Hide Decrumb** keeps cleaning active while hiding the windows. Reopening resumes
cleaning. A pending update keeps its recovery checkpoint until installation can
be reconciled on a later launch, without a Quit-created watchdog reopening the app.

Mac packaging and general publication are pending. The 1.1.3 store manifest
now pins the tested ARM64 and AMD64 image from source `7ef5e4a`; see
[UMBREL.md](UMBREL.md) for its immutable digest and validation evidence.

## 1.1.2: disappearing messages and visible cleaning rules

Build 9 cleans links in incoming disappearing messages and accepts authenticated
phone commands when Note to Self has a disappearing-message timer. Generated notes
follow the Note to Self timer and configured note-cleanup policy; the source chat's
timer is not copied. View-once content, spoilers and loop exclusions remain.

Mac **Settings → Cleaning rules → View domains and rules** shows the installed
defaults, including global parameters, Instagram and X/Twitter rules, exceptions,
and limits. The update packager embeds version-specific notes in its signed feed
so the release-notes box has content to display.

Release source `d88d022570931fdedc62c5f62ebf58f50b3a0223` passed
[Mac/Linux CI](https://github.com/moey823/decrumb/actions/runs/36154172238) and
[native Windows CI](https://github.com/moey823/decrumb/actions/runs/36154175687).
The offline suite passed 279 tests with 4 platform skips (283 total), and the
build/native status checks passed. Development and production packaged synthetic
smoke verified disappearing X-link cleaning and phone commands. All ten signed
Sparkle acceptance scenarios passed.

[Container CI](https://github.com/moey823/decrumb/actions/runs/36153723444) built,
tested and published both architectures from source
`b03d5a4701ab0b5e62a521ebca2513254a5f678e`. The immutable digest is pinned and
anonymously verified; see [UMBREL.md](UMBREL.md) for image provenance.

Published September 25, 2026: [Decrumb 1.1.2](https://github.com/moey823/decrumb/releases/tag/v1.1.2).
Tag `v1.1.2` identifies source `d88d022570931fdedc62c5f62ebf58f50b3a0223`.
The app and DMG have accepted Apple notarizations, stapled tickets and passing
Gatekeeper assessments. All eleven public GitHub asset sizes and SHA-256 digests
match the local artifacts. Downloaded checksums, signatures, stapled tickets,
Gatekeeper assessments and all six packaged smoke groups passed against an
isolated installed copy of the downloaded app. Official Sparkle verification
accepted the downloaded archive and feed, including the expected embedded notes.
Mkships commit `d42de5659f52a51dc7c542774c98154aaa5f1482` deployed the feed and
updated download, release, privacy and support pages. GitHub Pages built
successfully; every live file matches its expected bytes, and the downloaded
live feed passed official Sparkle signature verification. **Check for Updates**
now offers 1.1.2/build 9. See [RELEASE-1.1.2.md](RELEASE-1.1.2.md) for evidence
and the mounted-DMG smoke timing limitation.
Windows remains an unsigned source-build preview; live-device validation limits
are unchanged.

## 1.1.1: X/Twitter link cleanup and status version

Build 8 removes the `s` and `t` share parameters from X/Twitter links and adds
the running version/build to the optional `/decrumb status` reply. These changes
use the shared cleaner and phone-command implementation.

Tag `v1.1.1` records source commit `3b955b92eabe77ffb1809099484b432a23cdf53f`.
The 67.2 MB Mac DMG and app are Developer ID signed, Apple-notarized and stapled.
The matching corresponding-source archive, signed Sparkle archive/feed, checksums
and release receipt are published. Packaged synthetic smoke and all ten signed
Sparkle acceptance scenarios passed. The Python suite passed 272 tests with
4 skipped (276 total); Mac status tests passed. The fresh bundle reports 1.1.1,
build 8, and its X/Twitter cleanup was verified.

The source passed [Mac/Linux checks](https://github.com/moey823/decrumb/actions/runs/36140645832)
and [native Windows checks](https://github.com/moey823/decrumb/actions/runs/36140649249).
The matching Pi archive is published. Both Umbrel architectures passed
[container checks and publication](https://github.com/moey823/decrumb/actions/runs/36140653704);
their tested digest is pinned on `main` and verified publicly accessible. See
[UMBREL.md](UMBREL.md) for exact image provenance. Windows remains a source-build
preview; existing live-device validation limits still apply.

Published 2026-09-25: [Decrumb 1.1.1](https://github.com/moey823/decrumb/releases/tag/v1.1.1).
All eleven hosted assets match their local sizes and GitHub SHA-256 digests.
The downloaded Mac DMG passed signature, stapled-ticket, Gatekeeper and packaged
smoke checks. Downloaded update/archive signatures passed official Sparkle
verification. At publication, the live signed feed advertised build 8 with
identical bytes and **Check for Updates** offered it. See the complete evidence in
[RELEASE-1.1.1.md](RELEASE-1.1.1.md). Historical release assets remain immutable.

## 1.1.0: native Windows CLI

Build 7 adds a native Windows x64 CLI, private per-user state, terminal QR pairing,
background controls, optional login startup, and shared rules/note management.
All platform packages derive their version from the same metadata. Windows
builds are unsigned and experimental; see [WINDOWS.md](WINDOWS.md).

Published 2026-09-21: [Decrumb 1.1.0](https://github.com/moey823/decrumb/releases/tag/v1.1.0),
from source `27c41e493a462d9d201be15b5e688b8fbe83b821`. The 67.6 MB Mac DMG
is Developer ID signed, Apple-notarized and stapled. Its corresponding-source
archive, signed Sparkle archive/feed, checksums and release receipt accompany
the matching Pi installer. Mac v1/RC6 users can update to build 7. Existing
v1.0.0 artifacts and historical tags stay immutable.

Windows is available as an unsigned source-build preview; the tested development
ZIP is not promoted to a supported public binary. Windows signing, Java/JNI
source-and-notice review, live pairing and sleep/wake checks remain separate gates.

Both Umbrel architectures passed their native dependency and lifecycle checks
and are published at the pinned digest in [UMBREL.md](UMBREL.md). The shared
source passed [Mac/Linux release checks](https://github.com/moey823/decrumb/actions/runs/35630767712)
and [native Windows checks](https://github.com/moey823/decrumb/actions/runs/35630558407).
Packaged Mac smoke covered bootstrap, previews, pairing cancellation, incoming
processing, deduplication, Note-to-Self delivery, removal and phone commands using
synthetic fixtures; the real Signal client was probed with an empty account.

## V1: promotion of build 6

On 2026-09-21 the owner chose to close v1 scope and promote RC6 as
[Decrumb 1.0.0](https://github.com/moey823/decrumb/releases/tag/v1.0.0).
The stable tag points to the exact RC6 source commit
`a0766e98e8577e834a14716010228151b266b0e2`. Mac and Pi artifacts, corresponding
sources, checksums, signatures, receipts and the signed appcast are unchanged.
The Umbrel store labels the existing tested image `1.0.0` without replacing its
immutable digest. RC6 users already have v1; older Mac builds still update to 6.

The original build receipts, packaged channel metadata and image labels retain
RC6 provenance. The appcast continues to reference the immutable RC6 update
archive. Both release tags and all existing download URLs remain available.
`release.json` on main records the stable promotion for future builds. Any future
rebuild must use a higher build number and publish new matched materials.

Additional hardware and live Signal checks remain recorded as follow-up validation in
[V1-READINESS.md](V1-READINESS.md); Pi and Umbrel support remain experimental.

## RC6: private local diagnostics

Published 2026-09-21: [Decrumb 1.0.0 RC6](https://github.com/moey823/decrumb/releases/tag/v1.0.0-rc.6),
from source commit `a0766e98e8577e834a14716010228151b266b0e2`. All eleven
hosted assets match their local sizes and SHA-256 digests. The 66.8 MB Mac DMG
is signed, notarized and stapled; the Pi archive is 519,068 bytes.

RC6 adds a previewable, manually copied diagnostic report on every platform.
It replaces timed activity logging with bounded local error codes and adds no
automatic telemetry, crash upload, analytics SDK or hosted service. The report
excludes messages, links, contacts, identities, rules, activity counts and exact
event times. Read the [release notes](RELEASE-NOTES.md) and
[validation evidence](VALIDATION.md#rc6-private-local-diagnostics).

The Umbrel store pins the tested multiarchitecture image built from
`dcd4195c379fd0585f82b54f06db8d6e8c000385`, digest
`sha256:f49c757583e2f279af1680f34aca719b1d02c6a6822b60caab1e56962f6e728f`.
The final release source commit adds that immutable image pin.

## RC5: phone-command identity correction

[RC5 is published](https://github.com/moey823/decrumb/releases/tag/v1.0.0-rc.5)
from `80303eece3a9e87d456bec3d2ccf4bbeff440765`. Its 68.5 MB Mac DMG is
signed, notarized and stapled; all eleven hosted assets match their local hashes.
The public downloads and signed update feed passed verification.

RC5 resolves the linked account's UUID through the Signal client's self-recipient
lookup before accepting optional phone commands. signal-cli 0.14.8 returns only
the phone number from `listAccounts`; RC4 consequently rejected real self-sync
commands that also included UUID fields. The correction keeps every identity
check, privacy exclusion and replay boundary intact. It does not learn an
owner identity from incoming messages. Upgrade both Mac and Pi to RC5 for phone
commands. The feature remains optional and off by default for new installations.

## RC4: Mac and Raspberry Pi

Published 2026-09-20: [Decrumb 1.0.0 RC4](https://github.com/moey823/decrumb/releases/tag/v1.0.0-rc.4),
from source commit `d78fe487dbfed0f9df0d58c8997b474f0ece9876`. The Apple silicon
DMG is 69.5 MB, signed, notarized and stapled. The Pi installer archive is
494,370 bytes; its pinned Signal dependency is downloaded separately. All eleven
release assets match their local checksums. Both public downloads passed the
isolated packaged checks recorded in [VALIDATION.md](VALIDATION.md). Physical Pi
and live Signal acceptance remain before a stable release.

RC4 adds optional, owner-only phone commands on both platforms and the
experimental Raspberry Pi edition. Mac packaging remains the signed/notarized
DMG plus Sparkle archive described below. The Pi release is a separate source
installer archive in the same GitHub release:

```sh
python3 -B tools/package_pi.py --version 1.0.0 --build-number 4
python3 -B tools/smoke_pi.py --archive build/Decrumb-1.0.0-4-linux-arm64.tar.gz \
  --signal-archive /path/to/pinned-signal-cli-arm64.gz
```

Run Pi smoke as an unprivileged Linux ARM64 user. It installs only in temporary
directories, verifies native library loading with an empty account, and checks
QR generation and upgrade preservation. The optional `--systemd` test is limited
to a disposable GitHub ARM64 runner and uses fake Signal for all message traffic.
See [the Pi guide](RASPBERRY-PI.md) for dependencies, manual upgrades, and
remaining physical-device acceptance. Publish both Pi archive and checksum;
never replace an already published version's bytes.

## Previous published Mac candidate

Release status, 2026-09-20. [Decrumb 1.0.0 RC3](https://github.com/moey823/decrumb/releases/tag/v1.0.0-rc.3)
is published with a 67.8 MB Developer ID signed, Apple-notarized and stapled DMG,
matching corresponding-source archive, checksums, release receipt, and signed
Sparkle update archive/feed. The hosted app and DMG passed Gatekeeper and
synthetic packaged smoke. RC3 starts cleaning after pairing and every time the
app opens, including after a pause. Real-device acceptance remains before stable
v1; see [V1-READINESS.md](V1-READINESS.md).

## Installation

Use a signed, notarized DMG containing Decrumb.app and an Applications shortcut.
Users drag the app to Applications, launch it there, then pair with their phone.
Do not launch the worker from a mounted read-only image. The app, including its
Signal dependency, is replaced as a unit; account state stays in
`~/Library/Application Support/Decrumb`.

For the current development build:

```sh
python3 build.py --app
python3 -B tools/package_dmg.py
```

The default packager uses APFS/LZFSE, verifies the app signature and disk image,
writes a SHA-256 checksum file, and creates a development-labelled image in build/.
It does not upload anything. Selecting a signing identity alone never promotes a
development build into a production release.

## Production commands

Read the version and build number from `release.json`, then choose the tested minimum macOS version,
an existing **Developer ID Application** identity, and an existing `notarytool`
Keychain profile. The environment variables below are references and release
inputs; passwords, API keys, and private key material do not belong in commands
or this repository. App Store distribution identities cannot substitute for
Developer ID signing of a direct download.

The development app build above provides the frozen-worker inventory used to
identify its native dependencies. Then prepare verified corresponding sources
and notices for the exact checkout and dependency versions:

```sh
export DECRUMB_VERSION="$(python3 tools/release_version.py --field version)"
export DECRUMB_BUILD_NUMBER="$(python3 tools/release_version.py --field build)"
export DECRUMB_RELEASE_TAG="$(python3 tools/release_version.py --field tag)"

python3 -B tools/prepare_release_materials.py \
  --version "$DECRUMB_VERSION" --build "$DECRUMB_BUILD_NUMBER"

python3 build.py --app --production \
  --version "$DECRUMB_VERSION" --build-number "$DECRUMB_BUILD_NUMBER" \
  --minimum-macos "$DECRUMB_MINIMUM_MACOS" \
  --signing-identity "$DECRUMB_SIGNING_IDENTITY" \
  --release-materials build/release-materials

python3 -B tools/smoke_app.py

python3 -B tools/package_dmg.py --production \
  --signing-identity "$DECRUMB_SIGNING_IDENTITY" \
  --notary-profile "$DECRUMB_NOTARY_PROFILE" \
  --release-materials build/release-materials \
  --update-account decrumb-updates --release-tag "$DECRUMB_RELEASE_TAG"
```

The collector stops on missing or mismatched material. Source changes invalidate
the source inventory: regenerate materials before rebuilding the candidate.
The builder applies the selected Swift deployment target, signs with hardened
runtime and secure timestamps, and verifies identities, deployment floors, and
native-library loading. Signal CLI alone needs a library-validation exception
because its native image extracts embedded JNI libraries. The interface and
other helpers do not receive that exception.

Before packaging, add UTF-8 plain-text release notes in
`docs/update-notes/<version>-<build>.txt` matching the app's version and build
(for example, `docs/update-notes/1.1.3-10.txt`). Keep them nonempty and under 16 KiB.
The update packager embeds these notes in the signed feed and rejects missing or
mismatched notes. This lets the updater display notes without another network request.

The production packager notarizes and staples a staged copy of the app, assesses
it with Gatekeeper, creates and signs the DMG, then notarizes, staples, and assesses
the DMG. Rejected or unconfirmed submissions do not produce a completed release.
Successful output consists of the version/build-labelled DMG, corresponding-source
ZIP, a Sparkle update ZIP and signed appcast, their checksums, and a release receipt. Keep prior receipts to enforce increasing
build numbers locally. The complete upstream source archives accompany the download;
notices and the manifest are included in the installed app.

No script creates certificates or Apple accounts, supplies credentials, or
publishes to GitHub. Notarization submits the signed candidate to Apple using
the selected existing Keychain profile. Follow
[download and installation acceptance](RELEASE-ACCEPTANCE.md) against the exact
hosted artifact before promoting it to the general download.

## Hosting

The source home is [moey823/decrumb](https://github.com/moey823/decrumb). Product,
privacy, support, terms, and download information live at
[mkships.app/decrumb](https://mkships.app/decrumb/) on the existing GitHub Pages
site. The download page identifies the published release candidate. Development
DMGs stay local and are not public release assets.

Use GitHub Releases for completed consumer releases: a versioned DMG, checksums,
release notes, and corresponding source/build materials. Keep version-specific
URLs immutable. Production packaging emits an update archive and signed appcast
for the stable feed `https://mkships.app/decrumb/appcast.xml`. Publish the archive
at the exact GitHub release-tag URL embedded in the appcast, then deploy the
appcast unchanged at that stable URL; changing XML invalidates its signature.
To correct notes after publication, regenerate and verify the signed feed with
Sparkle's official tools, preserving the immutable archive URL, signature,
version and build, then deploy the regenerated feed at the stable URL. Leave
the existing GitHub release assets unchanged. No application server or message storage is
needed for this hosting arrangement.

## In-app updates

The app embeds official Sparkle 2.10.0 and presents Check for Updates in its app
and menu-bar menus. App updates settings offer separate automatic-check and
automatic download/install options; both default off. Turning automatic checks
off also disables automatic installation. Updates install when the user accepts,
or on quit when automatic installation was selected. Pairing and active settings
changes finish before installation proceeds. **Install and Relaunch** starts
cleaning after the updated app reopens. In 1.1.3 source, an explicit **Quit
Decrumb** stops cleaning and exits without requesting a relaunch; a downloaded
update may finish installing on exit. A durable transition prevents cleaning
from starting before an interrupted installation is reconciled. **Hide Decrumb**
keeps cleaning active. Pause lasts only until the app is reopened.

The stable HTTPS feed and update archive require EdDSA signatures using the
public key embedded in the app. Invalid feeds fail immediately (no expired-feed
fallback); archives are checked before extraction. The app and nested Sparkle
executables also have Developer ID signatures. `generate_appcast`, `sign_update`
and Keychain signing are Sparkle's official tools. The dedicated Keychain account
is `decrumb-updates`; only its public verification key is in source. No private
signing key is exported or hosted. Initial releases use full archives rather than
deltas, so the complete bundled Signal runtime updates as one unit.

Update checks do not send Signal identifiers, contacts, note IDs, rules, message
content or a system profile. The user agent contains Decrumb's version. Hosting
providers still receive ordinary HTTP connection information, including IP
addresses; the preferences page states this before the user enables checks.

The worker transition is durable and serialized with pairing/settings operations.
The app stops only its owned LaunchAgent, verifies the worker lock is released,
and records the intended build without changing the saved pause/login
preference during installation or opening the message database. A temporary recovery LaunchAgent can
reopen the app in the background after an interrupted installation. A new build
at least as recent as the intended build refreshes helper/login paths and starts
cleaning, ending a prior pause just like a normal app launch. An older build reattaches Sparkle's persisted update;
it does not infer completion from time passing or an idle updater session.
A verified cancellation/failure restores the previous worker state using the
same transition token; cancellation preserves a pause. Recovery removes the temporary job for active, paused
and unlinked configurations alike. Failure to restart reports an explicit Retry
connection action; it never unlinks an account or registers a new one.

RC1/build 1 has no updater. Install an updater-enabled signed release once using
its DMG; later releases arrive through the feed. Preserve existing immutable RC1
assets. Publish only a feed/archive combination verified against the same app
version, increasing build number, architecture, minimum OS, key, and checksum.
The source archive contains Sparkle's pinned source and original notices.
See [UPDATE-ACCEPTANCE.md](UPDATE-ACCEPTANCE.md) for tests and remaining acceptance.

## Before public release

- Publish completed release assets on GitHub Releases and update the download
  page with tested OS/architecture support. Publish the signed appcast at the configured stable feed URL only after
  all referenced immutable release assets are available.
- Supply Developer ID signing/notarization configuration. Enable appropriate
  hardened-runtime settings for every bundled executable; verify nested code.
- Notarize and staple the release artifacts. Test installation from a downloaded
  image on a clean Mac under normal Gatekeeper settings.
- Complete corresponding-source packages and third-party notices for the bundled
  dependencies; see THIRD-PARTY.md. Bundling upstream URLs alone is insufficient.
- Test on the macOS versions claimed by the release. The candidate targets
  Apple Silicon and macOS 26.4 or later; packaged worker checks pass on 26.4
  and 27.0. Downloaded installation and GUI acceptance remain separate checks.
- Retain release receipts and advance explicit version/build inputs. Match every
  published checksum, source archive, and release note to the final artifact.
- Perform real-device acceptance checks for linking, cleanup and update recovery.

## Sources

- [Sparkle setup and security](https://sparkle-project.org/documentation/)
- [Sparkle publishing, archive formats and delta updates](https://sparkle-project.org/documentation/publishing/)
- [GitHub release assets](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)
- [Stable latest-release links](https://docs.github.com/en/repositories/releasing-projects-on-github/linking-to-releases)
- [Apple notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
