# Decrumb distribution and updates

Release status, 2026-09-20. [Decrumb 1.0.0 RC1](https://github.com/moey823/decrumb/releases/tag/v1.0.0-rc.1)
is published with a 66.8 MB Developer ID signed, Apple-notarized and stapled DMG,
matching corresponding-source archive, checksums, and release receipt. The app
and DMG passed Gatekeeper assessment. Downloaded installation and real-device
acceptance precede stable v1; see [V1-READINESS.md](V1-READINESS.md).

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
  --release-materials build/release-materials
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
ZIP, both checksums, and a release receipt. Keep prior receipts to enforce increasing
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
site. The download page offers a source archive and says the macOS app is coming
soon. Development DMGs stay local and are not public release assets.

Use GitHub Releases for completed consumer releases: a versioned DMG, checksums,
release notes, and corresponding source/build materials. Keep version-specific
URLs immutable. An update archive and a stable HTTPS Sparkle feed can be added
when the updater is implemented. No application server or message storage is
needed for this hosting arrangement.

## Recommended in-app updater

The initial release can use a tested and documented manual replacement process.
Sparkle 2 can follow v1. When implemented, include Check for Updates in the app
menu; let the user choose automatic checks and installation. Update
checks must send no Signal identifiers, contact data, note IDs, rules or message
content. Use HTTPS, Developer ID signatures and Sparkle EdDSA archive signatures;
keep private signing keys outside the repository and hosting service.

The feed describes version, supported macOS/architecture, download and release
notes. Use Sparkle's feed-generation tools, rather than a hand-written installer
or a homegrown updater. Its delta updates can reduce downloads when the bundled
Signal binary has not changed. The host still sees ordinary HTTP connection
metadata; this should be described honestly in the eventual update preference.

Decrumb also has a background worker. Updating the GUI alone is insufficient:

1. Remember whether the worker was enabled and whether pairing is in progress.
2. Defer installation during pairing. Stop the owned worker and verify its lock
   is released before replacing binaries; do not discard queued notes or change
   the user's persistent pause preference as part of an update.
3. Let Sparkle verify and install the complete app bundle, then relaunch.
4. Refresh helper/LaunchAgent paths and resume only if previously enabled. Preserve
   the linked account, note receipts, settings and deduplication state.
5. Verify bootstrap/worker health. Failed updates need an actionable recovery
   path; never repair an update failure by unlinking or registering the account.

Test this with two distinct signed builds, a temporary runtime and fake Signal,
including a pending send, pending removal, paused worker and failed installation.
Database migrations must remain compatible with the previous release or provide
an explicit recovery strategy before automatic rollback is offered.

## Before public release

- Publish completed release assets on GitHub Releases and update the download
  page with tested OS/architecture support. Select a stable feed URL when adding
  the in-app updater.
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
