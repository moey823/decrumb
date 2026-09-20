# Decrumb distribution and updates

Release plan, 2026-09-20. Local development DMG packaging is implemented. The
public launch shares source and information pages; the consumer app download is
**coming soon**. Distribution signing, notarization and an in-app updater remain
release work. See [V1-READINESS.md](V1-READINESS.md) for the initial-release gate.

## Installation

Use a signed, notarized DMG containing Decrumb.app and an Applications shortcut.
Users drag the app to Applications, launch it there, then pair with their phone.
Do not launch the worker from a mounted read-only image. The app, including its
Signal dependency, is replaced as a unit; account state stays in the existing
Application Support directory.

For the current development build:

```sh
python3 build.py --app
python3 -B tools/package_dmg.py
```

The packager uses APFS/LZFSE, verifies the app signature and disk image, writes a
SHA-256 sidecar, and creates an explicitly development-labelled image in build/.
It does not sign for distribution, notarize, create release accounts, publish
source, or upload files. It deliberately cannot label an image a public release
merely because an app happens to have a signing identity.

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
- Test on the macOS versions claimed by the release. Current development artifacts
  declare macOS 27.0 and Apple Silicon; older versions/Intel are not validated.
- Make version/build numbers release inputs. CFBundleVersion is currently fixed
  at 1 and must become monotonically increasing before publishing an update feed.
- Perform real-device acceptance checks for linking, cleanup and update recovery.

## Sources

- [Sparkle setup and security](https://sparkle-project.org/documentation/)
- [Sparkle publishing, archive formats and delta updates](https://sparkle-project.org/documentation/publishing/)
- [GitHub release assets](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)
- [Stable latest-release links](https://docs.github.com/en/repositories/releasing-projects-on-github/linking-to-releases)
- [Apple notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
