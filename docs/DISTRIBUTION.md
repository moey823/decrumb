# Decrumb distribution and updates

## RC5: phone-command identity correction

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

First choose the version, increasing build number, tested minimum macOS version,
an existing **Developer ID Application** identity, and an existing `notarytool`
Keychain profile. The environment variables below are references and release
inputs; passwords, API keys, and private key material do not belong in commands
or this repository. App Store distribution identities cannot substitute for
Developer ID signing of a direct download.

The development app build above provides the frozen-worker inventory used to
identify its native dependencies. Then prepare verified corresponding sources
and notices for the exact checkout and dependency versions:

```sh
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
appcast unchanged at that stable URL; changing XML invalidates its signature. No application server or message storage is
needed for this hosting arrangement.

## In-app updates

The app embeds official Sparkle 2.10.0 and presents Check for Updates in its app
and menu-bar menus. App updates settings offer separate automatic-check and
automatic download/install options; both default off. Turning automatic checks
off also disables automatic installation. Updates install when the user accepts,
or on quit when automatic installation was selected. Pairing and active settings
changes finish before installation proceeds. Decrumb relaunches after installing
and starts cleaning automatically. Pause lasts only until the app is reopened.

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
